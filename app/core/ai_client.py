"""AI 客户端封装（M3 实现）。

百炼平台 OpenAI 兼容模式：
- 同步 httpx + @retry(times=3, timeout=30)
- LRU 缓存 100 条（key = SHA-256(prompt+model)）
- 失败降级返回 {"ok": False, "error": "...", "model": ...}
- 成功调用写入 SQLite ai_history（item_id 可为占位符如 "file-xxx"）

模型分工（思路 12.2）：
- classification / reasoning: glm-5
- vision:                     qwen3-vl-plus
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import httpx

from app.config import get_config
from app.core.db import get_conn
from app.utils.retry import retry

logger = logging.getLogger("pbc.ai_client")


def _get_ca_bundle():
    """获取 CA 证书路径。

    PyInstaller 打包后 Python ssl 模块可能找不到系统 CA 证书链，
    显式用 certifi 的 cacert.pem 作为 verify 参数。
    """
    try:
        import certifi
        return certifi.where()
    except Exception:
        # 打包环境 certifi 可能不在默认搜索路径，尝试手动定位
        try:
            # PyInstaller 打包后 _MEIPASS 或 _internal 目录
            base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent.parent.parent))
            cacert = base / 'certifi' / 'cacert.pem'
            if cacert.exists():
                return str(cacert)
            # 也可能是 _internal/certifi/cacert.pem
            cacert2 = base / '_internal' / 'certifi' / 'cacert.pem'
            if cacert2.exists():
                return str(cacert2)
        except Exception:
            pass
    return True  # 回退到默认行为

# 模型默认值（v7.7: 可被 api_config.json 覆盖）
MODEL_CLASSIFICATION = "qwen-plus"
MODEL_VISION          = "qwen-plus"  # v7.7: 不区分 vision，用同一个模型

# 默认期望期间（思路 16.x：客户财务报表以 2025-12-31 为基准日）
DEFAULT_EXPECTED_PERIOD = "2025年12月31日"


def _load_model_from_config() -> str:
    """从 api_config.json 读 model 字段，读不到用默认 qwen-plus。

    v7.7: 用户可在 AI 配置面板「高级选项」里改模型名。
    """
    try:
        from app.api.routes_config import _load_raw_config
        raw = _load_raw_config()
        bl = raw.get("bailian") or {}
        m = bl.get("model")
        if m and isinstance(m, str) and m.strip():
            return m.strip()
    except Exception as e:
        logger.debug("读取 model 配置失败用默认: %r", e)
    return MODEL_CLASSIFICATION


def _get_model() -> str:
    """获取当前模型名（每次调用都读配置，支持热切换）。"""
    return _load_model_from_config()



def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class _LRUCache:
    """线程安全的简易 LRU 缓存。"""

    def __init__(self, capacity: int = 100) -> None:
        self._cap = capacity
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
            self._data[key] = value
            while len(self._data) > self._cap:
                self._data.popitem(last=False)


# 全局共享缓存（进程内 100 条）
_cache: _LRUCache = _LRUCache(capacity=100)


class AIClient:
    """百炼（OpenAI 兼容模式）客户端封装。"""

    def __init__(self) -> None:
        cfg = get_config()
        self.api_key: str = cfg.bailian.api_key
        self.base_url: str = cfg.bailian.base_url
        self.timeout: int = cfg.ai_timeout_seconds
        self.retry_count: int = cfg.ai_retry_count

    # ------------------------------------------------------------------
    # 基础校验
    # ------------------------------------------------------------------
    def validate_api_key(self) -> tuple[bool, str]:
        """仅格式校验，不发实际请求（启动时使用）。"""
        if not self.api_key:
            return False, "API Key 为空（请检查 config/api_config.json）"
        if not self.api_key.startswith("sk-"):
            return False, "API Key 前缀异常（应以 sk- 开头）"
        if len(self.api_key) < 16:
            return False, "API Key 长度异常（过短）"
        return True, "API Key 格式 OK（未发起实际请求）"

    # P0-7: 启动时调一次真实 API 校验
    def verify_api_key_online(self) -> tuple[bool, str]:
        """启动时调一次真实 API 校验。

        发一次最小请求（messages=[{"role":"user","content":"ping"}], max_tokens=1）
        看是否返回 200。401/403 视为 Key 失效。
        """
        if not self.api_key:
            return False, "API Key 为空"
        try:
            with httpx.Client(timeout=self.timeout, verify=_get_ca_bundle()) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": MODEL_CLASSIFICATION,
                        "messages": [{"role": "user", "content": "ping"}],
                        "temperature": 0,
                        "max_tokens": 1,
                    },
                )
            if resp.status_code == 200:
                return True, "API Key 在线校验通过"
            if resp.status_code in (401, 403):
                return False, f"API Key 失效（HTTP {resp.status_code}）：请检查 config/api_config.json"
            return False, f"API Key 在线校验失败（HTTP {resp.status_code}）：{resp.text[:200]}"
        except Exception as e:
            return False, f"API Key 在线校验异常: {type(e).__name__}: {e}"

    # P0-7: 401 回调钩子（main.py 启动时注入）
    _on_key_invalidated: Optional[callable] = None

    @classmethod
    def set_key_invalid_callback(cls, callback) -> None:
        """注入 API Key 失效回调（main.py 启动时调用）。

        回调签名: () -> None，无返回值。main.py 用于停止 watchdog + 写日志。
        """
        cls._on_key_invalidated = callback

    def _notify_key_invalidated(self, reason: str) -> None:
        """检测到 401/403 时触发回调（仅触发一次，避免反复打挂的接口）。"""
        if AIClient._on_key_invalidated is None:
            return
        try:
            AIClient._on_key_invalidated()
            logger.error("API Key 失效回调已触发: %s", reason)
            # 触发一次后清空，避免重复
            AIClient._on_key_invalidated = None
        except Exception as e:
            logger.warning("API Key 失效回调异常: %r", e)

    # ------------------------------------------------------------------
    # 底层 chat 调用
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: list[dict[str, Any]],
        model: str = MODEL_CLASSIFICATION,
        temperature: float = 0.3,
        item_id: str = "",
        action: str = "chat",
        json_mode: bool = False,
    ) -> dict[str, Any]:
        """OpenAI 兼容 chat 调用。

        Args:
            messages: OpenAI 标准消息列表
            model: 模型 id
            temperature: 0-1
            item_id: 用于 ai_history 记录（可空/占位）
            action: 用于 ai_history 记录
            json_mode: True=强制 JSON 输出（response_format）

        Returns:
            {"ok": True, "content": "...", "model": "...", "raw": {...}}
            {"ok": False, "error": "...", "model": "..."}
        """
        # 缓存键：模型 + 消息哈希 + json_mode
        cache_key = _sha256(
            json.dumps({"model": model, "messages": messages, "temperature": temperature, "json_mode": json_mode},
                       ensure_ascii=False, sort_keys=True)
        )
        cached = _cache.get(cache_key)
        if cached is not None:
            logger.info("chat cache hit model=%s action=%s", model, action)
            return cached

        if not self.api_key:
            result = {"ok": False, "error": "API Key 未配置", "model": model}
            self._record_history(item_id, action, messages, result, None, model)
            return result

        prompt_preview = self._messages_to_text(messages)

        @retry(times=self.retry_count, timeout=self.timeout, delay=1.0)
        def _do_request() -> dict[str, Any]:
            # httpx 同步客户端（@retry 是同步装饰器，故不用 async）
            with httpx.Client(timeout=self.timeout, verify=_get_ca_bundle()) as client:
                body = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                # v7.7: JSON mode（OpenAI 标准，强制模型输出 JSON）
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
                # P0-7: 401/403 直接判定 Key 失效，触发回调后不再 retry
                if resp.status_code in (401, 403):
                    self._notify_key_invalidated(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                    # 直接返回失败结果，不抛异常避免 retry
                    return {
                        "ok": False,
                        "error": f"API Key 失效（HTTP {resp.status_code}）",
                        "model": model,
                        "key_invalidated": True,
                    }
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                data = resp.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                return {
                    "ok": True,
                    "content": content,
                    "model": model,
                    "raw": data,
                }

        try:
            result = _do_request()
        except Exception as e:
            logger.warning("chat 调用失败 model=%s action=%s: %r", model, action, e)
            result = {"ok": False, "error": f"{type(e).__name__}: {e}", "model": model}

        # 写缓存（失败也缓存，避免反复打挂的接口；TTL 由 LRU 容量间接保证）
        _cache.put(cache_key, result)

        # 写 SQLite ai_history
        confidence = self._extract_confidence(result)
        self._record_history(item_id, action, prompt_preview, result, confidence, model)

        return result

    # ------------------------------------------------------------------
    # 高层业务方法
    # ------------------------------------------------------------------
    def classify_file(
        self,
        file_text: str,
        pbc_items: list[dict[str, Any]],
        file_hint: str = "",
    ) -> dict[str, Any]:
        """环节2：识别归类。

        v7 加强：
        - 候选清单纳入 required_period（AI 可对照文件内容期间）
        - prompt 加"判断基础资料 vs 穿行测试证据"指引
        - 文件名作为分类因素（已有 filename-match 快路径，这里加强 AI fallback 的文件名权重）

        Args:
            file_text: 文件文本内容（前 3000 字）
            pbc_items: PBC 候选项 list[dict]
            file_hint: 文件名/路径提示（可空）

        Returns:
            {"ok": True, "item_id": "历-1", "confidence": 0.87, "reason": "...", "model": "glm-5"}
        """
        text = (file_text or "")[:3000]
        candidates = []
        for it in pbc_items or []:
            candidates.append({
                "item_id":         it.get("item_id", ""),
                "category":        it.get("category", ""),
                "entity":          it.get("entity", ""),
                "description":      (it.get("description") or "")[:200],
                "required_period":  it.get("required_period") or "",
            })

        prompt = (
            "你是 IPO 审计 PBC 资料分类助手。请基于文件内容判断它对应 PBC 清单中哪一项。\n\n"
            f"【文件名/路径提示（重要分类因素）】：{file_hint or '(未提供)'}\n"
            "  - 文件名常含清单编号前缀（如 历-1_股权架构图.pdf 对应 item_id=历-1）\n"
            "  - 文件名含 穿行/WT/控制点/系统截图 等字样 → 多为穿行测试证据\n"
            "  - 文件名含 合同/章程/决议/报表/明细账/流水 等 → 多为基础资料\n\n"
            f"【文件内容（前 3000 字）】：\n{text}\n\n"
            f"【PBC 清单候选（共 {len(candidates)} 项，含需求期间）】：\n"
            f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n\n"
            "【分类规则】：\n"
            "1. 优先用文件名匹配候选 item_id（文件名含编号前缀直接命中）\n"
            "2. 文件名无编号前缀时，用文件内容 + description 语义匹配\n"
            "3. 如果候选的 required_period 不为空，检查文件内容期间是否覆盖（影响置信度）\n"
            "4. 判断该资料是「基础资料」还是「穿行测试证据」（影响归档目录）\n\n"
            "请输出 JSON 格式：{\"item_id\": \"对应清单项的编号\", "
            "\"confidence\": 0.0-1.0, \"reason\": \"判断依据\", "
            "\"doc_type\": \"basic|walkthrough|unknown\"}\n"
            "如果都不能匹配，输出 {\"item_id\": null, \"confidence\": 0.0, "
            "\"reason\": \"无法识别\", \"doc_type\": \"unknown\"}\n"
            "注意：只输出 JSON，不要任何其他文字。"
        )

        placeholder_id = (
            candidates[0]["item_id"] if candidates else "file-unknown"
        )
        result = self.chat(
            messages=[
                {"role": "system", "content": "你是 IPO 审计 PBC 资料分类助手，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=_get_model(),
            temperature=0.1,
            item_id=placeholder_id,
            action="classify_file",
            json_mode=True,
        )

        if not result.get("ok"):
            return result

        parsed = self._safe_json(result.get("content", ""))
        item_id = parsed.get("item_id") if parsed else None
        confidence = float(parsed.get("confidence", 0.0)) if parsed else 0.0
        reason = (parsed.get("reason") if parsed else "") or result.get("content", "")[:500]
        doc_type = (parsed.get("doc_type") if parsed else "") or "unknown"

        return {
            "ok": True,
            "model": MODEL_CLASSIFICATION,
            "item_id": item_id,
            "confidence": confidence,
            "reason": reason,
            "doc_type": doc_type,
            "advisory_notes": self._build_classify_advisory_notes(item_id, confidence, reason),
        }

    def _build_classify_advisory_notes(
        self, item_id: Optional[str], confidence: float, reason: str,
    ) -> list[dict[str, Any]]:
        """根据 classify_file 结果生成 advisory_notes（供前端 toast 推送）。

        返回 list[{level, message, action}]
        - level: high / medium / low
        - message: 自然语言提示
        - action: 建议用户做的事
        """
        notes: list[dict[str, Any]] = []
        # 规则 1：置信度偏低
        if confidence < 0.7:
            level = "high" if confidence < 0.5 else "medium"
            notes.append({
                "level": level,
                "trigger": "confidence_low",
                "message": f"这份文件 AI 匹配置信度 {confidence:.2f}（偏低），原因：{(reason or '未知')[:60]}。建议人工确认",
                "action": "人工确认对应 PBC 清单项",
                "item_id": item_id,
            })
        # 规则 2：未识别
        if not item_id:
            notes.append({
                "level": "high",
                "trigger": "unmatched",
                "message": "AI 无法识别这份文件对应 PBC 清单哪一项，建议人工查看后指定对应编号",
                "action": "人工指定对应清单项编号",
                "item_id": None,
            })
        return notes

    def check_period_completeness(
        self,
        file_text: str,
        expected_period: str = DEFAULT_EXPECTED_PERIOD,
    ) -> dict[str, Any]:
        """环节2：期间连续性检查（简单版）。"""
        text = (file_text or "")[:3000]
        prompt = (
            "请检查以下文件内容是否覆盖期望期间。\n\n"
            f"文件内容：\n{text}\n\n"
            f"期望期间：{expected_period}\n\n"
            "输出 JSON：{\"covered\": true/false, "
            "\"detected_periods\": [...], "
            "\"missing\": [...], "
            "\"reason\": \"...\"}\n"
            "注意：只输出 JSON，不要任何其他文字。"
        )
        result = self.chat(
            messages=[
                {"role": "system", "content": "你是审计期间完整性检查助手，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=_get_model(),
            temperature=0.1,
            item_id=f"period-{_sha256(text)[:8]}",
            action="check_period_completeness",
        )
        if not result.get("ok"):
            return result

        parsed = self._safe_json(result.get("content", ""))
        covered = bool(parsed.get("covered")) if parsed else False
        detected = parsed.get("detected_periods", []) if parsed else []
        missing = parsed.get("missing", []) if parsed else []
        reason = (parsed.get("reason") if parsed else "") or result.get("content", "")[:500]

        return {
            "ok": True,
            "model": MODEL_CLASSIFICATION,
            "covered": covered,
            "detected_periods": detected,
            "missing": missing,
            "reason": reason,
            # v4 新增：advisory_notes 供前端 toast 推送用
            "advisory_notes": self._build_period_advisory_notes(covered, detected, missing, reason),
        }

    def _build_period_advisory_notes(
        self, covered: bool, detected: list, missing: list, reason: str,
    ) -> list[dict[str, Any]]:
        """根据 check_period_completeness 结果生成 advisory_notes。"""
        notes: list[dict[str, Any]] = []
        if not covered and missing:
            notes.append({
                "level": "high",  # 高优先级，前端 toast 常驻
                "trigger": "period_gap",
                "message": f"这份资料期间不完整，覆盖 {detected or []}，缺 {missing}。建议退回客户补料",
                "action": "退回客户补料",
            })
        elif not covered:
            notes.append({
                "level": "medium",
                "trigger": "period_uncertain",
                "message": "AI 无法判断这份资料是否覆盖期望期间，建议人工查看",
                "action": "人工查看期间覆盖情况",
            })
        return notes

    def suggest_alternative_procedures(
        self,
        item: dict[str, Any],
        gap_context: dict[str, Any],
    ) -> dict[str, Any]:
        """环节5：替代程序建议（基于审计准则）。"""
        prompt = (
            "你是 IPO 审计替代程序建议助手，依据《中国注册会计师审计准则》。\n\n"
            f"缺失资料编号：{item.get('item_id', '')}\n"
            f"缺失资料描述：{item.get('description', '')}\n"
            f"资料类型：{item.get('category', '')} / {item.get('subject', '')}\n"
            f"逾期天数：{gap_context.get('overdue_days', '')}\n"
            f"影响范围：{gap_context.get('affected_areas', '')}\n\n"
            "请基于审计准则，给出 1-3 条替代审计程序建议。\n\n"
            "输出 JSON：{\n"
            "  \"procedures\": [\n"
            "    {\"name\": \"程序名\", \"steps\": [\"步骤1\", \"步骤2\"], "
            "\"basis\": \"审计准则第 X 号 - 适用条款\"}\n"
            "  ],\n"
            "  \"impact_summary\": \"缺失此项可能导致...审计结论...\",\n"
            "  \"concern_level\": \"high/medium/low\"\n"
            "}\n"
            "注意：只输出 JSON，不要任何其他文字。"
        )
        result = self.chat(
            messages=[
                {"role": "system", "content": "你是 IPO 审计替代程序建议助手，依据《中国注册会计师审计准则》，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=MODEL_REASONING,
            temperature=0.3,
            item_id=item.get("item_id", "unknown"),
            action="suggest_alternative_procedures",
        )
        if not result.get("ok"):
            return result

        parsed = self._safe_json(result.get("content", ""))
        if not parsed:
            return {
                "ok": True,
                "model": MODEL_REASONING,
                "procedures": [],
                "impact_summary": result.get("content", "")[:500],
                "concern_level": "medium",
                "raw": result.get("content", ""),
            }
        return {
            "ok": True,
            "model": MODEL_REASONING,
            "procedures": parsed.get("procedures", []),
            "impact_summary": parsed.get("impact_summary", ""),
            "concern_level": parsed.get("concern_level", "medium"),
        }

    def analyze_impact(self, item: dict[str, Any]) -> dict[str, Any]:
        """环节5：影响分析。"""
        prompt = (
            "你是 IPO 审计影响分析助手。\n\n"
            f"缺失资料编号：{item.get('item_id', '')}\n"
            f"缺失资料描述：{item.get('description', '')}\n"
            f"资料类型：{item.get('category', '')} / {item.get('subject', '')}\n"
            f"逾期天数：{item.get('overdue_days', '')}\n\n"
            "请分析缺失此项对哪些审计科目/结论造成影响。\n\n"
            "输出 JSON：{\n"
            "  \"affected_areas\": [\"科目1\", \"科目2\"],\n"
            "  \"audit_risk\": \"缺失此项可能导致...的审计风险\",\n"
            "  \"concern_level\": \"high/medium/low\"\n"
            "}\n"
            "注意：只输出 JSON，不要任何其他文字。"
        )
        result = self.chat(
            messages=[
                {"role": "system", "content": "你是 IPO 审计影响分析助手，输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            model=MODEL_REASONING,
            temperature=0.3,
            item_id=item.get("item_id", "unknown"),
            action="analyze_impact",
        )
        if not result.get("ok"):
            return result

        parsed = self._safe_json(result.get("content", ""))
        if not parsed:
            return {
                "ok": True,
                "model": MODEL_REASONING,
                "affected_areas": [],
                "audit_risk": result.get("content", "")[:500],
                "concern_level": "medium",
            }
        return {
            "ok": True,
            "model": MODEL_REASONING,
            "affected_areas": parsed.get("affected_areas", []),
            "audit_risk": parsed.get("audit_risk", ""),
            "concern_level": parsed.get("concern_level", "medium"),
        }

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------
    @staticmethod
    def _messages_to_text(messages: list[dict[str, Any]]) -> str:
        """把 messages 拼成纯文本（用于 ai_history.prompt 字段）。"""
        try:
            return json.dumps(messages, ensure_ascii=False)[:4000]
        except Exception:
            return str(messages)[:4000]

    @staticmethod
    def _safe_json(text: str) -> Optional[dict[str, Any]]:
        """从可能包含 markdown 代码块或前后噪声的字符串中提取 JSON。"""
        if not text:
            return None
        s = text.strip()
        # 去掉 markdown 代码块
        if s.startswith("```"):
            # 去掉首行 ```json 或 ```
            lines = s.split("\n")
            if lines:
                lines = lines[1:] if lines[0].strip().startswith("```") else lines
            # 去掉末尾 ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        # 直接尝试
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            pass
        # 提取首个 {...} 块
        m = re.search(r"\{.*\}", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        return None

    @staticmethod
    def _extract_confidence(result: dict[str, Any]) -> Optional[float]:
        """从 chat 结果中尽量抽出 confidence 数值（用于 ai_history 索引）。"""
        # classify_file/check_period 的成功结果外层就有 confidence
        if "confidence" in result:
            try:
                return float(result["confidence"])
            except (TypeError, ValueError):
                return None
        return None

    @staticmethod
    def _record_history(
        item_id: str,
        action: str,
        prompt: str,
        result: dict[str, Any],
        confidence: Optional[float],
        model: str,
    ) -> None:
        """写 SQLite ai_history（失败不抛）。"""
        try:
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO ai_history
                       (item_id, action, prompt, response, confidence, model)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        item_id or "",
                        action or "",
                        (prompt or "")[:4000],
                        json.dumps(result, ensure_ascii=False)[:8000],
                        confidence,
                        model,
                    ),
                )
        except Exception as e:
            logger.error("ai_history 写入失败: %r", e)


if __name__ == "__main__":
    c = AIClient()
    print(c.validate_api_key())
