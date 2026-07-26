import sys, time, json
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright
BASE = 'http://127.0.0.1:8111'
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    logs = []
    page.on('console', lambda msg: logs.append(f'{msg.type}: {msg.text}'))
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(3)
    page.evaluate('() => { const el = document.querySelector(\'[x-data="pbcApp()"]\'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }')
    time.sleep(1)
    # 切项目5
    page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === '5');
            if (proj) { await d.switchProject(proj, true); }
        }
    }""")
    time.sleep(5)
    state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const d = el._x_dataStack[0]; return { pid: d.currentProjectId, changePanelShow: d.changePanel?.show, changePanelItems: (d.changePanel?.items||[]).length }; } return null; }""")
    print('切项目后:', state)
    
    # 打开文件变更面板
    page.evaluate("() => { const el = document.querySelector('[x-data=\"pbcApp()\"]'); if (el && el._x_dataStack) el._x_dataStack[0].openChangePanel(); }")
    time.sleep(2)
    state2 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const d = el._x_dataStack[0]; return { show: d.changePanel?.show, items: (d.changePanel?.items||[]).length, loading: d.changePanel?.loading, error: d.changePanel?.error }; } return null; }""")
    print('打开面板后:', state2)
    
    # 点刷新
    page.evaluate("() => { const el = document.querySelector('[x-data=\"pbcApp()\"]'); if (el && el._x_dataStack) el._x_dataStack[0].loadChangeLog(); }")
    time.sleep(3)
    state3 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const d = el._x_dataStack[0]; return { items: (d.changePanel?.items||[]).length, loading: d.changePanel?.loading, error: d.changePanel?.error }; } return null; }""")
    print('点刷新后:', state3)
    
    body = page.evaluate('document.body.innerText')
    idx = body.find('文件变更')
    if idx >= 0:
        print('面板内容:', body[idx:idx+300])
    
    for log in logs[-5:]:
        print('LOG:', log[:200])
    
    browser.close()
