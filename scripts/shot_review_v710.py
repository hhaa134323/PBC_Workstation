"""v7.10 待归档表格化视觉验收截图"""
from playwright.sync_api import sync_playwright
import time, json, urllib.request

BASE = "http://127.0.0.1:8000"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots"
import os; os.makedirs(SHOTS, exist_ok=True)

# 确认 demo 有待归档数据
r = json.loads(urllib.request.urlopen(f"{BASE}/api/files/demo/pending-confirm").read())
print(f"pending count: {len(r.get('items',[]))}")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1400,"height":900})
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(3)
    # 用 JS 直接切到 demo 项目 + 关闭引导遮罩
    page.evaluate(r"""() => {
        const app = Alpine.$data(document.querySelector('[x-data]'));
        app.showOnboarding = false;
        const demo = app.projects.find(p=>p.project_id==='demo');
        if(demo) app.switchProject(demo, true);
    }""")
    time.sleep(3)
    # 用 JS 切到待归档 tab
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('review'); }""")
    time.sleep(3)
    # 验证 tab 切换 + 等 loading 完成
    state = page.evaluate(r"""() => { const app = Alpine.$data(document.querySelector('[x-data]')); return {tab: app.currentTab, loading: app.loading, pendingCount: (app.pendingArchive.items||[]).length}; }""")
    print(f"currentTab={state['tab']}, loading={state['loading']}, pendingCount={state['pendingCount']}")
    # 等 loading 变 false
    for _ in range(30):
        if not page.evaluate(r"""() => Alpine.$data(document.querySelector('[x-data]')).loading"""):
            break
        time.sleep(1)
    time.sleep(3)
    # 滚动到表格
    page.evaluate("() => { const el = document.querySelector('.tbl-wrap') || document.querySelector('table.tbl'); if(el) el.scrollIntoView({block:'start'}); }")
    time.sleep(2)
    # 再验证
    # 切到 triage tab 对比
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('triage'); }""")
    time.sleep(2)
    triageState = page.evaluate(r"""() => { const tbl = document.querySelector('table.tbl'); const wrap = document.querySelector('.tbl-wrap'); return {tblHeight: tbl ? tbl.getBoundingClientRect().height : 0, wrapHeight: wrap ? wrap.getBoundingClientRect().height : 0}; }""")
    print(f"triage tab: {triageState}")
    # 切回 review
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('review'); }""")
    time.sleep(2)
    # 对比 review 和 triage 的 table HTML 结构
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('review'); }""")
    time.sleep(2)
    reviewTblHTML = page.evaluate(r"""() => { const tbl = document.querySelector('table.tbl'); return tbl ? tbl.outerHTML.slice(0, 400) : 'no table'; }""")
    print(f"REVIEW table outerHTML (first 400): {reviewTblHTML}")
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('triage'); }""")
    time.sleep(2)
    triageTblHTML = page.evaluate(r"""() => { const tbl = document.querySelector('table.tbl'); return tbl ? tbl.outerHTML.slice(0, 400) : 'no table'; }""")
    print(f"TRIAGE table outerHTML (first 400): {triageTblHTML}")
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('review'); }""")
    time.sleep(2)
    # 看 review 的 tbl-wrap 父元素
    # v7.10 选 review tab 容器内的 table
    reviewWrap = page.evaluate(r"""() => { const reviewDiv = document.querySelector('[x-show="!loading && currentTab===\'review\'"]'); if(!reviewDiv) return 'no reviewDiv'; const tbl = reviewDiv.querySelector('table.tbl'); const wrap = reviewDiv.querySelector('.tbl-wrap'); const filters = reviewDiv.querySelector('.filters'); const pagination = reviewDiv.querySelector('.pagination'); const search = reviewDiv.querySelector('input[x-model\\.debounce]'); const colcfg = reviewDiv.querySelector('.colcfg'); if(!tbl) return 'no tbl in review'; return {tblHeight: tbl.getBoundingClientRect().height, wrapHeight: wrap ? wrap.getBoundingClientRect().height : 0, rows: tbl.querySelectorAll('tbody tr').length, hasFilters: !!filters, hasSearch: !!search, hasPagination: !!pagination, hasColCfg: !!colcfg, reviewDivHeight: reviewDiv.getBoundingClientRect().height}; }""")
    print(f"REVIEW (in review div): {reviewWrap}")
    # 看 review 容器的所有子元素
    reviewChildren = page.evaluate(r"""() => { const div = document.querySelector('[x-show="!loading && currentTab===\'review\'"]'); if(!div) return []; return Array.from(div.children).map(c => ({tag: c.tagName, cls: c.className, display: getComputedStyle(c).display, h: c.getBoundingClientRect().height})); }""")
    print(f"REVIEW container children: {reviewChildren}")
    # 截图
    page.screenshot(path=f"{SHOTS}/review_v710_full.png", full_page=True)
    # 截 review tab 容器
    page.evaluate(r"""() => { const reviewDiv = document.querySelector('[x-show="!loading && currentTab===\'review\'"]'); if(reviewDiv) reviewDiv.scrollIntoView({block:'start'}); }""")
    time.sleep(1)
    reviewHandle = page.query_selector('[x-show="!loading && currentTab===\'review\'"]')
    if reviewHandle:
        try:
            reviewHandle.screenshot(path=f"{SHOTS}/review_v710_table.png")
        except Exception as e:
            print(f"review screenshot failed: {e}")
    # 截工具栏
    bar = page.query_selector('.toolbar')
    if bar:
        bar.screenshot(path=f"{SHOTS}/review_v710_toolbar.png")
    # 打印表格 HTML 结构（前 2000 字符）供检查
    html = page.evaluate("document.querySelector('table.tbl')?.outerHTML || 'no table'")
    print("TABLE HTML (first 1500):")
    print(html[:1500])
    print("---")
    # 检查关键元素
    checks = {
        'table': page.query_selector('table.tbl') is not None,
        'toolbar_search': page.query_selector('.toolbar input.search') is not None,
        'pagination': page.query_selector('.pagination') is not None,
        'archive_to': page.query_selector('.archive-to') is not None,
        'conf_bar': page.query_selector('.conf .bar') is not None,
        'btn_icon_preview': page.query_selector('button[title="预览原文件"]') is not None,
        'lowconf_row': page.query_selector('tr.lowconf') is not None,
        'badge_b_none': page.query_selector('.badge.b-none') is not None,
        'btn_icon_class': page.query_selector('.btn-icon') is not None,
    }
    print("关键元素检查:")
    for k,v in checks.items():
        print(f"  {'OK' if v else 'MISSING'}: {k}")
    browser.close()
print(f"截图保存到 {SHOTS}")
