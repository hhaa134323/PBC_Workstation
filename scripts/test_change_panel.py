"""截图变更记录面板看实际渲染。"""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000"

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    # 新 context 强制无缓存
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    page = ctx.new_page()

    page.goto(BASE, wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(3000)

    # 点变更记录按钮（pbc-enhance.js hook 的）
    page.evaluate("() => { const btns = document.querySelectorAll('button'); for(const b of btns){ if(b.textContent.includes('变更记录') || b.textContent.includes('文件变更')){ b.click(); break; } } }")
    page.wait_for_timeout(2000)

    # 截图
    page.screenshot(path="D:/AgentProjects/IpoPBC/screenshots/test_change_panel.png")
    print("screenshot saved")

    # 提取面板文字
    panel_text = page.evaluate("() => { const el = document.querySelector('.pbcg-vh'); if(!el) return 'no panel'; return el.textContent.substring(0, 500); }")
    print(f"panel text: {panel_text}")

    # 检查有没有那个按钮
    has_btn = page.evaluate("() => { return document.querySelector('.pbcg-vh-go') !== null; }")
    print(f"has button: {has_btn}")

    # 检查有没有"在清单里看"文字
    body_text = page.inner_text("body")
    if "在清单里看" in body_text:
        idx = body_text.index("在清单里看")
        print(f"FOUND '在清单里看': context={body_text[max(0,idx-30):idx+50]}")
    else:
        print("NOT FOUND '在清单里看' in body")

    browser.close()
