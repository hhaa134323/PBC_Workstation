"""UTF-8 / Windows 中文路径处理工具。

约定：
- 内部一律用 pathlib.Path，不字符串拼接
- 文件读写指定 encoding='utf-8'
- 大文件需"大小稳定 N 秒"才认为上传完成
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Union


def safe_path(p: Union[str, Path]) -> Path:
    """将字符串/Path 统一为绝对 Path 对象，避免相对路径歧义。"""
    path = Path(p) if not isinstance(p, Path) else p
    # 解析为绝对路径；不要求文件已存在
    return path.resolve() if path.is_absolute() else path.absolute()


def file_stable_size(path: Union[str, Path], stable_seconds: int = 2, timeout: int = 60) -> bool:
    """等待文件大小稳定 stable_seconds 秒才返回 True。

    用于判断拖拽上传/拷贝的文件是否已写完（半截文件场景）。
    超时返回 False。
    """
    p = safe_path(path)
    if not p.exists():
        return False
    last_size = -1
    stable_since: float | None = None
    start = time.time()
    while True:
        try:
            cur = p.stat().st_size
        except OSError:
            return False
        if cur == last_size:
            if stable_since is None:
                stable_since = time.time()
            if time.time() - stable_since >= stable_seconds:
                return True
        else:
            last_size = cur
            stable_since = None
        if time.time() - start > timeout:
            return False
        time.sleep(0.5)


def file_hash_sha256(path: Union[str, Path], chunk_size: int = 1 << 20) -> str:
    """计算文件 SHA-256（用于去重/校验）。"""
    p = safe_path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def rel_to_project(path: Union[str, Path]) -> str:
    """返回相对项目根的相对路径字符串（用于日志/前端展示）。"""
    from app.config import PROJECT_ROOT
    p = safe_path(path)
    try:
        return str(p.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(p)


if __name__ == "__main__":
    # 自检
    print(safe_path("./test"))
    print(rel_to_project(Path(__file__)))
