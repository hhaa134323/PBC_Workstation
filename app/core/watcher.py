"""客户共享文件夹 watchdog 监听（M4 + 多项目支持）。

约束：
- 用 watchdog Observer + FileSystemEventHandler
- 多项目：遍历所有活跃项目，每个项目启动一个 Observer 监听其 client_folder
- 文件创建/修改事件触发：等大小稳定 2 秒 → 调 on_new_file(path, project_id) 回调
- 启动时扫描一次已有文件（避免遗漏）
- OneDrive 网络盘场景：watchdog 大概率不触发，**失败仅 log warning，不报错**
- 用 SHA-256 去重避免重复处理（按 project_id+sha 维度去重）
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from app.config import get_config
from app.utils.path_utils import file_hash_sha256, file_stable_size, safe_path

logger = logging.getLogger("pbc.watcher")

# 允许监听的扩展名（与 routes_files 保持一致）
_ALLOWED_EXT = {".pdf", ".xlsx", ".xlsm", ".csv", ".txt", ".md", ".json", ".xml"}


# 回调签名：on_new_file(path: Path, project_id: Optional[str] = None)
# 为兼容旧的 watcher（只接 path），我们也支持 callback 只接受 path
NewFileCallback = Callable[..., None]


class _Handler:  # pragma: no cover - watchdog 事件适配
    """watchdog 事件处理适配器（不直接继承 FileSystemEventHandler 以便无 watchdog 时也能 import）。"""

    def __init__(self, callback: NewFileCallback, project_id: Optional[str] = None) -> None:
        self._callback = callback
        self._project_id = project_id

    def on_any_event(self, event):  # noqa: D401
        # 只处理文件，目录跳过
        if getattr(event, "is_directory", False):
            return
        src = getattr(event, "src_path", None) or getattr(event, "dest_path", None)
        if not src:
            return
        p = Path(str(src))
        if p.suffix.lower() not in _ALLOWED_EXT:
            return
        # 在后台线程触发，避免阻塞 observer
        t = threading.Thread(target=self._safe_callback, args=(p,), daemon=True)
        t.start()

    def _safe_callback(self, p: Path) -> None:
        try:
            # 尝试带 project_id 调用；如果回调只接受 1 个参数，则降级
            try:
                self._callback(p, project_id=self._project_id)
            except TypeError:
                self._callback(p)
        except Exception as e:
            logger.warning("watcher 回调失败 %s: %r", p, e)


class FolderWatcher:
    """客户共享文件夹监听器（watchdog + 启动时扫描）。单项目。"""

    def __init__(
        self,
        folder: Path | str | None = None,
        on_new_file: Optional[NewFileCallback] = None,
        project_id: Optional[str] = None,
    ) -> None:
        cfg = get_config()
        self.folder: Path = Path(folder) if folder else cfg.client_folder
        self.on_new_file = on_new_file
        self.project_id = project_id
        self._observer = None  # type: ignore[assignment]
        self._running = threading.Event()
        self._lock = threading.Lock()
        # SHA-256 去重缓存（按 project_id+sha 维度，进程内即可，重启重新处理也 OK）
        self._seen_sha: set[tuple[str, str]] = set()
        self._seen_lock = threading.Lock()

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """启动后台线程。返回 True 表示成功启动；失败仅 warning，返回 False。"""
        if self._running.is_set():
            logger.info("watcher 已在运行: %s", self.folder)
            return True

        if not self.folder.exists() or not self.folder.is_dir():
            logger.warning("watcher 启动失败：目录不存在 %s", self.folder)
            return False

        if not self.on_new_file:
            logger.warning("watcher 启动失败：未设置 on_new_file 回调")
            return False

        # v7.3: 启动时用 manifest 扫描——只处理新文件和变更文件，跳过未变文件
        # v7.4: 默认启动就扫描（manifest 快路径保证不重复处理），不再要环境变量
        import os
        try:
            self._scan_existing_with_manifest()
        except Exception as e:
            logger.warning("watcher 启动扫描失败 %r", e)

        # 启动 watchdog Observer
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            logger.warning("watchdog 未安装，FolderWatcher.start 仅扫描已有文件")
            return False

        outer = self

        class _EventHandler(FileSystemEventHandler):
            def on_created(self_inner, event):  # noqa: N802
                outer._dispatch_event(event)

            def on_modified(self_inner, event):  # noqa: N802
                outer._dispatch_event(event)

            def on_moved(self_inner, event):  # noqa: N802
                if getattr(event, "dest_path", None):
                    class _Mimic:
                        is_directory = event.is_directory
                        src_path = event.dest_path
                    outer._dispatch_event(_Mimic())

        try:
            self._observer = Observer()
            self._observer.schedule(_EventHandler(), str(self.folder), recursive=True)
            self._observer.daemon = True
            self._observer.start()
            self._running.set()
            logger.info(
                "watcher 启动成功，监听目录: %s (project_id=%s)",
                self.folder, self.project_id,
            )
            return True
        except Exception as e:
            logger.warning("watcher Observer 启动失败 %r（OneDrive 网络盘可能不支持）", e)
            self._observer = None
            return False

    def stop(self) -> None:
        """停止 Observer（关闭后台线程）。"""
        self._running.clear()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2.0)
            except Exception as e:
                logger.warning("watcher stop 失败 %r", e)
        self._observer = None

    def is_running(self) -> bool:
        return self._running.is_set() and self._observer is not None

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _scan_existing(self) -> None:
        """启动时扫描已有文件，触发 on_new_file 回调（旧版，全量扫描）。"""
        if not self.on_new_file:
            return
        count = 0
        for p in self.folder.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in _ALLOWED_EXT:
                continue
            count += 1
            t = threading.Thread(target=self._safe_trigger, args=(p,), daemon=True)
            t.start()
        logger.info(
            "watcher 启动扫描派发 %d 个候选文件到后台线程 (project_id=%s)",
            count, self.project_id,
        )

    def _scan_existing_with_manifest(self) -> None:
        """v7.5: 启动时用 manifest 补漏标记 pending（停机期间新文件）。

        借鉴 git 启动时的 index 恢复——只标记待处理，不处理。
        scan_client_folder 已经把新文件和变更文件标 pending 了。
        同时检测被删除的文件，标红 + 清单备注。
        """
        try:
            from app.core.manifest import scan_client_folder
            scan_result = scan_client_folder(self.folder, project_id=self.project_id)
        except Exception as e:
            logger.warning("manifest 扫描失败: %r", e)
            return

        pending_count = scan_result.get("pending_count", 0)
        skipped = scan_result.get("skipped_count", 0)
        total = scan_result.get("total_count", 0)
        missing_files = scan_result.get("missing_files", [])

        # 处理被删除的文件：标红 + 清单备注
        missing_count = 0
        for missing_info in missing_files:
            try:
                self._handle_missing_file(missing_info)
                missing_count += 1
            except Exception as e:
                logger.warning("处理缺失文件失败 %s: %r", missing_info.get("rel_name"), e)

        logger.info(
            "watcher 启动扫描: total=%d, marked_pending=%d, skipped=%d, missing=%d (project_id=%s)",
            total, pending_count, skipped, missing_count, self.project_id,
        )

    def _handle_missing_file(self, missing_info: dict) -> None:
        """客户删除了已归档文件的处理。

        1. 写一条 file_archive 标红记录（archived_by='file_missing'）
        2. PBC 清单状态回退：已提供/审核中 → 未提供
        3. 推送 briefing 事件
        """
        from app.core.db import execute_with_retry, get_conn
        item_id = missing_info.get("item_id", "")
        rel_name = missing_info.get("rel_name", "")

        if not item_id:
            # 未识别的文件被删了，只记日志
            logger.info("缺失文件无 item_id（未分类文件被删）: %s", rel_name)
            return

        # 1. SQLite 记标红（archived_by='file_missing'，但不改状态——等审计员确认）
        try:
            execute_with_retry(
                """UPDATE file_archive SET archived_by='file_missing'
                   WHERE item_id=? AND project_id=?""",
                (item_id, self.project_id or ""),
            )
            logger.info("file_archive 标红: item_id=%s file=%s", item_id, rel_name)
        except Exception as e:
            logger.warning("file_archive 标红失败: %r", e)

        # 2. PBC 清单只写备注提醒（不回退状态——需审计员确认后再改）
        try:
            from app.core.excel_io import write_pbc_list
            write_pbc_list([{
                "item_id": item_id,
                "remark": f"⚠ 客户文件夹中该文件已不存在（{rel_name}），请核实后确认是否标记为未提供",
            }], project_id=self.project_id)
            logger.info("PBC 清单备注已标注: item_id=%s（状态未变，等审计员确认）", item_id)
        except Exception as e:
            logger.warning("PBC 清单备注写入失败: %r", e)

        # 3. 推送 briefing 事件（前端 toast 弹出，需审计员确认）
        try:
            from app.api.routes_files import _push_briefing_event
            import time
            _push_briefing_event({
                "timestamp": time.time(),
                "event_type": "file_missing",
                "item_id": item_id,
                "summary": f"⚠ 文件缺失: {item_id} ({rel_name})。归档目录文件仍在，但客户文件夹中已不存在。请核实后决定是否标记为未提供",
                "needs_confirm": True,
            })
        except Exception as e:
            logger.debug("briefing 事件推送失败（不阻断）: %r", e)

    def _dispatch_event(self, event) -> None:
        if getattr(event, "is_directory", False):
            return
        src = getattr(event, "src_path", None) or getattr(event, "dest_path", None)
        if not src:
            return
        p = Path(str(src))
        if p.suffix.lower() not in _ALLOWED_EXT:
            return
        t = threading.Thread(target=self._safe_trigger, args=(p,), daemon=True)
        t.start()

    def _safe_trigger(self, p: Path) -> None:
        """对单个文件：等稳定 → 标记 pending（不处理不归档）。

        借鉴 git status：文件系统变化只标记，不提交。
        处理留给 scan-folder（审计员手动触发）。
        """
        if not file_stable_size(p, stable_seconds=2, timeout=30):
            logger.warning("watcher 文件未稳定，跳过: %s", p)
            return

        # 只标记 pending（不处理不归档不调 AI）
        try:
            from app.core.manifest import mark_pending
            from app.core.db import get_project as _get_proj
            pid = self.project_id or ""
            client_folder = None
            if pid:
                _proj = _get_proj(pid)
                if _proj and _proj.get("client_folder"):
                    client_folder = Path(_proj["client_folder"])
            mark_pending(p, project_id=pid, client_folder=client_folder, reason="watchdog")
            logger.info("watchdog 标记 pending: %s (project_id=%s)", p.name, pid)
        except Exception as e:
            logger.warning("watchdog 标记 pending 失败 %s: %r", p, e)


# ----------------------------------------------------------------------
# 多项目 Watcher：遍历所有活跃项目，每个项目一个 FolderWatcher
# ----------------------------------------------------------------------
class MultiProjectWatcher:
    """监听所有活跃项目的 client_folder。

    每个项目独立 FolderWatcher，独立 Observer，独立 SHA 去重 set。
    """

    def __init__(self, on_new_file: NewFileCallback) -> None:
        self.on_new_file = on_new_file
        self._watchers: dict[str, FolderWatcher] = {}
        self._lock = threading.Lock()

    def start(self) -> bool:
        """启动所有活跃项目的 watcher。返回 True 表示至少有一个成功启动。"""
        from app.core.db import list_projects
        try:
            projects = list_projects(active_only=True)
        except Exception as e:
            logger.warning("MultiProjectWatcher: list_projects 失败 %r", e)
            return False

        if not projects:
            logger.warning("MultiProjectWatcher: 无活跃项目，跳过启动")
            return False

        any_started = False
        for proj in projects:
            pid = proj.get("project_id")
            if not pid:
                continue
            client_folder = proj.get("client_folder")
            if not client_folder:
                continue
            folder = Path(client_folder)
            if not folder.exists() or not folder.is_dir():
                logger.info("MultiProjectWatcher: 项目 %s client_folder 不存在，跳过: %s", pid, folder)
                continue

            w = FolderWatcher(
                folder=folder,
                on_new_file=self.on_new_file,
                project_id=pid,
            )
            ok = w.start()
            with self._lock:
                self._watchers[pid] = w
            if ok:
                any_started = True
            else:
                logger.warning("MultiProjectWatcher: 项目 %s watcher 启动失败", pid)

        logger.info(
            "MultiProjectWatcher 启动完成: %d 个 watcher, 至少一个成功=%s",
            len(self._watchers), any_started,
        )
        return any_started

    def stop(self) -> None:
        with self._lock:
            watchers = list(self._watchers.values())
            self._watchers.clear()
        for w in watchers:
            try:
                w.stop()
            except Exception as e:
                logger.warning("MultiProjectWatcher stop %r", e)

    def is_running(self) -> bool:
        with self._lock:
            return any(w.is_running() for w in self._watchers.values())

    def get_watched_projects(self) -> list[str]:
        with self._lock:
            return list(self._watchers.keys())


# ----------------------------------------------------------------------
# 默认实例化辅助（main.py 用）
# ----------------------------------------------------------------------
# 单项目默认 watcher（保留以兼容旧调用）
_global_watcher: Optional[FolderWatcher] = None

# 多项目默认 watcher（main.py 实际使用）
_global_multi_watcher: Optional[MultiProjectWatcher] = None


def start_default_watcher(on_new_file: NewFileCallback) -> bool:
    """启动默认 watcher（多项目模式）。

    优先使用 MultiProjectWatcher 监听所有活跃项目。
    失败不抛异常。
    """
    global _global_multi_watcher, _global_watcher
    try:
        _global_multi_watcher = MultiProjectWatcher(on_new_file)
        ok = _global_multi_watcher.start()
        if ok:
            return True
        # 多项目全部失败时，回退到单项目默认 watcher（监听 cfg.client_folder）
        logger.info("多项目 watcher 启动失败，回退到单项目默认 watcher")
    except Exception as e:
        logger.warning("MultiProjectWatcher 启动异常 %r，回退到单项目默认 watcher", e)

    try:
        _global_watcher = FolderWatcher(on_new_file=on_new_file)
        return _global_watcher.start()
    except Exception as e:
        logger.warning("start_default_watcher 异常: %r", e)
        return False


def stop_default_watcher() -> None:
    global _global_multi_watcher, _global_watcher
    if _global_multi_watcher is not None:
        _global_multi_watcher.stop()
        _global_multi_watcher = None
    if _global_watcher is not None:
        _global_watcher.stop()
        _global_watcher = None


def is_watcher_running() -> bool:
    if _global_multi_watcher is not None and _global_multi_watcher.is_running():
        return True
    return _global_watcher is not None and _global_watcher.is_running()


if __name__ == "__main__":
    # 自检：启动 2 秒，看日志
    def _on_file(p: Path, project_id: Optional[str] = None) -> None:
        print(f"[watcher] detected: {p} (project_id={project_id})")

    w = FolderWatcher(on_new_file=_on_file, project_id="test")
    ok = w.start()
    print("started:", ok)
    time.sleep(2)
    w.stop()
    print("stopped")
