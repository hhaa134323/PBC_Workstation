"""风险信号字典（毫秒级查表，不走 AI）。

设计目的：
让"缺料 → 影响的审计结论 → IPO 问询热度"这条链路在界面上显式呈现，
不依赖 AI 推理时间（AI 调用慢 30-120 秒，字典查表毫秒级）。

调用方：
    from app.core.risk_signal import get_risk_signal, format_risk_signal_text

字段结构（对齐 demo 脚本的"风险信号卡"）：
    category                 一级分类
    affected_conclusions    list[str]   受影响的审计结论
    ipo_inquiry_risk        high/medium/low/none   发审委问询热度
    ipo_inquiry_scenarios   list[str]   典型问询场景
    risk_signal_text        str         一句话总结（钉在卡片顶部）
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("pbc.risk_signal")


# ----------------------------------------------------------------------
# 风险信号主表（覆盖 18 类一级分类）
# ----------------------------------------------------------------------
# ipo_inquiry_risk 评级原则：
#   high    = 发审委高频问询点（关联方/收入/资金/历史沿革）
#   medium  = 常规问询点（存货/往来/税务/薪酬/长期资产）
#   low     = 辅助披露项（费用/营业外/政府补助/租赁/其他）
#   none    = 不直接影响 IPO 关键结论（期后/不适用）
_RISK_SIGNALS: dict[str, dict[str, Any]] = {
    "历史沿革": {
        "category": "历史沿革",
        "affected_conclusions": ["公司主体资格", "股权结构", "实收资本", "历史沿革披露"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "发行人主体资格是否合法存续",
            "历次股权变动是否清晰、定价是否公允",
            "实缴资本是否到位、是否存在抽逃出资",
        ],
        "risk_signal_text": "缺此项将导致公司主体资格与股权结构审计结论悬空，属 IPO 高频问询点。",
    },
    "业务及财务概览": {
        "category": "业务及财务概览",
        "affected_conclusions": ["财务报表整体列报", "管理层声明", "业务模式披露"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "发行人业务模式与经营情况披露完整性",
            "财务报表整体列报是否恰当",
        ],
        "risk_signal_text": "缺此项影响业务与财务概览披露完整性，可能触发问询。",
    },
    "货币资金": {
        "category": "货币资金",
        "affected_conclusions": ["货币资金期末余额", "现金流量表", "受限货币资金披露"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "货币资金真实性、是否存在资金占用",
            "受限资金披露是否完整（保证金/冻结/质押）",
            "大额流水异常波动的合理性",
        ],
        "risk_signal_text": "缺此项将导致货币资金真实性证据缺失，属 IPO 资金真实性问询高频点。",
    },
    "存货": {
        "category": "存货",
        "affected_conclusions": ["存货期末余额", "存货跌价准备", "主营业务成本", "存货盘点"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "存货真实性、跌价准备计提是否充分",
            "存货盘点程序是否合规",
            "主营业务成本结转是否准确",
        ],
        "risk_signal_text": "缺此项将影响存货余额与跌价准备结论，可能触发成本与减值问询。",
    },
    "往来科目": {
        "category": "往来科目",
        "affected_conclusions": ["应收账款期末余额", "应付账款期末余额", "坏账准备", "关联往来"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "应收账款账龄与坏账准备计提合理性",
            "前五大客户/供应商披露完整性",
            "是否存在通过往来科目调节利润",
        ],
        "risk_signal_text": "缺此项将影响往来余额与坏账准备结论，属 IPO 应收/应付问询高频点。",
    },
    "长期资产": {
        "category": "长期资产",
        "affected_conclusions": ["固定资产期末余额", "无形资产期末余额", "资产减值准备", "折旧摊销"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "固定资产权属与折旧方法是否恰当",
            "无形资产摊销与减值测试",
            "在建工程转固时点合理性",
        ],
        "risk_signal_text": "缺此项将影响长期资产余额与减值结论，可能触发资产质量问询。",
    },
    "薪酬": {
        "category": "薪酬",
        "affected_conclusions": ["应付职工薪酬", "管理费用", "社保公积金", "员工结构披露"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "社保公积金是否足额缴纳",
            "薪酬费用归集是否合理",
            "员工结构披露完整性",
        ],
        "risk_signal_text": "缺此项将影响薪酬费用与社保披露结论，可能触发合规问询。",
    },
    "税务相关": {
        "category": "税务相关",
        "affected_conclusions": ["应交税费", "递延所得税资产", "递延所得税负债", "税收优惠"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "税收优惠是否合法有效、是否可持续",
            "递延所得税资产/负债计算是否准确",
            "是否存在税务处罚或重大税务风险",
        ],
        "risk_signal_text": "缺此项将影响税费与税收优惠结论，属 IPO 税务合规问询高频点。",
    },
    "收入成本": {
        "category": "收入成本",
        "affected_conclusions": ["营业收入", "营业成本", "毛利率", "收入截止性"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "收入确认政策是否符合新收入准则",
            "收入截止性、是否存在跨期调节",
            "毛利率波动合理性、与同行业比较",
            "前五大客户收入集中度",
        ],
        "risk_signal_text": "缺此项将影响收入确认与截止性结论，属 IPO 收入真实性问询核心点。",
    },
    "成本": {
        "category": "成本",
        "affected_conclusions": ["主营业务成本", "制造费用分配", "成本结转"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "成本结转方法是否一致、是否准确",
            "制造费用分配合理性",
        ],
        "risk_signal_text": "缺此项将影响成本结转准确性结论，可能触发成本问询。",
    },
    "营业外收支": {
        "category": "营业外收支",
        "affected_conclusions": ["营业外收入", "营业外支出", "非经常性损益"],
        "ipo_inquiry_risk": "low",
        "ipo_inquiry_scenarios": [
            "营业外收支真实性、是否有政府补助性质",
            "非经常性损益披露完整性",
        ],
        "risk_signal_text": "缺此项影响营业外收支与非经常性损益披露，属辅助披露项。",
    },
    "政府补助": {
        "category": "政府补助",
        "affected_conclusions": ["其他收益", "递延收益", "政府补助披露"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "政府补助是否与资产/收益相关",
            "递延收益摊销是否合理",
            "是否构成发行人主要利润来源",
        ],
        "risk_signal_text": "缺此项影响政府补助与递延收益结论，可能触发补助依赖问询。",
    },
    "费用": {
        "category": "费用",
        "affected_conclusions": ["管理费用", "销售费用", "研发费用", "期间费用披露"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "期间费用归集是否准确、波动合理性",
            "研发费用资本化与费用化划分",
            "是否存在费用跨期调节",
        ],
        "risk_signal_text": "缺此项影响期间费用归集结论，可能触发费用问询。",
    },
    "关联方": {
        "category": "关联方",
        "affected_conclusions": ["关联交易披露", "关联方资金占用", "关联方关系披露"],
        "ipo_inquiry_risk": "high",
        "ipo_inquiry_scenarios": [
            "关联方关系披露是否完整、是否存在未披露关联方",
            "关联交易定价是否公允、是否通过关联方调节利润",
            "是否存在关联方资金占用（IPO 红线）",
        ],
        "risk_signal_text": "缺此项将导致关联方披露结论悬空，属 IPO 关联交易与资金占用问询最高频点。",
    },
    "租赁类": {
        "category": "租赁类",
        "affected_conclusions": ["使用权资产", "租赁负债", "租赁披露"],
        "ipo_inquiry_risk": "low",
        "ipo_inquiry_scenarios": [
            "新租赁准则适用是否恰当",
            "使用权资产与租赁负债计量",
        ],
        "risk_signal_text": "缺此项影响租赁准则适用结论，属辅助披露项。",
    },
    "短期借款": {
        "category": "短期借款",
        "affected_conclusions": ["短期借款", "利息费用", "借款披露"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "短期借款真实性与抵押情况",
            "利息费用计算与资本化划分",
            "是否存在逾期借款",
        ],
        "risk_signal_text": "缺此项影响借款与利息费用结论，可能触发负债问询。",
    },
    "期后": {
        "category": "期后",
        "affected_conclusions": ["期后事项披露", "持续经营"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": [
            "期后事项披露是否完整",
            "是否存在影响持续经营的重大事项",
        ],
        "risk_signal_text": "缺此项影响期后事项披露结论，可能触发持续经营问询。",
    },
    "其他": {
        "category": "其他",
        "affected_conclusions": ["其他披露事项"],
        "ipo_inquiry_risk": "low",
        "ipo_inquiry_scenarios": ["其他披露事项完整性"],
        "risk_signal_text": "缺此项影响其他披露事项，属辅助披露项。",
    },
}


# ----------------------------------------------------------------------
# 公共 API
# ----------------------------------------------------------------------
def get_risk_signal(item: dict[str, Any]) -> dict[str, Any]:
    """根据 item 的 category（一级分类）查风险信号字典。

    毫秒级返回，不调 AI。返回结构固定（前端可直接消费）：

        {
            "category": str,
            "affected_conclusions": list[str],
            "ipo_inquiry_risk": "high"|"medium"|"low"|"none",
            "ipo_inquiry_scenarios": list[str],
            "risk_signal_text": str,
            "source": "risk_signal_dictionary",  # 标识来源
        }

    未知 category 时返回兜底结构，不抛异常。
    """
    category = (item.get("category") or "").strip()
    if category in _RISK_SIGNALS:
        return dict(_RISK_SIGNALS[category])

    # 兜底：未在字典中，给出最通用结论
    return {
        "category": category or "(未分类)",
        "affected_conclusions": ["相关审计结论"],
        "ipo_inquiry_risk": "medium",
        "ipo_inquiry_scenarios": ["相关披露完整性"],
        "risk_signal_text": f"缺此项可能影响 {category or '相关科目'} 审计证据完整性，建议人工评估。",
        "source": "risk_signal_dictionary_fallback",
    }


def format_risk_signal_brief(item: dict[str, Any]) -> str:
    """一句话简报，用于 dashboard 超期列表的 risk_signal_text 列。

    例：「关-1 — 未提供 186 天 — 影响：关联方披露」
    """
    rs = get_risk_signal(item)
    item_id = item.get("item_id", "")
    overdue = item.get("overdue_days") or 0
    # 取受影响结论第一条做简报
    first_conclusion = (rs.get("affected_conclusions") or ["相关审计结论"])[0]
    return f"{item_id} — 未提供 {overdue} 天 — 影响：{first_conclusion}"


def get_ipo_inquiry_risk_label(level: str) -> str:
    """把 risk 等级翻译成中文标签。"""
    return {
        "high": "高频",
        "medium": "常规",
        "low": "辅助",
        "none": "无",
    }.get(level, "常规")


def has_risk_signal(category: str) -> bool:
    """category 是否在字典中（用于判断是否走兜底）。"""
    return category in _RISK_SIGNALS


__all__ = [
    "get_risk_signal",
    "format_risk_signal_brief",
    "get_ipo_inquiry_risk_label",
    "has_risk_signal",
]
