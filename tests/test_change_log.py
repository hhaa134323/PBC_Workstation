"""
变更记录（change-log）功能测试。

测试策略：
- 使用 FastAPI TestClient + tmp_path 实现测试隔离
- 每个测试创建独立的项目目录、客户文件夹、数据库
- 不依赖外部 AI 服务（跳过分类，只测变更记录写入）
- 验证操作后的副作用（manifest 状态、change-log 记录、new-file-count 一致性）

覆盖场景：
1. 新项目 sync-changes 检测新文件 → change-log 有 added 记录
2. Excel 锁文件 ~$ 不被记录
3. 隐藏文件 .xxx 不被记录
4. 系统文件 Thumbs.db/desktop.ini 不被记录
5. 文件删除 → change-log 有 deleted 记录
6. 拖拽上传 → change-log 有 added 记录
7. change-log 按类型筛选
8. new-file-count 与 manifest 状态一致性
9. 重复 sync-changes 不产生重复记录
10. 子文件夹中的文件正确记录相对路径
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Optional

import pytest

# ── 测试隔离基础设施 ──────────────────────────────────────────────

_LOCK = threading.Lock()
_ORIGINAL_DB_PATH = None
_ORIGINAL_PROJECTS_DIR = None


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """每个测试用独立的 tmp_path 目录，互不干扰。

    创建：
    - tmp_path/db/test.db          → 独立数据库
    - tmp_path/projects/           → 项目目录
    - tmp_path/client_folder/      → 客户共享文件夹
    - tmp_path/archive_root/       → 归档目录
    """
    db_path = tmp_path / "db" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)

    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    client_folder = tmp_path / "client_folder"
    client_folder.mkdir(parents=True, exist_ok=True)

    archive_root = tmp_path / "archive_root"
    archive_root.mkdir(parents=True, exist_ok=True)

    # monkeypatch 配置
    import app.config as config_mod
    from app.config import AppConfig

    monkeypatch.setattr(config_mod, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config_mod, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config_mod, "PROJECTS_DIR", projects_dir)
    monkeypatch.setattr(config_mod, "LOGS_DIR", tmp_path / "data" / "logs")

    cfg = AppConfig()
    cfg.db_path = db_path
    cfg.projects_dir = projects_dir
    cfg.client_folder = client_folder
    cfg.archive_root = archive_root
    cfg.logs_dir = tmp_path / "data" / "logs"
    cfg.logs_dir.mkdir(parents=True, exist_ok=True)

    # 替换 get_config 返回隔离配置
    monkeypatch.setattr(config_mod, "get_config", lambda: cfg)
    import app.core.db as db_mod
    monkeypatch.setattr(db_mod, "get_config", lambda: cfg)

    # 重置 thread-local 连接
    if hasattr(db_mod._tls, "conn") and db_mod._tls.conn:
        db_mod._tls.conn.close()
        db_mod._tls.conn = None

    # 初始化数据库
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
    """创建 TestClient，跳过 lifespan（避免 watchdog 和 AI 校验）。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    # 直接导入路由，构建精简 app（跳过 lifespan 中的 watchdog/AI 初始化）
    app = FastAPI()
    from app.api.routes_files import router as files_router
    from app.api.routes_pbc import router as pbc_router
    from app.api.routes_projects import router as projects_router
    from app.api.routes_config import router as config_router

    app.include_router(files_router)
    app.include_router(pbc_router)
    app.include_router(projects_router)
    app.include_router(config_router)

    with TestClient(app) as c:
        yield c


@pytest.fixture
def test_project(isolated_env, client):
    """创建一个测试项目，配置客户文件夹和归档目录。

    返回 {project_id, client_folder, archive_root}
    """
    # 创建项目
    r = client.post("/api/projects/create", json={"name": "test-changelog", "client_name": "测试客户"})
    assert r.status_code == 200
    proj = r.json()["project"]
    pid = proj["project_id"]

    # 配置客户文件夹
    cf = isolated_env["client_folder"]
    r = client.post(f"/api/files/{pid}/config/folder", json={"client_folder": str(cf)})
    assert r.json()["ok"]

    # 配置归档目录
    ar = isolated_env["archive_root"]
    r = client.post(f"/api/files/{pid}/config/archive-root", json={"archive_root": str(ar)})
    assert r.json()["ok"]

    # 创建简单的 PBC 清单（16列模板）
    from app.core.excel_io import _COLUMN_MAP
    import openpyxl
    pbc_path = isolated_env["projects_dir"] / f"project_{pid}" / "01_PBC_List.xlsx"
    pbc_path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    ws = wb.active
    # _COLUMN_MAP 是 list[tuple(col_idx, zh_name, key)]
    headers = [tup[1] for tup in _COLUMN_MAP]
    ws.append(headers)
    ws.append(["财务报表", "财-1", "财务", "合并资产负债表", "资产负债表",
               "2024年度", "", "", "", "", "", "未提供", "", "", 0, "", ""])
    ws.append(["收入", "销-1", "销售", "销售合同台账", "合同台账",
               "2023-2025", "", "", "", "", "", "未提供", "", "", 0, "", ""])
    wb.save(str(pbc_path))

    # 更新项目的 PBC 清单路径
    from app.core.db import update_project
    update_project(pid, pbc_list_path=str(pbc_path))

    yield {
        "project_id": pid,
        "client_folder": cf,
        "archive_root": ar,
        "pbc_path": pbc_path,
    }


def _create_file(path: Path, content: bytes = b"test content"):
    """创建测试文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _get_change_log(project_id: str, db_path: Path) -> list[dict]:
    """直接从 DB 查 change_log。"""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM file_change_log WHERE project_id=? ORDER BY id",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── 测试用例 ──────────────────────────────────────────────────────


class TestSyncChanges:
    """sync-changes：打开项目时自动检测新文件。"""

    def test_new_files_detected_as_added(self, test_project, client):
        """场景1：客户文件夹有新文件 → sync-changes 写 added 记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        db_path = test_project["db_path"] if "db_path" in test_project else None

        # 找 db_path
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        # 创建3个文件
        _create_file(cf / "file1.xlsx", b"content1")
        _create_file(cf / "file2.pdf", b"content2")
        _create_file(cf / "subdir" / "file3.xlsx", b"content3")

        # 调 sync-changes
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.status_code == 200
        data = r.json()
        assert data["added"] == 3

        # 验证 change-log
        logs = _get_change_log(pid, db_path)
        added_logs = [l for l in logs if l["change_type"] == "added"]
        assert len(added_logs) == 3
        file_names = {l["file_name"] for l in added_logs}
        assert "file1.xlsx" in file_names
        assert "file2.pdf" in file_names
        assert "subdir/file3.xlsx" in file_names

    def test_excel_lock_file_not_recorded(self, test_project, client):
        """场景2：Excel 锁文件 ~$xxx.xlsx 不被记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        # 创建正常文件 + Excel 锁文件
        _create_file(cf / "销-1_销售合同台账.xlsx", b"real file")
        _create_file(cf / "~$销-1_销售合同台账.xlsx", b"lock file")

        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 1  # 只记1个，锁文件不记

        logs = _get_change_log(pid, db_path)
        file_names = [l["file_name"] for l in logs]
        assert not any("~$" in fn for fn in file_names), f"锁文件被记录了: {file_names}"

    def test_hidden_file_not_recorded(self, test_project, client):
        """场景3：隐藏文件 .xxx 不被记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        _create_file(cf / ".hidden.txt", b"hidden")
        _create_file(cf / "real.pdf", b"real")

        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 1

        logs = _get_change_log(pid, db_path)
        file_names = [l["file_name"] for l in logs]
        assert not any(fn.startswith(".") for fn in file_names)

    def test_system_file_not_recorded(self, test_project, client):
        """场景4：系统文件 Thumbs.db/desktop.ini 不被记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        _create_file(cf / "Thumbs.db", b"thumb")
        _create_file(cf / "desktop.ini", b"desktop")
        _create_file(cf / "real.xlsx", b"real")

        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 1

        logs = _get_change_log(pid, db_path)
        file_names = [l["file_name"] for l in logs]
        assert "Thumbs.db" not in file_names
        assert "desktop.ini" not in file_names

    def test_subfolder_relative_path(self, test_project, client):
        """场景10：子文件夹中的文件记录相对路径。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        _create_file(cf / "财务报表" / "合并资产负债表.xlsx", b"bs")
        _create_file(cf / "财务报表" / "子公司利润表.xlsx", b"pl")

        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 2

        r = client.get(f"/api/files/{pid}/change-log")
        logs = r.json()["logs"]
        file_names = {l["file_name"] for l in logs}
        assert "财务报表/合并资产负债表.xlsx" in file_names
        assert "财务报表/子公司利润表.xlsx" in file_names


class TestChangeLogFilter:
    """change-log 按类型筛选。"""

    def test_filter_by_change_type(self, test_project, client):
        """场景7：change-log 按类型筛选。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        # 创建文件 → sync → added 记录
        _create_file(cf / "a.pdf", b"a")
        _create_file(cf / "b.pdf", b"b")
        client.post(f"/api/files/{pid}/sync-changes", json={})

        # 验证全部
        r = client.get(f"/api/files/{pid}/change-log")
        assert r.json()["count"] >= 2

        # 验证按 added 筛选
        r = client.get(f"/api/files/{pid}/change-log?change_type=added")
        logs = r.json()["logs"]
        assert all(l["change_type"] == "added" for l in logs)
        assert len(logs) >= 2

        # 验证按 deleted 筛选（应返回0条）
        r = client.get(f"/api/files/{pid}/change-log?change_type=deleted")
        assert r.json()["count"] == 0


class TestDuplicateSync:
    """重复 sync-changes 不产生重复记录。"""

    def test_no_duplicate_on_resync(self, test_project, client):
        """场景9：重复 sync-changes 不产生重复记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        _create_file(cf / "a.pdf", b"a")
        _create_file(cf / "b.xlsx", b"b")

        # 第一次 sync
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 2

        # 第二次 sync（应该0新增）
        r = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r.json()["added"] == 0

        # 验证 change-log 只有2条
        logs = _get_change_log(pid, db_path)
        added = [l for l in logs if l["change_type"] == "added"]
        assert len(added) == 2


class TestNewFileCount:
    """new-file-count 与 manifest 状态一致性。"""

    def test_new_file_count_matches_manifest(self, test_project, client):
        """场景8：new-file-count 反映未处理文件数。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        # 创建5个文件
        for i in range(5):
            _create_file(cf / f"file{i}.pdf", f"content{i}".encode())

        # sync-changes 后 new-file-count 应该 = 5
        client.post(f"/api/files/{pid}/sync-changes", json={})
        r = client.get(f"/api/files/{pid}/new-file-count")
        assert r.json()["new_file_count"] == 5

    def test_new_file_count_zero_after_all_processed(self, test_project, client):
        """场景8b：全部处理后 new-file-count = 0。

        模拟：manifest 全标 processed + pending_confirm 有对应记录 → new-file-count = 0
        """
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        _create_file(cf / "a.pdf", b"a")
        client.post(f"/api/files/{pid}/sync-changes", json={})

        # 在 pending_confirm 里加一条已确认记录（模拟已处理）
        from app.core.db import insert_pending_confirm, get_conn
        from pathlib import Path
        insert_pending_confirm(
            project_id=pid,
            file_path=str(cf / "a.pdf"),
            file_name="a.pdf",
            sha256="",
            suggested_item_id="财-1",
            confidence=0.0,
            decision="",
        )
        # 标 confirmed=1
        with get_conn() as conn:
            conn.execute(
                "UPDATE pending_confirm SET confirmed=1 WHERE project_id=? AND file_path=?",
                (pid, str(cf / "a.pdf")),
            )
            conn.commit()

        # 手动把 manifest 全标 processed
        from app.core.manifest import load_manifest, save_manifest
        m = load_manifest(pid)
        for k, v in m.items():
            v["status"] = "processed"
            v["item_id"] = v.get("item_id") or "财-1"
        save_manifest(m, pid)

        r = client.get(f"/api/files/{pid}/new-file-count")
        assert r.json()["new_file_count"] == 0


class TestFileDeletion:
    """文件删除 → change-log 有 deleted 记录。"""

    def test_file_deletion_logged(self, test_project, client):
        """场景5：文件删除后 sync-changes 写 deleted 记录。

        sync-changes 的删除检测需要 manifest 有记录。先调 sync-changes 写 added，
        再手动通过 mark_pending 写 manifest，然后删文件再 sync。
        """
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        # 创建文件并 sync（写 change_log added）
        f = cf / "to_delete.pdf"
        _create_file(f, b"will be deleted")
        r1 = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r1.json()["added"] == 1

        # 手动写 manifest（sync-changes 不写 manifest，只有 scan-folder 才写）
        from app.core.manifest import mark_pending
        mark_pending(f, project_id=pid, client_folder=cf, reason="test")

        # 删除文件
        f.unlink()

        # 再次 sync → 应检测到删除
        r2 = client.post(f"/api/files/{pid}/sync-changes", json={})
        assert r2.json()["deleted"] == 1

        # 验证 change-log 有 deleted 记录
        logs = _get_change_log(pid, db_path)
        deleted = [l for l in logs if l["change_type"] == "deleted"]
        assert len(deleted) == 1
        assert deleted[0]["file_name"] == "to_delete.pdf"


class TestDragDrop:
    """拖拽上传 → change-log 有 added 记录。"""

    def test_drag_drop_logs_added(self, test_project, client):
        """场景6：拖拽上传文件后 change-log 有 added 记录。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        import app.config as config_mod
        db_path = config_mod.get_config().db_path

        # 模拟拖拽上传（FastAPI TestClient 支持 UploadFile）
        import io
        file_content = io.BytesIO(b"drag drop content")
        r = client.post(
            f"/api/files/{pid}/drag-drop",
            files={"files": ("dropped.xlsx", file_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert r.status_code == 200

        # 验证 change-log 有 added 记录
        logs = _get_change_log(pid, db_path)
        added = [l for l in logs if l["change_type"] == "added" and l["changed_by"] == "drag-drop"]
        assert len(added) >= 1
        assert "dropped.xlsx" in added[0]["file_name"]


class TestArchiveFileCount:
    """归档目录文件计数正确性（不含 manifest 等非归档文件）。"""

    def test_archive_file_count_excludes_manifest(self, test_project, client):
        """归档目录文件数不包含 .pbc_manifest.json 等隐藏文件。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]
        ar = test_project["archive_root"]

        # 在归档目录下创建文件 + manifest
        _create_file(ar / "历史沿革" / "历-1_股权架构图" / "历-1_股权架构图_v1.pdf", b"archived")
        _create_file(ar / ".pbc_manifest.json", b"{}")  # manifest 文件
        _create_file(ar / "Thumbs.db", b"thumb")  # 系统文件

        r = client.get(f"/api/files/{pid}/paths")
        data = r.json()
        assert data["archive_root"]["file_count"] == 1  # 只算1个归档文件

    def test_client_folder_file_count_excludes_lock_files(self, test_project, client):
        """客户文件夹文件数不包含 ~$ 锁文件。"""
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        _create_file(cf / "real.xlsx", b"real")
        _create_file(cf / "~$real.xlsx", b"lock")

        r = client.get(f"/api/files/{pid}/paths")
        data = r.json()
        assert data["client_folder"]["file_count"] == 1


class TestDirectoryArchiveFilePath:
    """目录归档后 PBC Excel file_path 不为空。"""

    def test_directory_archive_writes_file_path(self, test_project, client):
        """目录归档（archive_directory）返回 archived_dir，
        确认归档后 PBC Excel 的 file_path 必须写入归档目录路径，不能为空。
        """
        pid = test_project["project_id"]
        cf = test_project["client_folder"]

        # 创建穿行测试目录（整目录归档场景）
        walkthrough_dir = cf / "穿行测试_销售收款控制"
        _create_file(walkthrough_dir / "合同签字件.pdf", b"contract")
        _create_file(walkthrough_dir / "银行回单.pdf", b"receipt")

        # sync-changes 检测新文件
        client.post(f"/api/files/{pid}/sync-changes", json={})

        # 手动在 pending_confirm 里加一条目录归档记录
        from app.core.db import insert_pending_confirm
        insert_pending_confirm(
            project_id=pid,
            file_path=str(walkthrough_dir),
            file_name="穿行测试_销售收款控制",
            sha256="",
            suggested_item_id="销-1",  # 用 PBC 清单里有的 item
            confidence=0.0,
            decision="walkthrough",
        )

        # 确认归档
        from app.core.db import get_pending_confirm_list
        pending = get_pending_confirm_list(project_id=pid)
        confirm_id = pending[0]["id"]

        r = client.post(f"/api/files/{pid}/confirm/{confirm_id}", json={"new_item_id": ""})
        assert r.status_code == 200
        assert r.json()["ok"]

        # 验证 PBC Excel 的 file_path 不为空
        from app.core.excel_io import read_pbc_list
        items = read_pbc_list(project_id=pid)
        item = next((it for it in items if it.get("item_id") == "销-1"), None)
        assert item is not None, "PBC 清单中没有 销-1"
        assert item.get("file_path"), f"目录归档后 file_path 为空！item={item}"
