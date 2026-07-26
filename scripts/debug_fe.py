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
    time.sleep(5)
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }""")
    time.sleep(1)
    page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === 'e2e-3');
            if (proj) await d.switchProject(proj, true);
        }
    }""")
    time.sleep(8)
    state = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const d = el._x_dataStack[0]; return { pid: d.currentProjectId, pendingCount: d.pendingCount, loading: d.loading, pbcCount: (d.pbcList||[]).length, dashOk: !!d.dashboard }; } return null; }""")
    print('state:', state)
    # 直接调 new-file-count API 看返回
    api_result = page.evaluate("""async () => { const r = await fetch('/api/files/e2e-2/new-file-count'); return await r.json(); }""")
    print('API new-file-count:', api_result)
    # 直接调 reloadAll 看报错
    reload_result = page.evaluate("""async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            try { await el._x_dataStack[0].reloadAll(); return 'ok'; }
            catch(e) { return 'error: '+e.message; }
        }
        return 'no data';
    }""")
    print('reloadAll:', reload_result)
    time.sleep(3)
    state2 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { const d = el._x_dataStack[0]; return { pendingCount: d.pendingCount }; } return null; }""")
    print('reload后:', state2)
    for log in logs[-10:]:
        print('LOG:', log[:200])
    browser.close()
