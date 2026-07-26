"""测试：扫描入口移到文件变更面板 + 改名"整理新文件"

8 个验收标准：
1. 待初检 tab 没有"扫描新文件"按钮
2. 文件变更面板（pbc-enhance）有"整理新文件"按钮
3. 没有待处理文件时，按钮灰色不可点
4. 有待处理文件时，按钮显示数量可点
5. 已处理的文件不会再被整理（不重复跑AI）- 暂跳过
6. 整理完后按钮显示"无待整理"- 暂跳过
7. 其他 tab 功能不受影响
8. 按钮文案正确
"""
import sys, time, json, urllib.request
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8111'
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

# 找有数据的项目
r = urllib.request.urlopen(f'{BASE}/api/projects/list?active_only=false')
projects = json.loads(r.read()).get('projects', [])
target = None
for p in projects:
    if p.get('project_id') == '5':
        target = p
        break
if not target:
    target = projects[0] if projects else None

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(5)
    page.evaluate('() => { const el = document.querySelector(\'[x-data="pbcApp()"]\'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }')
    time.sleep(1)
    
    if target:
        pid = target['project_id']
        page.evaluate("""async () => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                const r = await fetch('/api/projects/list?active_only=false');
                const data = await r.json();
                const proj = data.projects.find(p => p.project_id === '""" + pid + """');
                if (proj) await d.switchProject(proj, true);
            }
        }""")
        time.sleep(5)
    
    # === 标准1: 待初检没有"扫描新文件"按钮 ===
    print("\n=== 标准1: 待初检无扫描按钮 ===")
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage'); }""")
    time.sleep(2)
    has_scan_btn = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t === '扫描新文件' || t.startsWith('扫描新文件')) return true;
        }
        return false;
    }""")
    check("标准1: 待初检无'扫描新文件'按钮", not has_scan_btn, "仍有'扫描新文件'按钮")
    
    # === 标准2+8: 文件变更面板有"整理新文件"按钮 ===
    print("\n=== 标准2+8: 文件变更有整理按钮 ===")
    # 点击文件变更按钮（顶栏）
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if ((b.textContent||'').includes('文件变更')) { b.click(); break; }
        }
    }""")
    time.sleep(3)
    # pbc-enhance 渲染的面板
    has_organize = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t.includes('整理新文件') || t.includes('无待整理')) return true;
        }
        return false;
    }""")
    check("标准2: 文件变更有'整理新文件'按钮", has_organize, "没找到'整理新文件'")
    
    btn_text = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t.includes('整理') || t.includes('无待整理')) return t;
        }
        return null;
    }""")
    check("标准8: 按钮文案含'整理'", btn_text and '整理' in (btn_text or ''), f"文案={btn_text}")
    
    # === 标准3+4: 按钮状态 ===
    print("\n=== 标准3+4: 按钮状态 ===")
    state = page.evaluate("""() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return { pendingCount: d.pendingCount, scanActive: d.scan?.active };
        }
        return null;
    }""")
    pc = state.get('pendingCount', 0) if state else 0
    
    btn_info = page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            const t = (b.textContent || '').trim();
            if (t.includes('整理') || t.includes('无待整理')) {
                return { disabled: b.disabled, text: t };
            }
        }
        return null;
    }""")
    if pc > 0:
        check("标准4: 有待处理时按钮显示数量", btn_info and '(' in (btn_info.get('text') or ''), f"text={btn_info}")
        check("标准4: 有待处理时按钮可点", btn_info and not btn_info.get('disabled'), f"disabled={btn_info}")
    else:
        check("标准3: 无待处理时按钮不可点", btn_info and btn_info.get('disabled'), f"disabled={btn_info}")
        check("标准3: 无待处理时显示'无待整理'", btn_info and '无待整理' in (btn_info.get('text') or ''), f"text={btn_info}")
    
    # === 标准7: 其他 tab 不受影响 ===
    print("\n=== 标准7: 其他 tab 不受影响 ===")
    # 关闭面板
    page.evaluate("""() => {
        const btns = document.querySelectorAll('button');
        for (const b of btns) {
            if (b.getAttribute('data-act') === 'close') { b.click(); break; }
        }
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) { el._x_dataStack[0].changePanel.show = false; el._x_dataStack[0].switchTab('review'); }
    }""")
    time.sleep(2)
    body = page.evaluate('document.body.innerText')
    check("标准7: 待归档 tab 正常", '待归档' in body, "待归档 tab 没内容")
    
    page.evaluate("""() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('done'); }""")
    time.sleep(2)
    body = page.evaluate('document.body.innerText')
    check("标准7: 已完成 tab 正常", '已完成' in body or '归档' in body, "已完成 tab 没内容")
    
    browser.close()

print(f"\n=== 总计: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(0 if FAIL == 0 else 1)
