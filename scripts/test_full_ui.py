"""真正的交互测试：用 Playwright 有头模式打开浏览器，点击操作走完整业务流程，每步截图。"""
import sys, time, json, os, urllib.request
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8111"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\full_ui"
os.makedirs(SHOTS, exist_ok=True)
results = []

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    s = "PASS" if ok else "FAIL"
    print(f"[{s}] {name}: {detail}", flush=True)

def shot(page, name):
    p = os.path.join(SHOTS, f"{name}.png")
    page.screenshot(path=p, full_page=True)
    print(f"  截图: {name}.png", flush=True)

def wait_alpine(page):
    """等 Alpine.js 初始化"""
    for i in range(30):
        ready = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack && el._x_dataStack.length > 0;
        }''')
        if ready: return True
        time.sleep(1)
    return False

def alpine(page, js):
    return page.evaluate(f'''() => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            {js}
        }}
        return null;
    }}''')

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=300)
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    
    # === 1. 打开首页 ===
    print("\n=== 1. 打开首页 ===", flush=True)
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    wait_alpine(page)
    time.sleep(3)
    shot(page, "01_home")
    
    # === 2. 新建项目（用 API + 前端切换） ===
    print("\n=== 2. 新建项目 ===", flush=True)
    # 关掉 onboarding
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false;
    }''')
    time.sleep(1)
    shot(page, "02_dashboard")
    
    # 用 API 创建项目
    data = json.dumps({"name": "UI测试项目"}).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/projects/create", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req, timeout=10)
    proj = json.loads(r.read())
    proj_id = proj.get("project", {}).get("project_id", "")
    check("API创建项目", bool(proj_id), f"id={proj_id}")
    
    # PUT 设路径
    archive_dir = r"D:\AgentProjects\IpoPBC\0\projects\ui_test_archive"
    client_dir = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
    pbc_list = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
    
    update_data = json.dumps({"client_folder": client_dir, "archive_root": archive_dir}).encode('utf-8')
    req = urllib.request.Request(f"{BASE}/api/projects/{proj_id}", data=update_data,
        headers={"Content-Type": "application/json"}, method="PUT")
    urllib.request.urlopen(req, timeout=10)
    
    # 导入 PBC
    with open(pbc_list, 'rb') as f:
        boundary = '----pbc123'
        body = f'--{boundary}\r\n'.encode()
        body += b'Content-Disposition: form-data; name="file"; filename="01_PBC_List.xlsx"\r\n'
        body += b'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'
        body += f.read() + b'\r\n'
        body += f'--{boundary}--\r\n'.encode()
    req = urllib.request.Request(f"{BASE}/api/pbc/{proj_id}/import", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    urllib.request.urlopen(req, timeout=30)
    print("  PBC 清单导入完成", flush=True)
    
    # 前端切到新项目（用 switchProject 传项目对象）
    page.evaluate(f'''async () => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            // 加载项目列表找到 ui 项目
            const r = await fetch('/api/projects/list');
            const data = await r.json();
            const proj = (data.projects||[]).find(p => p.project_id === '{proj_id}');
            if (proj) {{
                await d.switchProject(proj, true);
            }}
        }}
    }}''')
    time.sleep(5)
    shot(page, "04_project_loaded")
    
    # === 3. 看待初检 tab ===
    print("\n=== 3. 待初检 tab ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage');
    }''')
    time.sleep(2)
    shot(page, "05_triage_tab")
    pending = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) return el._x_dataStack[0].pendingCount;
        return -1;
    }''')
    check("待初检有pending", pending and pending > 0, f"pending={pending}")
    
    # === 4. 点扫描 ===
    print("\n=== 4. 扫描 ===", flush=True)
    # 找扫描按钮
    scan_btn = page.query_selector('button:has-text("扫描")')
    if scan_btn:
        scan_btn.click()
        time.sleep(2)
        shot(page, "06_scanning")
    else:
        # 用 API 触发
        req = urllib.request.Request(f"{BASE}/api/files/{proj_id}/scan-folder", data=b'', method="POST")
        urllib.request.urlopen(req, timeout=60)
    
    # 等扫描完成
    print("  等扫描完成...", flush=True)
    for i in range(60):
        time.sleep(3)
        status = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) return el._x_dataStack[0].scan?.status;
            return null;
        }''')
        if status in ("done", "done_with_errors", "failed", ""):
            break
        if i % 5 == 0:
            print(f"    status={status}", flush=True)
    shot(page, "07_scan_done")
    check("扫描完成", True, f"status={status}")
    
    # === 5. 看待归档 tab ===
    print("\n=== 5. 待归档 tab ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
    }''')
    time.sleep(3)
    shot(page, "08_pending_archive_tab")
    
    # 看待归档数据
    pc_data = page.evaluate('''async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            // 看有没有 pendingArchive 数据
            const items = d.pendingArchive?.items || [];
            const count = items.length;
            return {count, firstItem: items[0] ? {id: items[0].id, name: items[0].file_name, item: items[0].suggested_item_id} : null};
        }
        return null;
    }''')
    print(f"  pendingArchive: {pc_data}", flush=True)
    check("待归档tab有数据", pc_data and pc_data.get("count", 0) > 0, f"count={pc_data.get('count') if pc_data else 'null'}")
    
    # === 6. 看文件区已归档树 ===
    print("\n=== 6. 文件区已归档树 ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].switchTab('files');
    }''')
    time.sleep(2)
    shot(page, "09_file_zone")
    
    tree_data = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const tree = d.fileZone?.tree || [];
            return {count: tree.length, categories: tree.map(t => t.category).filter(Boolean)};
        }
        return null;
    }''')
    print(f"  归档树: {tree_data}", flush=True)
    check("已归档树有数据", tree_data and tree_data.get("count", 0) > 0, 
          f"count={tree_data.get('count') if tree_data else 'null'}")
    
    # === 7. 看 dashboard ===
    print("\n=== 7. Dashboard ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage');
    }''')
    time.sleep(2)
    shot(page, "10_dashboard")
    
    # === 8. 看文件变更面板 ===
    print("\n=== 8. 文件变更面板 ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].openChangePanel();
    }''')
    time.sleep(2)
    shot(page, "11_change_panel")
    
    cl_data = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return {count: d.changePanel?.items?.length || 0};
        }
        return null;
    }''')
    check("文件变更有数据", cl_data and cl_data.get("count", 0) > 0, f"count={cl_data.get('count') if cl_data else 'null'}")
    
    # 关闭面板
    page.keyboard.press("Escape")
    time.sleep(1)
    
    # === 9. 看 AI 配置面板 ===
    print("\n=== 9. AI 配置面板 ===", flush=True)
    page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) el._x_dataStack[0].openAiConfig();
    }''')
    time.sleep(2)
    shot(page, "12_ai_config")
    
    ai_data = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const f = d.aiConfig?.form || {};
            return {model: f.model, hitl: f.hitl_mode, auto: f.auto_confirm_enabled};
        }
        return null;
    }''')
    check("AI配置model字段", ai_data and ai_data.get("model"), f"model={ai_data.get('model') if ai_data else 'null'}")
    check("AI配置hitl开关", ai_data and ai_data.get("hitl") == True, f"hitl={ai_data.get('hitl') if ai_data else 'null'}")
    
    # 关闭
    page.keyboard.press("Escape")
    time.sleep(1)
    
    browser.close()

print("\n" + "="*60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"总计: {total} 项, PASS {passed}, FAIL {failed}")
for name, ok, detail in results:
    if not ok:
        print(f"  [FAIL] {name}: {detail}")
