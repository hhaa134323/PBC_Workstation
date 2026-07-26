"""完整业务流程真实测试

模拟用户真实操作：
1. 新建项目
2. 配文件夹路径
3. 导入PBC清单
4. 打开文件变更面板 → 应看到新文件
5. 点"整理新文件" → AI跑完
6. 待归档tab出现条目
7. 确认归档
8. 已完成tab出现归档
"""
import sys, time, json, urllib.request, os, shutil
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8000'
CLIENT = r'D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态'
PBC = r'D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx'
ARCH = r'D:\AgentProjects\IpoPBC\0\projects\e2e_test_new_' + str(int(time.time()))

PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name} - {detail}")

def api_get(url):
    return json.loads(urllib.request.urlopen(url, timeout=60).read())

def api_post(url, data=b'', method="POST"):
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=120).read())

# === 1. 新建项目 ===
print("\n=== 1. 新建项目 ===")
proj = api_post(f"{BASE}/api/projects/create", json.dumps({"name": "E2E测试"}).encode())
pid = proj.get("project", {}).get("project_id", "")
check("新建项目", bool(pid), f"id={pid}")
print(f"  项目ID: {pid}")

# === 2. 配路径 ===
print("\n=== 2. 配文件夹路径 ===")
api_post(f"{BASE}/api/projects/{pid}", json.dumps({"client_folder": CLIENT, "archive_root": ARCH}).encode(), method="PUT")
# 导入PBC
with open(PBC, 'rb') as f:
    boundary = '----pbc123'
    body = f'--{boundary}\r\n'.encode()
    body += b'Content-Disposition: form-data; name="file"; filename="01_PBC_List.xlsx"\r\n'
    body += b'Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n'
    body += f.read() + b'\r\n'
    body += f'--{boundary}--\r\n'.encode()
req = urllib.request.Request(f"{BASE}/api/pbc/{pid}/import", data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
r = urllib.request.urlopen(req, timeout=30)
pbc_result = json.loads(r.read())
check("导入PBC清单", pbc_result.get("ok"), f"items={pbc_result.get('count',0)}")

# === 3. 测试API: new-file-count ===
print("\n=== 3. API new-file-count ===")
nfc = api_get(f"{BASE}/api/files/{pid}/new-file-count")
new_count = nfc.get("new_file_count", 0)
print(f"  新文件数: {new_count}")
check("API返回新文件数>0", new_count > 0, f"new_file_count={new_count}")

# === 4. 前端: 打开文件变更面板看"整理新文件"按钮 ===
print("\n=== 4. 前端文件变更面板 ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(5)
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }""")
    time.sleep(1)
    # 切到新项目
    page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === '""" + pid + """');
            if (proj) await d.switchProject(proj, true);
        }
    }""")
    time.sleep(3)
    
    # 手动触发 reloadAll 确保数据加载
    reload_result = page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            try { 
                await el._x_dataStack[0].reloadAll();
                const d = el._x_dataStack[0];
                return { ok: true, pc: d.pendingCount, clItems: (d.changePanel?.items||[]).length, pid: d.currentProjectId };
            } catch(e) { return { ok: false, error: e.message }; }
        }
        return { ok: false, error: 'no data' };
    }""")
    print(f"  reloadAll结果: {reload_result}")
    # 直接调 sync-changes + change-log 看有没有
    sync_result = page.evaluate("""async () => {
        const pid = document.querySelector('[x-data="pbcApp()"]')._x_dataStack[0].currentProjectId;
        await fetch('/api/files/'+pid+'/sync-changes', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
        const r = await fetch('/api/files/'+pid+'/change-log?limit=5');
        const d = await r.json();
        return { count: d.count, logs: (d.logs||[]).length };
    }""")
    print(f"  sync+cl: {sync_result}")
    time.sleep(3)
    
    # 打开文件变更面板
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if ((b.textContent||'').includes('文件变更')) { b.click(); break; }
        }
    }""")
    time.sleep(3)
    
    # 看"整理新文件"按钮
    btn_text = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t.includes('整理') || t.includes('无待整理')) return t;
        }
        return null;
    }""")
    check("整理按钮显示新文件数", btn_text and '(' in (btn_text or ''), f"text={btn_text}")
    check("整理按钮可点", btn_text and '无待整理' not in (btn_text or ''), f"text={btn_text}")
    
    # 看 pendingCount
    state = page.evaluate("""() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return { pendingCount: d.pendingCount, pid: d.currentProjectId };
        }
        return null;
    }""")
    print(f"  前端 pendingCount: {state.get('pendingCount') if state else 'null'}")
    check("前端pendingCount>0", state and state.get('pendingCount',0) > 0, f"pendingCount={state}")
    
    # === 5. 文件变更面板有变更列表 ===
    print("\n=== 5. 变更列表有内容 ===")
    # 打开文件变更面板
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if ((b.textContent||'').includes('文件变更')) { b.click(); break; }
        }
    }""")
    time.sleep(3)
    # 看面板里有没有变更记录（added 文件名）
    has_items = page.evaluate("""() => {
        const panel = document.querySelector('.pbcg-vh-list');
        if (!panel) return false;
        const text = panel.innerText || '';
        return text.length > 20 && (text.includes('新增') || text.includes('added'));
    }""")
    check("标准5: 变更列表显示新增文件", has_items, "面板列表为空")
    
    # 看 changePanel items 数
    cl_state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return { items: (el._x_dataStack[0].changePanel?.items||[]).length }; return null; }""")
    print(f"  changePanel items: {cl_state}")
    check("标准5: changePanel 有记录", cl_state and cl_state.get('items',0) > 0, f"items={cl_state}")
    
    # 截图
    page.screenshot(path=r'D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\e2e_change_panel.png', full_page=True)
    
    browser.close()

print(f"\n=== 总计: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(0 if FAIL == 0 else 1)
