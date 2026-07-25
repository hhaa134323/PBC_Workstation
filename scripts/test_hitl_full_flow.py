"""
HITL 完整业务流程测试（Playwright 交互式）

流程：
1. 新建项目（客户文件夹 + 归档目录）
2. 导入 PBC 清单
3. 检查 AI 配置
4. 扫描新文件
5. 待归档列表检查
6. 确认单个文件归档
7. 跳过一个
8. 归档前改分类 + 确认
9. 批量归档剩余
10. 检查归档目录结构
11. 文件变更面板
"""
import sys, time, json, os
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8111"
CLIENT_FOLDER = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
PBC_LIST = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
ARCHIVE_ROOT = r"D:\AgentProjects\IpoPBC\0\projects\07-25-16-49"
SCREENSHOT_DIR = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)
results = []

def check(name, ok, detail=""):
    status = "PASS" if ok else "FAIL"
    results.append((name, ok, detail))
    print(f"  [{status}] {name}: {detail}", flush=True)

def shot(page, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}.png")
    page.screenshot(path=path)
    print(f"  [截图] {path}", flush=True)

def alpine_eval(page, js):
    """在 Alpine 上下文里执行 JS，返回结果"""
    return page.evaluate(f'''() => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            {js}
        }}
        return null;
    }}''')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    
    print("\n=== 1. 新建项目 ===", flush=True)
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    
    # 如果有 onboarding，跳过
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            d.showOnboarding = false;
        }
    }''')
    time.sleep(1)
    
    # 点设置/新建项目
    shot(page, "01_home")
    
    # 用 API 新建项目（先创建，再 PUT 设路径，再导入清单）
    import urllib.request
    # 1. 创建项目
    proj_data = json.dumps({
        "name": "测试项目HITL",
        "client_name": "测试客户",
    }).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/projects/create", data=proj_data,
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=30)
        proj = json.loads(r.read())
        proj_id = proj.get("project", {}).get("project_id", "")
        check("新建项目", bool(proj_id), f"id={proj_id}")
    except Exception as e:
        check("新建项目", False, f"error: {e}")
        r2 = urllib.request.urlopen(f"{BASE}/api/projects/list")
        projects = json.loads(r2.read()).get("projects", [])
        test_proj = next((p for p in projects if "测试项目" in p.get("name", "")), None)
        if test_proj:
            proj_id = test_proj["project_id"]
            check("找到已有项目", True, f"id={proj_id}")
        else:
            print("无法创建或找到项目，退出", flush=True)
            browser.close()
            sys.exit(1)
    
    # 2. PUT 设路径
    update_data = json.dumps({
        "client_folder": CLIENT_FOLDER,
        "archive_root": ARCHIVE_ROOT,
    }).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/projects/{proj_id}", data=update_data,
        headers={"Content-Type": "application/json"}, method="PUT")
    urllib.request.urlopen(req, timeout=10)
    print(f"  路径设置完成", flush=True)
    
    # 3. 导入 PBC 清单
    with open(PBC_LIST, 'rb') as f:
        import io
        boundary = '----pbc_boundary'
        body = f'--{boundary}\r\n'.encode()
        body += b'Content-Disposition: form-data; name="file"; filename="01_PBC_List.xlsx"\r\n'
        body += b'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'
        body += f.read() + b'\r\n'
        body += f'--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f"{BASE}/api/pbc/{proj_id}/import", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    urllib.request.urlopen(req, timeout=30)
    print(f"  PBC 清单导入完成", flush=True)
    
    # 切到新项目
    page.evaluate(f'''() => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            el._x_dataStack[0].currentProjectId = "{proj_id}";
            el._x_dataStack[0].reloadAll();
        }}
    }}''')
    time.sleep(3)
    shot(page, "02_project_loaded")
    
    print("\n=== 2. 导入 PBC 清单 ===", flush=True)
    # PBC 清单在新建项目时已通过 pbc_template_path 导入
    pbc_count = alpine_eval(page, f'return (d.pbcList||[]).length;')
    check("PBC清单已导入", pbc_count and pbc_count > 0, f"items={pbc_count}")
    
    print("\n=== 3. 检查 AI 配置 ===", flush=True)
    r = urllib.request.urlopen(f"{BASE}/api/config/ai")
    cfg = json.loads(r.read()).get("config", {})
    check("model=qwen-plus", cfg.get("model") == "qwen-plus", f"model={cfg.get('model')}")
    check("hitl_mode开", cfg.get("hitl_mode") == True, f"hitl={cfg.get('hitl_mode')}")
    check("auto_confirm关", cfg.get("auto_confirm_enabled") == False, f"auto={cfg.get('auto_confirm_enabled')}")
    
    print("\n=== 4. 扫描新文件 ===", flush=True)
    # 用 API 触发扫描
    req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/scan-folder", data=b'',
        method="POST")
    r = urllib.request.urlopen(req, timeout=60)
    scan_task = json.loads(r.read())
    task_id = scan_task.get("task_id", "")
    print(f"  扫描 task_id: {task_id}", flush=True)
    
    # 等扫描完成
    for i in range(60):
        time.sleep(3)
        r = urllib.request.urlopen(f"{BASE}/api/files/task/{task_id}")
        t = json.loads(r.read())
        scan_status = t.get("status", "")
        if scan_status in ("done", "done_with_errors", "failed"):
            break
        if i % 5 == 0:
            print(f"  扫描中... status={scan_status}", flush=True)
    shot(page, "04_scan_done")
    check("扫描完成", scan_status in ("done", "done_with_errors"), f"status={scan_status}")
    
    print("\n=== 5. 待归档列表检查 ===", flush=True)
    # 切到待归档 tab
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            el._x_dataStack[0].switchTab('review');
        }
    }''')
    time.sleep(2)
    shot(page, "05_pending_archive")
    
    r = urllib.request.urlopen(f"{BASE}/api/files/{proj_id}/pending-confirm")
    pc = json.loads(r.read())
    items = pc.get("items", [])
    check("待归档有数据", len(items) > 0, f"count={len(items)}")
    
    file_items = [it for it in items if it.get("decision") != "walkthrough"]
    dir_items = [it for it in items if it.get("decision") == "walkthrough"]
    print(f"  文件类型: {len(file_items)} 个", flush=True)
    print(f"  目录类型: {len(dir_items)} 个", flush=True)
    for it in items[:5]:
        t = "目录" if it.get("decision") == "walkthrough" else "文件"
        print(f"    id={it.get('id')} [{t}] {it.get('file_name','')[:25]} → {it.get('suggested_item_id')} conf={it.get('confidence')}", flush=True)
    
    print("\n=== 6. 确认单个文件归档 ===", flush=True)
    if file_items:
        c = file_items[0]
        cid = c["id"]
        data = json.dumps({"new_item_id": ""}).encode('utf-8')
        req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/confirm/{cid}",
            data=data, headers={"Content-Type": "application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=30)
        d = json.loads(r.read())
        check("确认文件归档", d.get("ok"), f"item={d.get('item_id')} version={d.get('version')}")
    else:
        check("确认文件归档", False, "无文件类型待归档")
    
    print("\n=== 7. 跳过一个 ===", flush=True)
    r = urllib.request.urlopen(f"{BASE}/api/files/{proj_id}/pending-confirm")
    items2 = json.loads(r.read()).get("items", [])
    file_items2 = [it for it in items2 if it.get("decision") != "walkthrough"]
    if len(file_items2) >= 1:
        c2 = file_items2[0]
        req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/skip-confirm/{c2['id']}",
            data=b'{}', headers={"Content-Type": "application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=10)
        d = json.loads(r.read())
        check("跳过", d.get("ok"), f"id={c2['id']} skipped={d.get('skipped')}")
    else:
        check("跳过", False, "无待归档")
    
    print("\n=== 8. 归档前改分类 + 确认 ===", flush=True)
    r = urllib.request.urlopen(f"{BASE}/api/files/{proj_id}/pending-confirm")
    items3 = json.loads(r.read()).get("items", [])
    file_items3 = [it for it in items3 if it.get("decision") != "walkthrough"]
    if file_items3:
        c3 = file_items3[0]
        old = c3.get("suggested_item_id", "")
        # 查 PBC 找一个不同的
        r2 = urllib.request.urlopen(f"{BASE}/api/pbc/{proj_id}/list")
        pbc = json.loads(r2.read()).get("items", [])
        new_item = next((it["item_id"] for it in pbc if it["item_id"] != old and it["item_id"]), None)
        if new_item:
            data = json.dumps({"new_item_id": new_item}).encode('utf-8')
            req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/reclassify-confirm/{c3['id']}",
                data=data, headers={"Content-Type": "application/json"}, method="POST")
            r = urllib.request.urlopen(req, timeout=10)
            d = json.loads(r.read())
            check("改分类", d.get("ok"), f"{old} → {new_item}")
            # 再确认
            data = json.dumps({"new_item_id": ""}).encode('utf-8')
            req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/confirm/{c3['id']}",
                data=data, headers={"Content-Type": "application/json"}, method="POST")
            r = urllib.request.urlopen(req, timeout=30)
            d = json.loads(r.read())
            check("改分类后确认", d.get("ok"), f"item={d.get('item_id')} (应为{new_item})")
    
    print("\n=== 9. 批量归档剩余 ===", flush=True)
    r = urllib.request.urlopen(f"{BASE}/api/files/{proj_id}/pending-confirm")
    items4 = json.loads(r.read()).get("items", [])
    ids = [it["id"] for it in items4]
    if ids:
        data = json.dumps({"confirm_ids": ids}).encode('utf-8')
        req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/batch-confirm",
            data=data, headers={"Content-Type": "application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=120)
        d = json.loads(r.read())
        check("批量归档", d.get("ok"), f"confirmed={d.get('confirmed_count')} errors={len(d.get('errors',[]))}")
        for e in d.get("errors", [])[:3]:
            print(f"    error: {e}", flush=True)
    else:
        check("批量归档", True, "无剩余")
    
    print("\n=== 10. 检查归档目录结构 ===", flush=True)
    # 归档目录可能就是 ARCHIVE_ROOT 本身（不一定要 /archives 子目录）
    archive_dir = ARCHIVE_ROOT
    if not os.path.exists(archive_dir) or not os.listdir(archive_dir):
        archive_dir = os.path.join(ARCHIVE_ROOT, "archives")
    if os.path.exists(archive_dir) and os.listdir(archive_dir):
        print(f"  归档目录: {archive_dir}", flush=True)
        entries = os.listdir(archive_dir)
        print(f"  一级目录: {entries}", flush=True)
        for entry in entries[:3]:
            sub = os.path.join(archive_dir, entry)
            if os.path.isdir(sub):
                subs = os.listdir(sub)[:5]
                print(f"    {entry}/ → {subs}", flush=True)
        check("归档目录有文件", len(entries) > 0, f"一级目录数={len(entries)}: {entries[:5]}")
    else:
        check("归档目录存在", False, f"不存在或为空: {archive_dir}")
    
    print("\n=== 11. 文件变更面板 ===", flush=True)
    r = urllib.request.urlopen(f"{BASE}/api/files/{proj_id}/change-log?limit=10")
    cl = json.loads(r.read())
    check("变更日志有数据", cl.get("count", 0) > 0, f"count={cl.get('count')}")
    for log in cl.get("logs", [])[:5]:
        print(f"  [{log.get('change_type')}] {log.get('file_name','')[:25]} by={log.get('changed_by')}", flush=True)
    
    browser.close()

print("\n" + "="*60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"总计: {total} 项, PASS {passed}, FAIL {failed}")
if failed:
    print("\n失败项:")
    for name, ok, detail in results:
        if not ok:
            print(f"  [FAIL] {name}: {detail}")
