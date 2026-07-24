"""文件上传/拖拽处理路由（M3 + M4 + 多项目支持）。

接口（多项目）：
- POST /api/files/{project_id}/drag-drop        接收文件，异步处理
- POST /api/files/{project_id}/scan-folder      扫描该项目客户共享文件夹
- GET  /api/files/{project_id}/task/{task_id}   查询异步任务状态
- GET  /api/files/{project_id}/recent-tasks     列出最近 N 个任务
- GET  /api/files/{project_id}/list             列出已归档文件
- GET  /api/files/{project_id}/config/folder    获取该项目客户文件夹配置
- POST /api/files/{project_id}/config/folder    设置该项目客户文件夹

兼容旧路由（不带 project_id，走 demo 项目）：
- POST /api/files/drag-drop
- POST /api/files/scan-folder
- GET  /api/files/task/{task_id}
- GET  /api/files/list
- GET  /api/files/recent-tasks
- GET  /api/files/config/folder
- POST /api/files/config/folder

处理流程（drag-drop / scan-folder / watchdog 共用 _process_one_file_sync）：
1. 文件 hash 去重（M4: 查 file_archive 表，按 project_id 维度去重）
2. file_parser.parse_file 提取文本
3. ai_client.classify_file 识别对应 PBC item（拿 actual_item_id）
4. 回填 ai_history.item_id（M4 新增）
5. ai_client.check_period_completeness 期间检查
6. archive_file 归档文件（按 project_id + entity 归档）
7. excel_io.write_pbc_list 写 file_path（用归档后路径）+ confidence
8. update_item_status 推进状态 未提供 → 已提供，审核中
9. db.insert_archive 写索引（带 project_id）
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Body, File, Query, UploadFile
from pydantic import BaseModel, Field

from app.config import (
    get_config,
    save_user_config,
    get_current_client_folder,
)
from app.core.ai_client import AIClient
from app.core import archive as archive_mod
from app.core.db import (
    get_archive_by_sha, get_project, insert_archive, get_task, get_latest_ai_history_id,
    list_recent_archives, list_recent_tasks, update_ai_history_item_id,
    upsert_task, get_archive_by_item, delete_archive_by_item, delete_archive_by_path,
    insert_change_log, get_change_log,
)
from app.core.excel_io import (
    STATUS_NOT_PROVIDED, STATUS_REVIEWING,
    get_item_by_id, read_pbc_list, update_item_status, write_pbc_list,
)
from app.core.file_parser import parse_file
from app.utils.path_utils import file_hash_sha256, safe_path

logger = logging.getLogger("pbc.routes_files")

router = APIRouter(prefix="/api/files", tags=["files"])

_DEFAULT_PROJECT = "demo"


# ----------------------------------------------------------------------
# 简报事件队列（watchdog 处理新文件后，主动评估"解除风险"事件，
# 推到这个队列，前端轮询 /api/files/briefing-events 拉取，呈现"主动开口"效果）
# ----------------------------------------------------------------------
_briefing_events: list[dict[str, Any]] = []
_BRIEFING_EVENTS_MAX = 20


def _push_briefing_event(evt: dict[str, Any]) -> None:
    """推送一条简报事件到内存队列（前端轮询消费）。"""
    _briefing_events.insert(0, evt)
    if len(_briefing_events) > _BRIEFING_EVENTS_MAX:
        del _briefing_events[_BRIEFING_EVENTS_MAX:]


@router.get("/briefing-events")
async def get_briefing_events(since: float = 0.0) -> dict[str, Any]:
    """前端轮询：返回 since 之后所有新事件（含 watchdog 触发的"解除风险"）。"""
    events = [e for e in _briefing_events if e.get("timestamp", 0) > since]
    return {"events": events, "count": len(events), "latest_ts": _briefing_events[0].get("timestamp", 0) if _briefing_events else 0}


# ----------------------------------------------------------------------
# 用户配置接口（M4.6 + 多项目）
# 主输入路径：用户配置"客户共享文件夹"路径 → 后端直接读本地路径（零上传）
# 拖拽上传保留为兜底路径，>50MB 警告用扫描代替
# ----------------------------------------------------------------------
class FolderConfigUpdate(BaseModel):
    """前端"设置→选择客户文件夹"提交的请求体。"""
    client_folder: Optional[str] = None
    pbc_list_path: Optional[str] = None


# ----------------------------------------------------------------------
# 进程内辅助状态
# ----------------------------------------------------------------------
# M3 的内存 _tasks dict 在 M4 中已迁移到 SQLite tasks 表（重启不丢）
# 进程内 hash_seen 仅作为本次进程的去重快路径，SQLite 是权威
# 多项目: key 改为 (project_id, sha256) 避免跨项目误判
_hash_seen: dict[tuple[str, str], str] = {}

_ai_client: Optional[AIClient] = None


def _get_ai_client() -> AIClient:
    global _ai_client
    if _ai_client is None:
        _ai_client = AIClient()
    return _ai_client


def _get_ai_flags() -> dict:
    """v7: 读 AI 配置里的两个开关（置信度阈值 + 文件名直配开关）。

    从 config/api_config.json 的 ai_flags 段读，失败用默认值。
    """
    try:
        from app.api.routes_config import _load_raw_config
        raw = _load_raw_config()
        flags = raw.get("ai_flags") or {}
        return {
            "confidence_threshold": float(flags.get("confidence_threshold", 0.7)),
            "filename_match_enabled": bool(flags.get("filename_match_enabled", True)),
        }
    except Exception:
        return {"confidence_threshold": 0.7, "filename_match_enabled": True}


def _xlsx_path(project_id: Optional[str] = None) -> str:
    """取该项目 PBC 清单路径；不传 project_id 用全局 config（兼容）。"""
    if project_id:
        proj = get_project(project_id)
        if proj is None:
            raise FileNotFoundError(f"项目不存在: {project_id}")
        return proj.get("pbc_list_path") or ""
    return str(get_config().pbc_list_path)


def _project_client_folder(project_id: str) -> Path:
    """从 projects 表取该项目的 client_folder；不存在则回退到全局 config。"""
    proj = get_project(project_id)
    if proj and proj.get("client_folder"):
        return Path(proj["client_folder"])
    return Path(get_config().client_folder)


def _new_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _set_task(task_id: str, project_id: Optional[str] = None, **fields: Any) -> None:
    """写入 SQLite tasks 表（M4：替代内存 _tasks dict）。"""
    try:
        upsert_task(task_id, project_id=project_id or "", **fields)
    except Exception as e:
        logger.error("upsert_task 失败 task_id=%s: %r", task_id, e)


# ----------------------------------------------------------------------
# 拖拽前文件大小检查（兼容旧调用，不走项目）
# ----------------------------------------------------------------------
@router.post("/drag-drop/check")
async def check_files_before_upload(files: list[UploadFile] = File(...)) -> dict:
    """前端拖拽前先调这个接口检查文件大小，>50MB 警告用扫描代替。"""
    cfg = get_config()
    threshold = cfg.file_size_threshold_mb * 1024 * 1024
    results = []
    for f in files:
        try:
            content = await f.read()
            size = len(content)
            await f.seek(0)
        except Exception:
            size = 0
        results.append({
            "name": f.filename,
            "size": size,
            "size_mb": round(size / 1024 / 1024, 2),
            "over_threshold": size > threshold,
            "suggestion": "建议改用扫描文件夹" if size > threshold else "可拖拽上传",
        })
    return {
        "ok": True,
        "threshold_mb": cfg.file_size_threshold_mb,
        "files": results,
        "any_over_threshold": any(r["over_threshold"] for r in results),
    }


# ----------------------------------------------------------------------
# 多项目路由：客户文件夹配置
# ----------------------------------------------------------------------
@router.get("/{project_id}/config/folder")
async def get_folder_config_by_project(project_id: str) -> dict:
    """获取某项目客户文件夹配置（前端展示用）。"""
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    cf_str = proj.get("client_folder") or ""
    p = Path(cf_str) if cf_str else None
    info = {
        "path": cf_str,
        "exists": p.exists() if p else False,
        "is_dir": p.is_dir() if (p and p.exists()) else False,
        "file_count": len(list(p.rglob("*"))) if (p and p.exists() and p.is_dir()) else 0,
    }
    return {
        "ok": True,
        "project_id": project_id,
        "current": info,
        "tip": (
            "建议指向 OneDrive 挂载点（如 C:/Users/审计员/OneDrive - 客户公司/PBC资料）。"
            "后端直接读本地路径，无上传，速度快且无失败风险。"
        ),
    }


@router.post("/{project_id}/config/folder")
async def set_folder_config_by_project(project_id: str, body: FolderConfigUpdate) -> dict:
    """保存某项目客户文件夹路径配置（写入 projects 表）。"""
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    if not body.client_folder and not body.pbc_list_path:
        return {"ok": False, "error": "至少要传一个字段"}

    fields: dict[str, Any] = {}
    if body.client_folder is not None:
        try:
            p = Path(body.client_folder).expanduser().resolve()
            if p.exists() and p.is_dir():
                fields["client_folder"] = str(p)
            else:
                # P1-14: 友好提示，列出路径与建议
                return {
                    "ok": False,
                    "error": "folder_not_found",
                    "path": body.client_folder,
                    "resolved_path": str(p),
                    "suggestion": (
                        f"请检查路径：{body.client_folder}，"
                        "建议改指向 OneDrive 挂载点（如 C:/Users/审计员/OneDrive - 客户公司/PBC资料）。"
                        "后端直接读本地路径，无上传。"
                    ),
                    "tip": "确认路径无误、盘符正确，或先在文件管理器中打开该文件夹验证。",
                }
        except Exception as e:
            return {"ok": False, "error": f"路径解析失败: {e}"}

    if body.pbc_list_path is not None:
        try:
            p = Path(body.pbc_list_path).expanduser().resolve()
            if p.exists() and p.is_file():
                fields["pbc_list_path"] = str(p)
            else:
                return {"ok": False, "error": f"PBC 清单文件不存在: {body.pbc_list_path}"}
        except Exception as e:
            return {"ok": False, "error": f"PBC 清单路径解析失败: {e}"}

    if not fields:
        return {"ok": False, "error": "无可更新字段"}

    from app.core.db import update_project
    updated = update_project(project_id, **fields)
    return {"ok": True, "project_id": project_id, "project": updated, "changed": list(fields.keys())}


# ----------------------------------------------------------------------
# 多项目路由：drag-drop
# ----------------------------------------------------------------------
@router.post("/{project_id}/drag-drop")
async def drag_drop_by_project(project_id: str, files: list[UploadFile] = File(...)) -> dict:
    """接收前端 HTML5 拖拽的文件列表，立即返回 task_id，异步处理。"""
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    task_id = _new_task_id()
    received = []
    saved_paths: list[Path] = []

    upload_dir = Path(proj.get("archive_root") or "") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    for f in files:
        name = f.filename or "unnamed"
        safe_name = Path(name).name
        dest = upload_dir / f"{uuid.uuid4().hex[:8]}_{safe_name}"
        try:
            content = await f.read()
            dest.write_bytes(content)
            saved_paths.append(dest)
            received.append({"name": name, "size": len(content), "saved": str(dest)})
        except Exception as e:
            logger.warning("drag-drop save %s failed: %r", name, e)
            received.append({"name": name, "error": str(e)})

    _set_task(
        task_id,
        project_id=project_id,
        status="processing",
        progress=0,
        source="drag-drop",
        received_json=received,
        results_json=[],
        started_at=_now_iso(),
    )

    # 异步处理
    asyncio.create_task(_process_paths(task_id, project_id, saved_paths, source="drag-drop"))

    return {
        "task_id": task_id,
        "project_id": project_id,
        "status": "processing",
        "received_files": received,
        "next": f"/api/files/{project_id}/task/{task_id}",
    }


# ----------------------------------------------------------------------
# 多项目路由：scan-folder
# ----------------------------------------------------------------------
@router.post("/{project_id}/scan-folder")
async def scan_folder_by_project(project_id: str, folder: Optional[str] = None) -> dict:
    """扫描该项目的客户共享文件夹——只处理 pending 队列。

    借鉴 git status + git commit：
    - pending 文件（watchdog 标记 / 启动补漏 / 变更）→ 处理
    - processed 且未变 → 跳过
    - manifest 有但文件夹没有 → 删除检测（标红 + 推消息）
    """
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    base = safe_path(folder) if folder else _project_client_folder(project_id)
    if not base.exists() or not base.is_dir():
        return {
            "project_id": project_id,
            "folder": str(base),
            "status": "not_found",
            "files": [],
            "count": 0,
            "suggestion": (
                f"请检查路径：{base}，建议改指向 OneDrive 挂载点"
                "（如 C:/Users/审计员/OneDrive - 客户公司/PBC资料）。"
                "后端直接读本地路径，无上传。"
            ),
        }

    # PBC 清单未导入 → 拦截
    try:
        from app.core.excel_io import read_pbc_list
        pbc_items_check = read_pbc_list(project_id=project_id)
        if not pbc_items_check:
            return {
                "project_id": project_id,
                "folder": str(base),
                "status": "no_pbc_list",
                "message": "PBC 清单为空，请先导入 PBC 清单再扫描",
                "suggestion": "导入 PBC 清单后，系统才能将客户文件匹配到清单项并归档",
            }
    except Exception:
        pass

    # 获取 pending 文件队列（借鉴 git status：只返回需要 commit 的）
    from app.core.manifest import get_pending_files
    pending_result = get_pending_files(project_id, base)

    pending_files = pending_result["pending_files"]
    new_files = pending_result["new_files"]
    changed_files = pending_result["changed_files"]
    skipped = pending_result["skipped_count"]
    total = pending_result["total_count"]
    missing_files = pending_result["missing_files"]

    # 合并待处理文件列表
    to_process_paths = pending_files + new_files + changed_files

    # 识别穿行测试子目录（一级子目录作为整目录归档单元）
    allowed_ext = {".pdf", ".xlsx", ".xlsm", ".csv", ".txt", ".md", ".json", ".xml"}
    directories: list[dict] = []
    dir_paths: list[Path] = []
    for p in base.iterdir():
        if p.is_dir() and p != base:
            sub_files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in allowed_ext]
            if sub_files:
                # 检查目录是否 pending（目录内任一文件 pending 则整目录 pending）
                from app.core.manifest import _rel_name, load_manifest
                manifest = pending_result["manifest"]
                dir_pending = False
                for sf in sub_files:
                    rn = _rel_name(sf, base)
                    rec = manifest.get(rn)
                    if not rec or rec.get("status") == "pending":
                        dir_pending = True
                        break
                if dir_pending:
                    directories.append({
                        "path": str(p.relative_to(base)),
                        "abs_path": str(p),
                        "name": p.name,
                        "file_count": len(sub_files),
                    })
                    dir_paths.append(p)
                    # 从散文件列表里移除属于子目录的文件
                    to_process_paths = [
                        fp for fp in to_process_paths
                        if not (fp.is_relative_to(p) if hasattr(fp, 'is_relative_to') else False)
                    ]

    # 处理删除检测（标红 + 推消息，不自动改状态）
    missing_count = 0
    for missing_info in missing_files:
        try:
            from app.core.watcher import FolderWatcher
            fw = FolderWatcher.__new__(FolderWatcher)
            fw.project_id = project_id
            fw._handle_missing_file(missing_info)
            missing_count += 1
        except Exception as e:
            logger.warning("删除检测处理失败 %s: %r", missing_info.get("rel_name"), e)

    # 没有待处理文件
    if len(to_process_paths) == 0 and len(directories) == 0:
        return {
            "project_id": project_id,
            "folder": str(base),
            "status": "no_pending",
            "files_found": total,
            "count": total,
            "to_process": 0,
            "skipped": skipped,
            "missing_detected": missing_count,
            "message": "没有待处理文件（已全部归档或无新文件）",
        }

    task_id = _new_task_id()
    _set_task(
        task_id,
        project_id=project_id,
        status="processing",
        progress=0,
        source="scan-folder",
        folder=str(base),
        total=len(to_process_paths) + len(directories),
        done_count=0,
        results_json=[],
        started_at=_now_iso(),
    )

    asyncio.create_task(
        _process_paths(
            task_id, project_id,
            to_process_paths,
            source="scan-folder",
            directories=dir_paths,
        )
    )

    return {
        "task_id": task_id,
        "project_id": project_id,
        "status": "processing",
        "folder": str(base),
        "files_found": total,
        "count": total,
        "to_process": len(to_process_paths),
        "directories_count": len(directories),
        "skipped": skipped,
        "missing_detected": missing_count,
        "next": f"/api/files/{project_id}/task/{task_id}",
    }


@router.get("/{project_id}/task/{task_id}")
async def get_task_route_by_project(project_id: str, task_id: str) -> dict:
    """查询某项目的异步任务状态。"""
    task = get_task(task_id)
    if task is None:
        return {"project_id": project_id, "task_id": task_id, "status": "unknown", "progress": 0}
    return {"project_id": project_id, "task_id": task_id, **task}


@router.get("/{project_id}/pending-count")
async def get_pending_count_route(project_id: str) -> dict:
    """获取待处理文件数（供前端展示，借鉴 git status 的未提交计数）。"""
    from app.core.manifest import get_pending_count
    count = get_pending_count(project_id)
    return {"project_id": project_id, "pending_count": count}


@router.get("/{project_id}/recent-tasks")
async def recent_tasks_by_project(
    project_id: str, limit: int = Query(20, ge=1, le=500)
) -> dict:
    """列出某项目最近 N 个任务。"""
    try:
        tasks = list_recent_tasks(limit=limit, project_id=project_id)
    except Exception as e:
        logger.error("recent-tasks 查询失败: %r", e)
        return {"project_id": project_id, "tasks": [], "count": 0, "error": str(e)}
    return {"project_id": project_id, "tasks": tasks, "count": len(tasks)}


@router.get("/{project_id}/list")
async def list_processed_files_by_project(project_id: str, limit: int = 100) -> dict:
    """列出某项目已归档文件。"""
    try:
        rows = list_recent_archives(limit=limit, project_id=project_id)
    except Exception as e:
        logger.error("list_processed_files 查询失败: %r", e)
        return {"project_id": project_id, "files": [], "count": 0, "error": str(e)}

    return {"project_id": project_id, "files": rows, "count": len(rows)}


@router.get("/{project_id}/archive-detail/{item_id}")
async def archive_detail_by_item(project_id: str, item_id: str) -> dict:
    """获取某 PBC 项的归档文件详情（用于文件详情弹窗）。"""
    try:
        from app.core.db import get_archive_by_item
        archives = get_archive_by_item(item_id, project_id=project_id)
    except Exception as e:
        logger.error("archive_detail 查询失败: %r", e)
        return {"project_id": project_id, "item_id": item_id, "archives": [], "count": 0, "error": str(e)}

    return {
        "project_id": project_id,
        "item_id": item_id,
        "archives": archives,
        "count": len(archives),
    }


# ----------------------------------------------------------------------
# v7: 路径透明化 API（文件流向图 + 归档目录可配置 + 文件失联检测）
# ----------------------------------------------------------------------
@router.get("/{project_id}/paths")
async def get_paths_by_project(project_id: str) -> dict:
    """v7: 返回客户文件夹路径 + 归档根目录 + 两边文件数（文件流向图用）。

    返回：
    {
      "project_id": ...,
      "client_folder": {"path":..., "exists":..., "file_count":...},
      "archive_root": {"path":..., "exists":..., "category_count":..., "file_count":...},
      "flow": "客户共享文件夹（未整理） → 归档目录（已整理，按一级分类）"
    }
    """
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    cf_str = proj.get("client_folder") or ""
    ar_str = proj.get("archive_root") or ""

    cf = Path(cf_str) if cf_str else None
    ar = Path(ar_str) if ar_str else None

    cf_info = {
        "path": cf_str,
        "exists": cf.exists() if cf else False,
        "is_dir": cf.is_dir() if (cf and cf.exists()) else False,
        "file_count": len([p for p in cf.rglob("*") if p.is_file()]) if (cf and cf.exists() and cf.is_dir()) else 0,
    }
    ar_info = {
        "path": ar_str,
        "exists": ar.exists() if ar else False,
        "is_dir": ar.is_dir() if (ar and ar.exists()) else False,
        "category_count": len([p for p in ar.iterdir() if p.is_dir()]) if (ar and ar.exists() and ar.is_dir()) else 0,
        "file_count": len([p for p in ar.rglob("*") if p.is_file()]) if (ar and ar.exists() and ar.is_dir()) else 0,
    }

    return {
        "project_id": project_id,
        "client_folder": cf_info,
        "archive_root": ar_info,
        "flow_hint": "客户共享文件夹（未整理）→ AI 分类 → 归档目录（已整理，按一级分类）",
        "archive_naming_hint": "归档路径格式：归档根目录/一级分类/编号_描述_期间_版本.ext",
    }


@router.get("/{project_id}/archive-tree")
async def get_archive_tree_by_project(project_id: str) -> dict:
    """v7: 返回归档目录树（按一级分类分组，前端右侧"已归档树"渲染）。

    返回：
    {
      "project_id": ...,
      "archive_root": "...",
      "tree": [
        {"category":"历史沿革", "path":..., "count":3, "files":[{name,path,size,mtime}, ...]},
        ...
      ]
    }
    """
    from app.core.archive import list_archive_tree, get_archive_root
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")
    root = get_archive_root(project_id=project_id)
    tree = list_archive_tree(project_id=project_id)
    return {
        "project_id": project_id,
        "archive_root": str(root),
        "tree": tree,
    }


@router.post("/{project_id}/config/archive-root")
async def set_archive_root_by_project(project_id: str, body: dict) -> dict:
    """v7: 配置归档根目录（用户可指定到桌面等可见位置）。

    请求体：{"archive_root": "D:/Desktop/PBC归档"}
    校验路径存在 + 是目录，写入 projects 表 archive_root 字段。
    """
    from app.core.db import update_project
    proj = get_project(project_id)
    if proj is None:
        raise FileNotFoundError(f"项目不存在: {project_id}")

    ar = body.get("archive_root")
    if not ar:
        return {"ok": False, "error": "archive_root 不能为空"}

    try:
        p = Path(ar).expanduser().resolve()
        if p.exists() and p.is_dir():
            updated = update_project(project_id, archive_root=str(p))
            return {"ok": True, "project_id": project_id, "archive_root": str(p), "project": updated}
        else:
            return {
                "ok": False,
                "error": "folder_not_found",
                "path": ar,
                "resolved_path": str(p),
                "suggestion": "归档目录必须存在且是文件夹。请先在文件管理器中创建该文件夹。",
            }
    except Exception as e:
        return {"ok": False, "error": f"路径解析失败: {e}"}


@router.post("/{project_id}/open-folder-path")
async def open_folder_path(project_id: str, body: dict) -> dict:
    """v7: 打开任意路径（归档目录 / 文件所在目录 / 客户文件夹）。

    请求体：{"path": "D:/.../PBC归档/历史沿革"}
    - 如果 path 是目录，直接打开
    - 如果 path 是文件，打开其父目录
    """
    import os
    import sys
    path_str = body.get("path")
    if not path_str:
        return {"ok": False, "error": "path 不能为空"}
    p = Path(path_str)
    target = p if p.is_dir() else p.parent
    if not target.exists():
        return {"ok": False, "error": f"路径不存在: {path_str}"}
    try:
        if sys.platform == "win32":
            os.startfile(str(target))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["open", str(target)])
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(target)])
        return {"ok": True, "path": str(target)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/{project_id}/check-valid/{item_id}")
async def check_archive_valid(project_id: str, item_id: str) -> dict:
    """v7: 检查某编号对应的归档文件是否仍存在（文件失联检测）。

    前端用：PBC list 文件路径列失效时标红 + 弹「重新定位」按钮。
    """
    from app.core.archive import check_archive_path_valid
    return check_archive_path_valid(item_id, project_id=project_id)


@router.post("/{project_id}/relocate/{item_id}")
async def relocate_archive_api(project_id: str, item_id: str, body: dict) -> dict:
    """v7: 文件失联后，用户指定新位置，后端按 sha256 重新绑定。

    请求体：{"new_path": "D:/.../新文件.pdf"}
    """
    from app.core.archive import relocate_archive
    new_path = body.get("new_path")
    if not new_path:
        return {"ok": False, "error": "new_path 不能为空"}
    return relocate_archive(item_id, new_path, project_id=project_id)


# ----------------------------------------------------------------------
# 兼容旧路由（不带 project_id，走 demo 项目）
# ----------------------------------------------------------------------
@router.get("/config/folder")
async def get_folder_config() -> dict:
    """获取当前客户文件夹配置（前端展示用，兼容旧调用）。"""
    info = get_current_client_folder()
    return {
        "ok": True,
        "current": info,
        "default_path": "mock_data/客户共享文件夹",
        "deprecated_hint": f"请改用 /api/files/{_DEFAULT_PROJECT}/config/folder",
        "tip": (
            "建议指向 OneDrive 挂载点（如 C:/Users/审计员/OneDrive - 客户公司/PBC资料）。"
            "后端直接读本地路径，无上传，速度快且无失败风险。"
        ),
    }


@router.post("/config/folder")
async def set_folder_config(body: FolderConfigUpdate) -> dict:
    """保存客户文件夹路径配置（user_config.json 持久化，兼容旧调用）。"""
    if not body.client_folder and not body.pbc_list_path:
        return {"ok": False, "error": "至少要传一个字段"}
    return save_user_config(
        client_folder=body.client_folder,
        pbc_list_path=body.pbc_list_path,
    )


@router.post("/drag-drop")
async def drag_drop(files: list[UploadFile] = File(...)) -> dict:
    """接收前端拖拽文件（兼容旧调用，走 demo 项目）。"""
    return await drag_drop_by_project(_DEFAULT_PROJECT, files)


@router.post("/scan-folder")
async def scan_folder(folder: Optional[str] = None) -> dict:
    """扫描客户共享文件夹（兼容旧调用，走 demo 项目）。"""
    return await scan_folder_by_project(_DEFAULT_PROJECT, folder=folder)


@router.get("/task/{task_id}")
async def get_task_route(task_id: str) -> dict:
    """查询异步任务状态（兼容旧调用）。"""
    task = get_task(task_id)
    if task is None:
        return {"task_id": task_id, "status": "unknown", "progress": 0}
    return {"task_id": task_id, **task}


@router.get("/list")
async def list_processed_files(limit: int = 100) -> dict:
    """列出已归档文件（兼容旧调用，走 demo 项目）。"""
    try:
        rows = list_recent_archives(limit=limit, project_id=_DEFAULT_PROJECT)
    except Exception as e:
        # 兜底：全量查
        try:
            rows = list_recent_archives(limit=limit)
        except Exception as e2:
            logger.error("list_processed_files 查询失败: %r", e2)
            return {"files": [], "count": 0, "error": str(e2)}

    return {"files": rows, "count": len(rows)}


@router.get("/recent-tasks")
async def recent_tasks(limit: int = Query(20, ge=1, le=500)) -> dict:
    """列出最近 N 个任务（兼容旧调用，走 demo 项目）。"""
    try:
        tasks = list_recent_tasks(limit=limit, project_id=_DEFAULT_PROJECT)
    except Exception as e:
        # 兜底：全量查
        try:
            tasks = list_recent_tasks(limit=limit)
        except Exception as e2:
            logger.error("recent-tasks 查询失败: %r", e2)
            return {"tasks": [], "count": 0, "error": str(e2)}
    return {"tasks": tasks, "count": len(tasks)}

# ----------------------------------------------------------------------
# 后台处理逻辑
# ----------------------------------------------------------------------
async def _process_paths(
    task_id: str,
    project_id: str,
    paths: list[Path],
    source: str = "drag-drop",
    directories: Optional[list[Path]] = None,
) -> None:
    """对每个文件依次处理（顺序避免 SQLite 锁竞争）。

    v7: directories 参数支持整目录归档单元（穿行测试资料）。
    """
    total = len(paths) + len(directories or [])
    results: list[dict[str, Any]] = []
    done = 0

    for p in paths:
        in_progress_pct = int(done * 100 / total) if total else 100
        in_progress_pct = max(in_progress_pct, 5)
        _set_task(
            task_id,
            project_id=project_id,
            progress=in_progress_pct,
            done_count=done,
            total=total,
            results_json=results,
            current_file=p.name,
            stage="processing",
        )
        result = await _process_one_file(p, project_id=project_id, source=source)
        results.append(result)
        done += 1
        progress = int(done * 100 / total) if total else 100
        _set_task(
            task_id,
            project_id=project_id,
            progress=progress,
            done_count=done,
            total=total,
            results_json=results,
            current_file=None,
            stage="completed" if done >= total else "processing",
        )

    # v7: 处理整目录归档单元
    for d in (directories or []):
        in_progress_pct = int(done * 100 / total) if total else 100
        in_progress_pct = max(in_progress_pct, 5)
        _set_task(
            task_id,
            project_id=project_id,
            progress=in_progress_pct,
            done_count=done,
            total=total,
            results_json=results,
            current_file=d.name + "/",
            stage="processing",
        )
        result = await asyncio.to_thread(_process_one_directory, d, project_id=project_id, source=source)
        results.append(result)
        done += 1
        progress = int(done * 100 / total) if total else 100
        _set_task(
            task_id,
            project_id=project_id,
            progress=progress,
            done_count=done,
            total=total,
            results_json=results,
            current_file=None,
            stage="completed" if done >= total else "processing",
        )

    status = "done" if all(r.get("ok") for r in results) else "done_with_errors"
    if total == 0:
        status = "done"
    _set_task(
        task_id,
        project_id=project_id,
        status=status,
        progress=100,
        done_count=done,
        total=total,
        results_json=results,
        finished_at=_now_iso(),
    )


def _process_one_directory(
    dir_path: Path,
    project_id: Optional[str] = None,
    source: str = "scan-folder",
) -> dict[str, Any]:
    """v7: 处理一个子目录（整目录归档，SOP §5.5 Tips）。

    流程：
    1. 取目录内代表性文件（按大小取前 3 个 PDF/Excel）合并文本
    2. 读 PBC 清单
    3. AI 分类（文件名优先匹配，fallback 用合并文本）
    4. 整目录归档到 archives/{一级分类}/{编号}_{文件夹名}/
    5. PBC list 反写目录路径
    """
    result: dict[str, Any] = {
        "ok": True, "path": str(dir_path), "name": dir_path.name,
        "project_id": project_id or "", "is_directory": True,
    }

    try:
        pbc_items = read_pbc_list(project_id=project_id)
    except Exception as e:
        return {**result, "ok": False, "error": f"read_pbc_list failed: {e}"}

    # 取代表性文件（按大小取前 3 个 PDF/Excel）
    sub_files = sorted(
        [f for f in dir_path.iterdir() if f.is_file()],
        key=lambda f: f.stat().st_size if f.exists() else 0,
        reverse=True,
    )[:3]

    merged_text = ""
    for f in sub_files:
        try:
            parsed = parse_file(f)
            if parsed.get("ok"):
                merged_text += "\n--- " + f.name + " ---\n" + parsed.get("text", "")[:1500]
        except Exception:
            pass

    # v7: 文件名优先匹配（受 ai_flags 开关控制）
    item_id = None
    entity = None
    category = None
    description = None
    required_period = None
    fname_matched = False
    client = _get_ai_client()
    pbc_list_empty = not pbc_items
    ai_flags = _get_ai_flags()

    if not pbc_list_empty and ai_flags.get("filename_match_enabled", True):
        for it in pbc_items:
            iid = it.get("item_id", "")
            if iid and iid in dir_path.name:
                item_id = iid
                entity = it.get("entity")
                category = it.get("category")
                description = it.get("description")
                required_period = it.get("required_period")
                fname_matched = True
                break

    if not fname_matched and not pbc_list_empty:
        classify = client.classify_file(merged_text, pbc_items, file_hint=dir_path.name)
        if classify.get("ok"):
            item_id = classify.get("item_id")
            if item_id:
                for it in pbc_items:
                    if str(it.get("item_id")) == str(item_id):
                        entity = it.get("entity")
                        category = it.get("category")
                        description = it.get("description")
                        required_period = it.get("required_period")
                        break

    # 整目录归档
    try:
        arc_result = archive_mod.archive_directory(
            source_dir=dir_path,
            item_id=item_id or "UNCLASSIFIED",
            entity=entity,
            category=category,
            archived_by=source,
            project_id=project_id,
            description=description,
        )
        if arc_result.get("ok"):
            result["archived"] = {
                "archived_dir": arc_result.get("archived_dir"),
                "file_count": arc_result.get("file_count"),
                "category": category or "未分类",
                "item_id": item_id,
                "is_directory": True,
            }
            # PBC list 反写目录路径
            if item_id:
                try:
                    write_pbc_list([{
                        "item_id": item_id,
                        "file_path": arc_result.get("archived_dir"),
                        "confidence": 0.90,
                    }], project_id=project_id)
                    result["excel_written"] = True
                except Exception as e:
                    result["excel_written"] = False
                    result["excel_error"] = str(e)
            try:
                update_item_status(
                    item_id=item_id,
                    new_status=STATUS_REVIEWING,
                    changed_by="ai-auto",
                    note=f"AI 识别整目录归档（穿行测试）",
                    project_id=project_id,
                )
            except Exception:
                pass
        else:
            result["archived"] = {"ok": False, "error": arc_result.get("error")}
    except Exception as e:
        result["archived"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    return result


async def _process_one_file(
    path: Path,
    project_id: Optional[str] = None,
    source: str = "drag-drop",
) -> dict[str, Any]:
    """处理单个文件（同步 IO + AI 调用包在 to_thread 中）。"""
    try:
        return await asyncio.to_thread(_process_one_file_sync, path, project_id, source)
    except Exception as e:
        logger.exception("_process_one_file failed: %s", path)
        return {
            "ok": False,
            "path": str(path),
            "error": f"{type(e).__name__}: {e}",
        }


def _process_one_file_sync(
    path: Path,
    project_id: Optional[str] = None,
    source: str = "drag-drop",
) -> dict[str, Any]:
    """单个文件处理（同步实现，M4 整合归档 + 回填 ai_history + 多项目支持）。

    v7.5: 三层职责分离——scan-folder 只处理 pending，watchdog 只标记 pending。
    """
    from app.utils.path_utils import file_hash_sha256 as _file_hash_fn
    file_hash_sha256 = _file_hash_fn  # 供后续 sha256 去重使用
    result: dict[str, Any] = {
        "ok": True, "path": str(path), "name": path.name,
        "project_id": project_id or "",
    }

    # 0.5 manifest 轻量指纹快路径（v7.3）
    # v7.5: pending 但 sha256 相同 → 跳过归档但改状态为 processed
    try:
        from app.core.manifest import should_skip as _manifest_should_skip, load_manifest as _load_manifest, update_entry as _manifest_update
        from app.core.db import get_project as _get_project_proj
        pid = project_id or ""
        client_folder = None
        if pid:
            _proj = _get_project_proj(pid)
            if _proj and _proj.get("client_folder"):
                client_folder = Path(_proj["client_folder"])
        manifest = _load_manifest(pid)
        skip, reason, existing_record = _manifest_should_skip(path, manifest, client_folder)
        if skip:
            result["dedup"] = True
            result["manifest_skip"] = True
            result["reason"] = "unchanged (size+mtime match manifest)"
            if existing_record:
                result["prev_archived_path"] = None
                result["item_id"] = existing_record.get("item_id")
            logger.info("manifest 跳过（size+mtime 未变）: %s", path.name)
            return result
        # pending 但内容没变（sha256 相同）→ 改 processed 跳过
        if reason == "pending" and existing_record:
            old_sha = existing_record.get("sha256", "")
            if old_sha:
                new_sha = file_hash_sha256(path)
                if new_sha == old_sha:
                    # 内容没变只是被标了 pending → 改回 processed
                    _manifest_update(path, new_sha, existing_record.get("item_id", ""),
                                     existing_record.get("version", "v1"),
                                     project_id=pid, client_folder=client_folder, manifest=manifest)
                    result["dedup"] = True
                    result["manifest_skip"] = True
                    result["reason"] = "pending but content unchanged (sha256 match)"
                    result["item_id"] = existing_record.get("item_id")
                    logger.info("pending 但 sha256 相同 → 改 processed: %s", path.name)
                    return result
    except Exception as e:
        logger.debug("manifest 快路径异常（降级到 sha256 去重）: %r", e)

    # 1. 文件 hash 去重（按 project_id 维度查 file_archive 表）
    try:
        h = file_hash_sha256(path)
    except Exception as e:
        return {"ok": False, "path": str(path), "error": f"hash failed: {e}"}
    result["sha256"] = h

    # 先查内存快路径（按 project_id+sha）
    pid = project_id or ""
    seen_task = _hash_seen.get((pid, h))
    if seen_task:
        result["dedup"] = True
        result["prev_task_id"] = seen_task
        return result
    # 再查 SQLite（重启后的去重）
    try:
        existing = get_archive_by_sha(h, project_id=project_id)
    except Exception as e:
        logger.warning("get_archive_by_sha 失败: %r", e)
        existing = None
    if existing is not None:
        _hash_seen[(pid, h)] = ""
        result["dedup"] = True
        result["prev_archived_path"] = existing.get("archived_path")
        return result
    _hash_seen[(pid, h)] = ""  # 占位

    # 2. 解析文件 — P0-2: 先检查文件大小是否稳定，不稳定直接跳过并提示前端
    from app.utils.path_utils import file_stable_size as _file_stable_size
    try:
        if not _file_stable_size(path, stable_seconds=2, timeout=30):
            return {
                **result,
                "ok": False,
                "skipped": True,
                "reason": "file_unstable",
                "error": "file_unstable",
                "advisory_notes": [{
                    "level": "medium",
                    "trigger": "file_unstable",
                    "message": f"文件 {path.name} 正在被写入，已跳过，稍后请重新扫描",
                    "action": "等待文件写入完成后重新扫描",
                    "item_id": None,
                }],
            }
    except Exception as e:
        logger.warning("file_stable_size 预检查异常 %s: %r", path, e)
        # 不阻断，继续尝试解析

    # 新-2/P1-23: advisory_notes 提前初始化（parse 失败分支也要用）
    advisory_notes: list[dict[str, Any]] = []

    parsed = parse_file(path)
    file_text = ""
    if not parsed.get("ok"):
        # 新-2: parse 失败不中断流程，用空 text 继续 classify（结果就是低置信度）
        # 对齐 P1-16 PDF 降级逻辑：Excel/CSV/其他格式解析失败也降级
        parse_err = parsed.get("error", "parse_failed")
        result["parse_error"] = parse_err
        result["ok"] = True  # 标记整体流程继续
        advisory_notes.append({
            "level": "medium",
            "trigger": f"parse_failed:{parse_err}",
            "message": f"文件 {path.name} 解析失败（{parse_err}），AI 将基于文件名尝试分类，置信度可能偏低",
            "action": "建议人工检查文件格式是否正确，或手动指定对应 PBC 编号",
            "item_id": None,
        })
    else:
        file_text = parsed.get("text", "")
    result["metadata"] = parsed.get("metadata", {})
    # P1-16: PDF 完全不可读时记录降级标记，不中断流程
    if parsed.get("error") == "pdf_unreadable":
        result["pdf_unreadable"] = True
        result["parse_error"] = "pdf_unreadable"

    # 如果 needs_ocr，尝试用 vision 兜底
    if parsed.get("needs_ocr") and not file_text:
        try:
            client = _get_ai_client()
            ocr = extract_text_with_vision_safe(path, client)
            if ocr.get("ok"):
                file_text = ocr.get("text", "")
                result["ocr_used"] = True
                result["ocr_pages"] = ocr.get("pages")
            else:
                result["ocr_error"] = ocr.get("error")
        except Exception as e:
            result["ocr_error"] = f"{type(e).__name__}: {e}"

    # 3. 读 PBC 候选清单（按项目）
    try:
        pbc_items = read_pbc_list(project_id=project_id)
    except Exception as e:
        return {**result, "ok": False, "error": f"read_pbc_list failed: {e}"}

    # advisory_notes 已在 parse_file 前初始化（新-2/P1-23 共用）
    # P1-23: PBC 清单为空时，文件全部归档到 "未分类/"，并推 toast
    pbc_list_empty = not pbc_items or len(pbc_items) == 0
    if pbc_list_empty:
        advisory_notes.append({
            "level": "high",
            "trigger": "pbc_list_empty",
            "message": f"PBC 清单为空，文件 {path.name} 已归档到 未分类/，请先导入清单或手动创建条目",
            "action": "在 PBC 清单中导入条目后再重新扫描",
            "item_id": None,
        })

    # 4. AI 分类（在调用前记录 latest ai_history id，用于回填）
    pre_history_id = get_latest_ai_history_id("classify_file") or 0
    client = _get_ai_client()
    # P1-23: 清单为空时跳过 AI 调用（无意义且浪费 token）
    if pbc_list_empty:
        classify = {"ok": True, "item_id": None, "confidence": 0.0, "reason": "PBC 清单为空"}
    else:
        # v7: 文件名优先匹配受 ai_flags.filename_match_enabled 开关控制
        ai_flags = _get_ai_flags()
        fname_matched = False
        if ai_flags.get("filename_match_enabled", True):
            for it in pbc_items:
                iid = it.get("item_id", "")
                if iid and iid in path.name:
                    classify = {
                        "ok": True,
                        "item_id": iid,
                        "confidence": 0.95,
                        "reason": f"文件名匹配（含 '{iid}'），跳过 AI 调用",
                        "model": "filename-match",
                    }
                    fname_matched = True
                    logger.info("文件名优先匹配: %s → item_id=%s（跳过 AI）", path.name, iid)
                    break
        if not fname_matched:
            # v7.4: 穿行测试前置检测 → 整目录归档
            from app.core.matcher import is_walkthrough_folder, score_file
            client_folder_path = None
            if pid:
                try:
                    _proj_info = _get_project_proj(pid)
                    if _proj_info and _proj_info.get("client_folder"):
                        client_folder_path = Path(_proj_info["client_folder"])
                except Exception:
                    pass

            if is_walkthrough_folder(path, client_folder_path):
                classify = {
                    "ok": True,
                    "item_id": None,
                    "confidence": 0.0,
                    "reason": "穿行测试文件夹，走整目录归档",
                    "model": "walkthrough-predetect",
                }
                logger.info("穿行测试前置检测: %s → 整目录归档", path.name)
            else:
                # v7.4: 打分模型——L1 miss 后先打分，够分就不调 LLM
                try:
                    score_result = score_file(
                        file_path=path,
                        pbc_items=pbc_items,
                        file_text=file_text,
                        client_folder=client_folder_path,
                    )
                    decision = score_result.get("decision", "llm")
                    logger.info("打分结果: %s → decision=%s, item_id=%s, confidence=%.4f", path.name, decision, score_result.get("item_id"), score_result.get("confidence", 0))
                except Exception as e:
                    logger.error("打分异常（降级到LLM）: %s → %r", path.name, e)
                    score_result = {"decision": "llm", "item_id": None, "confidence": 0.0, "score_breakdown": {}}
                    decision = "llm"

                if decision == "auto":
                    classify = {
                        "ok": True,
                        "item_id": score_result["item_id"],
                        "confidence": score_result["confidence"],
                        "reason": f"打分自动匹配（总分 {score_result['confidence']:.2f}）",
                        "model": "score-auto",
                    }
                    result["score_breakdown"] = score_result.get("score_breakdown", {})
                    logger.info("打分自动匹配: %s → item_id=%s (总分=%.2f)", path.name, score_result["item_id"], score_result["confidence"])
                elif decision == "suggest":
                    classify = {
                        "ok": True,
                        "item_id": score_result["item_id"],
                        "confidence": score_result["confidence"],
                        "reason": f"打分建议匹配（总分 {score_result['confidence']:.2f}），需审计员确认",
                        "model": "score-suggest",
                    }
                    result["score_breakdown"] = score_result.get("score_breakdown", {})
                    # 推 toast 让审计员确认
                    advisory_notes.append({
                        "level": "medium",
                        "trigger": "score_suggest",
                        "message": f"文件 {path.name} 建议匹配到 {score_result['item_id']}（置信度 {score_result['confidence']:.2f}），请确认",
                        "action": "在 PBC 清单中确认或修正对应编号",
                        "item_id": score_result["item_id"],
                    })
                    logger.info("打分建议匹配: %s → item_id=%s (总分=%.2f)", path.name, score_result["item_id"], score_result["confidence"])
                else:
                    # 打分不够 → LLM 兜底
                    logger.info("打分不足走LLM: %s → 最佳候选=%s (总分=%.2f, 阈值=%.2f)", path.name, score_result.get("item_id"), score_result["confidence"], 0.4)
                    classify = client.classify_file(file_text, pbc_items, file_hint=path.name)

                # v7.6: 编号矛盾信号 → advisory_notes
                conflict = score_result.get("conflict_signal")
                if conflict:
                    advisory_notes.append({
                        "level": "high",
                        "trigger": "id_description_conflict",
                        "message": conflict.get("hint", ""),
                        "action": "建议人工确认该文件应归到哪个 PBC 项，可用「改分类」功能修正",
                        "item_id": conflict.get("detected_item_id"),
                    })
                    result["conflict_signal"] = conflict
                    logger.warning("编号矛盾: %s → 文件名含'%s'但匹配到'%s'",
                                   path.name, conflict.get("detected_item_id"), conflict.get("matched_item_id"))

    item_id: Optional[str] = None
    confidence: float = 0.0
    # 记录处理前的逾期天数（用于 watchdog 触发"解除风险"简报事件）
    old_overdue_days: int = 0
    if classify.get("ok"):
        item_id = classify.get("item_id")
        confidence = float(classify.get("confidence", 0.0) or 0.0)
        # 查匹配到的 item 当前状态（拿 old_overdue_days）
        if item_id:
            try:
                _matched = get_item_by_id(item_id, project_id=project_id)
                if _matched:
                    _ov = _matched.get("overdue_days") or 0
                    try:
                        old_overdue_days = int(_ov) if _ov else 0
                    except Exception:
                        old_overdue_days = 0
            except Exception as _e:
                logger.debug("get_item_by_id for old_overdue_days failed: %r", _e)
        result["matched_item_id"] = item_id
        result["old_overdue_days"] = old_overdue_days
        result["classify"] = {
            "item_id": item_id,
            "confidence": confidence,
            "reason": classify.get("reason", ""),
            "model": classify.get("model"),
        }
        # 收集 classify 的 advisory_notes
        if classify.get("advisory_notes"):
            advisory_notes.extend(classify["advisory_notes"])
    else:
        result["classify"] = {"ok": False, "error": classify.get("error")}
        # 新-4: AI classify retry 全失败 → 推 toast 提示用户
        advisory_notes.append({
            "level": "high",
            "trigger": "ai_classify_failed",
            "message": f"AI 分类失败：{classify.get('error', '未知错误')}。文件已归档到未分类，请稍后重试或人工指定对应 PBC 编号",
            "action": "稍后重新扫描，或在清单中手动指定该文件对应的 PBC 编号",
            "item_id": None,
        })

    # 5. 回填 ai_history.item_id（M4 新增）
    if item_id:
        try:
            latest_id = get_latest_ai_history_id("classify_file", after_id=pre_history_id)
            if latest_id is not None:
                update_ai_history_item_id(latest_id, item_id)
                result["ai_history_updated"] = True
        except Exception as e:
            logger.warning("ai_history 回填失败 %s: %r", item_id, e)

    # 6. 期间检查（文件名匹配时跳过，避免百炼调用拖慢）
    # 先从 PBC 清单匹配项取 required_period（提前到期间检查之前）
    matched_required_period: Optional[str] = None
    if item_id:
        try:
            for it in pbc_items:
                if str(it.get("item_id")) == str(item_id):
                    matched_required_period = it.get("required_period") or None
                    break
        except Exception:
            pass

    if classify.get("model") in ("filename-match", "score-auto", "score-suggest", "walkthrough-predetect"):
        # 本地匹配（文件名/打分/穿行测试）→ 跳过 LLM 期间检查，不调百炼
        result["period_check"] = {"ok": True, "covered": True, "skipped": True, "reason": f"本地匹配（{classify.get('model')}），跳过期间检查"}
        logger.info("跳过期间检查（%s）: %s", classify.get("model"), path.name)
    elif not item_id:
        # AI 分类未匹配到 item_id，期间检查无对照基准，跳过
        result["period_check"] = {"ok": True, "covered": True, "skipped": True, "reason": "AI 未匹配到清单项，跳过期间检查"}
        logger.info("跳过期间检查（未匹配到 item_id）: %s", path.name)
    elif not matched_required_period:
        # 清单项没填 required_period，跳过期间检查（无对照基准）
        result["period_check"] = {"ok": True, "covered": True, "skipped": True, "reason": "清单项未填需求期间，跳过"}
        logger.info("跳过期间检查（清单项无 required_period）: %s → %s", path.name, item_id)
    else:
        # v7.5: 两层级期间检查（Layer A 正则 → Layer B LLM 兜底）
        from app.core.matcher import _extract_years
        import re as _re

        # Layer A: 正则提取年份
        file_years = _extract_years(file_text or "")
        # 也从文件名提取年份
        file_years |= _extract_years(path.name)
        # 从 required_period 提取期望年份
        expected_years = _extract_years(matched_required_period)

        logger.info("期间检查 Layer A: %s → 文件年份=%s, 期望年份=%s", path.name, file_years, expected_years)

        if file_years >= expected_years:
            # 文件年份 ⊇ 期望年份 → 完全覆盖，确定
            result["period_check"] = {
                "ok": True, "covered": True, "skipped": False,
                "method": "regex-full",
                "detected_periods": sorted(file_years),
                "missing": [],
                "reason": f"正则提取年份 {sorted(file_years)} ⊇ {sorted(expected_years)}，完全覆盖",
            }
            logger.info("期间检查确定（正则完全覆盖）: %s", path.name)
        elif not file_years & expected_years:
            # 文件年份 ∩ 期望年份 = 空集 → 确定不覆盖
            result["period_check"] = {
                "ok": True, "covered": False, "skipped": False,
                "method": "regex-empty",
                "detected_periods": sorted(file_years),
                "missing": sorted(expected_years),
                "reason": f"正则提取年份 {sorted(file_years)} 与期望 {sorted(expected_years)} 无交集",
            }
            logger.info("期间检查确定（正则空集）: %s", path.name)
        else:
            # 部分重叠 → 检查 S3: 该 item 是否有多份文件
            from app.core.db import get_archive_by_item
            try:
                all_archives = get_archive_by_item(item_id, project_id=project_id)
                # 合并所有已归档文件的年份
                merged_years = set(file_years)
                for arc in all_archives:
                    arc_path = Path(arc.get("archived_path") or "")
                    if arc_path.exists():
                        # 从归档文件名提取年份
                        merged_years |= _extract_years(arc_path.name)
                if merged_years >= expected_years:
                    result["period_check"] = {
                        "ok": True, "covered": True, "skipped": False,
                        "method": "regex-merge-s3",
                        "detected_periods": sorted(merged_years),
                        "missing": [],
                        "reason": f"S3 多文件合并年份 {sorted(merged_years)} ⊇ {sorted(expected_years)}，覆盖",
                    }
                    logger.info("期间检查确定（S3合并覆盖）: %s → 合并%d份文件", path.name, len(all_archives))
                else:
                    # 合并后仍不完整 → Layer B LLM
                    logger.info("期间检查 Layer B（部分重叠+S3合并不够）: %s → 调LLM", path.name)
                    period_check = client.check_period_completeness(file_text, expected_period=matched_required_period)
                    if period_check.get("ok"):
                        result["period_check"] = {
                            "covered": period_check.get("covered"),
                            "detected_periods": period_check.get("detected_periods"),
                            "missing": period_check.get("missing"),
                            "reason": period_check.get("reason"),
                            "method": "llm",
                        }
                        if period_check.get("advisory_notes"):
                            advisory_notes.extend(period_check["advisory_notes"])
                    else:
                        result["period_check"] = {"ok": False, "error": period_check.get("error")}
            except Exception as e:
                logger.warning("S3 合并检查失败（降级到 LLM）: %s → %r", path.name, e)
                period_check = client.check_period_completeness(file_text, expected_period=matched_required_period)
                if period_check.get("ok"):
                    result["period_check"] = {
                        "covered": period_check.get("covered"),
                        "detected_periods": period_check.get("detected_periods"),
                        "missing": period_check.get("missing"),
                        "reason": period_check.get("reason"),
                        "method": "llm-fallback",
                    }
                    if period_check.get("advisory_notes"):
                        advisory_notes.extend(period_check["advisory_notes"])
                else:
                    result["period_check"] = {"ok": False, "error": period_check.get("error")}

    # 6.5 advisory_notes 在归档阶段统一汇总（P0-1: 未识别归档时也要推送 toast）

    # 7. 归档文件（按 project_id）— P0-1: classify 失败/未识别也归档到 "未分类/"
    # v7: 按 SOP §5.5 归档，取 category（一级分类）+ description + required_period
    archived_path_str: Optional[str] = None
    entity: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    doc_name: Optional[str] = None
    required_period: Optional[str] = None
    # 取 entity / category / description / required_period：从 PBC 清单匹配项读
    if item_id:
        try:
            for it in pbc_items:
                if str(it.get("item_id")) == str(item_id):
                    entity = it.get("entity") or None
                    category = it.get("category") or None
                    description = it.get("description") or None
                    doc_name = it.get("doc_name") or None
                    required_period = it.get("required_period") or None
                    break
        except Exception:
            pass

    # P0-1: classify 未识别 → item_id 为空，仍归档到 "未分类/" + 标记 unclassified
    is_unclassified = not bool(item_id)
    if is_unclassified:
        entity = "未分类"
        # 推送前端 toast（advisory_notes 在 result 里会随 task results 返回前端）
        advisory_notes.append({
            "level": "high",
            "trigger": "unclassified_archive",
            "message": f"AI 无法识别文件 {path.name} 对应 PBC 清单项，已归档到 未分类/，请人工指定",
            "action": "在 PBC 清单中手动指定对应编号",
            "item_id": None,
        })

    try:
        arc_result = archive_mod.archive_file(
            source_path=path,
            item_id=item_id or "UNCLASSIFIED",
            entity=entity,
            sha256=h,
            archived_by=source,
            project_id=project_id,
            category=category,
            description=doc_name or description,
            period=required_period,
        )
        if arc_result.get("ok"):
            archived_path_str = arc_result.get("archived_path")
            result["archived"] = {
                "dedup": arc_result.get("dedup"),
                "archived_path": archived_path_str,
                "entity": entity or "未分类",
                "category": category or "未分类",
                "version": arc_result.get("version", "v1"),
                "unclassified": is_unclassified,
            }
            # v7.6: 写变更日志
            try:
                insert_change_log(
                    project_id=project_id,
                    file_name=path.name,
                    change_type="archived",
                    item_id=item_id or "UNCLASSIFIED",
                    sha256=h,
                    changed_by="ai-auto",
                    detail=f"归档到 {category or '未分类'}/{item_id or 'UNCLASSIFIED'} v{arc_result.get('version', 'v1')}",
                )
            except Exception:
                logger.debug("change_log archived 写入失败（非阻断）", exc_info=True)
        else:
            result["archived"] = {"ok": False, "error": arc_result.get("error")}
    except Exception as e:
        result["archived"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    # 汇总 advisory_notes 到 result（供前端 toast 推送）— P0-1 移到这里以便 unclassified 也能推送
    if advisory_notes:
        result["advisory_notes"] = advisory_notes

    # 8. 回写 Excel（file_path 用归档后路径；没有归档则用原路径）— P0-1: item_id 为空时跳过
    if item_id:
        file_path_for_excel = archived_path_str or str(path)
        try:
            write_pbc_list([{
                "item_id": item_id,
                "file_path": file_path_for_excel,
                "confidence": round(confidence, 2),
            }], project_id=project_id)
            result["excel_written"] = True
        except Exception as e:
            result["excel_written"] = False
            result["excel_error"] = f"{type(e).__name__}: {e}"

        # 9. 推进状态 未提供 → 已提供，审核中
        try:
            ok, msg, _updated = update_item_status(
                item_id=item_id,
                new_status=STATUS_REVIEWING,
                changed_by="ai-auto",
                note=f"AI 自动识别文件，置信度={confidence:.2f}",
                project_id=project_id,
            )
            result["status_update"] = {"ok": ok, "message": msg}
        except Exception as e:
            result["status_update"] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    else:
        # P0-1: 未识别也写 file_archive 记录（item_id 留空字符串，archived_by 标 unclassified）
        result["excel_written"] = False
        result["status_update"] = {"ok": False, "message": "未识别到对应 PBC item（已归档到未分类）"}

    # 10. 显式 insert_archive（即便 archive_file 内部已写过，这里保证记录存在）
    # P0-1: 未识别时也写一条 file_archive 记录，item_id="" archived_by="unclassified"
    if archived_path_str:
        try:
            insert_archive(
                item_id=item_id or "",
                original_path=str(path),
                archived_path=archived_path_str,
                sha256=h,
                file_size=path.stat().st_size if path.exists() else None,
                entity=entity or "",
                archived_by="unclassified" if is_unclassified else source,
                project_id=project_id,
            )
        except Exception as e:
            logger.warning("insert_archive 失败（已忽略，可能重复）: %r", e)

    # 11. 写 manifest（v7.3: 记录轻量指纹，下次启动跳过）
    try:
        from app.core.manifest import update_entry as _manifest_update
        final_version = arc_result.get("version", "v1") if arc_result.get("ok") else "v1"
        _manifest_update(
            file_path=path,
            sha256=h,
            item_id=item_id or "",
            version=final_version,
            project_id=project_id,
            client_folder=client_folder,
            manifest=manifest if 'manifest' in dir() else None,
        )
    except Exception as e:
        logger.debug("manifest 更新失败（不阻断）: %r", e)

    # v7.6: 结构化事件（替代 advisory_notes 杂乱数据，供消息中心使用）
    events: list[dict[str, Any]] = []
    classify_model = classify.get("model", "")
    if item_id and classify_model in ("filename-match", "score-auto"):
        events.append({
            "type": "file_classified",
            "file_name": path.name,
            "item_id": item_id,
            "confidence": round(confidence, 2),
            "action": None,
        })
    elif item_id and classify_model == "score-suggest":
        events.append({
            "type": "needs_confirm",
            "file_name": path.name,
            "item_id": item_id,
            "confidence": round(confidence, 2),
            "action": "goto_triage",
        })
    elif not item_id and is_unclassified:
        events.append({
            "type": "unclassified",
            "file_name": path.name,
            "item_id": None,
            "confidence": 0.0,
            "action": "goto_files",
        })
    elif classify.get("model") == "walkthrough-predetect":
        events.append({
            "type": "file_classified",
            "file_name": path.name,
            "item_id": item_id or "",
            "confidence": 0.0,
            "action": None,
        })
    # file_missing 事件由 watcher._handle_missing_file 推 briefing-events
    result["events"] = events

    return result


def extract_text_with_vision_safe(path: Path, client: AIClient) -> dict[str, Any]:
    """包装 vision 调用，避免异常冒泡。"""
    try:
        from app.core.file_parser import extract_text_with_vision
        return extract_text_with_vision(path, client)
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ----------------------------------------------------------------------
# watchdog 回调入口（main.py 启动时注入，多项目 watcher 调用）
# ----------------------------------------------------------------------
def handle_watcher_new_file(path: Path, project_id: Optional[str] = None) -> None:
    """watcher 检测到新文件时的回调（同步入口，避免与 uvicorn 主 loop 冲突）。

    在 watcher 后台线程中直接同步调用 _process_one_file_sync。
    失败仅 log。
    """
    pid = project_id or _DEFAULT_PROJECT
    try:
        task_id = f"task-{uuid.uuid4().hex[:12]}"
        _set_task(
            task_id,
            project_id=pid,
            status="processing",
            progress=0,
            source="watchdog",
            received_json=[{"name": path.name, "path": str(path), "project_id": pid}],
            results_json=[],
            started_at=_now_iso(),
        )

        # 同步处理单个文件（不用 asyncio，避免与 uvicorn 主 loop 冲突）
        try:
            result = _process_one_file_sync(path, project_id=pid, source="watchdog")
        except Exception as e:
            logger.exception("watchdog 处理任务 %s 失败: %r", task_id, e)
            _set_task(
                task_id,
                project_id=pid,
                status="failed",
                error=f"{type(e).__name__}: {e}",
                finished_at=_now_iso(),
            )
            return

        ok = bool(result.get("ok")) and not result.get("dedup")
        _set_task(
            task_id,
            project_id=pid,
            status="done" if ok else "done_with_errors",
            progress=100,
            done_count=1,
            total=1,
            results_json=[result],
            finished_at=_now_iso(),
        )

        # 简报引擎：watchdog 处理完后评估"是否解除了某项逾期风险"
        # 如果是，生成 file_resolved_risk 事件，推到全局事件队列供前端轮询
        try:
            from app.core.briefing import evaluate_file_impact
            matched_id = result.get("matched_item_id")
            old_ov = result.get("old_overdue_days") or 0
            if matched_id and old_ov > 0:
                evt = evaluate_file_impact(
                    project_id=pid,
                    item_id=matched_id,
                    old_overdue_days=int(old_ov),
                    new_overdue_days=0,
                )
                if evt:
                    _push_briefing_event(evt)
        except Exception:
            logger.debug("evaluate_file_impact failed (non-fatal)", exc_info=True)
    except Exception:
        logger.exception("handle_watcher_new_file 全局失败")


# ----------------------------------------------------------------------
# v7.6: 文件变更日志（持久化操作记录）
# ----------------------------------------------------------------------

@router.get("/{project_id}/change-log")
async def get_project_change_log(
    project_id: str,
    change_type: Optional[str] = Query(None, description="按类型筛选: added/archived/reclassified/approved/deleted/missing"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """获取项目的文件变更日志（按时间倒序）。"""
    logs = get_change_log(project_id=project_id, change_type=change_type, limit=limit)
    return {
        "project_id": project_id,
        "count": len(logs),
        "logs": logs,
    }


# ----------------------------------------------------------------------
# v7.6: 改分类（Senior 复核发现 AI 分错时直接指定新 item_id）
# ----------------------------------------------------------------------

class ReclassifyBody(BaseModel):
    new_item_id: str = Field(..., description="Senior 指定的正确 item_id")
    changed_by: str = Field("senior", description="操作人")
    reason: str = Field("", description="改分类原因")


@router.post("/{project_id}/reclassify/{item_id}")
async def reclassify_archive(project_id: str, item_id: str, body: ReclassifyBody) -> dict:
    """改分类：把指定 item_id 的所有归档文件重新归到 new_item_id。

    流程：
    1. 查旧 archive 记录（item_id + project_id）
    2. 取出每个归档文件的原文件路径（original_path）
    3. 删旧归档目录里的文件
    4. 删旧 archive 记录
    5. 用新 item_id 调 archive_file 重新归档（原文件还在客户文件夹）
    6. PBC Excel：旧 item_id file_path 清空，新 item_id file_path 填新路径
    7. 旧 item_id 状态改"未提供"（如果它没有其他归档了）
    8. 新 item_id 状态推进"审核中"

    覆盖场景：
    - 归错 item_id → 改到正确 item_id
    - 清单外误归 → 改到"未分类"
    - 多份其中 1 份错 → 单独按 archived_path 处理（本接口按 item_id 批量，单条用下方单文件版）
    """
    proj = get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    new_item_id = body.new_item_id.strip()
    if not new_item_id:
        raise HTTPException(status_code=400, detail="new_item_id 不能为空")

    # 查旧归档记录
    old_archives = get_archive_by_item(item_id, project_id=project_id)
    if not old_archives:
        raise HTTPException(
            status_code=404,
            detail=f"item_id '{item_id}' 无归档记录，无法改分类"
        )

    # 取新 item_id 的 PBC 信息（用于归档命名）
    from app.core.excel_io import get_item_by_id
    new_item = get_item_by_id(new_item_id, project_id=project_id)
    if new_item is None:
        raise HTTPException(
            status_code=400,
            detail=f"new_item_id '{new_item_id}' 在 PBC 清单中不存在"
        )

    results: list[dict] = []
    errors: list[str] = []

    for old in old_archives:
        old_archived_path = old.get("archived_path", "")
        original_path = old.get("original_path", "")
        old_sha = old.get("sha256", "")

        try:
            # 1. 删旧归档目录里的文件副本
            from pathlib import Path
            old_path = Path(old_archived_path)
            if old_path.exists():
                old_path.unlink(missing_ok=True)
                # 清理空目录（二级分类文件夹）
                if old_path.parent.exists() and not any(old_path.parent.iterdir()):
                    old_path.parent.rmdir()

            # 2. 删旧 archive 记录
            delete_archive_by_path(old_archived_path, project_id=project_id)

            # 3. 用新 item_id 重新归档（原文件还在客户文件夹）
            src = Path(original_path)
            if not src.exists():
                errors.append(f"原文件不存在: {original_path}，跳过")
                continue

            new_result = archive_mod.archive_file(
                source_path=src,
                item_id=new_item_id,
                entity=new_item.get("entity"),
                sha256=old_sha or None,
                archived_by=f"reclassify:{body.changed_by}",
                project_id=project_id,
                category=new_item.get("category"),
                description=new_item.get("doc_name"),
                period=new_item.get("required_period"),
            )

            if new_result.get("ok"):
                results.append({
                    "old_archived_path": old_archived_path,
                    "new_archived_path": new_result.get("archived_path"),
                    "sha256": old_sha,
                    "dedup": new_result.get("dedup", False),
                    "version": new_result.get("version"),
                })
            else:
                errors.append(f"重新归档失败: {new_result.get('error')}")

        except Exception as e:
            logger.exception("reclassify 单文件失败")
            errors.append(f"{type(e).__name__}: {e}")

    # 4. PBC Excel 更新
    try:
        from app.core.excel_io import write_pbc_list
        pbc_items = read_pbc_list(project_id=project_id)

        # 旧 item_id：清空 file_path（如果没其他归档了）
        remaining_old = get_archive_by_item(item_id, project_id=project_id)
        if not remaining_old:
            for it in pbc_items:
                if it.get("item_id") == item_id:
                    it["file_path"] = ""
                    # 状态改回未提供（状态机允许）
                    try:
                        update_item_status(
                            item_id=item_id,
                            new_status=STATUS_NOT_PROVIDED,
                            changed_by=body.changed_by,
                            note=f"改分类退回：{body.reason}" if body.reason else "改分类退回",
                            project_id=project_id,
                        )
                    except Exception:
                        pass  # 状态机不允许也无所谓
                    break

        # 新 item_id：填 file_path + 推进状态
        new_archived = get_archive_by_item(new_item_id, project_id=project_id)
        if new_archived:
            new_path = new_archived[0].get("archived_path", "")
            for it in pbc_items:
                if it.get("item_id") == new_item_id:
                    it["file_path"] = new_path
                    break
        write_pbc_list(pbc_items, project_id=project_id)

        # 新 item_id 状态推进到审核中
        try:
            update_item_status(
                item_id=new_item_id,
                new_status=STATUS_REVIEWING,
                changed_by=body.changed_by,
                note=f"改分类归入：{body.reason}" if body.reason else "改分类归入",
                project_id=project_id,
            )
        except Exception:
            pass  # 状态机不允许（如已经是审核中）也无所谓

    except Exception as e:
        logger.exception("reclassify PBC Excel 更新失败")
        errors.append(f"PBC Excel 更新失败: {e}")

    # v7.6: 写变更日志
    if results:
        try:
            insert_change_log(
                project_id=project_id,
                file_name=results[0].get("new_archived_path", "").split("/")[-1].split("\\")[-1] if results else "",
                change_type="reclassified",
                item_id=new_item_id,
                changed_by="manual",
                detail=f"{item_id} -> {new_item_id}" + (f" ({body.reason})" if body.reason else ""),
            )
        except Exception:
            logger.debug("change_log reclassified 写入失败（非阻断）", exc_info=True)

    return {
        "ok": len(errors) == 0,
        "project_id": project_id,
        "old_item_id": item_id,
        "new_item_id": new_item_id,
        "reclassified_count": len(results),
        "results": results,
        "errors": errors,
    }
