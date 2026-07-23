"""审计准则知识库兜底（M6 新增）。

当 AI 调用失败或不可用时，按 category（一级分类）匹配预置的
- 替代程序建议（含 name / steps / basis）
- 影响分析（含 affected_areas / audit_risk / concern_level）

覆盖 18 类一级分类中 10 类关键类：
  历史沿革 / 货币资金 / 存货 / 往来科目 / 长期资产
  薪酬 / 税务相关 / 收入成本 / 关联方 / 租赁类

设计原则：
- 完全离线、纯函数、无副作用，便于测试与单元回归
- 不依赖 AI / 网络 / 配置文件
- 字段结构与 ai_client.suggest_alternative_procedures / analyze_impact 输出一致
  （前端可无差别消费 AI 成功兜底或知识库兜底）
- basis 引用《中国注册会计师审计准则》具体条款，便于 Senior 复核

调用方：
    from app.core.knowledge_base import (
        get_fallback_alternative_procedures,
        get_fallback_impact_analysis,
        has_fallback_for_category,
    )
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("pbc.knowledge_base")


# ----------------------------------------------------------------------
# 知识库主表
# ----------------------------------------------------------------------
# 每条记录：
#   category          一级分类（必须与 PBC 清单一致）
#   procedures        list[dict]: name / steps / basis
#   affected_areas    list[str]
#   audit_risk        str
#   concern_level     high/medium/low
# ----------------------------------------------------------------------
_KB: dict[str, dict[str, Any]] = {
    "历史沿革": {
        "procedures": [
            {
                "name": "调阅工商档案",
                "steps": [
                    "向市场监管部门调阅目标公司工商档案",
                    "核对股东名册、出资比例、法定代表人",
                    "比对 PBC 历史沿革资料一致性",
                ],
                "basis": "审计准则第 1301 号 - 审计证据（外部独立来源优先）",
            },
            {
                "name": "查阅公开商业信息",
                "steps": [
                    "获取第三方商业查询平台（如天眼查/企查查）数据",
                    "查阅公司官方网站披露信息",
                    "比对实缴资本、股权结构变动历史",
                ],
                "basis": "审计准则第 1101 号 - 注册会计师审计目标与基本责任",
            },
        ],
        "affected_areas": ["公司主体资格", "股权结构审计结论", "实收资本"],
        "audit_risk": "缺失此项可能导致公司主体资格与股权结构审计证据不完整，影响历史沿革审计结论。",
        "concern_level": "medium",
    },
    "货币资金": {
        "procedures": [
            {
                "name": "银行函证",
                "steps": [
                    "编制银行账户清单，制作函证",
                    "经客户盖章后寄出银行函证",
                    "跟踪回函并核对回函金额与账面一致",
                ],
                "basis": "审计准则第 1312 号 - 函证",
            },
            {
                "name": "检查银行对账单与网银流水",
                "steps": [
                    "取得期末银行对账单",
                    "与银行存款明细账核对",
                    "抽样核对网银流水（大额发生额）",
                ],
                "basis": "审计准则第 1312 号 - 函证（替代程序）",
            },
        ],
        "affected_areas": ["货币资金期末余额", "现金流量表", "受限货币资金披露"],
        "audit_risk": "缺失此项可能导致货币资金期末余额证据不完整，影响现金流量表与受限资金披露。",
        "concern_level": "high",
    },
    "存货": {
        "procedures": [
            {
                "name": "存货盘点监盘",
                "steps": [
                    "评价客户盘点计划合理性",
                    "实地参与期末存货盘点监盘",
                    "对盘点结果执行抽盘并与账面核对",
                ],
                "basis": "审计准则第 1311 号 - 存货监盘",
            },
            {
                "name": "执行存货减值测试",
                "steps": [
                    "获取存货明细与库龄表",
                    "识别滞销/残损/冷背存货",
                    "复核可变现净值与跌价准备计提",
                ],
                "basis": "审计准则第 1322 号 - 存货（减值）",
            },
            {
                "name": "调阅生产台账",
                "steps": [
                    "取得生产台账与成本计算表",
                    "核对料工费归集与分配合理性",
                    "抽样验证单位成本计算",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
        ],
        "affected_areas": ["存货期末余额", "存货跌价准备", "主营业务成本"],
        "audit_risk": "缺失此项可能导致存货盘点证据不完整，影响存货期末余额、跌价准备及主营业务成本审计结论。",
        "concern_level": "high",
    },
    "往来科目": {
        "procedures": [
            {
                "name": "往来函证",
                "steps": [
                    "筛选重要往来单位",
                    "制作并发送函证",
                    "跟进回函并处理未回函替代程序",
                ],
                "basis": "审计准则第 1312 号 - 函证",
            },
            {
                "name": "检查期后收款/付款",
                "steps": [
                    "取得期后银行流水与往来明细",
                    "核对期后收付与期末余额匹配性",
                    "评估可回收性",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "调阅重要合同",
                "steps": [
                    "获取大额往来交易合同",
                    "核对手写/盖章效力",
                    "比对合同金额与账面一致",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
        ],
        "affected_areas": ["应收账款期末余额", "应付账款期末余额", "坏账准备"],
        "audit_risk": "缺失此项可能导致往来函证证据不完整，影响应收/应付账款期末余额与坏账准备审计结论。",
        "concern_level": "high",
    },
    "长期资产": {
        "procedures": [
            {
                "name": "实物盘点",
                "steps": [
                    "获取固定资产/在建工程明细",
                    "实地盘点重要资产",
                    "核对盘点结果与账面",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "调阅产权证明",
                "steps": [
                    "取得房产证、土地使用权证、车辆登记证",
                    "核对权利人与公司一致",
                    "查验抵押/受限情况",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "执行减值测试",
                "steps": [
                    "识别减值迹象",
                    "复核可收回金额（公允价值/未来现金流量现值）",
                    "核对减值准备计提",
                ],
                "basis": "审计准则第 1322 号 - 资产减值",
            },
        ],
        "affected_areas": ["固定资产", "无形资产", "在建工程", "减值准备"],
        "audit_risk": "缺失此项可能导致长期资产权属与减值证据不完整，影响固定资产、无形资产与减值准备审计结论。",
        "concern_level": "high",
    },
    "薪酬": {
        "procedures": [
            {
                "name": "调阅工资台账",
                "steps": [
                    "取得工资表与社保公积金台账",
                    "抽样核对至员工与银行流水",
                    "复核计提与发放差异",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "检查社保申报记录",
                "steps": [
                    "取得社保/公积金申报记录",
                    "与工资台账核对一致性",
                    "评估欠缴风险",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "抽样访谈员工",
                "steps": [
                    "随机选取员工访谈",
                    "确认在职状态与薪酬发放",
                    "记录访谈底稿",
                ],
                "basis": "审计准则第 1301 号 - 审计证据（询问）",
            },
        ],
        "affected_areas": ["应付职工薪酬", "管理费用", "销售费用"],
        "audit_risk": "缺失此项可能导致薪酬完整性证据不完整，影响应付职工薪酬与相关费用审计结论。",
        "concern_level": "medium",
    },
    "税务相关": {
        "procedures": [
            {
                "name": "调阅纳税申报表",
                "steps": [
                    "取得各税种纳税申报表",
                    "与账面计提数核对",
                    "识别差异并落实原因",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "核对税务系统数据",
                "steps": [
                    "登录电子税务局查询实际申报数据",
                    "与申报表比对",
                    "查验税款缴纳状态",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "获取税务师事务所报告",
                "steps": [
                    "取得年度涉税鉴证报告",
                    "评估专家独立性",
                    "复核与账面差异",
                ],
                "basis": "审计准则第 1421 号 - 利用专家工作",
            },
        ],
        "affected_areas": ["应交税费", "递延所得税资产", "递延所得税负债", "所得税费用"],
        "audit_risk": "缺失此项可能导致税务合规性证据不完整，影响应交税费与递延所得税资产/负债审计结论。",
        "concern_level": "high",
    },
    "收入成本": {
        "procedures": [
            {
                "name": "截止性测试",
                "steps": [
                    "取得资产负债表日前后收入/成本明细",
                    "抽取大额凭证核对收入确认时点",
                    "验证归属期间正确性",
                ],
                "basis": "审计准则第 1301 号 - 审计证据（截止性测试）",
            },
            {
                "name": "穿行测试",
                "steps": [
                    "选取典型销售交易",
                    "从订单→出库→开票→收款全流程追踪",
                    "确认控制有效性与收入确认依据",
                ],
                "basis": "审计准则第 1231 号 - 针对评估风险采取的应对措施",
            },
            {
                "name": "分析性复核",
                "steps": [
                    "对收入/成本/毛利率月度波动分析",
                    "对比同行业可比公司",
                    "识别异常波动并调查",
                ],
                "basis": "审计准则第 1313 号 - 分析程序",
            },
        ],
        "affected_areas": ["营业收入", "营业成本", "毛利率", "应收账款"],
        "audit_risk": "缺失此项可能导致收入确认证据不完整，影响营业收入、营业成本与毛利率审计结论，存在收入截止或确认风险。",
        "concern_level": "high",
    },
    "关联方": {
        "procedures": [
            {
                "name": "调阅关联交易台账",
                "steps": [
                    "取得关联方及关联交易台账",
                    "核对大额关联交易合同",
                    "抽样验证交易真实性",
                ],
                "basis": "审计准则第 1323 号 - 关联方",
            },
            {
                "name": "获取关联方声明",
                "steps": [
                    "向管理层获取关联方完整性声明",
                    "与已知关联方清单核对",
                    "识别未披露关联方",
                ],
                "basis": "审计准则第 1341 号 - 书面声明",
            },
            {
                "name": "检查交易公允性",
                "steps": [
                    "对比关联交易价格与独立第三方价格",
                    "识别异常定价",
                    "评估利益输送风险",
                ],
                "basis": "审计准则第 1323 号 - 关联方",
            },
        ],
        "affected_areas": ["关联交易披露", "关联方资金占用", "关联方往来余额"],
        "audit_risk": "缺失此项可能导致关联交易披露不完整，影响关联方审计结论，存在资金占用与利益输送风险。",
        "concern_level": "high",
    },
    "租赁类": {
        "procedures": [
            {
                "name": "实地查看租赁物",
                "steps": [
                    "对重要租赁物实地查看",
                    "确认使用状态",
                    "拍照留底",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "调阅租赁合同",
                "steps": [
                    "取得全部租赁合同",
                    "识别租赁期/租金/续租/终止条款",
                    "确认是否适用新租赁准则",
                ],
                "basis": "审计准则第 1301 号 - 审计证据",
            },
            {
                "name": "重新计算租赁负债",
                "steps": [
                    "获取折现率假设",
                    "重新计算租赁负债与使用权资产",
                    "核对与账面一致",
                ],
                "basis": "审计准则第 1301 号 - 审计证据（重新计算）",
            },
        ],
        "affected_areas": ["使用权资产", "租赁负债", "相关费用"],
        "audit_risk": "缺失此项可能导致租赁安排证据不完整，影响使用权资产与租赁负债审计结论。",
        "concern_level": "medium",
    },
}


# ----------------------------------------------------------------------
# 通用兜底（未在 KB 中明确覆盖的分类）
# ----------------------------------------------------------------------
_GENERIC_FALLBACK: dict[str, Any] = {
    "procedures": [
        {
            "name": "向客户再次索取并记录沟通过程",
            "steps": [
                "书面/邮件联系客户对接人",
                "记录催办日期与对方承诺日期",
                "若仍未取得，触发替代程序",
            ],
            "basis": "审计准则第 1301 号 - 审计证据",
        },
        {
            "name": "执行替代审计程序",
            "steps": [
                "评估缺失资料对相关科目审计结论的影响",
                "选取可替代的外部证据或第三方确认",
                "若无可替代证据，考虑保留意见或无法表示意见",
            ],
            "basis": "审计准则第 1502 号 - 在审计报告中发表非无保留意见",
        },
    ],
    "affected_areas": ["相关科目期末余额", "相关审计结论"],
    "audit_risk": "缺失此项可能导致相关科目审计证据不完整，需评估对审计意见的影响。",
    "concern_level": "medium",
}


def has_fallback_for_category(category: Optional[str]) -> bool:
    """该分类是否有专门的兜底知识库条目。"""
    return bool(category and category in _KB)


def _select_kb(item: dict[str, Any]) -> dict[str, Any]:
    """根据 item.category 选 KB 条目，未命中返回通用兜底。"""
    cat = (item or {}).get("category") or ""
    if cat and cat in _KB:
        return _KB[cat]
    return _GENERIC_FALLBACK


def get_fallback_alternative_procedures(item: dict[str, Any]) -> list[dict[str, Any]]:
    """按 category 匹配预置替代程序建议（不调 AI）。

    返回结构：
        [{"name": str, "steps": [str, ...], "basis": str}, ...]

    与 ai_client.suggest_alternative_procedures 返回的 procedures 字段一致。
    """
    kb = _select_kb(item)
    procedures = kb.get("procedures") or []
    # 深拷贝避免外部修改污染知识库
    out: list[dict[str, Any]] = []
    for p in procedures:
        out.append({
            "name": p.get("name", ""),
            "steps": list(p.get("steps", [])),
            "basis": p.get("basis", ""),
        })
    return out


def get_fallback_impact_analysis(item: dict[str, Any]) -> dict[str, Any]:
    """按 category 匹配预置影响分析（不调 AI）。

    返回结构：
        {"affected_areas": [...], "audit_risk": str, "concern_level": str,
         "source": "knowledge_base", "category": str}
    """
    kb = _select_kb(item)
    return {
        "affected_areas": list(kb.get("affected_areas", [])),
        "audit_risk": kb.get("audit_risk", ""),
        "concern_level": kb.get("concern_level", "medium"),
        "source": "knowledge_base",
        "category": (item or {}).get("category") or "",
    }


def get_fallback_escalation(item: dict[str, Any]) -> dict[str, Any]:
    """生成兜底汇报包（不调 AI）。

    用于 AI 失败时的快速兜底；与 routes_risk._build_escalation_report 输出结构对齐。
    """
    impact = get_fallback_impact_analysis(item)
    procedures = get_fallback_alternative_procedures(item)
    overdue = item.get("overdue_days") or 0

    lines: list[str] = [
        "【风险化解汇报（兜底版）】",
        f"资料编号: {item.get('item_id', '')}",
        f"资料描述: {(item.get('description') or '')[:120]}",
        f"实体: {item.get('entity', '')} | 一级分类: {item.get('category', '')}",
        f"逾期天数: {overdue} | 关注等级: {impact.get('concern_level', 'medium')}",
        "",
        "【影响分析】（来源：审计准则知识库兜底）",
        "  受影响领域: " + " / ".join(impact.get("affected_areas") or []),
        f"  审计风险: {impact.get('audit_risk', '')}",
        "",
        f"【替代程序建议】共 {len(procedures)} 条（来源：知识库兜底）",
    ]
    for i, p in enumerate(procedures, 1):
        lines.append(f"  {i}. {p.get('name', '')}")
        for s in p.get("steps", []):
            lines.append(f"     - {s}")
        if p.get("basis"):
            lines.append(f"     依据: {p['basis']}")

    lines.append("")
    lines.append("建议 Senior 复核并选择是否采纳替代程序；如不可化解，应上报 Manager。")

    return {
        "report_text": "\n".join(lines),
        "items_overdue": [item.get("item_id")] if item.get("item_id") else [],
        "total_impact": "1 个资料项",
        "concern_level": impact.get("concern_level", "medium"),
        "prepared_for": "Senior/Manager",
        "source": "knowledge_base",
    }


if __name__ == "__main__":
    # 自检
    sample = {"item_id": "货-1", "category": "货币资金", "description": "银行流水"}
    print(get_fallback_alternative_procedures(sample))
    print(get_fallback_impact_analysis(sample))
