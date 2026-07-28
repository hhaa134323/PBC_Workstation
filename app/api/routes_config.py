"""v7: AI 配置路由（GET/PUT /api/config/ai + POST /api/config/ai/test）。

审计员反馈 #7：AI 配置入口。
- GET /api/config/ai：返回当前模型/key/base_url（key 脱敏）
- PUT /api/config/ai：保存（写 config/api_config.json）
- POST /api/config/ai/test：真发一条测试请求验证连通

模型可选列表也提供：
- GET /api/config/ai/models：返回推荐模型清单（含说明）
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

from app.config import CONFIG_API_PATH, get_config

logger = logging.getLogger("pbc.routes_config")

router = APIRouter(prefix="/api/config", tags=["config"])


# 推荐模型清单（思路 12 + v7 扩展）
_RECOMMENDED_MODELS = [
    {
        "id": "glm-5",
        "name": "GLM-5（智谱）",
        "use_case": "文件内容识别 + 分类",
        "note": "中文理解强，分类准确。百炼通用域名。",
    },
    {
        "id": "qwen-plus",
        "name": "Qwen3-Plus（通义千问）",
        "use_case": "文件内容识别 + 分类",
        "note": "阿里自研，百炼通用域名。",
    },
    {
        "id": "qwen-max",
        "name": "Qwen3-Max（通义千问）",
        "use_case": "推理 / 替代程序建议",
        "note": "推理能力强，适合复杂任务。",
    },
    {
        "id": "qwen3-vl-plus",
        "name": "Qwen3-VL-Plus（视觉）",
        "use_case": "期间连续性检查（读 PDF/扫描件图片）",
        "note": "能读 PDF/扫描件图片，OCR 能力。",
    },
    {
        "id": "deepseek-v4-pro",
        "name": "DeepSeek-V4 Pro",
        "use_case": "推理 / 替代程序建议",
        "note": "强推理，带思考能力。百炼通用域名可用。",
    },
]


class AIConfigUpdate(BaseModel):
    """前端保存 AI 配置的请求体。"""
    api_key: Optional[str] = Field(None, description="百炼 API Key（脱敏后展示，保存时原样回传）")
    base_url: Optional[str] = Field(None, description="百炼 base_url，默认 https://dashscope.aliyuncs.com/compatible-mode/v1")
    model: Optional[str] = Field(None, description="模型名（v7.7: 统一一个字段，分类+OCR 共用），如 qwen-plus / gpt-4o")
    # v7: Opus 4.8 收敛清单 #6 要求的两个开关
    confidence_threshold: Optional[float] = Field(None, description="置信度阈值（0-1），低于此值标红需人工复核，默认 0.7")
    filename_match_enabled: Optional[bool] = Field(None, description="文件名直配开关，True=启用文件名优先匹配跳过 AI，默认 True")
    # v7.7: auto 档批量确认开关（HITL）
    auto_confirm_enabled: Optional[bool] = Field(None, description="自动确认高置信度文件（auto档>0.70跳过待确认直接归档），默认 False")
    # v7.7: HITL 模式开关（从环境变量改成配置项，默认开启）
    hitl_mode: Optional[bool] = Field(None, description="HITL人机协同（AI预分析不归档，人确认后才归档），默认 True")


def _mask_key(key: str) -> str:
    """API Key 脱敏：保留前 6 + 后 4，中间用 *** 代替。"""
    if not key or len(key) <= 12:
        return "***" if key else ""
    return f"{key[:6]}***{key[-4:]}"


def _load_raw_config() -> dict:
    """读取 config/api_config.json 原始 JSON。"""
    if not CONFIG_API_PATH.exists():
        return {}
    try:
        with CONFIG_API_PATH.open("r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_raw_config(raw: dict) -> None:
    """保存 config/api_config.json。"""
    CONFIG_API_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_API_PATH.open("w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False, indent=2)


@router.get("/ai")
async def get_ai_config() -> dict:
    """v7: 获取当前 AI 配置（key 脱敏）。"""
    raw = _load_raw_config()
    bl = raw.get("bailian") or {}
    ai_models = raw.get("ai_models") or {}
    ai_flags = raw.get("ai_flags") or {}
    return {
        "ok": True,
        "config": {
            "api_key_masked": _mask_key(bl.get("api_key") or ""),
            "api_key_set": bool(bl.get("api_key")),
            "base_url": bl.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": bl.get("model") or "qwen-plus",
            # v7: 两个开关
            "confidence_threshold": float(ai_flags.get("confidence_threshold", 0.7)),
            "filename_match_enabled": bool(ai_flags.get("filename_match_enabled", True)),
            # v7.7: auto 批量确认开关
            "auto_confirm_enabled": bool(ai_flags.get("auto_confirm_enabled", False)),
            # v7.7: HITL 模式开关
            "hitl_mode": bool(ai_flags.get("hitl_mode", True)),
        },
    }


@router.put("/ai")
async def update_ai_config(body: AIConfigUpdate) -> dict:
    """v7: 保存 AI 配置到 config/api_config.json。

    api_key 字段：
    - 如果前端传的是脱敏格式（含 ***），说明用户没改 key，保留原值
    - 如果传的是完整 key，覆盖
    """
    raw = _load_raw_config()
    bl = raw.get("bailian") or {}
    ai_models = raw.get("ai_models") or {}
    ai_flags = raw.get("ai_flags") or {}

    changed = []

    if body.api_key is not None:
        if "***" not in body.api_key and body.api_key:
            bl["api_key"] = body.api_key
            changed.append("api_key")

    if body.base_url is not None:
        bl["base_url"] = body.base_url
        changed.append("base_url")

    # v7.7: 统一 model 字段（替代 model_classification/vision/reasoning）
    if body.model is not None:
        bl["model"] = body.model.strip()
        changed.append("model")

    # v7: 两个开关
    if body.confidence_threshold is not None:
        try:
            v = float(body.confidence_threshold)
            if 0.0 <= v <= 1.0:
                ai_flags["confidence_threshold"] = v
                changed.append("confidence_threshold")
        except (TypeError, ValueError):
            pass

    if body.filename_match_enabled is not None:
        ai_flags["filename_match_enabled"] = bool(body.filename_match_enabled)
        changed.append("filename_match_enabled")

    # v7.7: auto 批量确认开关
    if body.auto_confirm_enabled is not None:
        ai_flags["auto_confirm_enabled"] = bool(body.auto_confirm_enabled)
        changed.append("auto_confirm_enabled")

    # v7.7: HITL 模式开关
    if body.hitl_mode is not None:
        ai_flags["hitl_mode"] = bool(body.hitl_mode)
        changed.append("hitl_mode")

    raw["bailian"] = bl
    raw["ai_models"] = ai_models
    raw["ai_flags"] = ai_flags

    _save_raw_config(raw)

    from app.config import _CONFIG
    import app.config as _cfg_mod
    _cfg_mod._CONFIG = None

    return {
        "ok": True,
        "changed": changed,
        "saved_to": str(CONFIG_API_PATH),
        "message": f"AI 配置已保存（{len(changed)} 项变更）",
    }


@router.get("/test-data-package")
async def download_test_data_package():
    """v7: 下载测试数据包（zip）。

    如果 data/test_data_package 不存在，先调 scripts/generate_test_data.py 生成。
    然后把整个目录打成 zip 给前端下载。

    审计员反馈 #8：造一套测试数据让审计员拿来创建项目测试。
    """
    import os
    import sys
    import tempfile
    import zipfile
    from pathlib import Path
    from fastapi.responses import FileResponse

    from app.config import DATA_DIR
    pkg_dir = DATA_DIR / "test_data_package"

    # 不存在或为空 → 自动生成
    if not pkg_dir.exists() or not any(pkg_dir.rglob("*")):
        try:
            from app.config import PROJECT_ROOT
            gen_script = PROJECT_ROOT / "scripts" / "generate_test_data.py"
            if gen_script.exists():
                import subprocess
                subprocess.run(
                    [sys.executable, str(gen_script)],
                    check=True,
                    capture_output=True,
                    timeout=60,
                )
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": f"生成测试数据失败: {e.stderr.decode('utf-8', errors='ignore')[:500]}"}
        except Exception as e:
            return {"ok": False, "error": f"生成测试数据异常: {type(e).__name__}: {e}"}

    if not pkg_dir.exists():
        return {"ok": False, "error": "测试数据包目录不存在且自动生成失败"}

    # 打成 zip 到临时文件
    tmp_zip = Path(tempfile.gettempdir()) / "pbc_test_data_package.zip"
    try:
        with zipfile.ZipFile(str(tmp_zip), "w", zipfile.ZIP_DEFLATED) as zf:
            for p in pkg_dir.rglob("*"):
                if p.is_file():
                    arcname = p.relative_to(pkg_dir.parent)
                    zf.write(str(p), str(arcname))
    except Exception as e:
        return {"ok": False, "error": f"打包失败: {e}"}

    return FileResponse(
        path=str(tmp_zip),
        media_type="application/zip",
        filename="PBC_测试数据包.zip",
    )


@router.get("/ai/models")
async def list_ai_models() -> dict:
    """v7: 返回推荐模型清单（前端下拉用）。"""
    return {
        "ok": True,
        "models": _RECOMMENDED_MODELS,
    }


class AITestBody(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


@router.post("/ai/test")
async def test_ai_connection(body: AITestBody = Body(default=AITestBody())) -> dict:
    """v7: 测试 AI 连接（真发一条 chat 请求）。

    优先级：body.api_key > 配置文件里的 key
    model 默认 glm-5
    """
    raw = _load_raw_config()
    bl = raw.get("bailian") or {}

    api_key = body.api_key or bl.get("api_key") or ""
    base_url = body.base_url or bl.get("base_url") or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # v7.11: model 默认用配置文件里的，不写死 glm-5（百炼不认 glm-5）
    model = body.model or bl.get("model") or raw.get("ai_models", {}).get("model_classification") or "qwen-plus"

    if not api_key:
        return {
            "ok": False,
            "error": "未配置 API Key",
            "hint": "请先在 AI 配置面板填写 API Key",
        }

    # 含 *** 视为用已保存的 key（前端测试时通常只改 model 不改 key）
    if "***" in api_key:
        api_key = bl.get("api_key") or ""
        if not api_key:
            return {"ok": False, "error": "API Key 是脱敏值，但配置文件没有真实 key"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": "回复 OK 两个字符，用于连通性测试"},
        ],
        "max_tokens": 10,
        "temperature": 0,
    }

    try:
        # 同步 httpx（短超时）
        with httpx.Client(timeout=15.0) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
        if r.status_code == 200:
            data = r.json()
            content = ""
            try:
                content = data["choices"][0]["message"]["content"]
            except Exception:
                pass
            return {
                "ok": True,
                "status_code": r.status_code,
                "model": model,
                "response_preview": content[:100] if content else "(empty)",
                "message": f"连接成功，模型 {model} 响应正常",
            }
        else:
            try:
                err_body = r.json()
                err_msg = err_body.get("error", {}).get("message") or r.text[:200]
            except Exception:
                err_msg = r.text[:200]
            return {
                "ok": False,
                "status_code": r.status_code,
                "error": err_msg,
                "hint": f"HTTP {r.status_code}，请检查 API Key 或 model id 是否正确",
            }
    except httpx.TimeoutException:
        return {"ok": False, "error": "请求超时（15s）", "hint": "网络问题或 base_url 不可达"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "hint": "连接异常，请检查 base_url"}
