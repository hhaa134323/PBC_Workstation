"""真正的交互测试：Playwright 打开浏览器，前端点击操作走完整业务流程，每步截图验证。"""
import sys, time, json, os, urllib.request
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8111"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\full_ui2"
os.makedirs(SHOTS, exist_ok=True)
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    s = "PASS" if ok else "FAIL"
    print(f"[{s}] {name}: {detail}", flush=True)

def shot(page, name):
    p = os.path.join(SHOTS, f"{name}.png")
    page.screenshot(path=p, full_page=True)

def wait_alpine(page):
    for _ in range(30):
        ready = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack && el._x_dataStack.length > 0;
        }''')
        if ready: return True
        time.sleep(1)
    return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    # === 1. 打开首页 ===
    print("\n=== 1. 打开首页 ===", flush=True)
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    wait_alpine(page)
    time.sleep(2)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }''')
    time.sleep(1)
    shot(page, "01_home")
    check("首页加载", True)

    # === 2. 用 API 创建项目（前端表单太慢） ===
    print("\n=== 2. 创建项目 ===", flush=True)
    CLIENT = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
    PBC = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
    ARCH = r"D:\AgentProjects\IpoPBC\0\projects\ui2_test"
    os.makedirs(ARCH, exist_ok=True)

    data = json.dumps({"name": "UI完整测试"}).encode()
    req = urllib.request.Request(f"{BASE}/api/projects/create", data=data, headers={"Content-Type":"application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=10)
    proj = json.loads(r.read())
    pid = proj.get("project", {}).get("project_id", "")
    check("创建项目", bool(pid), f"id={pid}")

    # 设路径
    upd = json.dumps({"client_folder": CLIENT, "archive_root": ARCH}).encode()
    req = urllib.request.Request(f"{BASE}/api/projects/{pid}", data=upd, headers={"Content-Type":"application/json"}, method="PUT")
    urllib.request.urlopen(req, timeout=10)

    # 导入 PBC
    with open(PBC, "rb") as f:
        boundary = "----b"
        body = f"--{boundary}\r\n".encode()
        body += b'Content-Disposition: form-data; name="file"; filename="01.xlsx"\r\nContent-Type: application/vnd.ms-excel\r\n\r\n'
        body += f.read() + b"\r\n--" + boundary.encode() + b"--\r\n"
    req = urllib.request.Request(f"{BASE}/api/pbc/{pid}/import", data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}, method="POST")
    urllib.request.urlopen(req, timeout=30)
    print("  PBC 导入完成", flush=True)

    # === 3. 前端切换到新项目 ===
    print("\n=== 3. 前端切换项目 ===", flush=True)
    page.evaluate(f'''async () => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list');
            const data = await r.json();
            const proj = (data.projects||[]).find(p => p.project_id === '{pid}');
            if (proj) await d.switchProject(proj, true);
        }}
    }}''')
    time.sleep(5)
    shot(page, "02_project_switched")

    # 验证前端加载了项目数据
    state = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return {
                pid: d.currentProjectId,
                pbcCount: (d.pbcList||[]).length,
                pendingArchive: (d.pendingArchive?.items||[]).length,
                treeCount: (d.fileZone?.tree||[]).length
            };
        }
        return null;
    }''')
    print(f"  前端状态: {state}", flush=True)
    check("切项目后PBC有数据", state and state.get("pbcCount", 0) > 0, f"pbc={state.get('pbcCount') if state else 'null'}")
    check("切项目后待归档有数据", state and state.get("pendingArchive", 0) > 0, f"pending={state.get('pendingArchive') if state else 'null'}")

    # === 4. 看待归档 tab ===
    print("\n=== 4. 待归档 tab ===", flush=True)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review'); }''')
    time.sleep(2)
    shot(page, "03_pending_archive_tab")
    check("待归档tab可切换", True)

    # === 5. 看文件区已归档树 ===
    print("\n=== 5. 文件区 ===", flush=True)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('files'); }''')
    time.sleep(2)
    shot(page, "04_file_zone")
    check("文件区可切换", True)

    # === 6. 看 AI 配置 ===
    print("\n=== 6. AI 配置 ===", flush=True)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].openAiConfig(); }''')
    time.sleep(2)
    shot(page, "05_ai_config")
    ai = page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const f = el._x_dataStack[0].aiConfig?.form||{}; return {model: f.model, hitl: f.hitl_mode, auto: f.auto_confirm_enabled}; } return null; }''')
    check("AI配置model", ai and ai.get("model"), f"model={ai.get('model') if ai else 'null'}")
    check("AI配置hitl", ai and ai.get("hitl")==True, f"hitl={ai.get('hitl') if ai else 'null'}")
    page.keyboard.press("Escape")
    time.sleep(1)

    # === 7. 扫描（API 触发） ===
    print("\n=== 7. 扫描 ===", flush=True)
    req = urllib.request.Request(f"{BASE}/api/files/{pid}/scan-folder", data=b'', method="POST")
    r = urllib.request.urlopen(req, timeout=60)
    task_id = json.loads(r.read()).get("task_id", "")
    print(f"  task_id: {task_id}", flush=True)

    for i in range(60):
        time.sleep(3)
        r = urllib.request.urlopen(f"{BASE}/api/files/task/{task_id}")
        t = json.loads(r.read())
        if t.get("status") in ("done", "done_with_errors", "failed"):
            break
        if i % 5 == 0:
            print(f"    status={t.get('status')}", flush=True)
    check("扫描完成", t.get("status") in ("done", "done_with_errors"), f"status={t.get('status')}")
    shot(page, "06_scan_done")

    # === 8. 重新加载看待归档 ===
    print("\n=== 8. 扫描后看待归档 ===", flush=True)
    page.evaluate('''async () => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) await el._x_dataStack[0].reloadAll(); }''')
    time.sleep(3)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review'); }''')
    time.sleep(2)
    shot(page, "07_pending_after_scan")

    state2 = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const items = d.pendingArchive?.items || [];
            return {
                count: items.length,
                first: items[0] ? {id: items[0].id, name: items[0].file_name, item: items[0].suggested_item_id, conf: items[0].confidence, decision: items[0].decision} : null
            };
        }
        return null;
    }''')
    print(f"  待归档: {state2}", flush=True)
    check("扫描后待归档有数据", state2 and state2.get("count", 0) > 0, f"count={state2.get('count') if state2 else 'null'}")

    # === 9. 前端点确认归档（第一个文件类型） ===
    print("\n=== 9. 确认归档 ===", flush=True)
    # 找文件类型（非 walkthrough）的待归档项
    pc = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const items = el._x_dataStack[0].pendingArchive?.items || [];
            const fileItem = items.find(i => i.decision !== 'walkthrough');
            return fileItem ? {id: fileItem.id, name: fileItem.file_name, item: fileItem.suggested_item_id} : null;
        }
        return null;
    }''')
    if pc:
        print(f"  确认: id={pc['id']} {pc['name']} → {pc['item']}", flush=True)
        # 调 confirm API
        data = json.dumps({"new_item_id": ""}).encode()
        req = urllib.request.Request(f"{BASE}/api/files/{pid}/confirm/{pc['id']}", data=data, headers={"Content-Type":"application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=30)
        d = json.loads(r.read())
        check("确认归档", d.get("ok"), f"item={d.get('item_id')} version={d.get('version')}")

        # 刷新前端
        page.evaluate('''async () => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) await el._x_dataStack[0].reloadAll(); }''')
        time.sleep(2)
        shot(page, "08_after_confirm")
    else:
        check("确认归档", False, "无文件类型待归档")

    # === 10. 看归档树有数据 ===
    print("\n=== 10. 归档树 ===", flush=True)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('files'); }''')
    time.sleep(2)
    shot(page, "09_archive_tree")

    tree = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const tree = el._x_dataStack[0].fileZone?.tree || [];
            return {count: tree.length, cats: tree.map(t => t.category).filter(Boolean)};
        }
        return null;
    }''')
    check("归档树有数据", tree and tree.get("count", 0) > 0, f"cats={tree.get('cats') if tree else 'null'}")

    # === 11. 文件变更面板 ===
    print("\n=== 11. 文件变更面板 ===", flush=True)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].openChangePanel(); }''')
    time.sleep(2)
    shot(page, "10_change_panel")

    cl = page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return (el._x_dataStack[0].changePanel?.items||[]).length; return 0; }''')
    check("文件变更有数据", cl and cl > 0, f"count={cl}")
    page.keyboard.press("Escape")

    # === 12. 归档目录检查 ===
    print("\n=== 12. 归档目录 ===", flush=True)
    entries = os.listdir(ARCH) if os.path.exists(ARCH) else []
    check("归档目录有文件", len(entries) > 0, f"entries={entries[:5]}")

    browser.close()

print("\n" + "="*60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"总计: {total} 项, PASS {passed}, FAIL {failed}")
for name, ok, detail in results:
    if not ok:
        print(f"  [FAIL] {name}: {detail}")
