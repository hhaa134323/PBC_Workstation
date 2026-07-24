"""PBC 文件匹配打分模块（多字段加权 + 三档决策）。

借鉴银行对账（三档匹配）、Fellegi-Sunter 概率匹配模型（多字段加权），
用 4 个字段加权打分决定：自动匹配 / 建议匹配（需人确认）/ LLM 兜底。

字段权重（v7.4）：
  F1: 文件夹名 vs category（一级分类）     W1=0.25
  F2: 文件名 vs doc_name（资料名称）        W2=0.40  ← 最可靠信号
  F3: 文件名+内容头 vs description          W3=0.20  N-gram Jaccard
  F4: 文件夹名/文件名 vs required_period    W4=0.15  年份匹配

三档决策：
  total > 0.75  → 自动匹配（不调 LLM）
  0.4-0.75     → 建议匹配（toast 推审计员确认）
  < 0.4        → LLM 兜底（调百炼）

穿行测试前置检测：
  文件夹名含"穿行/截图/签字/回单/控制" → 走整目录归档，不逐文件打分
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("pbc.matcher")

# 权重
W1_CATEGORY = 0.25
W2_DOC_NAME = 0.40
W3_DESCRIPTION = 0.20
W4_PERIOD = 0.15

# 阈值
THRESHOLD_AUTO = 0.70
THRESHOLD_SUGGEST = 0.30

# 穿行测试关键词
WALKTHROUGH_KEYWORDS = {"穿行", "截图", "签字", "回单", "控制", "内控", "walkthrough", "wt"}


def _ngrams(text: str, n: int = 2) -> set[str]:
    """生成 N-gram 字符集合（2-gram，中英文兼容）。

    不依赖 jieba 分词，纯字符滑窗。
    如 "银行流水" → {"银行", "行流", "流水"}
    """
    if not text:
        return set()
    # 去标点、空格、扩展名
    text = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    if len(text) < n:
        return {text} if text else set()
    return {text[i:i+n] for i in range(len(text) - n + 1)}


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard 相似度 = 交集 / 并集。"""
    if not set_a and not set_b:
        return 0.0
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / len(union)


def _extract_folder_names(file_path: Path, client_folder: Optional[Path] = None) -> list[str]:
    """提取文件所在的所有上级文件夹名（不含文件名本身）。

    如 /客户文件夹/财务报表/合并资产负债表.xlsx → ["财务报表"]
    如 /客户文件夹/2023年度/银行流水.xlsx → ["2023年度"]
    如 /客户文件夹/盘点计划.pdf → []
    """
    try:
        if client_folder:
            rel = file_path.relative_to(client_folder)
        else:
            rel = Path(file_path.name)
    except ValueError:
        return []

    parts = rel.parts
    # parts[-1] 是文件名，去掉
    folders = list(parts[:-1]) if len(parts) > 1 else []
    return folders


def _extract_years(text: str) -> set[str]:
    """从文本中提取年份（4位数字）。"""
    if not text:
        return set()
    return set(re.findall(r"\d{4}", text))


def _score_folder_vs_category(
    file_path: Path,
    pbc_item: dict[str, Any],
    client_folder: Optional[Path] = None,
) -> float:
    """F1: 文件夹名 vs 一级分类(category)。

    文件夹名完全包含 category → 1.0
    文件夹名跟 category 有部分重叠（N-gram Jaccard）→ 0-1
    没有文件夹（根目录文件）→ 0
    """
    folders = _extract_folder_names(file_path, client_folder)
    if not folders:
        return 0.0

    category = pbc_item.get("category") or ""
    if not category:
        return 0.0

    # 精确匹配优先
    for f in folders:
        if category in f or f in category:
            return 1.0

    # N-gram 包含率（category 的 grams 有多少出现在文件夹名里）
    cat_grams = _ngrams(category, 2)
    best = 0.0
    for f in folders:
        f_grams = _ngrams(f, 2)
        if not cat_grams or not f_grams:
            continue
        overlap = cat_grams & f_grams
        containment = len(overlap) / len(cat_grams)
        if containment > best:
            best = containment
    return best


def _score_filename_vs_docname(
    file_path: Path,
    pbc_item: dict[str, Any],
) -> float:
    """F2: 文件名 vs 资料名称(doc_name)。

    文件名（去扩展名）完全包含 doc_name → 1.0
    N-gram Jaccard 模糊匹配 → 0-1
    """
    doc_name = pbc_item.get("doc_name") or ""
    if not doc_name:
        # 退化到 description
        doc_name = pbc_item.get("description") or ""
    if not doc_name:
        return 0.0

    filename = file_path.stem  # 去扩展名
    if not filename:
        return 0.0

    # 精确包含
    if doc_name in filename or filename in doc_name:
        return 1.0

    # N-gram 包含率（doc_name 的 grams 有多少出现在 filename 里）
    name_grams = _ngrams(filename, 2)
    doc_grams = _ngrams(doc_name, 2)
    if not name_grams or not doc_grams:
        return 0.0
    overlap = doc_grams & name_grams
    containment = len(overlap) / len(doc_grams)
    return containment


def _score_content_vs_description(
    file_text: str,
    file_path: Path,
    pbc_item: dict[str, Any],
) -> float:
    """F3: 文件名+内容头200字 vs description 关键词重叠。

    用 N-gram 包含率（description 的 grams 有多少出现在文件内容里）。
    """
    description = pbc_item.get("description") or ""
    if not description:
        return 0.0

    # 合并文件名 + 内容头
    text = (file_path.stem + " " + (file_text or "")[:200]).strip()
    if not text:
        return 0.0

    text_grams = _ngrams(text, 2)
    desc_grams = _ngrams(description, 2)
    if not text_grams or not desc_grams:
        return 0.0
    overlap = desc_grams & text_grams
    return len(overlap) / len(desc_grams)


def _score_folder_vs_period(
    file_path: Path,
    pbc_item: dict[str, Any],
    client_folder: Optional[Path] = None,
) -> float:
    """F4: 文件夹名/文件名 vs 报告期间(required_period)。

    从文件夹名和文件名中提取年份，
    跟 required_period 里的年份做交集比例。
    """
    required_period = pbc_item.get("required_period") or ""
    if not required_period:
        return 0.0

    # 从清单项的 required_period 提取年份
    item_years = _extract_years(required_period)
    if not item_years:
        return 0.0

    # 从文件夹名+文件名提取年份
    folders = _extract_folder_names(file_path, client_folder)
    all_text = " ".join(folders) + " " + file_path.name
    file_years = _extract_years(all_text)

    if not file_years:
        return 0.0

    # 交集比例
    overlap = file_years & item_years
    return len(overlap) / len(item_years)


def is_walkthrough_folder(
    file_path: Path,
    client_folder: Optional[Path] = None,
) -> bool:
    """穿行测试前置检测：文件夹名含关键词 → 整目录归档。

    检测文件所在的所有上级文件夹名是否含穿行测试关键词。
    """
    folders = _extract_folder_names(file_path, client_folder)
    if not folders:
        return False

    for f in folders:
        f_lower = f.lower()
        for kw in WALKTHROUGH_KEYWORDS:
            if kw in f_lower:
                return True
    return False


def score_file(
    file_path: Path,
    pbc_items: list[dict[str, Any]],
    file_text: str = "",
    client_folder: Optional[Path] = None,
) -> dict[str, Any]:
    """对文件打分，返回最佳匹配项 + 得分明细。

    遍历所有 PBC 清单项，计算 4 字段加权总分，取最高分项。

    Returns:
        {
            "item_id": "历-1" or None,
            "confidence": 0.0-1.0,
            "decision": "auto" | "suggest" | "llm",
            "best_item": {...} or None,
            "score_breakdown": {
                "F1_folder_vs_category": 0.25,
                "F2_filename_vs_doc_name": 0.32,
                "F3_content_vs_description": 0.14,
                "F4_folder_vs_period": 0,
                "total": 0.71,
            },
            "all_scores": [{"item_id": "历-1", "total": 0.71}, ...],
        }
    """
    if not pbc_items:
        return {
            "item_id": None,
            "confidence": 0.0,
            "decision": "llm",
            "best_item": None,
            "score_breakdown": {},
            "all_scores": [],
        }

    all_scores: list[dict[str, Any]] = []
    best_score = 0.0
    best_item: Optional[dict[str, Any]] = None
    best_breakdown: dict[str, float] = {}

    for item in pbc_items:
        f1 = _score_folder_vs_category(file_path, item, client_folder)
        f2 = _score_filename_vs_docname(file_path, item)
        f3 = _score_content_vs_description(file_text, file_path, item)
        f4 = _score_folder_vs_period(file_path, item, client_folder)

        total = (
            f1 * W1_CATEGORY
            + f2 * W2_DOC_NAME
            + f3 * W3_DESCRIPTION
            + f4 * W4_PERIOD
        )

        breakdown = {
            "F1_folder_vs_category": round(f1 * W1_CATEGORY, 4),
            "F2_filename_vs_doc_name": round(f2 * W2_DOC_NAME, 4),
            "F3_content_vs_description": round(f3 * W3_DESCRIPTION, 4),
            "F4_folder_vs_period": round(f4 * W4_PERIOD, 4),
            "total": round(total, 4),
        }

        all_scores.append({
            "item_id": item.get("item_id", ""),
            "doc_name": item.get("doc_name", ""),
            "total": round(total, 4),
            "breakdown": breakdown,
        })

        if total > best_score:
            best_score = total
            best_item = item
            best_breakdown = breakdown

    # 三档决策
    if best_score > THRESHOLD_AUTO:
        decision = "auto"
    elif best_score >= THRESHOLD_SUGGEST:
        decision = "suggest"
    else:
        decision = "llm"

    # all_scores 按总分降序
    all_scores.sort(key=lambda x: x["total"], reverse=True)

    return {
        "item_id": best_item.get("item_id") if best_item else None,
        "confidence": round(best_score, 4),
        "decision": decision,
        "best_item": best_item,
        "score_breakdown": best_breakdown,
        "all_scores": all_scores[:5],  # 只返回 top 5 供调试
    }
