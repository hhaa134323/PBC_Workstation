"""今日简报功能验收：各种情况下前端预期 vs 实际"""
from playwright.sync_api import sync_playwright
import time, json

BASE = "http://127.0.0.1:8000"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots"
import os; os.makedirs(SHOTS, exist_ok=True)

def check(page, name, desc):
    """检查简报状态"""
    state = page.evaluate(r"""() => {
        const app = Alpine.$data(document.querySelector('[x-data]'));
        const bd = app.briefingDelta;
        return {
            currentProjectId: app.currentProjectId,
            briefHasDelta: app.briefHasDelta,
            has_delta: bd ? bd.has_delta : 'no briefingDelta',
            delta_count: bd ? bd.delta_count : null,
            delta_groups: bd ? bd.delta_groups : null,
            stock_total: bd ? bd.stock_total : null,
            events_count: bd ? (bd.events||[]).length : null,
            bb_msg_text: document.querySelector('.bb-msg') ? document.querySelector('.bb-msg').textContent.trim() : 'no .bb-msg',
        };
    }""")
    print(f"\n--- {name} ---")
    print(f"  {desc}")
    print(f"  project={state['currentProjectId']}, briefHasDelta={state['briefHasDelta']}")
    print(f"  has_delta={state['has_delta']}, delta_count={state['delta_count']}")
    print(f"  delta_groups={state['delta_groups']}")
    print(f"  stock_total={state['stock_total']}, events={state['events_count']}")
    print(f"  简报文字: {state['bb_msg_text']}")
    page.screenshot(path=f"{SHOTS}/briefing_{name}.png")
    return state

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1400,"height":900})
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    time.sleep(3)
    page.evaluate(r"""() => {
        const app = Alpine.$data(document.querySelector('[x-data]'));
        app.showOnboarding = false;
    }""")
    time.sleep(2)

    # 场景1：默认进入（第一个项目）
    check(page, "s1_default", "默认进入第一个项目，无操作")

    # 场景2：切到 demo 项目
    page.evaluate(r"""() => {
        const app = Alpine.$data(document.querySelector('[x-data]'));
        const demo = app.projects.find(p=>p.project_id==='demo');
        if(demo) app.switchProject(demo, true);
    }""")
    time.sleep(3)
    check(page, "s2_demo", "切到 demo 项目")

    # 场景3：待归档 tab（看是否有文件新增）
    page.evaluate(r"""() => { Alpine.$data(document.querySelector('[x-data]')).switchTab('review'); }""")
    time.sleep(2)
    check(page, "s3_demo_review", "demo 项目待归档 tab")

    # 场景4：回到第一个项目
    page.evaluate(r"""() => {
        const app = Alpine.$data(document.querySelector('[x-data]'));
        if(app.projects[0]) app.switchProject(app.projects[0], true);
    }""")
    time.sleep(3)
    check(page, "s4_back_first", "切回第一个项目")

    browser.close()
print(f"\n截图保存到 {SHOTS}")
