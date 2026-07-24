"""PBC 智能管理工作站 - 全局配置加载。

所有路径走 pathlib 相对项目根，避免硬编码绝对路径。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

# 项目根目录：app/config.py 的父目录的父目录（即 D:/AgentProjects/IpoPBC/0）
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# app 目录
APP_DIR: Path = PROJECT_ROOT / "app"

# 关键相对路径（相对项目根）
CONFIG_API_PATH: Path = PROJECT_ROOT / "config" / "api_config.json"
CONFIG_USER_PATH: Path = PROJECT_ROOT / "config" / "user_config.json"
MOCK_DATA_DIR: Path = PROJECT_ROOT / "mock_data"
DATA_DIR: Path = PROJECT_ROOT / "data"
LOGS_DIR: Path = DATA_DIR / "logs"
ARCHIVES_DIR: Path = DATA_DIR / "archives"

# 多项目: 项目独立目录的根（每个项目一个子目录）
PROJECTS_DIR: Path = PROJECT_ROOT / "projects"


@dataclass
class BailianConfig:
    api_key: str = ""
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    note: str = ""


@dataclass
class AppConfig:
    # 服务
    host: str = "127.0.0.1"
    port_start: int = 8000
    port_max: int = 8005

    # 数据/文件路径（相对项目根，存为 Path）
    # client_folder 可被用户覆盖（user_config.json），默认指向 mock_data
    pbc_list_path: Path = field(default_factory=lambda: MOCK_DATA_DIR / "01_PBC_List.xlsx")
    client_folder: Path = field(default_factory=lambda: MOCK_DATA_DIR / "客户共享文件夹")
    archive_root: Path = field(default_factory=lambda: DATA_DIR / "archives")
    db_path: Path = field(default_factory=lambda: DATA_DIR / "pbc_workstation.db")
    logs_dir: Path = field(default_factory=lambda: LOGS_DIR)

    # AI 客户端
    file_size_threshold_mb: int = 50
    ai_timeout_seconds: int = 60
    ai_retry_count: int = 2

    # 百炼配置
    bailian: BailianConfig = field(default_factory=BailianConfig)

    # 用户配置原始 JSON（调试用）
    user_raw: Optional[dict[str, Any]] = None

    # 原始 JSON（调试用）
    raw: Optional[dict[str, Any]] = None


def load_config() -> AppConfig:
    """从 config/api_config.json + config/user_config.json 加载配置并合并默认值。

    优先级：user_config.json > api_config.json > 默认值
    - api_config.json：百炼 API Key（敏感，用户不直接改）
    - user_config.json：客户文件夹路径、PBC 清单路径（用户可改，非敏感）
    """
    cfg = AppConfig()

    # 1. api_config.json（百炼配置）
    raw: dict[str, Any] = {}
    try:
        if CONFIG_API_PATH.exists():
            with CONFIG_API_PATH.open("r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        else:
            raw = {}
    except Exception:
        raw = {}

    bl = raw.get("bailian") or {}
    cfg.bailian = BailianConfig(
        api_key=str(bl.get("api_key", "")),
        base_url=str(bl.get("base_url", cfg.bailian.base_url)),
        note=str(bl.get("note", "")),
    )
    cfg.raw = raw

    # 2. user_config.json（用户可改的路径配置，非敏感）
    user_raw: dict[str, Any] = {}
    try:
        if CONFIG_USER_PATH.exists():
            with CONFIG_USER_PATH.open("r", encoding="utf-8") as f:
                user_raw = json.load(f) or {}
        else:
            user_raw = {}
    except Exception:
        user_raw = {}

    # 客户文件夹路径（用户可配置，用于 OneDrive 挂载点等真实场景）
    cf = user_raw.get("client_folder")
    if cf:
        try:
            p = Path(cf).expanduser().resolve()
            if p.exists() and p.is_dir():
                cfg.client_folder = p
            else:
                # 路径不存在时保留字符串但标记（启动时 watchdog 会处理失败）
                cfg.client_folder = Path(cf)
        except Exception:
            pass  # 保留默认

    # PBC 清单路径（用户可配置）
    pl = user_raw.get("pbc_list_path")
    if pl:
        try:
            cfg.pbc_list_path = Path(pl).expanduser().resolve()
        except Exception:
            pass

    cfg.user_raw = user_raw
    return cfg


def save_user_config(client_folder: Optional[str] = None,
                     pbc_list_path: Optional[str] = None) -> dict:
    """保存用户配置到 config/user_config.json。

    用于前端"设置→选择客户文件夹"配置面板。
    只保存非敏感的路径配置，不写百炼 API Key（API Key 走 api_config.json）。
    """
    import logging
    logger = logging.getLogger("pbc.config")

    # 先读现有 user_config
    user_raw: dict[str, Any] = {}
    try:
        if CONFIG_USER_PATH.exists():
            with CONFIG_USER_PATH.open("r", encoding="utf-8") as f:
                user_raw = json.load(f) or {}
    except Exception:
        user_raw = {}

    changed = []
    if client_folder is not None:
        # 校验路径存在
        try:
            p = Path(client_folder).expanduser().resolve()
            if p.exists() and p.is_dir():
                user_raw["client_folder"] = str(p)
                changed.append(f"client_folder={p}")
            else:
                return {"ok": False, "error": f"路径不存在或不是目录: {client_folder}"}
        except Exception as e:
            return {"ok": False, "error": f"路径解析失败: {e}"}

    if pbc_list_path is not None:
        try:
            p = Path(pbc_list_path).expanduser().resolve()
            if p.exists() and p.is_file():
                user_raw["pbc_list_path"] = str(p)
                changed.append(f"pbc_list_path={p}")
            else:
                return {"ok": False, "error": f"PBC 清单文件不存在: {pbc_list_path}"}
        except Exception as e:
            return {"ok": False, "error": f"PBC 清单路径解析失败: {e}"}

    # 写入文件
    try:
        CONFIG_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with CONFIG_USER_PATH.open("w", encoding="utf-8") as f:
            json.dump(user_raw, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"ok": False, "error": f"写入失败: {e}"}

    # 强制下次 get_config 重新加载
    global _CONFIG
    _CONFIG = None

    logger.info("user_config 已更新: %s", ", ".join(changed))
    return {"ok": True, "changed": changed, "saved_to": str(CONFIG_USER_PATH)}


def get_current_client_folder() -> dict:
    """返回当前客户文件夹路径信息（前端展示用）。"""
    cfg = get_config()
    p = cfg.client_folder
    return {
        "path": str(p),
        "exists": p.exists() if p else False,
        "is_dir": p.is_dir() if p.exists() else False,
        "is_default": str(p) == str(MOCK_DATA_DIR / "客户共享文件夹"),
        "file_count": len(list(p.rglob("*"))) if p.exists() and p.is_dir() else 0,
    }


# 模块级单例（首次导入即加载）
_CONFIG: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """返回全局配置单例。"""
    global _CONFIG
    if _CONFIG is None:
        _CONFIG = load_config()
    return _CONFIG


def ensure_runtime_dirs() -> None:
    """启动时确保运行时目录存在。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    c = get_config()
    print(f"project_root={PROJECT_ROOT}")
    print(f"db_path={c.db_path}")
    print(f"bailian.api_key={'***' if c.bailian.api_key else '(empty)'}")
