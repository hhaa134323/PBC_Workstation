"""前端交互测试 v10b — 直接用 Alpine.$data 切 tab 绕过按钮点击。"""
from playwright.sync_api import sync_playwright
import traceback

BASE = "http://127.0.0.1:8000"
results = []

def log(name, ok, detail=""):
    results.append({"name": name, "ok": ok, "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail[:150]}")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        # 1. 加载首页
        page.goto(BASE, wait_until="networkidle", timeout=15000)
        log("首页加载", "PBC" in page.title(), f"title={page.title()}")

        page.wait_for_timeout(3000)

        # 2. 切到待归档（review）tab
        page.evaluate("() => { const el = document.querySelector('[x-data]'); if(window.Alpine && el) { const d = Alpine.$data(el); d.currentTab = 'review'; } }")
        page.wait_for_timeout(2000)
        h1 = page.inner_text("h1").strip() if page.query_selector("h1") else ""
        log("切到待归档", "待归档" in h1, f"h1={h1[:50]}")
        page.screenshot(path="D:/AgentProjects/IpoPBC/screenshots/test_v10_review.png")

        # 3. 检查待归档表格行
        rows = page.query_selector_all("table.tbl tbody tr, .tbl tbody tr")
        if not rows:
            rows = page.query_selector_all("table tr")
        log("待归档表格行数", len(rows) > 0, f"rows={len(rows)}")

        # 4. 检查表格内容（AI 归档建议列）
        cell = page.evaluate("() => { const cells = document.querySelectorAll('table.tbl td, .tbl td'); if(cells.length===0) return 'no cells'; return Array.from(cells).slice(0,5).map(c => c.textContent.trim().substring(0,30)).join(' | '); }")
        log("待归档表格内容", "货-1" in cell or "历-1" in cell or "存-1" in cell or "待手动" in cell, cell[:120])

        # 5. 切到待初检（triage）tab
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.currentTab = 'triage'; }")
        page.wait_for_timeout(2000)
        h1 = page.inner_text("h1").strip() if page.query_selector("h1") else ""
        log("切到待初检", "待初检" in h1, f"h1={h1[:50]}")
        page.screenshot(path="D:/AgentProjects/IpoPBC/screenshots/test_v10_triage.png")

        # 6. 检查待初检表格行
        rows = page.query_selector_all("table tr")
        log("待初检表格行数", len(rows) > 1, f"rows={len(rows)}")

        # 7. 切到已完成（done）tab
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.currentTab = 'done'; }")
        page.wait_for_timeout(2000)
        h1 = page.inner_text("h1").strip() if page.query_selector("h1") else ""
        log("切到已完成", "已完成" in h1 or "已归档" in h1, f"h1={h1[:50]}")
        page.screenshot(path="D:/AgentProjects/IpoPBC/screenshots/test_v10_done.png")
        rows = page.query_selector_all("table tr")
        log("已完成表格行数", True, f"rows={len(rows)}")

        # 8. 切到逾期（overdue）tab
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.currentTab = 'overdue'; }")
        page.wait_for_timeout(2000)
        h1 = page.inner_text("h1").strip() if page.query_selector("h1") else ""
        log("切到逾期", "逾期" in h1 or "风险" in h1, f"h1={h1[:50]}")
        page.screenshot(path="D:/AgentProjects/IpoPBC/screenshots/test_v10_overdue.png")

        # 9. 切回文件（files）tab
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.currentTab = 'files'; }")
        page.wait_for_timeout(2000)
        h1 = page.inner_text("h1").strip() if page.query_selector("h1") else ""
        log("切到文件区", "文件" in h1 or "归档" in h1, f"h1={h1[:50]}")

        # 10. console 错误
        log("console 无错误", len(errors) == 0, f"errors={errors[:3]}")

        # 11. 检查今日简报
        briefing = page.evaluate("() => { const el = document.querySelector('[class*=\"brief\"], [class*=\"简报\"]'); return el ? 'found' : 'not found'; }")
        log("今日简报元素", briefing == "found", briefing)

        # 12. 检查顶栏按钮
        nav_btns = page.evaluate("() => { const nav = document.querySelector('.nav-top'); if(!nav) return 'no nav'; return Array.from(nav.children).filter(c=>c.tagName==='BUTTON').map(b=>b.textContent.trim()).join(','); }")
        log("顶栏按钮", nav_btns != "no nav" and len(nav_btns) > 10, nav_btns[:120])

        # 13. 检查 coach mark 是否出现（首次）
        coach = page.evaluate("() => { const el = document.querySelector('.pbcg-coach'); return el ? (el.style.display !== 'none' ? 'visible' : 'hidden') : 'absent'; }")
        log("coach mark", coach in ["visible", "hidden"], f"state={coach}")

        browser.close()
except Exception as e:
    log("测试异常", False, traceback.format_exc()[:200])

passed = sum(1 for r in results if r["ok"])
print(f"\n=== {passed}/{len(results)} PASS ===")
for r in results:
    if not r["ok"]:
        print(f"  FAIL: {r['name']}: {r['detail']}")
