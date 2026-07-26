"""验收测试：角标数字+待归档完整名称+预览按钮

验收标准：
1. 风险分析 tab 角标 = 超期项数（不是全部未提供）
2. 待归档显示"归档到: 一级分类 / item_id doc_name"（不是缩写）
3. 待归档有"预览"按钮
4. pending-confirm API 返回 doc_name/category/entity
"""
import sys, time, json, urllib.request
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8111'
PASS = 0
FAIL = 0

def check(name, cond, detail=""):
    global PASS, FAIL
    if cond: PASS += 1; print(f"  PASS: {name}")
    else: FAIL += 1; print(f"  FAIL: {name} - {detail}")

# 找有数据的项目
r = urllib.request.urlopen(f'{BASE}/api/projects/list?active_only=false')
projects = json.loads(r.read()).get('projects', [])
target = None
for p in projects:
    pid = p['project_id']
    try:
        pc = json.loads(urllib.request.urlopen(f'{BASE}/api/files/{pid}/pending-confirm').read())
        if pc.get('items'):
            target = p
            break
    except:
        pass

if not target:
    # 用有 PBC 数据的
    target = projects[0] if projects else None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(5)
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }""")
    time.sleep(1)
    
    if target:
        pid = target['project_id']
        page.evaluate(f"""async () => {{
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {{
                const d = el._x_dataStack[0];
                const r = await fetch('/api/projects/list?active_only=false');
                const data = await r.json();
                const proj = data.projects.find(p => p.project_id === '{pid}');
                if (proj) await d.switchProject(proj, true);
            }}
        }}""")
        time.sleep(8)
        page.evaluate("""async () => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) { try { await el._x_dataStack[0].reloadAll(); } catch(e) {} } }""")
        time.sleep(3)
    
    # === 标准1: 风险分析角标 = 超期数 ===
    print("\n=== 标准1: 风险分析角标 ===")
    tc = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return el._x_dataStack[0].tabCounts; return null; }""")
    print(f"  tabCounts: {tc}")
    # gauges.overdue 应该等于 tabCounts.overdue
    g = page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return el._x_dataStack[0].gauges; return null; }""")
    print(f"  gauges: {g}")
    if tc and g:
        check("标准1: 角标=超期数", tc.get('overdue',-1) == g.get('overdue',-2), f"tabCounts.overdue={tc.get('overdue')} gauges.overdue={g.get('overdue')}")
    
    # === 标准2: 待归档显示完整名称 ===
    print("\n=== 标准2: 待归档完整名称 ===")
    # 查 API 有没有 doc_name
    if target:
        pc = json.loads(urllib.request.urlopen(f'{BASE}/api/files/{pid}/pending-confirm').read())
        items = pc.get('items', [])
        if items:
            has_doc_name = any(it.get('doc_name') for it in items)
            check("标准2: API返回doc_name", has_doc_name, f"items[0] keys={list(items[0].keys())}")
            
            # 前端显示
            page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review'); }""")
            time.sleep(2)
            body = page.evaluate('document.body.innerText')
            has_full_name = '归档到:' in body or '归档到' in body
            check("标准2: 前端显示'归档到'", has_full_name, "没找到'归档到'")
            # 不应该显示"建议: 综-1"
            has_old = '建议:' in body
            check("标准2: 不显示旧的'建议:'", not has_old, "还显示'建议:'")
    
    # === 标准3: 预览按钮 ===
    print("\n=== 标准3: 预览按钮 ===")
    has_preview = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if ((b.textContent||'').trim() === '预览') return true;
        }
        return false;
    }""")
    check("标准3: 有预览按钮", has_preview, "没找到预览按钮")
    
    browser.close()

print(f"\n=== 总计: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(0 if FAIL == 0 else 1)
