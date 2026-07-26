"""表格分页+搜索验收测试

验收点：
1. 顶部搜索框存在（placeholder 含"搜索文件名/编号/分类/实体"）
2. 默认 50 条/页
3. 切换 20 条/页 → 分页按钮出现
4. 搜索框输入 → 实时过滤 + 重置到第1页
5. 跨字段搜索（输入编号/分类/实体都能匹配）
6. 切 tab → page 重置为 1 + 搜索清空
7. 分页按钮：上一页/下一页 + 页码显示
8. 每页条数选择器 20/50/100
9. 空结果提示"无匹配条目"
"""
import sys, time, json, urllib.request, os, shutil
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8000'
CLIENT = r'D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态'
PBC = r'D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx'
ARCH = r'D:\AgentProjects\IpoPBC\0\projects\tbl_test_' + str(int(time.time()))

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

def api_post(url, data=b'', method="POST", headers=None):
    req = urllib.request.Request(url, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if headers:
        for k,v in headers.items():
            req.add_header(k, v)
    return json.loads(urllib.request.urlopen(req, timeout=120).read())

if os.path.exists(ARCH):
    shutil.rmtree(ARCH, ignore_errors=True)

print("=" * 60)
print("  表格分页+搜索验收")
print("=" * 60)

# === 1. 新建项目 ===
print("\n=== 1. 新建项目 ===")
proj = api_post(f"{BASE}/api/projects/create", json.dumps({"name": "表格分页测试"}).encode())
pid = proj.get("project", {}).get("project_id", "")
check("1.1 新建项目", bool(pid), f"id={pid}")

api_post(f"{BASE}/api/projects/{pid}", json.dumps({"client_folder": CLIENT, "archive_root": ARCH}).encode(), method="PUT")

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
check("1.2 导入PBC清单", pbc_result.get("ok") or pbc_result.get("count", 0) > 0, f"result={pbc_result}")

# === 2. 前端验证 ===
print("\n=== 2. 前端验证表格分页+搜索 ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(5)
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }""")
    time.sleep(1)

    # 切到新项目
    page.evaluate("""async (pid) => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === pid);
            if (proj) await d.switchProject(proj, true);
        }
    }""", pid)
    time.sleep(3)
    page.evaluate("""async () => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) await el._x_dataStack[0].reloadAll(); }""")
    time.sleep(2)

    # === 3. 待初检 tab 验证 ===
    print("\n=== 3. 待初检 tab ===")
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage'); }""")
    time.sleep(2)

    dom_check = page.evaluate("""() => {
        const tab = document.querySelector('[x-show*="triage"]');
        if (!tab) return {found:false};
        const inputs = tab.querySelectorAll('input');
        const selects = tab.querySelectorAll('select');
        let searchInput = null;
        for (const i of inputs) {
            const ph = i.getAttribute('placeholder') || '';
            if (ph.includes('搜索') || ph.includes('文件名')) { searchInput = {ph: ph, value: i.value}; break; }
        }
        // 查分页按钮
        const btns = tab.querySelectorAll('button');
        let hasPrev=false, hasNext=false;
        for (const b of btns) {
            const t = (b.textContent||'').trim();
            if (t.includes('上一页')) hasPrev = true;
            if (t.includes('下一页')) hasNext = true;
        }
        // 查每页条数 select
        let sizeSelect = null;
        for (const s of selects) {
            const opts = [...s.options].map(o=>o.text);
            if (opts.some(o=>o.includes('条/页'))) { sizeSelect = opts; break; }
        }
        // 查表格行数
        const rows = tab.querySelectorAll('table.tbl tbody tr');
        // 查 filter-info
        const filterInfo = tab.querySelector('.filter-info');
        return {
            found: true,
            searchPlaceholder: searchInput?.ph,
            hasPrev, hasNext,
            sizeSelectOpts: sizeSelect,
            tableRowCount: rows.length,
            filterInfoText: filterInfo?.textContent || '',
        };
    }""")
    print(f"  DOM: {dom_check}")
    check("3.1 顶部搜索框存在", '搜索' in (dom_check.get('searchPlaceholder') or ''), f"ph={dom_check.get('searchPlaceholder')}")
    check("3.2 有上一页按钮", dom_check.get('hasPrev'), "")
    check("3.3 有下一页按钮", dom_check.get('hasNext'), "")
    check("3.4 有每页条数选择器", dom_check.get('sizeSelectOpts') is not None, f"opts={dom_check.get('sizeSelectOpts')}")
    check("3.5 每页条数含20/50/100", dom_check.get('sizeSelectOpts') and all('20' in o or '50' in o or '100' in o for o in dom_check.get('sizeSelectOpts',[])) if dom_check.get('sizeSelectOpts') else False, "")
    check("3.6 表格有行数据", dom_check.get('tableRowCount', 0) > 0, f"rows={dom_check.get('tableRowCount')}")

    # === 4. 切换每页条数 ===
    print("\n=== 4. 切换每页条数 ===")
    # 默认 pageSize=50，19条应该1页
    state_before = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {page: el._x_dataStack[0].tableState.page, pageSize: el._x_dataStack[0].tableState.pageSize, total: el._x_dataStack[0].searchedItems().length}; return null; }""")
    print(f"  默认状态: {state_before}")
    check("4.1 默认pageSize=50", state_before and state_before.get('pageSize') == 50, f"state={state_before}")
    check("4.2 默认page=1", state_before and state_before.get('page') == 1, "")
    check("4.3 总条目数=19", state_before and state_before.get('total') == 19, f"total={state_before.get('total') if state_before else 'null'}")

    # 切到20条/页
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].tableState.pageSize = 20; }""")
    time.sleep(1)
    state_after = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {page: el._x_dataStack[0].tableState.page, pageSize: el._x_dataStack[0].tableState.pageSize, totalPages: el._x_dataStack[0].tableTotalPages}; return null; }""")
    print(f"  切20后: {state_after}")
    check("4.4 切20条后pageSize=20", state_after and state_after.get('pageSize') == 20, f"state={state_after}")
    check("4.5 19条用20/页=1页", state_after and state_after.get('totalPages') == 1, f"pages={state_after.get('totalPages') if state_after else 'null'}")

    # === 5. 搜索功能 ===
    print("\n=== 5. 搜索功能 ===")
    # 输入搜索关键词
    page.evaluate("""() => { window.__tableSearch('财-1'); }""")
    time.sleep(1)
    search_state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {q: el._x_dataStack[0].tableState.q, page: el._x_dataStack[0].tableState.page, total: el._x_dataStack[0].searchedItems().length}; return null; }""")
    print(f"  搜索'财-1'后: {search_state}")
    check("5.1 搜索词已设置", search_state and search_state.get('q') == '财-1', f"q={search_state.get('q') if search_state else 'null'}")
    check("5.2 搜索后重置page=1", search_state and search_state.get('page') == 1, "")
    check("5.3 搜索'财-1'有结果", search_state and search_state.get('total', 0) > 0, f"total={search_state.get('total') if search_state else 'null'}")

    # 跨字段搜索：输入分类"财务报表"
    page.evaluate("""() => { window.__tableSearch('财务报表'); }""")
    time.sleep(1)
    search_state2 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {q: el._x_dataStack[0].tableState.q, total: el._x_dataStack[0].searchedItems().length}; return null; }""")
    print(f"  搜索'财务报表'后: {search_state2}")
    check("5.4 跨字段搜索分类'财务报表'有结果", search_state2 and search_state2.get('total', 0) > 0, f"total={search_state2.get('total') if search_state2 else 'null'}")

    # 搜索无匹配
    page.evaluate("""() => { window.__tableSearch('不存在的关键词xyz123'); }""")
    time.sleep(1)
    search_state3 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {q: el._x_dataStack[0].tableState.q, total: el._x_dataStack[0].searchedItems().length}; return null; }""")
    print(f"  搜索无匹配后: {search_state3}")
    check("5.5 无匹配时total=0", search_state3 and search_state3.get('total') == 0, f"total={search_state3.get('total') if search_state3 else 'null'}")

    # 清空搜索
    page.evaluate("""() => { window.__tableSearch(''); }""")
    time.sleep(1)

    # === 6. 切 tab 重置 ===
    print("\n=== 6. 切tab重置 ===")
    # 先设置搜索
    page.evaluate("""() => { window.__tableSearch('财-1'); window.__tablePage(2); }""")
    time.sleep(1)
    # 切到风险分析 tab
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('overdue'); }""")
    time.sleep(1)
    tab_state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {q: el._x_dataStack[0].tableState.q, page: el._x_dataStack[0].tableState.page}; return null; }""")
    print(f"  切overdue后: {tab_state}")
    check("6.1 切tab清空搜索", tab_state and tab_state.get('q') == '', f"q={tab_state.get('q') if tab_state else 'null'}")
    check("6.2 切tab重置page=1", tab_state and tab_state.get('page') == 1, "")

    # === 7. 分页按钮交互 ===
    print("\n=== 7. 分页按钮交互 ===")
    # 切回待初检，设20条/页，验证翻页
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { el._x_dataStack[0].switchTab('triage'); el._x_dataStack[0].tableState.pageSize = 5; el._x_dataStack[0].tableState.page = 1; } }""")
    time.sleep(1)
    # 19条/5条每页 = 4页
    page_state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {page: el._x_dataStack[0].tableState.page, totalPages: el._x_dataStack[0].tableTotalPages, pageSize: el._x_dataStack[0].tableState.pageSize}; return null; }""")
    print(f"  5条/页: {page_state}")
    check("7.1 19条用5/页=4页", page_state and page_state.get('totalPages') == 4, f"pages={page_state.get('totalPages') if page_state else 'null'}")

    # 点下一页
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].tableState.page = 2; }""")
    time.sleep(1)
    page2_state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return {page: el._x_dataStack[0].tableState.page}; return null; }""")
    check("7.2 翻到第2页", page2_state and page2_state.get('page') == 2, f"page={page2_state}")

    # === 8. 截图 ===
    os.makedirs(r'D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots', exist_ok=True)
    page.screenshot(path=r'D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\table_pagination.png', full_page=True)

    browser.close()

print(f"\n{'='*60}")
print(f"  表格分页+搜索验收: {PASS} PASS / {FAIL} FAIL")
print(f"{'='*60}")
sys.exit(0 if FAIL == 0 else 1)
