#!/usr/bin/env python3
"""验证确认归档后 manifest 是否真的更新了（之前出bug的地方）。"""
import tempfile, shutil
from pathlib import Path
import openpyxl

from app.config import AppConfig
from app.core.db import init_db, create_project, update_project, insert_pending_confirm
from app.core.manifest import load_manifest, mark_pending, update_entry
from app.core import archive as archive_mod
from app.core.excel_io import _COLUMN_MAP

tmp = Path(tempfile.mkdtemp())
cfg = AppConfig()
cfg.db_path = tmp / "test.db"
cfg.projects_dir = tmp / "projects"
cfg.projects_dir.mkdir(parents=True, exist_ok=True)
cfg.client_folder = tmp / "cf"
cfg.client_folder.mkdir(parents=True, exist_ok=True)
cfg.archive_root = tmp / "ar"
cfg.archive_root.mkdir(parents=True, exist_ok=True)

import app.config as cm
cm.get_config = lambda: cfg
import app.core.db as dbm
dbm.get_config = lambda: cfg
if hasattr(dbm._tls, "conn") and dbm._tls.conn:
    dbm._tls.conn.close()
    dbm._tls.conn = None
dbm.init_db(cfg.db_path)

create_project("test", project_id="test1")
update_project("test1", client_folder=str(cfg.client_folder), archive_root=str(cfg.archive_root))

pbc_path = cfg.projects_dir / "project_test1" / "01_PBC_List.xlsx"
pbc_path.parent.mkdir(parents=True, exist_ok=True)
wb = openpyxl.Workbook()
ws = wb.active
ws.append([tup[1] for tup in _COLUMN_MAP])
ws.append(["历史沿革", "历-1", "历史", "股权架构图", "ABC股权架构图",
           "2024年度", "", "", "", "2026-07-15", 0, "未提供", "", "集团合并", 0, ""])
wb.save(str(pbc_path))
update_project("test1", pbc_list_path=str(pbc_path))

f = cfg.client_folder / "历-1_股权架构图.pdf"
f.write_bytes(b"content")

mark_pending(f, project_id="test1", client_folder=cfg.client_folder)

m = load_manifest("test1")
rel = str(f.relative_to(cfg.client_folder)).replace("\\", "/")
print(f"Before confirm: {rel} -> status={m[rel]['status']}")

insert_pending_confirm(
    project_id="test1", file_path=str(f), file_name=f.name,
    sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
)

arc_result = archive_mod.archive_file(
    source_path=f, item_id="历-1", entity="集团合并",
    sha256=None, archived_by="test", project_id="test1",
    category="历史沿革", description="股权架构图",
)
print(f"archive_file: ok={arc_result['ok']}")
print(f"  archived_path key: {'archived_path' in arc_result}")
print(f"  archived_dir key: {'archived_dir' in arc_result}")
print(f"  sha256: {arc_result.get('sha256', '')[:20]}")

# 手动调 update_entry（确认归档代码里做的事）
update_entry(f, arc_result.get("sha256", ""), "历-1", "v1",
             project_id="test1", client_folder=cfg.client_folder, manifest=m)

m2 = load_manifest("test1")
print(f"After update_entry: {rel} -> status={m2[rel]['status']} item_id={m2[rel].get('item_id', '')}")

# 现在用 TestClient 走完整 confirm 看看 manifest 有没有更新
print("\n--- 用 TestClient 走完整 confirm ---")
from fastapi import FastAPI
from fastapi.testclient import TestClient
app = FastAPI()
from app.api.routes_files import router as files_router
from app.api.routes_pbc import router as pbc_router
from app.api.routes_projects import router as projects_router
app.include_router(files_router)
app.include_router(pbc_router)
app.include_router(projects_router)

c = TestClient(app)
# 再创建一个文件走完整流程
f2 = cfg.client_folder / "历-1_公司章程.pdf"
f2.write_bytes(b"charter content")
mark_pending(f2, project_id="test1", client_folder=cfg.client_folder)
cid2 = insert_pending_confirm(
    project_id="test1", file_path=str(f2), file_name=f2.name,
    sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
)
r = c.post(f"/api/files/test1/confirm/{cid2}", json={"new_item_id": ""})
print(f"confirm status: {r.status_code} ok={r.json().get('ok')}")

m3 = load_manifest("test1")
rel2 = str(f2.relative_to(cfg.client_folder)).replace("\\", "/")
if rel2 in m3:
    print(f"After confirm: {rel2} -> status={m3[rel2]['status']} item_id={m3[rel2].get('item_id', '')}")
else:
    print(f"After confirm: {rel2} NOT IN MANIFEST!")
    print(f"  manifest keys: {list(m3.keys())}")

shutil.rmtree(str(tmp))
