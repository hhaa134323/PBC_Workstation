import sys, time, json
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright
BASE = 'http://127.0.0.1:8111'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(5)
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }""")
    time.sleep(1)
    page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === 'demo');
            if (proj) await d.switchProject(proj, true);
        }
    }""")
    time.sleep(5)
    # 打开变更记录面板
    page.evaluate("""() => { const btns = document.querySelectorAll('button'); for (const b of btns) { if ((b.textContent||'').includes('变更记录')) { b.click(); break; } } }""")
    time.sleep(3)
    body = page.evaluate('document.body.innerText')
    has_file_change = '文件变更' in body
    has_op_log = '操作日志' in body
    has_organize = '整理新文件' in body or '无待整理' in body
    print(f'有"文件变更"子页签: {has_file_change}')
    print(f'有"操作日志"子页签: {has_op_log}')
    print(f'有整理按钮: {has_organize}')
    # 切到操作日志
    page.evaluate("""() => { const btns = document.querySelectorAll('.pbcg-vh-tab'); for (const b of btns) { if (b.getAttribute('data-tab') === 'auditor') { b.click(); break; } } }""")
    time.sleep(2)
    body2 = page.evaluate('document.body.innerText')
    has_archived = '归档' in body2
    print(f'操作日志有归档记录: {has_archived}')
    browser.close()
