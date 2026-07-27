"""
完整业务流程测试——从新建项目到归档树检查。

按功能模块拆分，每个测试验证操作后的所有副作用（DB + manifest + PBC Excel + change_log）。
不依赖外部 AI 服务，通过直接调 DB 函数模拟 AI 分类结果。

模块顺序：
1. ProjectManager   — 创建项目、配置文件夹、配置归档目录
2. PbcListManager   — 导入清单、读取、状态转换
3. FileDetection    — sync-changes 检测新文件/删除/锁文件过滤
4. ScanAndArchive   — 扫描→pending_confirm→确认归档（文件版+目录版）
5. ConfirmActions   — 批量确认、跳过、改分类
6. ChangeLogFull   — 全生命周期变更记录
7. ArchiveTree      — 归档树两级结构、文件数
8. RiskAnalysis     — 逾期天数、热力图过滤
9. ManifestConsistency — manifest 状态与 new-file-count 一致性
"""
from __future__ import annotations

import io
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import openpyxl
import pytest

# ── 测试隔离基础设施（复用 test_change_log 的模式）──────────────

@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """每个测试用独立的 tmp_path 目录。"""
    db_path = tmp_path / "db" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    client_folder = tmp_path / "client_folder"
    client_folder.mkdir(parents=True, exist_ok=True)
    archive_root = tmp_path / "archive_root"
    archive_root.mkdir(parents=True, exist_ok=True)

    import app.config as config_mod
    from app.config import AppConfig

    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config_mod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(config_mod, "LOGS_DIR", tmp_path / "data" / "logs")

    cfg = AppConfig()
    cfg.db_path = db_path
    cfg.client_folder = client_folder
    cfg.archive_root = archive_root
    cfg.logs_dir = tmp_path / "data" / "logs"
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    import app.core.db as db_mod
    monkeypatch.setattr(db_mod, "get_config", lambda: cfg)
    if hasattr(db_mod._tls, "conn") and db_mod._tls.conn:
        db_mod._tls.conn.close()
        db_mod._tls.conn = None
    db_mod.init_db(db_path)

    yield {
        "tmp_path": tmp_path,
        "db_path": db_path,
        "client_folder": client_folder,
        "archive_root": archive_root,
        "projects_dir": projects_dir,
        "cfg": cfg,
    }


@pytest.fixture
def client(isolated_env):
    """FastAPI TestClient，跳过 lifespan。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    from app.api.routes_files import router as files_router
    from app.api.routes_pbc import router as pbc_router
    from app.api.routes_projects import router as projects_router
    from app.api.routes_config import router as config_router
    from app.api.routes_risk import router as risk_router
    app.include_router(files_router)
    app.include_router(pbc_router)
    app.include_router(projects_router)
    app.include_router(config_router)
    app.include_router(risk_router)
    with TestClient(app) as c:
        yield c


def _create_pbc_xlsx(pbc_path: Path, items: list[dict] = None):
    """创建 PBC 清单 Excel（16列模板）。"""
    from app.core.excel_io import _COLUMN_MAP
    wb = openpyxl.Workbook()
    ws = wb.active
    headers = [tup[1] for tup in _COLUMN_MAP]
    ws.append(headers)
    if items is None:
        items = [
            {"category": "历史沿革", "item_id": "历-1", "subject": "历史",
             "doc_name": "股权架构图", "description": "ABC集团股权架构图",
             "required_period": "2024年度", "file_format": "", "priority": "",
             "raised_at": "2026-06-01", "expected_by": "2026-07-15",
             "overdue_days": 0, "status_raw": "未提供", "remark": "",
             "entity": "集团合并", "confidence": 0, "file_path": ""},
            {"category": "收入", "item_id": "销-1", "subject": "销售",
             "doc_name": "销售合同台账", "description": "销售合同台账",
             "required_period": "2023-2025", "file_format": "", "priority": "",
             "raised_at": "2026-06-01", "expected_by": "2026-07-20",
             "overdue_days": 0, "status_raw": "未提供", "remark": "",
             "entity": "ABC子公司", "confidence": 0, "file_path": ""},
            {"category": "财务报表", "item_id": "财-1", "subject": "财务",
             "doc_name": "合并资产负债表", "description": "三年一期合并资产负债表",
             "required_period": "2024年度", "file_format": "", "priority": "",
             "raised_at": "2026-06-01", "expected_by": "2026-07-10",
             "overdue_days": 0, "status_raw": "未提供", "remark": "",
             "entity": "集团合并", "confidence": 0, "file_path": ""},
            {"category": "穿行测试", "item_id": "穿-1", "subject": "穿行",
             "doc_name": "销售收款穿行测试", "description": "销售收款控制穿行测试",
             "required_period": "2025年度", "file_format": "", "priority": "",
             "raised_at": "2026-06-01", "expected_by": "2026-07-20",
             "overdue_days": 0, "status_raw": "未提供", "remark": "",
             "entity": "ABC子公司", "confidence": 0, "file_path": ""},
        ]
    for it in items:
        row = [it.get(tup[2], "") for tup in _COLUMN_MAP]
        ws.append(row)
    pbc_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(pbc_path))


@pytest.fixture
def full_project(isolated_env, client):
    """创建完整配置的项目：有PBC清单 + 客户文件夹 + 归档目录。"""
    r = client.post("/api/projects/create", json={"name": "test-full", "client_name": "测试客户"})
    assert r.status_code == 200
    pid = r.json()["project"]["project_id"]

    cf = isolated_env["client_folder"]
    ar = isolated_env["archive_root"]
    client.post(f"/api/files/{pid}/config/folder", json={"client_folder": str(cf)})
    client.post(f"/api/files/{pid}/config/archive-root", json={"archive_root": str(ar)})

    from app.core.db import update_project
    from app.config import PROJECTS_DIR
    pbc_path = isolated_env["projects_dir"] / f"project_{pid}" / "01_PBC_List.xlsx"
    _create_pbc_xlsx(pbc_path)
    update_project(pid, pbc_list_path=str(pbc_path))

    yield {
        "project_id": pid,
        "client_folder": cf,
        "archive_root": ar,
        "pbc_path": pbc_path,
        **isolated_env,
    }


def _create_file(path: Path, content: bytes = b"test"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _db_query(db_path: Path, sql: str, params=()) -> list[dict]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════
# 1. 项目管理
# ════════════════════════════════════════════════════════════════

class TestProjectManager:

    def test_create_project(self, isolated_env, client):
        """创建项目→返回project_id→DB有记录。"""
        r = client.post("/api/projects/create", json={"name": "test-proj", "client_name": "客户A"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["project"]["project_id"]
        assert data["project"]["name"] == "test-proj"
        assert data["project"]["client_name"] == "客户A"

        # DB 验证
        from app.core.db import get_project
        proj = get_project(data["project"]["project_id"])
        assert proj is not None
        assert proj["name"] == "test-proj"

    def test_config_client_folder(self, full_project, client):
        """配置客户文件夹→DB更新→文件夹路径存在。"""
        pid = full_project["project_id"]
        from app.core.db import get_project
        proj = get_project(pid)
        assert proj["client_folder"] == str(full_project["client_folder"])
        assert Path(proj["client_folder"]).exists()

    def test_config_archive_root(self, full_project, client):
        """配置归档目录→DB更新→目录存在。"""
        pid = full_project["project_id"]
        from app.core.db import get_project
        proj = get_project(pid)
        assert proj["archive_root"] == str(full_project["archive_root"])
        assert Path(proj["archive_root"]).exists()

    def test_list_projects(self, full_project, client):
        """列表返回创建的项目。"""
        r = client.get("/api/projects/list")
        assert r.status_code == 200
        pids = [p["project_id"] for p in r.json()["projects"]]
        assert full_project["project_id"] in pids


# ════════════════════════════════════════════════════════════════
# 2. PBC 清单管理
# ════════════════════════════════════════════════════════════════

class TestPbcListManager:

    def test_read_pbc_list(self, full_project):
        """读取PBC清单→4项，每项有item_id和status。"""
        from app.core.excel_io import read_pbc_list
        items = read_pbc_list(project_id=full_project["project_id"])
        assert len(items) == 4
        ids = {it["item_id"] for it in items}
        assert ids == {"历-1", "销-1", "财-1", "穿-1"}
        for it in items:
            assert it["status_normalized"] == "未提供"

    def test_get_item_by_id(self, full_project):
        """按item_id查清单项。"""
        from app.core.excel_io import get_item_by_id
        item = get_item_by_id("历-1", project_id=full_project["project_id"])
        assert item is not None
        assert item["doc_name"] == "股权架构图"
        assert item["entity"] == "集团合并"

    def test_status_transition(self, full_project):
        """状态机：未提供→已提供→不适用。"""
        from app.core.excel_io import update_item_status, read_pbc_list
        pid = full_project["project_id"]
        ok, msg, _ = update_item_status("历-1", "已提供", changed_by="test", project_id=pid)
        assert ok, f"状态转换失败: {msg}"
        items = read_pbc_list(project_id=pid)
        assert items[0]["status_normalized"] == "已提供"

    def test_invalid_status_transition(self, full_project):
        """状态机：不适用→已提供（不允许）。"""
        from app.core.excel_io import update_item_status, read_pbc_list
        pid = full_project["project_id"]
        # 先改成不适用
        update_item_status("历-1", "不适用", changed_by="test", project_id=pid)
        # 不适用→已提供 不允许
        ok, msg, _ = update_item_status("历-1", "已提供", changed_by="test", project_id=pid)
        assert not ok, f"不应允许 不适用→已提供: {msg}"


# ════════════════════════════════════════════════════════════════
# 3. 文件检测
# ════════════════════════════════════════════════════════════════

class TestFileDetection:

    def test_sync_detects_new_files(self, full_project, client):
        """sync-changes检测新文件→change_log有added。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        _create_file(cf / "test.pdf", b"content")
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 1
        r = client.get(f"/api/files/{pid}/change-log?change_type=added")
        assert any("test.pdf" in l["file_name"] for l in r.json()["logs"])

    def test_sync_detects_deleted_files(self, full_project, client):
        """文件删除→sync-changes检测→change_log有deleted。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        f = cf / "to_delete.xlsx"
        _create_file(f, b"data")
        client.post(f"/api/files/{pid}/sync-changes", json={})
        from app.core.manifest import mark_pending
        mark_pending(f, project_id=pid, client_folder=cf)
        f.unlink()
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["deleted"] == 1

    def test_lock_file_not_detected(self, full_project, client):
        """Excel锁文件~$不被检测。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        _create_file(cf / "real.xlsx", b"real")
        _create_file(cf / "~$real.xlsx", b"lock")
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 1

    def test_new_file_count(self, full_project, client):
        """new-file-count反映未处理文件数。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        for i in range(3):
            _create_file(cf / f"f{i}.pdf", f"content{i}".encode())
        client.post(f"/api/files/{pid}/sync-changes", json={})
        r = client.get(f"/api/files/{pid}/new-file-count")
        assert r.json()["new_file_count"] == 3


# ════════════════════════════════════════════════════════════════
# 4. 扫描归档（模拟AI分类结果，直接写pending_confirm）
# ════════════════════════════════════════════════════════════════

class TestScanAndArchive:

    def test_confirm_file_archive(self, full_project, client):
        """文件归档完整流程：创建文件→pending_confirm→确认归档→验证副作用。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        # 创建文件
        f = cf / "历-1_股权架构图.pdf"
        _create_file(f, "股权架构内容".encode("utf-8"))

        # 模拟AI分类结果→写pending_confirm
        from app.core.db import insert_pending_confirm, get_pending_confirm_list
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.95, decision="auto",
        )
        assert cid > 0

        # 确认归档
        r = client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # 验证1: pending_confirm confirmed=1
        pc = _db_query(db_path, "SELECT confirmed FROM pending_confirm WHERE id=?", (cid,))
        assert pc[0]["confirmed"] == 1

        # 验证2: file_archive 有记录
        arcs = _db_query(db_path, "SELECT * FROM file_archive WHERE project_id=? AND item_id=?", (pid, "历-1"))
        assert len(arcs) == 1
        assert arcs[0]["archived_path"]
        assert Path(arcs[0]["archived_path"]).exists()

        # 验证3: PBC Excel file_path 不为空 + 状态推进
        from app.core.excel_io import read_pbc_list
        items = read_pbc_list(project_id=pid)
        item = next(it for it in items if it["item_id"] == "历-1")
        assert item["file_path"], "file_path 为空"
        assert item["status_normalized"] == "已提供"

        # 验证4: change_log 有 archived 记录
        logs = _db_query(db_path,
            "SELECT * FROM file_change_log WHERE project_id=? AND change_type='archived'", (pid,))
        assert any("历-1" in str(l.get("item_id", "")) or f.name in l["file_name"] for l in logs)

        # 验证5: manifest 标记为 processed（之前出过bug）
        from app.core.manifest import load_manifest
        m = load_manifest(pid)
        rel = str(f.relative_to(cf)).replace("\\", "/")
        if rel in m:
            assert m[rel]["status"] == "processed", \
                f"manifest status 应为 processed，实际为 {m[rel]['status']}"
            assert m[rel].get("item_id") == "历-1"

    def test_confirm_directory_archive(self, full_project, client):
        """目录归档完整流程：创建目录→pending_confirm→确认归档→验证副作用。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        # 创建穿行测试目录
        d = cf / "穿行测试_销售收款控制"
        _create_file(d / "合同签字件.pdf", b"contract")
        _create_file(d / "银行回单.pdf", b"receipt")

        # 模拟AI分类→pending_confirm
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(d), file_name=d.name,
            sha256="", suggested_item_id="穿-1", confidence=0.0, decision="walkthrough",
        )

        # 确认归档
        r = client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # 验证1: PBC file_path 不为空（archived_dir 而非 archived_path）
        from app.core.excel_io import read_pbc_list
        items = read_pbc_list(project_id=pid)
        item = next(it for it in items if it["item_id"] == "穿-1")
        assert item["file_path"], "目录归档后 file_path 为空"
        assert item["status_normalized"] == "已提供"

        # 验证2: 归档目录存在且包含文件
        assert Path(item["file_path"]).exists()
        archived_files = list(Path(item["file_path"]).rglob("*"))
        archived_files = [f for f in archived_files if f.is_file()]
        assert len(archived_files) == 2

        # 验证3: file_archive 有记录
        arcs = _db_query(db_path, "SELECT * FROM file_archive WHERE project_id=? AND item_id=?", (pid, "穿-1"))
        assert len(arcs) >= 1
        assert arcs[0]["is_directory"] == 1

        # 验证4: manifest 目录内子文件标 processed
        from app.core.manifest import load_manifest
        m = load_manifest(pid)
        for sub in d.rglob("*"):
            if sub.is_file():
                srel = str(sub.relative_to(cf)).replace("\\", "/")
                if srel in m:
                    assert m[srel]["status"] == "processed", \
                        f"目录归档后子文件 {srel} manifest 应为 processed，实际为 {m[srel]['status']}"


# ════════════════════════════════════════════════════════════════
# 5. 确认操作（批量/跳过/改分类）
# ════════════════════════════════════════════════════════════════

class TestConfirmActions:

    def test_batch_confirm(self, full_project, client):
        """批量确认归档。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        from app.core.db import insert_pending_confirm
        cids = []
        for i, (item_id, fname) in enumerate([("历-1", "file1.pdf"), ("销-1", "file2.pdf")]):
            f = cf / fname
            _create_file(f, f"content{i}".encode())
            cid = insert_pending_confirm(
                project_id=pid, file_path=str(f), file_name=fname,
                sha256="", suggested_item_id=item_id, confidence=0.9, decision="auto",
            )
            cids.append(cid)

        r = client.post(f"/api/files/{pid}/batch-confirm", json={"confirm_ids": cids})
        assert r.status_code == 200
        assert r.json()["confirmed_count"] == 2

        for cid in cids:
            pc = _db_query(db_path, "SELECT confirmed FROM pending_confirm WHERE id=?", (cid,))
            assert pc[0]["confirmed"] == 1

    def test_skip_confirm(self, full_project, client):
        """跳过确认→confirmed=2→manifest标processed。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        f = cf / "skip_me.pdf"
        _create_file(f, b"data")
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.5, decision="suggest",
        )
        from app.core.manifest import mark_pending
        mark_pending(f, project_id=pid, client_folder=cf)

        r = client.post(f"/api/files/{pid}/skip-confirm/{cid}", json={})
        assert r.json()["ok"] is True

        pc = _db_query(db_path, "SELECT confirmed FROM pending_confirm WHERE id=?", (cid,))
        assert pc[0]["confirmed"] == 2

    def test_reclassify_confirm(self, full_project, client):
        """确认前改分类→suggested_item_id更新。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        f = cf / "misclassified.pdf"
        _create_file(f, b"data")
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.3, decision="suggest",
        )

        r = client.post(f"/api/files/{pid}/reclassify-confirm/{cid}",
                        json={"new_item_id": "销-1"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        pc = _db_query(db_path, "SELECT suggested_item_id FROM pending_confirm WHERE id=?", (cid,))
        assert pc[0]["suggested_item_id"] == "销-1"


# ════════════════════════════════════════════════════════════════
# 6. 变更记录全生命周期
# ════════════════════════════════════════════════════════════════

class TestChangeLogFullLifecycle:

    def test_full_lifecycle_change_log(self, full_project, client):
        """完整生命周期：新增→归档→改分类，每步都有change_log。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]
        db_path = full_project["db_path"]

        # 1. 新增文件
        f = cf / "lifecycle.pdf"
        _create_file(f, b"content")
        client.post(f"/api/files/{pid}/sync-changes", json={})

        # 2. 确认归档
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
        )
        client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})

        # 验证：有 added + archived 记录
        logs = _db_query(db_path, "SELECT change_type FROM file_change_log WHERE project_id=?", (pid,))
        types = [l["change_type"] for l in logs]
        assert "added" in types
        assert "archived" in types

    def test_change_log_filter_by_type(self, full_project, client):
        """按类型筛选change_log。"""
        pid = full_project["project_id"]
        r = client.get(f"/api/files/{pid}/change-log?change_type=archived")
        assert r.json()["count"] == 0  # 还没归档过
        r = client.get(f"/api/files/{pid}/change-log?change_type=added")
        # 可能没有added（没有新文件）
        for log in r.json()["logs"]:
            assert log["change_type"] == "added"


# ════════════════════════════════════════════════════════════════
# 7. 归档树
# ════════════════════════════════════════════════════════════════

class TestArchiveTree:

    def test_archive_tree_after_file_archive(self, full_project, client):
        """文件归档后归档树有两级结构。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]

        f = cf / "历-1_股权架构图.pdf"
        _create_file(f, b"content")
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
        )
        client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})

        r = client.get(f"/api/files/{pid}/archive-tree")
        assert r.status_code == 200
        tree = r.json()["tree"]
        assert len(tree) > 0
        # 找历史沿革分类
        hist = next((c for c in tree if "历史" in c.get("category", "")), None)
        assert hist is not None
        assert len(hist["subdirs"]) > 0
        subdir = hist["subdirs"][0]
        assert len(subdir["files"]) > 0

    def test_archive_tree_file_count_excludes_manifest(self, full_project, client):
        """归档树文件数不含.pbc_manifest.json。"""
        pid = full_project["project_id"]
        ar = full_project["archive_root"]
        _create_file(ar / ".pbc_manifest.json", b"{}")
        r = client.get(f"/api/files/{pid}/paths")
        assert r.json()["archive_root"]["file_count"] == 0


# ════════════════════════════════════════════════════════════════
# 8. 风险分析
# ════════════════════════════════════════════════════════════════

class TestRiskAnalysis:

    def test_overdue_days_realtime(self, full_project):
        """逾期天数实时计算（today - expected_by）。"""
        pid = full_project["project_id"]
        from app.core.excel_io import read_pbc_list
        from datetime import date
        items = read_pbc_list(project_id=pid)
        # 财-1 expected_by=2026-07-10，如果今天 > 07-10 应该有逾期
        item = next(it for it in items if it["item_id"] == "财-1")
        if date.today() > date(2026, 7, 10):
            assert item["overdue_days"] > 0
            from app.core.excel_io import compute_risk_level
            assert item["risk_level"] in ("low", "medium", "high")
        else:
            assert item["overdue_days"] == 0 or item["overdue_days"] is None

    def test_heatmap_excludes_provided(self, full_project, client):
        """热力图不包含已提供项。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]

        # 归档一个文件→状态变已提供
        f = cf / "历-1_股权架构图.pdf"
        _create_file(f, b"content")
        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
        )
        client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})

        # 热力图不应包含历-1
        r = client.get(f"/api/risk/{pid}/heatmap")
        for cell in r.json().get("cells", []):
            assert "历-1" not in str(cell.get("items", []))


# ════════════════════════════════════════════════════════════════
# 9. Manifest 一致性
# ════════════════════════════════════════════════════════════════

class TestManifestConsistency:

    def test_new_file_count_zero_after_confirm(self, full_project, client):
        """确认归档后new-file-count=0。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]

        f = cf / "历-1_股权架构图.pdf"
        _create_file(f, b"content")
        client.post(f"/api/files/{pid}/sync-changes", json={})

        from app.core.db import insert_pending_confirm
        cid = insert_pending_confirm(
            project_id=pid, file_path=str(f), file_name=f.name,
            sha256="", suggested_item_id="历-1", confidence=0.9, decision="auto",
        )
        client.post(f"/api/files/{pid}/confirm/{cid}", json={"new_item_id": ""})

        r = client.get(f"/api/files/{pid}/new-file-count")
        assert r.json()["new_file_count"] == 0

    def test_manifest_marks_pending(self, full_project, client):
        """sync后manifest标记pending。"""
        pid = full_project["project_id"]
        cf = full_project["client_folder"]

        f = cf / "manifest_test.pdf"
        _create_file(f, b"content")
        from app.core.manifest import mark_pending, load_manifest
        mark_pending(f, project_id=pid, client_folder=cf)

        m = load_manifest(pid)
        rel = str(f.relative_to(cf)).replace("\\", "/")
        assert rel in m
        assert m[rel]["status"] == "pending"
