"""M7 最终打包脚本（基于 M4.5 试打包验证过的配置）。

打包目标：在 dist/PBC-Workstation/ 下生成 onedir 应用。
入口：app/main.py（FastAPI app 对象）。

M7 vs M4.5 优化点：
1. 加 knowledge_base.py（M6 新增模块）
2. 加 routes_chat 等 M5 后可能新增的模块
3. 排除不必要的测试依赖（pytest 等）减小体积
4. 保留 onedir 模式（onefile 启动慢，不适合双击即用）
5. 排除 __pycache__（避免打包缓存）

数据文件：
- app/static/ → 静态前端（M5 完成后会含完整 UI）
- mock_data/ → 模拟数据集（演示用，runtime 也用）
- config/ → api_config.json + user_config.json

用法：
    cd D:/AgentProjects/IpoPBC/0
    C:/Users/caca/.workbuddy/binaries/python/envs/default/Scripts/python.exe scripts/build_exe.py

注意：
- 必须从项目根 D:/AgentProjects/IpoPBC/0 跑，否则 --add-data 路径会错
- M4.5 验证过 PyInstaller 路径完全可行
- 关键修复：app/main.py 用 uvicorn.run(app, ...) 直接传对象（不是字符串 "app.main:app"）
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 确保从项目根跑
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
print(f"[build] cwd = {PROJECT_ROOT}")

import PyInstaller.__main__ as pyi

# Patch: 禁用 PyInstaller 隔离子进程（Windows 环境下 SubprocessDiedError）
# 让 collect_submodules / is_package 等函数在主进程直接执行
from PyInstaller import isolated as _iso_mod
import PyInstaller.isolated._parent as _iso_parent

class _FakeIsolated:
    """Mock isolated.Python() context manager — 直接在主进程执行函数"""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def call(self, function, *args, **kwargs):
        return function(*args, **kwargs)

# 必须同时 patch 两个位置：_parent 模块 + isolated 包的 __init__ 已绑定引用
_iso_parent.Python = _FakeIsolated
_iso_parent.call = lambda fn, *a, **kw: fn(*a, **kw)
_iso_mod.Python = _FakeIsolated
_iso_mod.call = lambda fn, *a, **kw: fn(*a, **kw)
# decorate 也 patch：让 @isolated.decorate 装饰的函数直接在主进程执行
def _patched_decorate(func):
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    wrapper.__wrapped__ = func
    return wrapper
_iso_parent.decorate = _patched_decorate
_iso_mod.decorate = _patched_decorate
print("[build] PyInstaller isolated subprocess fully disabled (monkey-patch)")


def build() -> None:
    # Windows 数据分隔符是 ;，Linux 是 :
    sep = ";" if sys.platform == "win32" else ":"

    # 隐藏导入清单（M7 新增 knowledge_base）
    hidden = [
        # 项目内子模块
        "app.api.routes_pbc",
        "app.api.routes_files",
        "app.api.routes_risk",
        "app.core.db",
        "app.core.ai_client",
        "app.core.excel_io",
        "app.core.file_parser",
        "app.core.watcher",
        "app.core.archive",
        "app.core.knowledge_base",  # M6 新增
        "app.utils.path_utils",
        "app.utils.retry",
        # 第三方动态导入
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.loops.http11",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.httptools",
        "uvicorn.lifespan.on",
        # pdfplumber 内部子模块
        "pdfplumber",
        "pdfminer.high_level",
        "pdfminer.pdfdocument",
        "pdfminer.pdfpage",
        # watchdog 观察者后端
        "watchdog.observers",
        "watchdog.observers.polling",
        # Pillow 图片插件（视觉兜底可能用）
        "PIL._typing",
        # httpx 异步 HTTP（M3 新增）
        "httpx",
        "httpx._transports",
        "httpx._transports.default",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
    ]

    # 数据文件 - 用绝对路径
    datas = [
        f"{PROJECT_ROOT / 'app' / 'static'}{sep}app/static",
        f"{PROJECT_ROOT / 'mock_data'}{sep}mock_data",
        f"{PROJECT_ROOT / 'config'}{sep}config",
        # P1 修复：打包 projects/ 目录（含 6 项精简版 demo 清单 + 客户共享文件夹）
        f"{PROJECT_ROOT / 'projects'}{sep}projects",
    ]

    # 排除的不必要模块（减小体积）
    excludes = [
        "pytest",
        "pytest_asyncio",
        "IPython",
        "jupyter",
        "notebook",
        "matplotlib",
        "numpy",  # 不用 numpy（pandas 装了但我们不用）
        "scipy",
        "sklearn",
        "tensorflow",
        "torch",
        "websockets",      # 不用的 websocket 依赖（Python 3.13 兼容性问题）
    ]

    args = [
        "app/main.py",
        "--name=PBC-Agent-v6",
        "--onedir",                       # onedir 启动快（M4.5 验证过）
        "--noconsole",                    # 不开控制台窗口
        # "--clean",                      # 沙箱里删不掉 build，跳过 clean
        "--noconfirm",
        f"--distpath={PROJECT_ROOT}",     # 2026-07-21: 输出到项目根目录 D:/AgentProjects/IpoPBC/0/
        f"--workpath={PROJECT_ROOT / 'build'}",
        f"--specpath={PROJECT_ROOT / 'scripts'}",
    ]

    for h in hidden:
        args.append(f"--hidden-import={h}")

    for d in datas:
        args.append(f"--add-data={d}")

    for e in excludes:
        args.append(f"--exclude-module={e}")

    # 收集所有子模块（避免 FastAPI 路由注册失败）
    args.append("--collect-submodules=app")
    args.append("--collect-submodules=pdfplumber")
    args.append("--collect-submodules=pdfminer")
    args.append("--collect-submodules=watchdog")

    print("[build] PyInstaller args:")
    for a in args:
        print(f"  {a}")
    print()

    pyi.run(args)


if __name__ == "__main__":
    build()
