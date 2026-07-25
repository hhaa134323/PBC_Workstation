"""PBC 文件处理 manifest（轻量指纹 + pending/processed 状态机）。

借鉴 VSCode Git 插件模型：检测与提交分离。
  - watchdog 事件 → 只标 pending（不处理不归档）
  - scan-folder → 只处理 pending 队列（分类归档 → 改 processed）
  - 启动扫描 → 用 manifest 补漏标记 pending（停机期间新文件）

manifest 记录每条文件的：
  (name, size, mtime, sha256, status, item_id, version, processed_at, pending_at)

status 取值：
  - "pending"  — 已检测待处理（watchdog 标记 / 启动补漏）
  - "processed" — 已处理归档（scan-folder 处理完）
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("pbc.manifest")

MANIFEST_FILENAME = ".pbc_manifest.json"

STATUS_PENDING = "pending"
STATUS_PROCESSED = "processed"


def _manifest_path(project_id: Optional[str] = None) -> Path:
    """manifest 文件路径：projects/{project_id}/.pbc_manifest.json"""
    from app.config import PROJECTS_DIR
    if project_id:
        return PROJECTS_DIR / project_id / MANIFEST_FILENAME
    return PROJECTS_DIR / MANIFEST_FILENAME


def load_manifest(project_id: Optional[str] = None) -> dict[str, dict]:
    """加载 manifest，返回 {relative_name: {size, mtime, sha256, status, ...}}。

    文件不存在返回空 dict（不抛异常）。
    """
    mp = _manifest_path(project_id)
    if not mp.exists():
        return {}
    try:
        with mp.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as e:
        logger.warning("manifest 读取失败 %s: %r", mp, e)
        return {}


def save_manifest(manifest: dict[str, dict], project_id: Optional[str] = None) -> None:
    """保存 manifest 到文件。"""
    mp = _manifest_path(project_id)
    mp.parent.mkdir(parents=True, exist_ok=True)
    try:
        with mp.open("w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("manifest 保存失败 %s: %r", mp, e)


def _file_stat(path: Path) -> Optional[dict[str, Any]]:
    """取文件 stat 信息（size + mtime），失败返回 None。"""
    try:
        st = path.stat()
        return {
            "size": st.st_size,
            "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
        }
    except OSError:
        return None


def _rel_name(file_path: Path, client_folder: Optional[Path] = None) -> str:
    """算相对客户文件夹的路径名（兼容子文件夹）。"""
    try:
        if client_folder:
            return str(file_path.relative_to(client_folder)).replace("\\", "/")
        return file_path.name
    except ValueError:
        return file_path.name


def mark_pending(
    file_path: Path,
    project_id: Optional[str] = None,
    client_folder: Optional[Path] = None,
    reason: str = "watchdog",
    manifest: Optional[dict[str, dict]] = None,
) -> dict[str, dict]:
    """watchdog 事件触发——标记文件为 pending（不处理不归档）。

    借鉴 git status：文件系统变化只标记，不提交。
    """
    if manifest is None:
        manifest = load_manifest(project_id)

    rn = _rel_name(file_path, client_folder)
    stat_info = _file_stat(file_path) or {}

    # 如果已有记录且是 processed，改回 pending（文件变了需重新处理）
    existing = manifest.get(rn, {})
    existing.update({
        "size": stat_info.get("size", 0),
        "mtime": stat_info.get("mtime", ""),
        "status": STATUS_PENDING,
        "pending_at": datetime.now().isoformat(timespec="seconds"),
        "pending_reason": reason,
        # 保留旧 item_id/version 供参考（但需要重新处理）
        "item_id": existing.get("item_id", ""),
        "version": existing.get("version", "v1"),
        "sha256": existing.get("sha256", ""),
    })
    manifest[rn] = existing
    save_manifest(manifest, project_id)

    # v7.6: 写变更日志
    try:
        from app.core.db import insert_change_log
        was_processed = existing.get("status") == "processed" if existing else False
        insert_change_log(
            project_id=project_id,
            file_name=file_path.name,
            change_type="modified" if was_processed else "added",
            changed_by=reason,
            detail=f"watchdog 标记 pending: {rn}",
        )
    except Exception:
        pass  # 日志写入失败不阻断主流程

    return manifest


def should_skip(
    file_path: Path,
    manifest: dict[str, dict],
    client_folder: Optional[Path] = None,
) -> tuple[bool, Optional[str], Optional[dict]]:
    """判断文件是否可以跳过（已处理且内容未变且非 pending）。

    Returns:
        (skip, reason, existing_record)
        skip=True: 文件已 processed 且 size+mtime 未变 → 跳过
        skip=False: 需要处理（new_file / stat_changed / pending）
    """
    rn = _rel_name(file_path, client_folder)
    record = manifest.get(rn)

    if not record:
        return False, "new_file", None

    status = record.get("status", "")

    # pending 状态 → 不跳过，需要处理
    if status == STATUS_PENDING:
        return False, "pending", record

    stat_info = _file_stat(file_path)
    if not stat_info:
        return False, "stat_failed", None

    # processed + size+mtime 没变 → 跳过
    if (stat_info["size"] == record.get("size")
            and stat_info["mtime"] == record.get("mtime")):
        return True, "unchanged", record

    # processed 但内容变了 → 不跳过（需要重新处理）
    return False, "stat_changed", record


def update_entry(
    file_path: Path,
    sha256: str,
    item_id: str = "",
    version: str = "v1",
    project_id: Optional[str] = None,
    client_folder: Optional[Path] = None,
    manifest: Optional[dict[str, dict]] = None,
) -> dict[str, dict]:
    """处理完一个文件后更新 manifest——标记为 processed。

    借鉴 git commit：提交后才标记为已处理。
    item_id 为空时不标记 processed（未分类的文件下次还要重试）。
    """
    if manifest is None:
        manifest = load_manifest(project_id)

    rn = _rel_name(file_path, client_folder)
    stat_info = _file_stat(file_path) or {}

    # item_id 为空 = 未分类/匹配失败 → 不标记 processed，下次重试
    status = STATUS_PROCESSED if item_id else STATUS_PENDING

    manifest[rn] = {
        "size": stat_info.get("size", 0),
        "mtime": stat_info.get("mtime", ""),
        "sha256": sha256,
        "status": status,
        "processed_at": datetime.now().isoformat(timespec="seconds") if item_id else "",
        "item_id": item_id,
        "version": version,
    }
    save_manifest(manifest, project_id)
    return manifest


def get_pending_files(
    project_id: Optional[str] = None,
    client_folder: Optional[Path] = None,
) -> dict[str, Any]:
    """获取 pending 文件列表（供 scan-folder 处理）。

    借鉴 git status：只返回需要 commit 的文件。

    Returns:
        {
            "pending_files": [Path, ...],     # status=pending 的文件
            "new_files": [Path, ...],        # manifest 里没有的文件
            "changed_files": [Path, ...],    # processed 但内容变了
            "skipped_count": int,            # processed 且未变
            "total_count": int,
            "missing_files": [dict, ...],    # manifest 有但文件夹没有
            "manifest": dict,
        }
    """
    manifest = load_manifest(project_id)

    pending_files: list[Path] = []
    new_files: list[Path] = []
    changed_files: list[Path] = []
    missing_files: list[dict[str, Any]] = []
    skipped = 0
    total = 0

    if not client_folder or not client_folder.exists() or not client_folder.is_dir():
        return {
            "pending_files": [],
            "new_files": [],
            "changed_files": [],
            "skipped_count": 0,
            "total_count": 0,
            "missing_files": [],
            "manifest": manifest,
        }

    existing_rels: set[str] = set()

    for p in client_folder.rglob("*"):
        if not p.is_file():
            continue
        if p.name.startswith(".") or p.name in ("Thumbs.db", "desktop.ini"):
            continue
        total += 1

        rn = _rel_name(p, client_folder)
        existing_rels.add(rn)

        record = manifest.get(rn)
        if not record:
            new_files.append(p)
            continue

        status = record.get("status", "")
        if status == STATUS_PENDING:
            pending_files.append(p)
            continue

        # processed → 检查 size+mtime
        stat_info = _file_stat(p)
        if stat_info and (stat_info["size"] == record.get("size")
                          and stat_info["mtime"] == record.get("mtime")):
            skipped += 1
        else:
            changed_files.append(p)

    # v7.7: 检测删除——只查有 file_archive 记录的（曾经归档过但现在客户文件夹没了）
    # 不检查"清单有但没提供"的——那不是缺失
    try:
        from app.core.db import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT item_id, original_path, sha256, version FROM file_archive WHERE project_id=?",
                (project_id or "",),
            )
            for row in cur:
                orig = row["original_path"] if isinstance(row, dict) else row[2]
                if not orig or not isinstance(orig, str):
                    continue
                if not Path(orig).exists():
                    missing_files.append({
                        "rel_name": Path(orig).name,
                        "item_id": row["item_id"] if isinstance(row, dict) else row[0],
                        "sha256": row["sha256"] if isinstance(row, dict) else row[1],
                        "version": row["version"] if isinstance(row, dict) else row[3],
                        "processed_at": "",
                    })
    except Exception as e:
        logger.warning("file_archive missing check failed: %r", e)

    logger.info(
        "get_pending_files: total=%d, pending=%d, new=%d, changed=%d, skipped=%d, missing=%d (project=%s)",
        total, len(pending_files), len(new_files), len(changed_files), skipped, len(missing_files), project_id,
    )

    return {
        "pending_files": pending_files,
        "new_files": new_files,
        "changed_files": changed_files,
        "skipped_count": skipped,
        "total_count": total,
        "missing_files": missing_files,
        "manifest": manifest,
    }


def scan_client_folder(
    client_folder: Path,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """扫描客户文件夹——启动时补漏标记 pending（停机期间新文件）。

    借鉴 git 启动时的 index 恢复。
    """
    result = get_pending_files(project_id, client_folder)

    # 启动扫描：把 new_files 也标 pending（它们还没在 manifest 里）
    manifest = result["manifest"]
    now = datetime.now().isoformat(timespec="seconds")
    for p in result["new_files"]:
        rn = _rel_name(p, client_folder)
        stat_info = _file_stat(p) or {}
        manifest[rn] = {
            "size": stat_info.get("size", 0),
            "mtime": stat_info.get("mtime", ""),
            "status": STATUS_PENDING,
            "pending_at": now,
            "pending_reason": "startup_scan",
            "item_id": "",
            "version": "v1",
            "sha256": "",
        }

    # changed_files 也标 pending
    for p in result["changed_files"]:
        rn = _rel_name(p, client_folder)
        existing = manifest.get(rn, {})
        stat_info = _file_stat(p) or {}
        existing.update({
            "size": stat_info.get("size", 0),
            "mtime": stat_info.get("mtime", ""),
            "status": STATUS_PENDING,
            "pending_at": now,
            "pending_reason": "stat_changed",
        })
        manifest[rn] = existing

    if result["new_files"] or result["changed_files"]:
        save_manifest(manifest, project_id)

    # 重新计算 pending 总数
    pending_count = len(result["pending_files"]) + len(result["new_files"]) + len(result["changed_files"])

    logger.info(
        "scan_client_folder (startup): marked %d pending (project=%s)",
        pending_count, project_id,
    )

    result["pending_count"] = pending_count
    return result


def detect_missing_files(
    client_folder: Path,
    manifest: dict[str, dict],
    project_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """检测客户文件夹中哪些已归档文件被删除了。
    
    v7.7: 只检查有 file_archive 记录的文件（曾经归档过），
    不检查"清单有但没提供"的——那不是缺失，是还没提供。
    """
    missing: list[dict[str, Any]] = []
    
    # v7.7: 从 file_archive 表查曾经归档过的文件（original_path）
    try:
        from app.core.db import get_conn
        with get_conn() as conn:
            cur = conn.execute(
                "SELECT item_id, original_path, sha256, version FROM file_archive WHERE project_id=?",
                (project_id or "",),
            )
            archive_records = [dict(r) for r in cur.fetchall()]
    except Exception:
        archive_records = []
    
    # 检查每个曾归档过的文件在不在客户文件夹
    for ar in archive_records:
        orig = ar.get("original_path", "")
        if not orig:
            continue
        file_path = Path(orig)
        if not file_path.exists():
            missing.append({
                "rel_name": file_path.name,
                "item_id": ar.get("item_id", ""),
                "sha256": ar.get("sha256", ""),
                "version": ar.get("version", "v1"),
            })
            # v7.6: 写变更日志
            try:
                from app.core.db import insert_change_log
                insert_change_log(
                    project_id=project_id,
                    file_name=rel_name,
                    change_type="deleted",
                    item_id=record.get("item_id", ""),
                    sha256=record.get("sha256", ""),
                    changed_by="watchdog",
                    detail=f"客户文件夹文件消失: {rel_name}",
                )
            except Exception:
                pass
    return missing


def get_pending_count(project_id: Optional[str] = None) -> int:
    """获取 pending 文件数（供前端展示待处理数）。"""
    manifest = load_manifest(project_id)
    return sum(1 for r in manifest.values() if r.get("status") == STATUS_PENDING)
