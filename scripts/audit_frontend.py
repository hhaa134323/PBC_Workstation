"""全栈前端排查：逐 tab 检查每个页面渲染 + 交互"""
import sys, time, json, os
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8111"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\audit"
os.makedirs(SHOTS, exist_ok=True)

def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1400,"height":900})
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }''')
    time.sleep(1)
    shot(page, "00_home")

    # 切到 ui-3 项目
    page.evaluate('''async () => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list');
            const data = await r.json();
            const proj = (data.projects||[]).find(p => p.project_id === 'ui-3');
            if (proj) await d.switchProject(proj, true);
        }
    }''')
    time.sleep(5)
    shot(page, "01_project")

    # 收集当前状态
    state = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return {
                pid: d.currentProjectId,
                pbcCount: (d.pbcList||[]).length,
                pendingArchiveCount: (d.pendingArchive?.items||[]).length,
                treeCount: (d.fileZone?.tree||[]).length,
                changeLogCount: (d.changePanel?.items||[]).length,
                tabCounts: d.tabCounts,
                gauges: d.gauges,
                aiConfigForm: {
                    model: d.aiConfig?.form?.model,
                    hitl: d.aiConfig?.form?.hitl_mode,
                    auto: d.aiConfig?.form?.auto_confirm_enabled
                }
            };
        }
        return null;
    }''')
    print("=== 项目状态 ===")
    print(json.dumps(state, indent=2, ensure_ascii=False, default=str))

    # 逐 tab 检查
    tabs = ['triage', 'review', 'overdue', 'done', 'files']
    for tab in tabs:
        print(f"\n=== Tab: {tab} ===")
        page.evaluate(f'''() => {{ const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('{tab}'); }}''')
        time.sleep(2)
        shot(page, f"02_tab_{tab}")
        
        body = page.evaluate('document.body.innerText')
        # 检查关键内容
        lines = [l.strip() for l in body.split('\n') if l.strip()]
        # 找 tab 标题
        tab_idx = -1
        for i, l in enumerate(lines):
            if tab == 'triage' and '待初检' in l: tab_idx = i
            elif tab == 'review' and '待归档' in l: tab_idx = i
            elif tab == 'overdue' and '超期' in l: tab_idx = i
            elif tab == 'done' and '已完成' in l: tab_idx = i
            elif tab == 'files' and '文件区' in l: tab_idx = i
        
        if tab_idx >= 0:
            # 打印 tab 标题后的 15 行
            tab_content = lines[tab_idx:tab_idx+20]
            for line in tab_content:
                print(f"  {line}")
        else:
            print(f"  没找到 tab 标题")
            print(f"  body 前200字: {body[:200]}")

    # 检查 AI 配置面板
    print("\n=== AI 配置面板 ===")
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].openAiConfig(); }''')
    time.sleep(2)
    shot(page, "03_ai_config")
    
    body = page.evaluate('document.body.innerText')
    # 看 AI 配置面板内容
    ai_idx = body.find('AI')
    if ai_idx >= 0:
        ai_content = body[ai_idx:ai_idx+500]
        print(f"  AI配置内容: {ai_content[:300]}")

    # 检查文件变更面板
    print("\n=== 文件变更面板 ===")
    page.keyboard.press("Escape")
    time.sleep(1)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].openChangePanel(); }''')
    time.sleep(2)
    shot(page, "04_change_panel")
    
    cl = page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) return (el._x_dataStack[0].changePanel?.items||[]).length; return -1; }''')
    print(f"  变更日志条数: {cl}")
    
    body = page.evaluate('document.body.innerText')
    if '文件变更' in body:
        idx = body.find('文件变更')
        print(f"  变更面板内容: {body[idx:idx+300]}")

    browser.close()

print("\n=== 排查完成，截图在:", SHOTS, "===")
