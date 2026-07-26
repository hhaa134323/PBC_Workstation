"""文件归档管理（M4 + 多项目支持 + v7 SOP §5.5 重构）。

v7: 按 SOP §5.5 重构归档路径
- 旧：{archive_root}/{entity}/{item_id}_{文件名}
- 新：{archive_root}/{一级分类}/{编号}_{描述}_{期间}_{版本}.ext
  + 一级分类建文件夹（不是 entity）
  + 命名按 SOP 标准：编号_描述_期间_版本
  + 编号锚定（item_id 不变），改名不失联
  + sha256 双锚（换内容 = 新版本，删文件 = 标红）

多项目支持：archive_file 加 project_id 参数。传 project_id 时归档到该项目的
archive_root（projects/{project_id}/archives/{一级分类}/...）；不传时回退到全局
archive_root（兼容旧调用）。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from app.config import get_config
from app.utils.path_utils import file_hash_sha256, safe_path

logger = logging.getLogger("pbc.archive")


def get_archive_root(project_id: Optional[str] = None) -> Path:
    """归档根目录（archive_root），保证存在。

    v7: archive_root 可在 projects 表配置（update_project archive_root 字段），
    用户可指定到桌面等可见位置。传 project_id 取该项目的 archive_root；
    不传：返回全局 cfg.archive_root（兼容旧调用）。
    """
    if project_id:
        from app.core.db import get_project
        proj = get_project(project_id)
        if proj and proj.get("archive_root"):
            root = Path(proj["archive_root"])
        else:
            root = Path(get_config().archive_root) / (project_id or "unknown")
    else:
        root = Path(get_config().archive_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize(name: str) -> str:
    """清理文件名中的非法字符（Windows 不允许 <>:"/\\|?*）。"""
    if not name:
        return "unnamed"
    out = name
    for ch in ('<', '>', ':', '"', '/', '\\', '|', '?', '*'):
        out = out.replace(ch, "_")
    out = " ".join(out.split())
    return out.strip(" .") or "unnamed"


def _build_archive_name(
    item_id: str,
    description: Optional[str] = None,
    period: Optional[str] = None,
    version: Optional[str] = None,
    original_name: Optional[str] = None,
    ext: Optional[str] = None,
) -> str:
    """v7.4: 按 SOP §5.5 构建归档文件名。

    格式：编号_资料名称_期间_版本.ext
    - 编号：item_id（必填），如 历-1
    - 资料名称：从 doc_name 取（简短名称如"股权架构图"），最长 30 字
    - 期间：从 required_period 取，多个用-连接（如 2023-2025），取年份
    - 版本：默认 v1，重复归档递增 v2/v3
    - ext：扩展名，从 original_name 取或显式传

    退化策略：description/period 为空时跳过该段，但至少保留 编号 + ext。
    """
    parts: list[str] = []
    safe_item = _sanitize(item_id) if item_id else ""
    if safe_item:
        parts.append(safe_item)

    if description:
        desc = _sanitize(str(description))[:30]
        if desc:
            parts.append(desc)

    if period:
        # v7.4: 多个期间用 / 分隔（如 "2023年度/2024年度/2025年度"）
        # 取年份用-连接：2023-2024-2025
        period_parts = str(period).split("/")
        years = []
        for p in period_parts:
            p = p.strip()
            if not p:
                continue
            # 提取年份（4位数字）
            import re
            m = re.search(r"\d{4}", p)
            if m:
                years.append(m.group(0))
            else:
                years.append(_sanitize(p))
        if years:
            parts.append("-".join(years))

    if version:
        parts.append(_sanitize(version))
    else:
        parts.append("v1")

    base = "_".join(parts) if parts else "unnamed"
    if ext:
        if not ext.startswith("."):
            ext = "." + ext
        return f"{base}{ext}"
    if original_name:
        o_ext = Path(original_name).suffix
        if o_ext:
            return f"{base}{o_ext}"
    return base


def archive_file(
    source_path: Path | str,
    item_id: str,
    entity: Optional[str] = None,
    sha256: Optional[str] = None,
    archived_by: str = "ai-auto",
    project_id: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    period: Optional[str] = None,
    version: Optional[str] = None,
) -> dict[str, Any]:
    """v7: 按 SOP §5.5 归档文件。

    归档路径：{archive_root}/{一级分类}/{编号}_{描述}_{期间}_{版本}.ext
    - 一级分类：传 category 用 category；不传 fallback 到 entity（兼容旧调用）
    - 编号锚定：item_id 不变，改名不影响归属
    - sha256 双锚：换内容 = 新版本，删文件 = 标红

    返回:
        成功: {ok: True, archived_path, sha256, size, archived_by, dedup: bool, version}
        失败: {ok: False, error, source_path}
    """
    src = safe_path(source_path)
    if not src.exists() or not src.is_file():
        return {"ok": False, "error": "source not found", "source_path": str(src)}

    if not sha256:
        try:
            sha256 = file_hash_sha256(src)
        except Exception as e:
            return {"ok": False, "error": f"hash failed: {e}", "source_path": str(src)}

    from app.core.db import get_archive_by_sha, insert_archive
    existing = get_archive_by_sha(sha256, project_id=project_id)
    if existing is not None:
        existing_path = Path(existing.get("archived_path") or "")
        try:
            size = src.stat().st_size
        except OSError:
            size = None
        insert_archive(
            item_id=item_id or "",
            original_path=str(src),
            archived_path=str(existing_path),
            sha256=sha256,
            file_size=size,
            entity=entity or "",
            archived_by=archived_by,
            project_id=project_id,
        )
        return {
            "ok": True,
            "dedup": True,
            "archived_path": str(existing_path),
            "sha256": sha256,
            "size": size,
            "archived_by": archived_by,
            "version": existing.get("version") or "v1",
        }

    category_dir_name = _sanitize(category or entity or "未分类")
    # v7.2: 归档路径分两级——一级分类/二级分类(编号_资料名称)/文件
    # 如：archives/历史沿革/历-1_股权架构图/历-1_股权架构图_2024_v1.pdf
    safe_item = _sanitize(item_id) if item_id else "UNCLASSIFIED"
    # 二级分类文件夹名：编号_资料名称（如果有 description/doc_name）
    desc_short = _sanitize(str(description or "")[:30]) if description else ""
    if desc_short:
        sub_dir_name = f"{safe_item}_{desc_short}"
    else:
        sub_dir_name = safe_item
    entity_dir = get_archive_root(project_id=project_id) / category_dir_name / sub_dir_name
    entity_dir.mkdir(parents=True, exist_ok=True)

    ext = src.suffix
    target_name = _build_archive_name(
        item_id=item_id,
        description=description,
        period=period,
        version=version,
        original_name=src.name,
        ext=ext,
    )
    target = entity_dir / target_name

    if target.exists():
        try:
            existing_size = target.stat().st_size
            src_size = src.stat().st_size
            if existing_size != src_size:
                stem_parts = target.stem.split("_")
                base_stem = "_".join(stem_parts[:-1]) if stem_parts else target.stem
                i = 2
                while True:
                    candidate = entity_dir / f"{base_stem}_v{i}{ext}"
                    if not candidate.exists():
                        target = candidate
                        if not version:
                            version = f"v{i}"
                        break
                    i += 1
        except OSError:
            pass

    try:
        shutil.copy2(str(src), str(target))
    except Exception as e:
        return {
            "ok": False,
            "error": f"copy failed: {type(e).__name__}: {e}",
            "source_path": str(src),
        }

    try:
        size = target.stat().st_size
    except OSError:
        size = None

    final_version = version or "v1"
    try:
        insert_archive(
            item_id=item_id or "",
            original_path=str(src),
            archived_path=str(target),
            sha256=sha256,
            file_size=size,
            entity=entity or "",
            archived_by=archived_by,
            project_id=project_id,
            is_directory=0,
            version=final_version,
            doc_type=None,
            category=category or entity or "未分类",
        )
    except Exception as e:
        logger.warning("file_archive 写入失败（文件已归档）: %r", e)

    return {
        "ok": True,
        "dedup": False,
        "archived_path": str(target),
        "sha256": sha256,
        "size": size,
        "archived_by": archived_by,
        "version": final_version,
    }


def archive_directory(
    source_dir: Path | str,
    item_id: str,
    entity: Optional[str] = None,
    category: Optional[str] = None,
    archived_by: str = "ai-auto",
    project_id: Optional[str] = None,
    description: Optional[str] = None,
) -> dict[str, Any]:
    """v7: 整目录归档（穿行测试资料，SOP §5.5 Tips）。

    把整个文件夹归档到 {archive_root}/{一级分类}/{编号}_{文件夹名}/，
    保留内部结构。file_archive 记一条 is_directory=1 的索引。

    AI 分类由调用方先做好（取文件夹内代表性文件合并文本送 AI）。
    本函数只负责物理拷贝 + 写索引。

    返回：
        {ok: True, archived_dir, file_count, item_id, ...}
        {ok: False, error, source_dir}
    """
    src = Path(source_dir)
    if not src.exists() or not src.is_dir():
        return {"ok": False, "error": "source dir not found", "source_dir": str(src)}

    category_dir_name = _sanitize(category or entity or "未分类")
    # v7.2: 整目录归档也分两级——一级分类/二级分类(编号_文件夹名)/
    safe_item = _sanitize(item_id) if item_id else ""
    src_name = _sanitize(src.name)
    if safe_item and not src_name.startswith(safe_item):
        sub_dir_name = f"{safe_item}_{src_name}"
    else:
        sub_dir_name = src_name
    base_dir = get_archive_root(project_id=project_id) / category_dir_name / sub_dir_name

    # v7.7: 检查是否已归档过同一 item（防止重复归档加 _v2）
    try:
        from app.core.db import get_conn
        with get_conn() as conn:
            existing = conn.execute(
                "SELECT id, archived_path FROM file_archive WHERE project_id=? AND item_id=? AND is_directory=1",
                (project_id or "", item_id or ""),
            ).fetchone()
            if existing:
                # 已归档过——复用旧目录，不加 _v2
                old_path = existing[1]
                if old_path and Path(old_path).exists():
                    target_dir = Path(old_path)
                    logger.info("archive_directory: 复用已有目录（同item）: %s", old_path)
                    # copytree 合并进去
                    try:
                        shutil.copytree(str(src), str(target_dir), dirs_exist_ok=True)
                    except Exception as e:
                        return {"ok": False, "error": f"copytree(merge) failed: {e}", "source_dir": str(src)}
                    file_count = sum(1 for p in target_dir.rglob("*") if p.is_file())
                    total_size = sum(p.stat().st_size for p in target_dir.rglob("*") if p.is_file())
                    return {
                        "ok": True, "archived_dir": str(target_dir),
                        "file_count": file_count, "item_id": item_id or "",
                        "skipped": True, "reason": "already_archived_same_item",
                    }
    except Exception as e:
        logger.warning("check existing archive failed: %r", e)

    # 目标文件夹名：直接用 sub_dir_name
    target_dir = base_dir

    # v7.7: 先清理可能残留的空目录（之前mkdir+exists bug产生的）
    if base_dir.exists() and not any(base_dir.iterdir()):
        try:
            base_dir.rmdir()
        except Exception:
            pass

    # 重名时：非空目录加版本后缀
    if base_dir.exists() and any(base_dir.iterdir()):
        i = 2
        while True:
            candidate = base_dir.parent / f"{sub_dir_name}_v{i}"
            if not candidate.exists() or (candidate.exists() and not any(candidate.iterdir())):
                if candidate.exists():
                    try: candidate.rmdir()
                    except: pass
                target_dir = candidate
                break
            i += 1
    
    target_dir.mkdir(parents=True, exist_ok=True)

    # 整目录拷贝（保留内部结构，允许目录已存在）
    try:
        shutil.copytree(str(src), str(target_dir), dirs_exist_ok=True)
    except Exception as e:
        return {
            "ok": False,
            "error": f"copytree failed: {type(e).__name__}: {e}",
            "source_dir": str(src),
        }

    # 统计文件数 + 总大小
    file_count = 0
    total_size = 0
    for p in target_dir.rglob("*"):
        if p.is_file():
            file_count += 1
            try:
                total_size += p.stat().st_size
            except OSError:
                pass

    # 写一条 is_directory=1 的索引（archived_path 指向目录）
    try:
        from app.core.db import insert_archive
        insert_archive(
            item_id=item_id or "",
            original_path=str(src),
            archived_path=str(target_dir),
            sha256="",
            file_size=total_size,
            entity=entity or "",
            archived_by=archived_by,
            project_id=project_id,
            is_directory=1,
            version="v1",
            doc_type="walkthrough",
            category=category or entity or "未分类",
        )
    except Exception as e:
        logger.warning("file_archive 目录归档写入失败: %r", e)

    return {
        "ok": True,
        "dedup": False,
        "archived_dir": str(target_dir),
        "file_count": file_count,
        "total_size": total_size,
        "item_id": item_id,
        "entity": entity,
        "category": category or entity or "未分类",
        "version": "v1",
    }


def list_archives_by_entity(entity: str, project_id: Optional[str] = None) -> list[dict[str, Any]]:
    """列出某 entity 的归档文件（直接读目录，不查 SQLite）。"""
    entity_dir = get_archive_root(project_id=project_id) / _sanitize(entity or "未分类")
    if not entity_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(entity_dir.iterdir()):
        if p.is_file():
            try:
                st = p.stat()
            except OSError:
                st = None
            out.append({
                "name": p.name,
                "path": str(p),
                "size": st.st_size if st else None,
                "mtime": st.st_mtime if st else None,
            })
    return out


def list_archive_tree(project_id: Optional[str] = None) -> list[dict[str, Any]]:
    """v7.2: 列出归档目录树（按一级分类→二级分类两级嵌套）。

    返回：
    [
      {
        "category": "历史沿革",
        "path": ".../archives/历史沿革",
        "subdirs": [
          {
            "name": "历-1_股权架构图",
            "path": ".../archives/历史沿革/历-1_股权架构图",
            "files": [{"name":..., "path":..., "size":..., "mtime":...}, ...],
            "count": 2
          },
          ...
        ],
        "count": 5
      },
      ...
    ]
    前端右侧"已归档树"直接渲染这个两级结构。
    """
    root = get_archive_root(project_id=project_id)
    out: list[dict[str, Any]] = []
    if not root.exists():
        return out
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        subdirs: list[dict[str, Any]] = []
        category_count = 0
        for sd in sorted(p.iterdir()):
            if not sd.is_dir():
                continue
            files: list[dict[str, Any]] = []
            for f in sorted(sd.iterdir()):
                if f.is_file():
                    try:
                        st = f.stat()
                    except OSError:
                        st = None
                    files.append({
                        "name": f.name,
                        "path": str(f),
                        "size": st.st_size if st else None,
                        "mtime": st.st_mtime if st else None,
                    })
            category_count += len(files)
            subdirs.append({
                "name": sd.name,
                "path": str(sd),
                "files": files,
                "count": len(files),
            })
        out.append({
            "category": p.name,
            "path": str(p),
            "subdirs": subdirs,
            "count": category_count,
        })
    return out


def check_archive_path_valid(item_id: str, project_id: Optional[str] = None) -> dict[str, Any]:
    """v7: 检查某编号对应的归档文件是否仍存在（文件失联检测）。

    查 file_archive 表拿 archived_path，检查文件是否还在。
    返回：
    - {valid: True, archived_path: ...}  文件存在
    - {valid: False, archived_path: ..., reason: "file_missing"}  文件被删/移走
    - {valid: False, reason: "no_archive_record"}  没归档记录
    """
    from app.core.db import get_archive_by_item
    archives = get_archive_by_item(item_id, project_id=project_id)
    if not archives:
        return {"valid": False, "reason": "no_archive_record", "item_id": item_id}
    # 取最新一条
    latest = archives[0]
    archived_path = latest.get("archived_path") or ""
    if not archived_path:
        return {"valid": False, "reason": "no_path", "item_id": item_id}
    p = Path(archived_path)
    if not p.exists():
        return {
            "valid": False,
            "archived_path": archived_path,
            "reason": "file_missing",
            "item_id": item_id,
            "sha256": latest.get("sha256"),
        }
    return {
        "valid": True,
        "archived_path": archived_path,
        "item_id": item_id,
        "sha256": latest.get("sha256"),
    }


def relocate_archive(
    item_id: str,
    new_path: Path | str,
    project_id: Optional[str] = None,
) -> dict[str, Any]:
    """v7: 文件失联后，用户指定新位置，后端按 sha256 重新绑定。

    new_path 是用户在前端选的新文件路径。后端：
    1. 计算新文件 sha256
    2. 更新 file_archive 表的 archived_path
    3. 如果 sha256 变了，记录为新版本
    """
    from app.core.db import get_archive_by_item, execute_with_retry
    new_p = Path(new_path)
    if not new_p.exists() or not new_p.is_file():
        return {"ok": False, "error": "新文件不存在"}
    try:
        new_sha = file_hash_sha256(new_p)
    except Exception as e:
        return {"ok": False, "error": f"hash failed: {e}"}

    archives = get_archive_by_item(item_id, project_id=project_id)
    if not archives:
        return {"ok": False, "error": "无归档记录，无法重新定位"}
    latest = archives[0]
    old_sha = latest.get("sha256") or ""
    old_path = latest.get("archived_path") or ""

    try:
        size = new_p.stat().st_size
    except OSError:
        size = None

    # 写一条新记录（保留旧记录用于审计追溯）
    from app.core.db import insert_archive
    insert_archive(
        item_id=item_id,
        original_path=str(new_p),
        archived_path=str(new_p),
        sha256=new_sha,
        file_size=size,
        entity=latest.get("entity") or "",
        archived_by="relocate",
        project_id=project_id,
    )
    return {
        "ok": True,
        "item_id": item_id,
        "old_path": old_path,
        "new_path": str(new_p),
        "sha_changed": new_sha != old_sha,
        "old_sha": old_sha,
        "new_sha": new_sha,
    }


if __name__ == "__main__":
    src = Path(get_config().client_folder) / "集团合并" / "历-1_股权架构图.pdf"
    if src.exists():
        r = archive_file(
            src,
            item_id="历-1",
            entity="集团合并",
            category="历史沿革",
            description="股权架构图",
            period="2024",
            archived_by="self-test",
        )
        print(r)
    else:
        print("self-test source not found:", src)
