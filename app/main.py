"""PBC 智能管理工作站 - FastAPI 入口。

启动：
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
"""
from __future__ import annotations

import logging
import socket
import webbrowser
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import routes_briefing, routes_config, routes_files, routes_pbc, routes_projects, routes_risk
from app.config import APP_DIR, get_config, ensure_runtime_dirs
from app.core.ai_client import AIClient
from app.core.db import init_db, get_or_create_default_project

# 日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pbc.main")


def _write_startup_log(message: str) -> None:
    """启动日志写入 data/logs/startup.log（UTF-8）。"""
    cfg = get_config()
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = cfg.logs_dir / "startup.log"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def _find_available_port(start: int, end: int) -> int:
    """在 [start, end] 范围内寻找可用端口。"""
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"无可用端口：{start}-{end} 均被占用")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动/关闭钩子。"""
    ensure_runtime_dirs()
    _write_startup_log("应用启动开始")
    # 1. 初始化 SQLite
    try:
        init_db()
        _write_startup_log(f"SQLite 初始化成功: {get_config().db_path}")
    except Exception as e:
        _write_startup_log(f"SQLite 初始化失败: {e}")
        logger.warning("SQLite 初始化失败: %s", e)

    # 2. 确保有"示例项目"（多项目支持）
    # P1-12: 异步创建 demo，不阻塞 lifespan（避免首次加载慢）
    try:
        default_proj = get_or_create_default_project()
        _write_startup_log(
            f"默认项目就绪: project_id={default_proj.get('project_id')} "
            f"name={default_proj.get('name')}"
        )
        logger.info("默认项目就绪: %s", default_proj.get("project_id"))
    except Exception as e:
        _write_startup_log(f"默认项目创建失败（异步重试）: {e}")
        logger.warning("默认项目创建失败（异步重试）: %s", e)
        # 异步兜底：后台再尝试一次，前端通过健康检查发现
        async def _retry_create_default():
            for _i in range(3):
                await asyncio.sleep(2.0)
                try:
                    p = get_or_create_default_project()
                    _write_startup_log(f"默认项目异步重试成功: {p.get('project_id')}")
                    logger.info("默认项目异步重试成功: %s", p.get("project_id"))
                    return
                except Exception as e2:
                    _write_startup_log(f"默认项目异步重试失败 #{_i+1}: {e2}")
                    logger.warning("默认项目异步重试失败 #%d: %r", _i+1, e2)
        asyncio.create_task(_retry_create_default())

    # 3. 校验 API Key（失败只警告不退出）
    # P0-7: 启动时调一次真实 API 校验（在线校验）
    try:
        client = AIClient()
        # 先做格式校验
        ok_fmt, msg_fmt = client.validate_api_key()
        if ok_fmt:
            # 格式 OK 再做在线校验
            ok_online, msg_online = client.verify_api_key_online()
            _write_startup_log(f"API Key 在线校验: {msg_online}")
            if ok_online:
                logger.info("API Key 在线校验: %s", msg_online)
            else:
                logger.warning("API Key 在线校验失败（警告）: %s", msg_online)
        else:
            _write_startup_log(f"API Key 格式校验失败: {msg_fmt}")
            logger.warning("API Key 格式校验失败: %s", msg_fmt)
    except Exception as e:
        _write_startup_log(f"API Key 校验异常: {e}")
        logger.warning("API Key 校验异常: %s", e)

    # P0-7: 注入 401 回调（运行时检测到 401 自动停止 watchdog + 弹 toast）
    def _on_api_key_invalidated() -> None:
        _write_startup_log("API Key 运行时失效！停止 watchdog + 推送 toast")
        logger.error("API Key 运行时失效（401/403），已停止 watchdog")
        try:
            from app.core.watcher import stop_default_watcher
            stop_default_watcher()
        except Exception as e:
            logger.warning("watchdog 停止异常: %r", e)
        # toast 由前端轮询 ai_history 表 key_invalidated 标记后弹出
        # 这里写一条 ai_history 记录便于前端发现
        try:
            from app.core.db import get_conn
            with get_conn() as conn:
                conn.execute(
                    """INSERT INTO ai_history
                       (item_id, action, prompt, response, confidence, model)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    ("", "api_key_invalidated", "", "API Key 失效，请检查 config",
                     None, "system"),
                )
        except Exception as e:
            logger.warning("写 ai_history api_key_invalidated 失败: %r", e)

    try:
        AIClient.set_key_invalid_callback(_on_api_key_invalidated)
    except Exception as e:
        logger.warning("set_key_invalid_callback 失败: %r", e)

    # 4. 启动 watchdog 监听所有活跃项目的 client_folder（M4 + 多项目）
    watcher_started = False
    try:
        from app.api.routes_files import handle_watcher_new_file
        from app.core.watcher import start_default_watcher, is_watcher_running
        watcher_started = start_default_watcher(handle_watcher_new_file)
        _write_startup_log(
            f"watchdog 启动: {'成功' if watcher_started else '失败（仅扫描已有文件）'} "
            f"running={is_watcher_running()}"
        )
        logger.info("watchdog started=%s running=%s", watcher_started, is_watcher_running())
    except Exception as e:
        _write_startup_log(f"watchdog 启动异常（不影响主服务）: {e}")
        logger.warning("watchdog 启动异常: %r", e)

    _write_startup_log("应用启动完成")
    yield
    # 关闭 watchdog（如果启动过）
    try:
        from app.core.watcher import stop_default_watcher
        stop_default_watcher()
    except Exception as e:
        logger.warning("watchdog stop 异常: %r", e)
    _write_startup_log("应用关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="PBC 智能管理工作站",
        version="0.1.0",
        description="IPO 审计 PBC 智能管理工作站 - 安永 AI 创新大赛",
        lifespan=lifespan,
    )

    # CORS：仅允许本机访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 路由
    app.include_router(routes_projects.router)
    app.include_router(routes_pbc.router)
    app.include_router(routes_files.router)
    app.include_router(routes_risk.router)
    app.include_router(routes_briefing.router)
    # v7: AI 配置路由
    app.include_router(routes_config.router)

    # 静态文件挂载
    static_dir = APP_DIR / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # 根路由：返回 index.html
    @app.get("/")
    async def root() -> FileResponse:
        idx = static_dir / "index.html"
        if idx.exists():
            return FileResponse(str(idx))
        return JSONResponse({"message": "PBC 智能管理工作站 (static/index.html 未找到)"}, status_code=404)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": "0.1.0"}

    @app.post("/api/open-folder/{project_id}")
    async def _open_folder_direct(project_id: str):
        """浏览器 → 后端打开此项目的客户共享文件夹（系统文件管理器）。"""
        from pathlib import Path as _P
        from app.core.db import get_project as _gp
        import os as _os
        import sys as _sys
        proj = _gp(project_id)
        if not proj:
            return {"ok": False, "error": f"项目不存在: {project_id}"}
        folder = proj.get("client_folder") or ""
        if not folder:
            return {"ok": False, "error": "未配置客户共享文件夹"}
        p = _P(folder)
        if not p.exists() or not p.is_dir():
            return {"ok": False, "error": f"文件夹不存在: {folder}"}
        try:
            if _sys.platform == "win32":
                _os.startfile(str(p))
            elif _sys.platform == "darwin":
                import subprocess as _sp
                _sp.Popen(["open", str(p)])
            else:
                import subprocess as _sp
                _sp.Popen(["xdg-open", str(p)])
            return {"ok": True, "folder": str(p)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    return app


app = create_app()


def _show_port_conflict_dialog(start: int, end: int) -> None:
    """P0-10: 端口全占时弹 tkinter messagebox + fallback 写桌面 txt。

    优先用 tkinter（Windows 自带），不可用时 fallback 写桌面 txt 文件。
    """
    msg = (
        f"PBC 智能管理工作站启动失败\n\n"
        f"端口 {start}-{end} 全部被占用。\n\n"
        f"请按以下任一方式处理：\n"
        f"1. 关闭占用 8000-8005 端口的进程（可能是之前的 PBC 工作站未正常关闭）\n"
        f"2. 修改 app/config.py 的 port_start/port_max 改用其他端口\n"
        f"3. 重启电脑后再次双击 exe\n\n"
        f"查看端口占用：netstat -ano | findstr :8000"
    )
    _write_startup_log(f"端口全占（P0-10）: {msg.replace(chr(10), ' | ')}")

    # 优先 tkinter messagebox
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showerror("PBC 工作站 - 端口冲突", msg)
        root.destroy()
        return
    except Exception as e:
        logger.warning("tkinter messagebox 不可用，fallback 写桌面 txt: %r", e)

    # fallback: 写桌面 txt
    try:
        import os
        desktop = Path(os.path.expanduser("~")) / "Desktop"
        if not desktop.exists():
            desktop = Path(os.path.expanduser("~"))
        txt_path = desktop / "PBC工作站-端口冲突.txt"
        txt_path.write_text(
            f"PBC 智能管理工作站 - 端口冲突\n"
            f"========================================\n\n"
            f"{msg}\n\n"
            f"========================================\n"
            f"时间: {datetime.now().isoformat()}\n",
            encoding="utf-8",
        )
        # 尝试用 os.startfile 打开 txt
        try:
            os.startfile(str(txt_path))  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception as e:
        logger.error("写桌面 txt 也失败（最后兜底）: %r", e)


def run() -> None:
    """直接 python app/main.py 启动入口。"""
    cfg = get_config()
    try:
        port = _find_available_port(cfg.port_start, cfg.port_max)
    except Exception as e:
        _write_startup_log(f"端口选择失败: {e}")
        # P0-10: 弹友好提示框，不只是抛异常
        _show_port_conflict_dialog(cfg.port_start, cfg.port_max)
        raise

    url = f"http://127.0.0.1:{port}"
    _write_startup_log(f"选中端口: {port}; URL: {url}")
    print(f"[PBC 工作站] 启动中 → {url}")

    # 尝试自动开浏览器（失败仅打印 URL，不阻塞启动）
    try:
        webbrowser.open(url)
    except Exception as e:
        _write_startup_log(f"webbrowser 打开失败: {e}")
        print(f"[警告] 浏览器自动打开失败，请手动访问: {url}")

    try:
        # 直接传 app 对象（而非字符串 "app.main:app"），适配 PyInstaller 打包场景
        # 修复 PyInstaller + --noconsole 模式下 uvicorn logging 崩溃问题：
        # --noconsole 时 sys.stderr/sys.stdout 为 None，uvicorn 的 DefaultFormatter 调用
        # sys.stderr.isatty() 会抛 AttributeError。
        # 解决方案：用自定义 log_config 替代 uvicorn 默认配置，不用 isatty 判断。
        import logging
        from uvicorn.config import LOGGING_CONFIG

        # 复制默认配置，但把所有 handler 的 stream 设为 sys.stderr（如果 None 就用 io.StringIO 兜底）
        import sys
        import io
        if sys.stderr is None:
            sys.stderr = io.StringIO()
        if sys.stdout is None:
            sys.stdout = io.StringIO()

        custom_log_config = dict(LOGGING_CONFIG)
        # 确保所有 handler 的 stream 不为 None
        for handler_name, handler in custom_log_config.get("handlers", {}).items():
            if handler.get("stream") is None:
                handler["stream"] = sys.stderr

        uvicorn.run(
            app,                          # 已实例化的 FastAPI 对象
            host=cfg.host,
            port=port,
            log_level="info",
            log_config=custom_log_config,
            ws="none",                    # 不加载 websocket（减少依赖体积）
        )
    except Exception as e:
        _write_startup_log(f"uvicorn 启动失败: {e}")
        print(f"[错误] uvicorn 启动失败: {e}")
        raise


if __name__ == "__main__":
    run()
