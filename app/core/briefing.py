"""后台简报引擎（主动化产品 L3 的核心）。

设计目的：
让产品"主动开口"——不等人点，启动时自动扫一遍 PBC 清单，
把"今天最该关注的事"主动推送出来。这是 L3 主动式产品的最小可见形态。

事件类型（risk_event_type）：
- new_overdue         新跨过阈值（首次超过 30/100 天）
- status_rollback     状态回退（已提供 → 审核中、审核中 → 未提供）
- high_risk_gap       高风险缺料（未提供 + 影响IPO高频问询点）
- file_resolved_risk  新文件解除了某项逾期风险（watchdog 触发后评估）

调用方：
    from app.core.briefing import generate_daily_briefing, evaluate_file_impact
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from app.core.db import list_projects, get_project
from app.core.excel_io import read_pbc_list
from app.core.risk_signal import get_risk_signal

logger = logging.getLogger("pbc.briefing")


# 事件优先级（数字越大越靠前）
_PRIORITY = {"high": 3, "medium": 2, "low": 1, "none": 0}

# 最多返回 N 条事件
_MAX_BRIEFING_ITEMS = 8


def _parse_overdue(val: Any) -> int:
    """容错地把 overdue_days 字段转成 int。"""
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    try:
        return int(str(val).replace("天", "").strip())
    except Exception:
        return 0


def _event_for_item(item: dict[str, Any], project_id: str) -> Optional[dict[str, Any]]:
    """对单个超期 item 生成一条简报事件。"""
    overdue = _parse_overdue(item.get("overdue_days"))
    if overdue <= 0:
        return None

    risk_signal = get_risk_signal(item)
    inquiry_risk = risk_signal.get("ipo_inquiry_risk", "medium")

    # 等级：>100天 high / >30天 medium / 其他 low；关联方类直接 high
    risk = item.get("risk_level") or "low"
    if risk == "high":
        priority = "high"
    elif risk == "medium":
        priority = "medium"
    else:
        priority = "low"

    # 高风险问询点升级一级
    if inquiry_risk == "high" and priority != "high":
        priority = "high"

    item_id = item.get("item_id", "")
    category = item.get("category", "")
    entity = item.get("entity", "")
    first_conclusion = (risk_signal.get("affected_conclusions") or ["相关审计结论"])[0]

    # 一句话（钉在简报卡片上）
    text = f"{item_id} 未提供 {overdue} 天 → 影响 {first_conclusion}"

    # 详细说明
    detail = risk_signal.get("risk_signal_text", "")

    return {
        "event_type": "high_risk_gap" if inquiry_risk == "high" else "new_overdue",
        "priority": priority,
        "project_id": project_id,
        "item_id": item_id,
        "category": category,
        "entity": entity,
        "overdue_days": overdue,
        "risk_level": item.get("risk_level", risk),
        "ipo_inquiry_risk": inquiry_risk,
        "title": text,
        "detail": detail,
        "risk_signal": risk_signal,
        "timestamp": time.time(),
    }


def generate_daily_briefing(project_id: Optional[str] = None) -> dict[str, Any]:
    """启动时/手动触发时生成"今日简报"。

    Args:
        project_id: 指定项目。None 时扫所有项目。

    Returns:
        {
            "generated_at": ISO,
            "project_id": str|None,
            "events": list[dict],   # 按 priority 降序，最多 _MAX_BRIEFING_ITEMS 条
            "summary": {
                "high_count": int,
                "medium_count": int,
                "total_events": int,
                "scanned_projects": int,
            }
        }
    """
    events: list[dict[str, Any]] = []
    scanned_projects = 0

    if project_id:
        project_ids = [project_id]
    else:
        # 扫所有项目
        try:
            all_projects = list_projects(active_only=False)
            project_ids = [p.get("project_id") for p in all_projects if p.get("project_id")]
        except Exception as e:
            logger.warning("list projects failed: %r, fallback to demo only", e)
            project_ids = ["demo"]

    for pid in project_ids:
        if not pid:
            continue
        try:
            items = read_pbc_list(project_id=pid)
        except Exception as e:
            logger.warning("read_pbc_list failed for project %s: %r", pid, e)
            continue
        scanned_projects += 1

        for item in items:
            evt = _event_for_item(item, pid)
            if evt:
                events.append(evt)

    # 排序：priority desc → overdue desc
    events.sort(
        key=lambda e: (-_PRIORITY.get(e.get("priority", "low"), 0), -e.get("overdue_days", 0))
    )

    total = len(events)
    high_count = sum(1 for e in events if e.get("priority") == "high")
    medium_count = sum(1 for e in events if e.get("priority") == "medium")

    # 去重：同一 item_id 在多项目场景下只取一条（取最高优）
    seen_items: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for e in events:
        key = e.get("item_id", "")
        if key in seen_items:
            continue
        seen_items.add(key)
        deduped.append(e)
        if len(deduped) >= _MAX_BRIEFING_ITEMS:
            break

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "project_id": project_id,
        "events": deduped,
        "summary": {
            "high_count": high_count,
            "medium_count": medium_count,
            "total_events": total,
            "scanned_projects": scanned_projects,
        },
    }


def evaluate_file_impact(
    project_id: str,
    item_id: str,
    old_overdue_days: int,
    new_overdue_days: int,
) -> Optional[dict[str, Any]]:
    """watchdog 收到新文件 + AI 匹配到 item_id 后调用。

    评估"这个文件是否解除了某项逾期风险"，若是则生成 file_resolved_risk 事件。

    Args:
        project_id: 项目 id
        item_id: 匹配到的 PBC 项 id
        old_overdue_days: 处理前的逾期天数（>0 表示之前是逾期的）
        new_overdue_days: 处理后的逾期天数（通常 0，因为文件到了状态变成已提供审核中）

    Returns:
        事件 dict 或 None（无影响时不返回）
    """
    if old_overdue_days <= 0:
        return None  # 之前就没逾期，不算"解除"

    # 文件到了，逾期解除
    try:
        from app.core.excel_io import get_item_by_id
        item = get_item_by_id(item_id, project_id=project_id)
    except Exception as e:
        logger.warning("get_item_by_id failed for %s: %r", item_id, e)
        item = {}

    risk_signal = get_risk_signal(item or {"category": ""})
    first_conclusion = (risk_signal.get("affected_conclusions") or ["相关审计结论"])[0]

    return {
        "event_type": "file_resolved_risk",
        "priority": "low",  # 好消息用低优先级（视觉用绿色）
        "project_id": project_id,
        "item_id": item_id,
        "category": item.get("category", ""),
        "entity": item.get("entity", ""),
        "overdue_days_before": old_overdue_days,
        "overdue_days_after": new_overdue_days,
        "ipo_inquiry_risk": risk_signal.get("ipo_inquiry_risk", "medium"),
        "title": f"{item_id} 解除 {old_overdue_days} 天逾期风险",
        "detail": f"新文件解除了 {first_conclusion} 的缺料风险。",
        "risk_signal": risk_signal,
        "timestamp": time.time(),
    }


__all__ = ["generate_daily_briefing", "evaluate_file_impact"]
