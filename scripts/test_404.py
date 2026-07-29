"""查 404 资源 + tab 切换验证。"""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1400, "height": 900})

    failed_urls = []
    page.on("response", lambda resp: failed_urls.append(f"{resp.status} {resp.url}") if resp.status >= 400 else None)

    page.goto(BASE, wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(3000)

    print("=== 404 资源 ===")
    for u in failed_urls:
        print(f"  {u}")

    print("\n=== 所有 script/img 请求 ===")
    scripts = page.evaluate("() => { return Array.from(document.querySelectorAll('script[src], link[href], img[src]')).map(e => e.src || e.href).filter(Boolean); }")
    for s in scripts:
        print(f"  {s}")

    print("\n=== tab 切换测试（用 switchTab 方法）===")
    for tab in ["review", "triage", "done", "overdue", "files"]:
        page.evaluate(f"(tab) => {{ const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); if(typeof d.switchTab === 'function') d.switchTab('{tab}'); else d.currentTab = '{tab}'; }}", tab)
        page.wait_for_timeout(1500)
        # 看当前显示的 x-show 区块
        visible_block = page.evaluate("() => { const blocks = document.querySelectorAll('[x-show*=\"currentTab\"]'); for(const b of blocks) { if(b.style.display !== 'none' && getComputedStyle(b).display !== 'none') { const h = b.querySelector('h1'); return h ? h.textContent.trim() : '(no h1)'; } } return '(none visible)'; }")
        print(f"  tab={tab}: visible_h1={visible_block}")

    browser.close()
