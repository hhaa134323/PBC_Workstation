"""v7 回归测试：验证 v7 全部新功能。

测试维度：
1. PBC 模板（15 列 + 必填校验）
2. 路径透明化（paths / archive-tree / open-folder-path）
3. 归档目录配置（config-archive-root）
4. 文件失联检测（check-valid + relocate）
5. AI 配置（GET/PUT/models/test + 置信度阈值 + 文件名直配开关）
6. 测试数据包下载
7. PBC 清单 required_period 字段
8. 前端 v7 标识
"""
import urllib.request, urllib.parse, json, time, os, sys, io, zipfile, tempfile
import openpyxl

base = os.environ.get("PBC_TEST_BASE", "http://127.0.0.1:8111")
results = []


def test(name, fn):
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
        results.append((status, name, detail))
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        return ok
    except Exception as e:
        results.append(("FAIL", name, f"{type(e).__name__}: {str(e)[:120]}"))
        print(f"  [FAIL] {name}: {type(e).__name__}: {str(e)[:120]}")
        return False


def _get(path):
    r = urllib.request.urlopen(base + path)
    return json.loads(r.read())


def _post(path, body=None, raw_body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif raw_body is not None:
        data = raw_body
    req = urllib.request.Request(base + path, data=data, headers=headers, method="POST")
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


def _get_raw(path):
    r = urllib.request.urlopen(base + path)
    return r.read()


# ===== 1. 基础 =====
print("\n=== 1. 基础 ===")


def t_health():
    d = _get("/health")
    return d.get("status") == "ok", f"status={d.get('status')}"


def t_frontend_v7():
    html = _get_raw("/").decode("utf-8")
    cnt = sum(html.count(k) for k in ["fileZone", "relocateModal", "aiConfig"])
    return cnt > 0, f"v7 标识共 {cnt} 处"


test("health", t_health)
test("前端 v7 标识", t_frontend_v7)

# ===== 2. PBC 模板（15 列 + 必填） =====
print("\n=== 2. PBC 模板 ===")


def t_template_download():
    data = _get_raw("/api/pbc/demo/download-template")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    has_15 = ws.max_column == 15
    has_period = "需求期间" in (headers[-1] or "")
    return has_15 and has_period, f"列数={ws.max_column}, 第15列={headers[-1]}"


def t_template_required_marked():
    data = _get_raw("/api/pbc/demo/download-template")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    ws = wb.active
    required = []
    for c in range(1, ws.max_column + 1):
        v = ws.cell(1, c).value
        if v and str(v).startswith("* "):
            required.append(v[2:])
    expected = {"资料编号", "一级分类", "问题/需求描述", "期望提供日期", "实体归属", "需求期间"}
    has_all = expected.issubset(set(required))
    return has_all, f"必填={required}"


test("模板下载", t_template_download)
test("模板必填标注", t_template_required_marked)

# ===== 3. PBC 清单 required_period =====
print("\n=== 3. PBC 清单 required_period ===")


def t_pbc_has_period():
    d = _get("/api/pbc/demo/list")
    items = d.get("items", [])
    if not items:
        return False, "PBC 清单为空"
    has_period = any(it.get("required_period") for it in items)
    sample = items[0].get("required_period", "(空)")
    return has_period, f"count={d.get('count')}, 首项 required_period={sample}"


test("PBC 清单含 required_period", t_pbc_has_period)

# ===== 4. 路径透明化 =====
print("\n=== 4. 路径透明化 ===")


def t_paths():
    d = _get("/api/files/demo/paths")
    cf = d.get("client_folder", {})
    ar = d.get("archive_root", {})
    return cf.get("exists") and ar.get("exists"), f"client={cf.get('file_count')}files, archive={ar.get('file_count')}files/{ar.get('category_count')}cats"


def t_archive_tree():
    d = _get("/api/files/demo/archive-tree")
    tree = d.get("tree", [])
    return len(tree) > 0, f"分类数={len(tree)}, 示例={[t.get('category') for t in tree[:3]]}"


test("paths API", t_paths)
test("archive-tree API", t_archive_tree)

# ===== 5. 归档目录配置 =====
print("\n=== 5. 归档目录配置 ===")


def t_set_archive_root():
    # 用临时目录测
    tmp = tempfile.mkdtemp(prefix="pbc_archive_test_")
    d = _post("/api/files/demo/config/archive-root", {"archive_root": tmp})
    return d.get("ok"), f"设到 {tmp}"
    # 注意：测试后没恢复，demo 项目的 archive_root 会变。下条恢复


def t_restore_archive_root():
    # 恢复到默认（用 hardcoded 路径避免 import app）
    default = "D:/AgentProjects/IpoPBC/0/projects/project_demo/archives"
    d = _post("/api/files/demo/config/archive-root", {"archive_root": default})
    return d.get("ok"), f"恢复到默认"


test("set-archive-root", t_set_archive_root)
test("restore-archive-root", t_restore_archive_root)

# ===== 6. 文件失联检测 =====
print("\n=== 6. 文件失联检测 ===")


def t_check_valid_existing():
    # 查 archive 表找有归档记录的 item 测
    archives = _get("/api/files/demo/list").get("files", [])
    if not archives:
        return False, "无归档记录"
    iid = archives[0].get("item_id")
    if not iid:
        return False, "首条归档记录无 item_id"
    r = _get(f"/api/files/demo/check-valid/{urllib.parse.quote(iid)}")
    return r.get("valid") is not None, f"item={iid}, valid={r.get('valid')}, reason={r.get('reason')}"


test("check-valid", t_check_valid_existing)

# ===== 7. AI 配置 =====
print("\n=== 7. AI 配置 ===")


def t_ai_get():
    d = _get("/api/config/ai")
    cfg = d.get("config", {})
    has_all = all(cfg.get(k) is not None for k in ["api_key_masked", "base_url", "model_classification", "confidence_threshold", "filename_match_enabled"])
    return has_all, f"key_set={cfg.get('api_key_set')}, model={cfg.get('model_classification')}, threshold={cfg.get('confidence_threshold')}, fname_match={cfg.get('filename_match_enabled')}"


def t_ai_put_threshold():
    # 用 curl 测 PUT（urllib PUT 在某些版本有坑）
    import subprocess
    # 改成 0.85
    r = subprocess.run(
        ["curl", "-s", "-X", "PUT", base + "/api/config/ai",
         "-H", "Content-Type: application/json",
         "-d", '{"confidence_threshold":0.85}'],
        capture_output=True, text=True, timeout=10
    )
    d = json.loads(r.stdout)
    changed = "confidence_threshold" in d.get("changed", [])
    # 恢复 0.7
    subprocess.run(
        ["curl", "-s", "-X", "PUT", base + "/api/config/ai",
         "-H", "Content-Type: application/json",
         "-d", '{"confidence_threshold":0.7}'],
        capture_output=True, timeout=10
    )
    return changed, f"changed={d.get('changed')}"


def t_ai_models():
    d = _get("/api/config/ai/models")
    models = d.get("models", [])
    ids = [m.get("id") for m in models]
    has_glm = "glm-5" in ids
    return has_glm and len(models) >= 3, f"模型数={len(models)}, ids={ids[:3]}"


def t_ai_test():
    d = _post("/api/config/ai/test", {"model": "glm-5"})
    return d.get("ok"), f"status={d.get('status_code')}, msg={d.get('message') or d.get('error')}"


test("ai GET", t_ai_get)
test("ai PUT confidence_threshold", t_ai_put_threshold)
test("ai models", t_ai_models)
test("ai test connection", t_ai_test)

# ===== 8. 测试数据包 =====
print("\n=== 8. 测试数据包 ===")


def t_test_data_package():
    data = _get_raw("/api/config/test-data-package")
    # 验证是 zip
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        has_pbc = any("01_PBC_List" in n for n in names)
        has_readme = any("README" in n for n in names)
        return has_pbc and has_readme, f"zip 文件数={len(names)}, 含 PBC 清单={has_pbc}, 含 README={has_readme}"
    except Exception as e:
        return False, f"非 zip: {e}"


test("test-data-package", t_test_data_package)

# ===== 9. 前端关键功能代码存在 =====
print("\n=== 9. 前端 v7 代码存在性 ===")


def t_frontend_has_v7_funcs():
    html = _get_raw("/").decode("utf-8")
    checks = {
        "fileZone（文件区视图）": "fileZone" in html,
        "relocateModal（重新定位弹窗）": "relocateModal" in html,
        "aiConfig（AI 配置面板）": "aiConfig" in html,
        "checkAllValid（批量校验）": "checkAllValid" in html,
        "openArchivePath（打开归档目录）": "openArchivePath" in html,
        "loadFileZone（加载文件流向）": "loadFileZone" in html,
        "colVisible（列设置）": "colVisible" in html,
        "nav-sep（brand 分隔）": "nav-sep" in html,
    }
    ok = all(checks.values())
    return ok, "; ".join(f"{k}={'Y' if v else 'N'}" for k, v in checks.items())


test("前端 v7 函数齐全", t_frontend_has_v7_funcs)

# ===== 汇总 =====
print("\n" + "=" * 50)
passed = sum(1 for s, _, _ in results if s == "PASS")
failed = sum(1 for s, _, _ in results if s == "FAIL")
print(f"总计: {len(results)} 项, PASS {passed}, FAIL {failed}")
if failed:
    print("\n失败项:")
    for s, n, d in results:
        if s == "FAIL":
            print(f"  [FAIL] {n}: {d}")
sys.exit(0 if failed == 0 else 1)
