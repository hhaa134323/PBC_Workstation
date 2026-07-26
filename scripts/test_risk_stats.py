import sys, time, json
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright
BASE = 'http://127.0.0.1:8111'
PASS = 0
FAIL = 0
def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  PASS: {name}")
    else: FAIL += 1; print(f"  FAIL: {name} - {detail}")

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
            const proj = data.projects.filter(p => p.name && p.name.includes('文件变更')).sort((a,b)=>(b.created_at||'').localeCompare(a.created_at||''))[0];
            if (proj) await d.switchProject(proj, true);
        }
    }""")
    time.sleep(8)
    page.evaluate("""async () => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { try { await el._x_dataStack[0].reloadAll(); } catch(e) {} } }""")
    time.sleep(3)
    
    state = page.evaluate("""() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const g = d.gauges;
            return { done: g.done, review: g.review, overdue: g.overdue, high: g.high, na: g.na, pbcCount: (d.pbcList||[]).length };
        }
        return null;
    }""")
    print(f"前端 gauges: {state}")
    
    check("gauges.done=9", state and state.get('done')==9, f"done={state}")
    check("gauges.overdue=7", state and state.get('overdue')==7, f"overdue={state}")
    check("gauges.high=1", state and state.get('high')==1, f"high={state}")
    
    # 风险分析 tab
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('overdue'); }""")
    time.sleep(2)
    fi1 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return el._x_dataStack[0].filteredItems().length; return -1; }""")
    print(f"风险分析 filteredItems: {fi1}")
    check("风险分析只显示超期的(7条)", fi1==7, f"count={fi1}")
    
    # 已完成 tab
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('done'); }""")
    time.sleep(2)
    fi2 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return el._x_dataStack[0].filteredItems().length; return -1; }""")
    print(f"已完成 filteredItems: {fi2}")
    check("已完成显示9条", fi2==9, f"count={fi2}")
    
    # 待初检 tab
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage'); }""")
    time.sleep(2)
    fi3 = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return el._x_dataStack[0].filteredItems().length; return -1; }""")
    print(f"待初检 filteredItems: {fi3}")
    check("待初检显示未提供(10条)", fi3==10, f"count={fi3}")
    
    browser.close()

print(f"\n=== 总计: {PASS} PASS / {FAIL} FAIL ===")
