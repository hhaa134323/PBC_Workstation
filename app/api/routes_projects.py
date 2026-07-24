"""项目管理路由（多项目支持）。

接口：
- GET    /api/projects/list             列出所有项目
- POST   /api/projects/create           创建新项目
- GET    /api/projects/{project_id}     获取项目详情
- PUT    /api/projects/{project_id}     更新项目（如改 client_folder）
- DELETE /api/projects/{project_id}     删除项目（soft delete）
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import PROJECTS_DIR
from app.core.db import (
    create_project,
    delete_project,
    get_project,
    list_projects,
    update_project,
)

logger = logging.getLogger("pbc.routes_projects")

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectCreateBody(BaseModel):
    name: str = Field(..., description="项目显示名（如 '华银康医疗 IPO'）")
    client_name: str = Field("", description="客户名")
    base_dir: Optional[str] = Field(None, description="项目根目录（不传用默认 projects/）")
    project_id: Optional[str] = Field(None, description="自定义项目 ID（不传自动 slug）")
    note: str = Field("", description="备注")


class ProjectUpdateBody(BaseModel):
    name: Optional[str] = None
    client_name: Optional[str] = None
    folder_path: Optional[str] = None
    pbc_list_path: Optional[str] = None
    client_folder: Optional[str] = None
    archive_root: Optional[str] = None
    is_active: Optional[int] = Field(None, description="0=归档，1=活跃", ge=0, le=1)
    note: Optional[str] = None


@router.get("/list")
async def list_all_projects(active_only: bool = True) -> dict:
    """列出所有项目。"""
    try:
        projects = list_projects(active_only=active_only)
    except Exception as e:
        logger.exception("list_projects failed")
        raise HTTPException(status_code=500, detail=f"查询项目列表失败: {e}")
    return {
        "count": len(projects),
        "projects": projects,
        "active_only": active_only,
    }


@router.post("/create")
async def create_new_project(body: ProjectCreateBody) -> dict:
    """创建新项目。"""
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="项目名 name 不能为空")

    try:
        base_dir = Path(body.base_dir) if body.base_dir else None
        record = create_project(
            name=body.name.strip(),
            client_name=body.client_name or "",
            base_dir=base_dir,
            project_id=body.project_id,
            note=body.note or "",
        )
    except Exception as e:
        logger.exception("create_project failed")
        raise HTTPException(status_code=500, detail=f"创建项目失败: {e}")

    return {
        "ok": True,
        "project": record,
        "next": f"/api/projects/{record['project_id']}",
    }


@router.post("/create-with-demo-data")
async def create_with_demo_data(body: ProjectCreateBody) -> dict:
    """P1-11: 一键创建新项目并复制示例数据。

    v7.5: 改用混合形态测试数据包（19 项 PBC + 16 文件 + 6 子目录），
    覆盖 5 种交付形态 + 3 种特殊情况（穿行测试整目录归档/S3 多份/清单外未分类）。
    数据来源：data/test_data_package/

    1. 调 create_project 创建空项目骨架
    2. 复制 混合形态 PBC 清单到项目 PBC 清单
    3. 复制 混合形态客户文件夹到项目客户文件夹
    """
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="项目名 name 不能为空")

    try:
        base_dir = Path(body.base_dir) if body.base_dir else None
        record = create_project(
            name=body.name.strip(),
            client_name=body.client_name or "",
            base_dir=base_dir,
            project_id=body.project_id,
            note=body.note or "",
        )
    except Exception as e:
        logger.exception("create_project failed")
        raise HTTPException(status_code=500, detail=f"创建项目失败: {e}")

    # 复制示例数据
    import shutil
    from app.config import MOCK_DATA_DIR, PROJECTS_DIR
    copied: list[str] = []
    errors: list[str] = []

    # v7.5: 数据源优先级
    #   1. data/test_data_package/混合形态版（首选）
    #   2. mock_data/01_PBC_List.xlsx + 客户共享文件夹/（fallback）
    test_data_pkg = PROJECTS_DIR.parent / "data" / "test_data_package"
    mixed_pbc = test_data_pkg / "01_PBC_List_混合形态.xlsx"
    mixed_client = test_data_pkg / "客户共享文件夹_混合形态"

    # fallback
    mock_pbc = MOCK_DATA_DIR / "01_PBC_List.xlsx"
    mock_client = MOCK_DATA_DIR / "客户共享文件夹"

    # 1. PBC 清单
    pbc_dest = Path(record["pbc_list_path"])
    if mixed_pbc.exists():
        pbc_src = mixed_pbc
    elif mock_pbc.exists():
        pbc_src = mock_pbc
    else:
        pbc_src = None
    if pbc_src and pbc_src.exists():
        try:
            shutil.copy2(str(pbc_src), str(pbc_dest))
            copied.append(f"01_PBC_List.xlsx (from {pbc_src.parent.name})")
        except Exception as e:
            errors.append(f"PBC 清单复制失败: {e}")

    # 2. 客户共享文件夹
    if mixed_client.exists():
        client_src = mixed_client
    elif mock_client.exists():
        client_src = mock_client
    else:
        client_src = None
    proj_client = Path(record["client_folder"])
    if client_src and client_src.exists():
        try:
            for p in client_src.rglob("*"):
                rel = p.relative_to(client_src)
                dest = proj_client / rel
                if p.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif p.is_file():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(p), str(dest))
                    copied.append(str(rel))
        except Exception as e:
            errors.append(f"客户文件夹复制失败: {e}")

    return {
        "ok": True,
        "project": record,
        "copied_files": copied,
        "errors": errors,
        "next": f"/api/projects/{record['project_id']}",
    }


@router.get("/{project_id}")
async def get_project_detail(project_id: str) -> dict:
    """获取单个项目详情。"""
    proj = get_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    # 附带一些运行时信息（目录是否存在、文件数等）
    extras: dict[str, Any] = {}
    for key in ("folder_path", "pbc_list_path", "client_folder", "archive_root"):
        p_str = proj.get(key)
        if not p_str:
            extras[key + "_exists"] = False
            continue
        p = Path(p_str)
        extras[key + "_exists"] = p.exists()
        if key == "client_folder" and p.exists() and p.is_dir():
            try:
                extras["client_folder_file_count"] = len(list(p.rglob("*")))
            except Exception:
                extras["client_folder_file_count"] = None
        if key == "pbc_list_path" and p.exists() and p.is_file():
            try:
                extras["pbc_list_size"] = p.stat().st_size
            except Exception:
                extras["pbc_list_size"] = None

    return {"project": proj, "runtime": extras}


@router.put("/{project_id}")
async def update_project_detail(project_id: str, body: ProjectUpdateBody) -> dict:
    """更新项目元数据。"""
    existing = get_project(project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    # 收集非 None 字段
    fields: dict[str, Any] = {}
    for k in ("name", "client_name", "folder_path", "pbc_list_path",
              "client_folder", "archive_root", "is_active", "note"):
        v = getattr(body, k)
        if v is not None:
            fields[k] = v

    if not fields:
        return {"ok": True, "project": existing, "changed": []}

    try:
        updated = update_project(project_id, **fields)
    except Exception as e:
        logger.exception("update_project failed")
        raise HTTPException(status_code=500, detail=f"更新项目失败: {e}")

    return {"ok": True, "project": updated, "changed": list(fields.keys())}


@router.delete("/{project_id}")
async def delete_project_detail(project_id: str, soft: bool = True) -> dict:
    """删除项目（默认 soft delete，仅标记 is_active=0）。"""
    existing = get_project(project_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"项目不存在: {project_id}")

    if project_id == "demo":
        # demo 项目不允许删除（系统默认）
        raise HTTPException(
            status_code=400,
            detail="示例项目（demo）不允许删除，是系统默认项目",
        )

    try:
        result = delete_project(project_id, soft=soft)
    except Exception as e:
        logger.exception("delete_project failed")
        raise HTTPException(status_code=500, detail=f"删除项目失败: {e}")

    return {"ok": True, **result}
