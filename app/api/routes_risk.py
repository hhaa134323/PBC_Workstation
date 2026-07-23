"""风险化解助手路由（M6 完善版 + 多项目支持）。

接口（多项目）：
- GET /api/risk/{project_id}/dashboard           风险雷达仪表盘
- GET /api/risk/{project_id}/resolve/{item_id}    风险化解助手
- GET /api/risk/{project_id}/escalation           整体升级汇报包
- GET /api/risk/{project_id}/heatmap              风险热力图

兼容旧路由（不带 project_id，走 demo 项目）。

聚合数据全部从 read_pbc_list 取，不新加 Excel 读写。
AI 调用结果做 5 分钟内存缓存，AI 失败时降级到 knowledge_base 兜底。
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.config import get_config
from app.core.ai_client import AIClient
from app.core.excel_io import (
    compute_risk_level, get_item_by_id, read_pbc_list,
)
from app.core.knowledge_base import (
    get_fallback_alternative_procedures,
    get_fallback_impact_analysis,
    has_fallback_for_category,
)
from app.core.risk_signal import (
    format_risk_signal_brief,
    get_ipo_inquiry_risk_label,
    get_risk_signal,
)

logger = logging.getLogger("pbc.routes_risk")

router = APIRouter(prefix="/api/risk", tags=["risk"])

_DEFAULT_PROJECT = "demo"

_ai_client: Optional[AIClient] = None

# (project_id, item_id) -> (timestamp, payload)
_resolve_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_CACHE_TTL = 300.0  # 5 分钟


def _get_ai_client() -> AIClient:
    global _ai_client
    if _ai_client is None:
        _ai_client = AIClient()
    return _ai_client


def _xlsx_path(project_id: Optional[str] = None) -> str:
    """兼容旧调用：不传 project_id 时用全局 config.pbc_list_path。"""
    from app.core.db import get_project
    if project_id:
        proj = get_project(project_id)
        if proj is None:
            raise FileNotFoundError(f"项目不存在: {project_id}")
        return proj.get("pbc_list_path") or ""
    return str(get_config().pbc_list_path)


# 颜色常量（前端 Matrix 视图用，符合中国审计红涨绿跌习惯，但风险等级用红黄绿）
_LEGEND = {
    "high":   {"color": "#E24B4A", "label": "高风险（>100天）"},
    "medium": {"color": "#EF9F27", "label": "中风险（30-100天）"},
    "low":    {"color": "#97C459", "label": "低风险（<30天）"},
    "none":   {"color": "#F1EFE8", "label": "无超期"},
}

# 风险热点反推：按 category 映射到常见受影响的审计结论
_CATEGORY_AFFECTED_CONCLUSIONS = {
    "历史沿革": ["公司主体资格", "股权结构", "实收资本"],
    "业务及财务概览": ["财务报表整体列报", "管理层声明"],
    "货币资金": ["货币资金期末余额", "现金流量表", "资金受限情况"],
    "存货": ["存货期末余额", "存货跌价准备", "主营业务成本"],
    "往来科目": ["应收账款期末余额", "应付账款期末余额", "坏账准备"],
    "长期资产": ["固定资产期末余额", "无形资产期末余额", "资产减值准备"],
    "薪酬": ["应付职工薪酬", "管理费用", "社保公积金"],
    "税务相关": ["应交税费", "递延所得税资产", "递延所得税负债"],
    "收入成本": ["营业收入", "营业成本", "毛利率", "截止性"],
    "成本": ["主营业务成本", "制造费用分配"],
    "营业外收支": ["营业外收入", "营业外支出"],
    "政府补助": ["其他收益", "递延收益"],
    "费用": ["管理费用", "销售费用", "研发费用"],
    "关联方": ["关联交易披露", "关联方资金占用"],
    "租赁类": ["使用权资产", "租赁负债"],
    "短期借款": ["短期借款", "利息费用"],
    "期后": ["期后事项披露", "持续经营"],
    "其他": ["其他披露事项"],
}


# ----------------------------------------------------------------------
# 风险雷达仪表盘（M6 完善：补 overdue_summary/risk_heatmap/audit_risk_hotspots）
# 多项目：/dashboard 走 demo；/{project_id}/dashboard 走指定项目
# ----------------------------------------------------------------------
@router.get("/{project_id}/dashboard")
async def dashboard_by_project(project_id: str) -> dict:
    """风险雷达仪表盘数据（多项目）。"""
    return _dashboard_impl(project_id=project_id)


@router.get("/dashboard")
async def dashboard() -> dict:
    """风险雷达仪表盘数据（兼容旧调用，走 demo 项目）。"""
    try:
        return _dashboard_impl(project_id=_DEFAULT_PROJECT)
    except FileNotFoundError as e:
        # 兜底：用全局 config
        try:
            return _dashboard_impl(project_id=None)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=str(e))


def _dashboard_impl(project_id: Optional[str]) -> dict:
    """dashboard 主体逻辑，可被新旧路由复用。"""
    try:
        items = read_pbc_list(project_id=project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("dashboard read_pbc_list failed")
        raise HTTPException(status_code=500, detail=f"读取清单失败: {e}")

    # 总体进度
    progress: dict[str, int] = {
        "已提供": 0, "已提供，审核中": 0, "未提供": 0, "不适用": 0, "待定": 0,
    }
    overdue_items: list[dict[str, Any]] = []
    heatmap_cells: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"overdue_count": 0, "max_overdue": 0, "items": []}
    )
    # 按一级分类聚合（用于风险热点反推）
    category_overdue: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "max_overdue": 0, "entities": set(), "items": []}
    )

    high_count = 0
    medium_count = 0
    max_overdue_days = 0

    for it in items:
        status = it.get("status_normalized") or "待定"
        if status in progress:
            progress[status] += 1
        else:
            progress[status] = progress.get(status, 0) + 1

        overdue = it.get("overdue_days") or 0
        if not isinstance(overdue, (int, float)):
            try:
                overdue = int(str(overdue).replace("天", "").strip()) if overdue else 0
            except Exception:
                overdue = 0

        if overdue and overdue > 0:
            risk = it.get("risk_level") or compute_risk_level(overdue)
            entity = it.get("entity") or "(未归属)"
            category = it.get("category") or "(未分类)"

            overdue_items.append({
                "item_id": it.get("item_id"),
                "category": category,
                "subject": it.get("subject"),
                "description": (it.get("description") or "")[:80],
                "entity": entity,
                "overdue_days": overdue,
                "risk_level": risk,
                "status": status,
                # 风险信号一句话（钉在超期列表行上，让"缺料 → 影响什么结论"在 dashboard 显式呈现）
                "risk_signal_text": format_risk_signal_brief(it),
                "ipo_inquiry_risk": get_risk_signal(it).get("ipo_inquiry_risk", "medium"),
            })

            # 热力图聚合
            hm = heatmap_cells[(entity, category)]
            hm["overdue_count"] += 1
            hm["max_overdue"] = max(hm["max_overdue"], overdue)
            hm["items"].append(it.get("item_id"))

            # 风险等级统计
            if risk == "high":
                high_count += 1
            elif risk == "medium":
                medium_count += 1
            if overdue > max_overdue_days:
                max_overdue_days = overdue

            # 按 category 聚合
            co = category_overdue[category]
            co["count"] += 1
            co["max_overdue"] = max(co["max_overdue"], overdue)
            co["entities"].add(entity)
            co["items"].append(it.get("item_id"))

    # 排序超期项（按风险等级 + 逾期天数）
    risk_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
    overdue_items.sort(
        key=lambda x: (-risk_order.get(x.get("risk_level", "none"), 0), -x.get("overdue_days", 0))
    )

    # 热力图 cells
    heatmap_list = [
        {
            "entity": k[0],
            "category": k[1],
            "count": v["overdue_count"],
            "max_overdue": v["max_overdue"],
            "risk_level": compute_risk_level(v["max_overdue"]),
            "items": v["items"],
        }
        for k, v in heatmap_cells.items()
    ]

    # 审计风险热点（按 category 反推）
    hotspots = []
    for category, info in category_overdue.items():
        affected = _CATEGORY_AFFECTED_CONCLUSIONS.get(category, ["相关审计结论"])
        # 评级：>100天 high / >30天 medium / 其他 low
        concern = compute_risk_level(info["max_overdue"])
        hotspots.append({
            "area": category,
            "missing_count": info["count"],
            "max_overdue": info["max_overdue"],
            "affected_conclusions": affected,
            "affected_entities": sorted(info["entities"]),
            "concern_level": concern,
        })
    # 热点按 max_overdue 降序
    hotspots.sort(key=lambda x: -x["max_overdue"])

    progress["总计"] = len(items)

    return {
        "project_id": project_id,
        "overall_progress": progress,
        "overdue_summary": {
            "count": len(overdue_items),
            "high_count": high_count,
            "medium_count": medium_count,
            "max_overdue_days": max_overdue_days,
        },
        "overdue_items": overdue_items,
        "risk_heatmap": {
            "entities": sorted({k[0] for k in heatmap_cells.keys()}),
            "categories": sorted({k[1] for k in heatmap_cells.keys()}),
            "cells": heatmap_list,
        },
        "audit_risk_hotspots": hotspots,
        "total": len(items),
    }


# ----------------------------------------------------------------------
# 风险化解助手（M6 完善：AI 失败降级 + 缓存）
# 多项目路由：/{project_id}/resolve/{item_id}
# 兼容旧路由：/resolve/{item_id}（走 demo 项目）
# 路由顺序：3 seg 的 /{project_id}/resolve/{item_id} 必须先声明
# ----------------------------------------------------------------------
@router.get("/{project_id}/resolve/{item_id}")
async def resolve_by_project(project_id: str, item_id: str) -> dict:
    """风险化解助手（多项目）。"""
    return _resolve_impl(project_id=project_id, item_id=item_id)


@router.get("/resolve/{item_id}")
async def resolve(item_id: str) -> dict:
    """风险化解助手（兼容旧调用，走 demo 项目）。"""
    try:
        return _resolve_impl(project_id=_DEFAULT_PROJECT, item_id=item_id)
    except FileNotFoundError as e:
        # 兜底：用全局 config
        try:
            return _resolve_impl(project_id=None, item_id=item_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=str(e))


def _resolve_impl(project_id: Optional[str], item_id: str) -> dict:
    """resolve 主体逻辑（P0-6: 任何失败都不抛 500，降级失败也返回 ok=False + fallback_used）。"""
    # 1. 读 item
    try:
        item = get_item_by_id(item_id, project_id=project_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("resolve get_item_by_id failed")
        # P0-6: 读取失败也返回结构化错误（不抛 500，但前端能拿到错误信息）
        return {
            "project_id": project_id,
            "item_id": item_id,
            "ok": False,
            "error": f"读取失败: {type(e).__name__}: {e}",
            "fallback_used": True,
            "cached": False,
        }

    if item is None:
        raise HTTPException(status_code=404, detail=f"未找到资料项: {item_id}")

    # 2. 缓存（按 project_id+item_id）
    now = time.time()
    cache_key = (project_id or "", item_id)
    cached = _resolve_cache.get(cache_key)
    if cached and (now - cached[0]) < _CACHE_TTL:
        return {"project_id": project_id, "item_id": item_id, "cached": True, **cached[1]}

    # 3. 风险信号（毫秒级查表，不走 AI，秒回；前端"风险信号卡"主数据源）
    risk_signal = get_risk_signal(item)

    # 4. 调 AI（失败时降级到 knowledge_base 兜底）
    # P0-6: 包 try/except，AI 调用本身异常也要降级
    client = _get_ai_client()
    gap_context = {
        "overdue_days": item.get("overdue_days") or 0,
        "affected_areas": item.get("subject") or item.get("category") or "",
    }

    try:
        impact = client.analyze_impact(item)
    except Exception as e:
        logger.exception("analyze_impact 异常，降级到 fallback: %r", e)
        impact = {
            "ok": False,
            "error": f"analyze_impact 异常: {type(e).__name__}: {e}",
        }

    try:
        procedures = client.suggest_alternative_procedures(item, gap_context)
    except Exception as e:
        logger.exception("suggest_alternative_procedures 异常，降级到 fallback: %r", e)
        procedures = {
            "ok": False,
            "error": f"suggest_alternative_procedures 异常: {type(e).__name__}: {e}",
        }

    # AI 失败时降级（P0-6: 降级本身也包 try/except）
    used_fallback = False
    fallback_error: Optional[str] = None
    try:
        if not impact.get("ok"):
            impact = get_fallback_impact_analysis(item)
            used_fallback = True
    except Exception as e:
        fallback_error = (fallback_error or "") + f" | impact fallback 异常: {e}"
        impact = {"ok": False, "error": f"impact fallback 异常: {e}"}
        used_fallback = True

    try:
        if not procedures.get("ok"):
            procs = get_fallback_alternative_procedures(item)
            procedures = {
                "ok": True,
                "source": "knowledge_base",
                "procedures": procs,
                "impact_summary": (
                    procedures.get("impact_summary") if procedures.get("ok") else
                    f"缺失 {item.get('category', '')} 类资料可能影响审计证据完整性"
                ),
                "concern_level": compute_risk_level(item.get("overdue_days") or 0),
            }
            used_fallback = True
    except Exception as e:
        fallback_error = (fallback_error or "") + f" | procedures fallback 异常: {e}"
        procedures = {
            "ok": False,
            "error": f"procedures fallback 异常: {e}",
            "procedures": [],
            "impact_summary": f"缺失 {item.get('category', '')} 类资料可能影响审计证据完整性",
            "concern_level": compute_risk_level(item.get("overdue_days") or 0),
        }
        used_fallback = True

    # 4. 汇报文本（构造失败也兜底）
    overdue = item.get("overdue_days") or 0
    concern = (
        impact.get("concern_level")
        or procedures.get("concern_level")
        or compute_risk_level(overdue)
    )
    try:
        escalation = _build_escalation_report(item, impact, procedures, concern)
    except Exception as e:
        logger.warning("escalation 文本构造失败: %r", e)
        escalation = f"【风险化解汇报】item_id={item_id}（汇报文本构造失败: {e}）"

    # P0-6: 如果连降级都失败，impact 和 procedures 都不 ok，明确返回 ok=False + fallback_used=True
    overall_ok = bool(impact.get("ok")) or bool(procedures.get("ok"))

    payload = {
        "ok": overall_ok,
        "item": {
            "item_id": item.get("item_id"),
            "category": item.get("category"),
            "subject": item.get("subject"),
            "description": item.get("description"),
            "entity": item.get("entity"),
            "overdue_days": overdue,
            "status_raw": item.get("status_raw"),
            "status_normalized": item.get("status_normalized"),
            "risk_level": item.get("risk_level"),
        },
        # 风险信号（秒回，毫秒级查表，不走 AI）
        # 前端"风险信号卡"顶部主数据：影响结论 / IPO 问询热度 / 问询场景
        "risk_signal": risk_signal,
        "impact_analysis": impact,
        "alternative_procedures": procedures,
        "escalation_report": {
            "report_text": escalation,
            "items_overdue": [{
                "item_id": item.get("item_id"),
                "category": item.get("category"),
                "overdue_days": overdue,
            }],
            "total_impact": f"{len(impact.get('affected_areas', []) or [])} 个领域",
            "concern_level": concern,
            "prepared_for": "Senior/Manager",
        },
        "concern_level": concern,
        "used_fallback": used_fallback,
        "fallback_error": fallback_error,
        "cached": False,
    }

    # 5. 写缓存（只在整体 ok 时写，避免错误结果被缓存）
    if overall_ok:
        _resolve_cache[cache_key] = (now, payload)
        if len(_resolve_cache) > 100:
            for k in list(_resolve_cache.keys())[:10]:
                _resolve_cache.pop(k, None)

    return {"project_id": project_id, "item_id": item_id, **payload}


# ----------------------------------------------------------------------
# 整体升级汇报包（M6 新增）
# 多项目：/escalation 走 demo；/{project_id}/escalation 走指定项目
# ----------------------------------------------------------------------
@router.get("/{project_id}/escalation")
async def escalation_by_project(project_id: str) -> dict:
    """生成给 Senior/Manager 的整体升级汇报（多项目）。"""
    return _escalation_impl(project_id=project_id)


@router.get("/escalation")
async def escalation() -> dict:
    """生成给 Senior/Manager 的整体升级汇报（兼容旧调用，走 demo 项目）。"""
    try:
        return _escalation_impl(project_id=_DEFAULT_PROJECT)
    except FileNotFoundError as e:
        try:
            return _escalation_impl(project_id=None)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=str(e))


def _escalation_impl(project_id: Optional[str]) -> dict:
    """escalation 主体逻辑。"""
    try:
        items = read_pbc_list(project_id=project_id)
    except Exception as e:
        logger.exception("escalation read_pbc_list failed")
        raise HTTPException(status_code=500, detail=f"读取清单失败: {e}")

    # 收集所有超期项
    overdue_list = []
    affected_entities_set = set()
    affected_categories_set = set()

    for it in items:
        overdue = it.get("overdue_days") or 0
        if not isinstance(overdue, (int, float)):
            try:
                overdue = int(str(overdue).replace("天", "").strip()) if overdue else 0
            except Exception:
                overdue = 0
        if not overdue or overdue <= 0:
            continue

        risk = it.get("risk_level") or compute_risk_level(overdue)
        entity = it.get("entity") or "(未归属)"
        category = it.get("category") or "(未分类)"
        affected_entities_set.add(entity)
        affected_categories_set.add(category)

        overdue_list.append({
            "item_id": it.get("item_id"),
            "category": category,
            "subject": it.get("subject"),
            "description": (it.get("description") or "")[:80],
            "entity": entity,
            "overdue_days": overdue,
            "risk_level": risk,
            "status": it.get("status_normalized"),
        })

    # 按优先级排序（high > medium > low，同级别按 overdue_days 降序）
    risk_order = {"high": 3, "medium": 2, "low": 1, "none": 0}
    overdue_list.sort(
        key=lambda x: (-risk_order.get(x.get("risk_level", "none"), 0), -x.get("overdue_days", 0))
    )

    high_count = sum(1 for x in overdue_list if x["risk_level"] == "high")
    medium_count = sum(1 for x in overdue_list if x["risk_level"] == "medium")

    # 生成汇报文本（中文，正式审计语气）
    report_text = _build_global_escalation_text(
        overdue_list, high_count, medium_count,
        sorted(affected_entities_set), sorted(affected_categories_set),
    )

    return {
        "project_id": project_id,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": {
            "total_overdue": len(overdue_list),
            "high_count": high_count,
            "medium_count": medium_count,
            "affected_entities": sorted(affected_entities_set),
            "affected_categories": sorted(affected_categories_set),
        },
        "items_by_priority": overdue_list,
        "report_text": report_text,
    }


# ----------------------------------------------------------------------
# 风险热力图（M6 新增独立接口）
# 多项目：/heatmap 走 demo；/{project_id}/heatmap 走指定项目
# ----------------------------------------------------------------------
@router.get("/{project_id}/heatmap")
async def heatmap_by_project(project_id: str) -> dict:
    """风险热力图数据（多项目）。"""
    return _heatmap_impl(project_id=project_id)


@router.get("/heatmap")
async def heatmap() -> dict:
    """风险热力图数据（兼容旧调用，走 demo 项目）。"""
    try:
        return _heatmap_impl(project_id=_DEFAULT_PROJECT)
    except FileNotFoundError as e:
        try:
            return _heatmap_impl(project_id=None)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=str(e))


def _heatmap_impl(project_id: Optional[str]) -> dict:
    """heatmap 主体逻辑。"""
    try:
        items = read_pbc_list(project_id=project_id)
    except Exception as e:
        logger.exception("heatmap read_pbc_list failed")
        raise HTTPException(status_code=500, detail=f"读取清单失败: {e}")

    cells_map: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "max_overdue": 0, "items": []}
    )
    entities_set = set()
    categories_set = set()

    for it in items:
        overdue = it.get("overdue_days") or 0
        if not isinstance(overdue, (int, float)):
            try:
                overdue = int(str(overdue).replace("天", "").strip()) if overdue else 0
            except Exception:
                overdue = 0
        entity = it.get("entity") or "(未归属)"
        category = it.get("category") or "(未分类)"
        entities_set.add(entity)
        categories_set.add(category)

        if overdue and overdue > 0:
            cell = cells_map[(entity, category)]
            cell["count"] += 1
            cell["max_overdue"] = max(cell["max_overdue"], overdue)
            cell["items"].append(it.get("item_id"))

    cells = [
        {
            "entity": k[0],
            "category": k[1],
            "count": v["count"],
            "max_overdue": v["max_overdue"],
            "risk_level": compute_risk_level(v["max_overdue"]),
            "items": v["items"],
        }
        for k, v in cells_map.items()
    ]
    # 按 max_overdue 降序
    cells.sort(key=lambda x: -x["max_overdue"])

    return {
        "project_id": project_id,
        "entities": sorted(entities_set),
        "categories": sorted(categories_set),
        "cells": cells,
        "legend": _LEGEND,
    }


# ----------------------------------------------------------------------
# 辅助：汇报文本生成
# ----------------------------------------------------------------------
def _build_escalation_report(
    item: dict[str, Any],
    impact: dict[str, Any],
    procedures: dict[str, Any],
    concern: str,
) -> str:
    """生成单条 item 的结构化汇报文本。"""
    lines: list[str] = []
    lines.append("【风险化解汇报】")
    lines.append(f"资料编号: {item.get('item_id', '')}")
    lines.append(f"资料描述: {(item.get('description') or '')[:120]}")
    lines.append(f"实体: {item.get('entity', '')} | 一级分类: {item.get('category', '')}")
    lines.append(f"逾期天数: {item.get('overdue_days', 0)} | 关注等级: {concern}")
    lines.append("")

    source_tag = ""
    if impact.get("source") == "knowledge_base":
        source_tag = "（知识库兜底）"
    elif impact.get("ok"):
        source_tag = "（AI 生成）"

    lines.append(f"【影响分析】{source_tag}")
    areas = impact.get("affected_areas") or []
    if areas:
        lines.append("  受影响领域: " + " / ".join(areas))
    if impact.get("audit_risk"):
        lines.append(f"  审计风险: {impact['audit_risk']}")
    lines.append("")

    proc_source = ""
    if procedures.get("source") == "knowledge_base":
        proc_source = "（知识库兜底）"
    elif procedures.get("ok"):
        proc_source = "（AI 生成）"

    ps = procedures.get("procedures") or []
    lines.append(f"【替代程序建议】共 {len(ps)} 条{proc_source}")
    for i, p in enumerate(ps, 1):
        lines.append(f"  {i}. {p.get('name', '')}")
        for s in p.get("steps", []):
            lines.append(f"     - {s}")
        if p.get("basis"):
            lines.append(f"     依据: {p['basis']}")
    if procedures.get("impact_summary"):
        lines.append(f"  影响概述: {procedures['impact_summary']}")
    lines.append("")
    lines.append("建议 Senior 复核并选择是否采纳替代程序；如不可化解，应上报 Manager。")
    return "\n".join(lines)


def _build_global_escalation_text(
    overdue_list: list[dict[str, Any]],
    high_count: int,
    medium_count: int,
    entities: list[str],
    categories: list[str],
) -> str:
    """生成给 Senior/Manager 的整体升级汇报文本。"""
    lines: list[str] = []
    lines.append("【PBC 缺料风险升级汇报】")
    lines.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("一、总体情况")
    lines.append(f"  本次审计 PBC 资料收集中，共有 {len(overdue_list)} 项资料出现超期未提供情况。")
    lines.append(f"  其中高风险项（逾期 > 100 天）{high_count} 项，中风险项（30-100 天）{medium_count} 项。")
    lines.append(f"  受影响实体: {', '.join(entities)}")
    lines.append(f"  受影响审计科目: {', '.join(categories)}")
    lines.append("")

    lines.append("二、按优先级排序的超期项")
    # 按 risk_level 分组
    for level_name, level_label in [("high", "高风险"), ("medium", "中风险"), ("low", "低风险")]:
        level_items = [x for x in overdue_list if x["risk_level"] == level_name]
        if not level_items:
            continue
        lines.append(f"  【{level_label}】共 {len(level_items)} 项:")
        for i, it in enumerate(level_items, 1):
            lines.append(
                f"    {i}. [{it['item_id']}] {it['description']}"
                f" | 实体: {it['entity']} | 科目: {it['category']}"
                f" | 逾期: {it['overdue_days']} 天"
            )
    lines.append("")

    lines.append("三、影响范围")
    lines.append("  上述缺料主要影响以下审计科目与结论:")
    seen_areas = set()
    for cat in categories:
        areas = _CATEGORY_AFFECTED_CONCLUSIONS.get(cat, ["相关审计结论"])
        for a in areas:
            if a not in seen_areas:
                seen_areas.add(a)
    for a in sorted(seen_areas):
        lines.append(f"    - {a}")
    lines.append("")

    lines.append("四、建议处理顺序")
    lines.append("  1. Senior 优先复核高风险项，按本汇报第二节的优先级排序逐项处理。")
    lines.append("  2. 对每项调用风险化解助手（GET /api/risk/resolve/{item_id}）获取替代程序建议。")
    lines.append("  3. 采纳的替代程序应记录入审计底稿，并标注依据的审计准则条款。")
    lines.append("  4. 不可化解的项应立即上报 Manager，启动与客户高层的沟通。")
    lines.append("  5. Manager 应在 5 个工作日内对升级汇报做出书面回应（依据 SOP §6 异常处理）。")
    lines.append("")
    lines.append("—— 本汇报由 PBC 智能管理工作站自动生成 ——")
    return "\n".join(lines)
