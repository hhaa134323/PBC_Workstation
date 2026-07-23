"""通用重试装饰器（AI 调用、文件解析等场景）。

用法：
    @retry(times=3, timeout=30)
    def call_ai(prompt: str) -> str: ...
"""
from __future__ import annotations

import functools
import logging
import time
from typing import Callable, TypeVar

T = TypeVar("T")

logger = logging.getLogger("pbc.retry")


def retry(times: int = 3, timeout: int = 30, delay: float = 1.0):
    """重试装饰器。

    Args:
        times: 最大重试次数（含首次调用，总共 times 次）
        timeout: 每次调用最多等待秒数（信号化参数，由被装饰函数自身超时机制实现）
        delay: 失败后等待秒数（指数退避 base）
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exc: Exception | None = None
            for attempt in range(1, times + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    wait = delay * attempt
                    logger.warning(
                        "retry %s attempt=%d/%d failed: %r; waiting %.1fs",
                        func.__name__, attempt, times, e, wait,
                    )
                    if attempt < times:
                        time.sleep(wait)
            # 全部失败
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator


if __name__ == "__main__":
    calls = {"n": 0}

    @retry(times=3, timeout=5, delay=0.1)
    def flaky() -> int:
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError(f"flaky fail #{calls['n']}")
        return 42

    print("result=", flaky(), "calls=", calls["n"])
