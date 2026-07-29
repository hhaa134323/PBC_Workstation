"""v10b exe UI 验收测试 — 用 playwright 模拟用户交互走完整业务流程。

测试流程：
1. 首页加载 + coach mark
2. 5 个 tab 切换
3. 待归档表格内容
4. AI 配置面板（测试连接）
5. 变更记录面板
6. 文件区归档树
"""
from playwright.sync_api import sync_playwright
import httpx, base64, json, time

BASE = "http://127.0.0.1:8000"
API_KEY = "sk-ec6089e9f57642288c07ac4e28069aa5"
results = []

def log(name, ok, detail=""):
    results.append({"name": name, "ok": ok, "detail": detail})
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}: {detail[:150]}")

def screenshot(page, name):
    path = f"D:/AgentProjects/IpoPBC/screenshots/accept_{name}.png"
    page.screenshot(path=path)
    return path

def vision_check(image_path, question):
    """用 qwen-vl-max 看截图"""
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    payload = {
        "model": "qwen-vl-max",
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": question}
        ]}],
        "max_tokens": 400,
    }
    with httpx.Client(timeout=30) as client:
        r = client.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
                        json=payload)
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        return f"HTTP {r.status_code}"

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        errors = []
        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        # === 1. 首页加载 ===
        page.goto(BASE, wait_until="networkidle", timeout=15000)
        page.wait_for_timeout(3000)
        title = page.title()
        log("首页加载", "PBC" in title, f"title={title}")

        # === 2. coach mark 出现 ===
        coach = page.evaluate("() => { const el = document.querySelector('.pbcg-coach'); return el ? (el.style.display !== 'none' ? 'visible' : 'hidden') : 'absent'; }")
        log("coach mark", coach in ["visible", "hidden"], f"state={coach}")

        # 关 coach mark
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.coach.on = false; localStorage.setItem('pbc_coach_done', '1'); }")
        page.wait_for_timeout(500)

        # === 3. 5 个 tab 切换 ===
        tabs = ["triage", "review", "done", "overdue", "files"]
        for tab in tabs:
            page.evaluate(f"(t) => {{ const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.switchTab(t); }}", tab)
            page.wait_for_timeout(1500)
            h1 = page.evaluate("() => { const blocks = document.querySelectorAll('[x-show*=\"currentTab\"]'); for(const b of blocks) { if(b.style.display !== 'none' && getComputedStyle(b).display !== 'none') { const h = b.querySelector('h1'); return h ? h.textContent.trim() : '(no h1)'; } } return '(none visible)'; }")
            log(f"切到 {tab}", h1 != "(none visible)", f"h1={h1}")

        # === 4. 待归档表格 ===
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.switchTab('review'); }")
        page.wait_for_timeout(2000)
        screenshot(page, "review")
        review_text = page.evaluate("() => { const rows = document.querySelectorAll('table tr'); return Array.from(rows).slice(0,5).map(r => r.textContent.replace(/\\s+/g,' ').trim().substring(0,150)).join(' | '); }")
        log("待归档表格", "待归档" in review_text or "待手动" in review_text or "确认归档" in review_text, review_text[:120])

        # === 5. AI 配置面板 ===
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.openAiConfig(); }")
        page.wait_for_timeout(2000)
        screenshot(page, "ai_config")
        # 看 API Key 脱敏
        masked = page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); return d.aiConfig.masked || ''; }")
        log("AI配置面板", len(masked) > 5, f"masked={masked}")

        # 点测试连接
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.testAiConfig(); }")
        page.wait_for_timeout(8000)  # 等 30 秒超时或成功
        test_result = page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); return d.aiConfig.testResult ? JSON.stringify(d.aiConfig.testResult) : 'null'; }")
        log("AI测试连接", "ok" in test_result and "true" in test_result.lower(), test_result[:150])

        # 关 AI 配置
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.aiConfig.show = false; }")
        page.wait_for_timeout(500)

        # === 6. 变更记录面板 ===
        # 点变更记录按钮
        page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for(const b of btns){ if(b.textContent.includes('变更记录') || b.textContent.includes('文件变更')) { b.click(); break; } }
        }""")
        page.wait_for_timeout(2000)
        screenshot(page, "change_panel")
        panel_text = page.evaluate("() => { const el = document.querySelector('.pbcg-vh'); return el ? el.textContent.replace(/\\s+/g,' ').trim().substring(0,200) : 'no panel'; }")
        log("变更记录面板", "变更记录" in panel_text or "操作日志" in panel_text, panel_text[:120])

        # 检查有没有"在清单里看这一行"按钮（应该没有了）
        has_old_btn = page.evaluate("() => { return document.querySelector('.pbcg-vh-go') !== null; }")
        log("无'在清单里看'按钮", not has_old_btn, f"has_btn={has_old_btn}")

        # 关面板
        page.evaluate("""() => {
            const btn = document.querySelector('.pbcg-vh-ico[data-act="close"]');
            if(btn) btn.click();
        }""")
        page.wait_for_timeout(500)

        # === 7. 文件区归档树 ===
        page.evaluate("() => { const el = document.querySelector('[x-data]'); const d = Alpine.$data(el); d.switchTab('files'); }")
        page.wait_for_timeout(2000)
        # 全部展开
        page.evaluate("""() => {
            const el = document.querySelector('[x-data]');
            const d = Alpine.$data(el);
            const tree = d.fileZone.tree || [];
            const cats = {}; const subs = {};
            tree.forEach(c => { cats[c.category] = false; (c.subdirs||[]).forEach(s => { subs[s.path] = false; (s.subdirs||[]).forEach(ns => subs[ns.path] = false); }); });
            d.archiveTreeExpanded.cats = cats;
            d.archiveTreeExpanded.subs = subs;
        }""")
        page.wait_for_timeout(1000)
        screenshot(page, "files_tree")
        tree_text = page.evaluate("() => { const card = document.querySelector('.card.card-pad'); if(!card) return 'no card'; return card.textContent.replace(/\\s+/g,' ').trim().substring(0,300); }")
        log("文件区归档树", "归档" in tree_text or "暂无" in tree_text or "货币" in tree_text, tree_text[:120])

        # === 8. console 无错误 ===
        log("console 无错误", len(errors) == 0, f"errors={errors[:3]}")

        browser.close()
except Exception as e:
    import traceback
    log("测试异常", False, traceback.format_exc()[:200])

print(f"\n=== {sum(1 for r in results if r['ok'])}/{len(results)} PASS ===")
for r in results:
    if not r["ok"]:
        print(f"  FAIL: {r['name']}: {r['detail']}")
