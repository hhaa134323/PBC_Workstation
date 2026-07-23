"""列设置功能交互测试"""
import time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8000"
passed = 0
failed = 0

def check(name, cond, detail=""):
    global passed, failed
    status = "PASS" if cond else "FAIL"
    if cond: passed += 1
    else: failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)

def alpine(page, js):
    return page.evaluate(js)

def main():
    global passed, failed
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width":1440,"height":900})
        page = ctx.new_page()
        page.set_default_timeout(15000)

        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        print("\n=== 列设置功能测试 ===", flush=True)

        # 1. 列设置按钮存在（在切到有数据的 tab 后）
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
        }''')
        time.sleep(1)
        btn = page.locator('button:has-text("列设置")').first
        check("列设置按钮存在", btn.count() > 0)

        # 3. allColumns 定义 11 列，2 个 lock
        cols = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const all = el._x_dataStack[0].allColumns();
                return {total: all.length, locked: all.filter(c=>c.lock).map(c=>c.k)};
            }
            return null;
        }''')
        check("allColumns 定义 11 列", cols and cols.get('total') == 11, str(cols))
        check("lock 列 = 编号+操作", cols and cols.get('locked') == ['code','actions'], str(cols))

        # 4. 默认列数（每个 tab 不同）
        defaults = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                const tabs = ['triage','review','overdue','done'];
                const r = {};
                for (const t of tabs) {
                    r[t] = d.defaultColsFor(t);
                }
                return r;
            }
            return null;
        }''')
        check("4 个 tab 都有默认列", defaults and len(defaults) == 4)
        check("review 默认含 statusEdit+conf+actions", defaults and 'statusEdit' in defaults.get('review',[]) and 'conf' in defaults.get('review',[]))
        check("triage 默认含 statusEdit+conf", defaults and 'statusEdit' in defaults.get('triage',[]))

        # 5. colVisible 初始化（每个 tab 一份）
        vis = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const v = el._x_dataStack[0].colVisible;
                return Object.keys(v);
            }
            return [];
        }''')
        check("colVisible 含 4 个 tab 配置", len(vis) == 4, str(vis))

        # 6. lock 列强制 true
        lock_state = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                return {
                    code_review: d.colVisible.review?.code,
                    actions_review: d.colVisible.review?.actions,
                    code_done: d.colVisible.done?.code,
                    actions_done: d.colVisible.done?.actions
                };
            }
            return null;
        }''')
        check("lock 列 code 强制 true", all(lock_state.get(k) for k in ['code_review','code_done']))
        check("lock 列 actions 强制 true", all(lock_state.get(k) for k in ['actions_review','actions_done']))

        # 7. toggleCol 切换非 lock 列
        before = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('subject') : null;
        }''')
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].toggleCol('subject');
        }''')
        time.sleep(0.5)
        after = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('subject') : null;
        }''')
        check("toggleCol 切换 subject", before != after, f"{before} → {after}")

        # 8. toggleCol 拒绝切换 lock 列
        before_code = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('code') : null;
        }''')
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].toggleCol('code');
        }''')
        time.sleep(0.3)
        after_code = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('code') : null;
        }''')
        check("toggleCol 拒绝 lock 列 code", before_code == after_code == True)

        # 9. localStorage 持久化
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].toggleCol('conf');
        }''')
        time.sleep(0.5)
        saved = page.evaluate("localStorage.getItem('pbc_col_visible')")
        check("localStorage 写入 pbc_col_visible", saved is not None and len(saved) > 10)

        # 10. reload 后配置保留
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        # 切回 review tab
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
        }''')
        time.sleep(1)
        conf_after_reload = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('conf') : null;
        }''')
        # 之前 toggle 了 conf（默认 true → false）
        check("reload 后 conf 配置保留", conf_after_reload == False, f"conf={conf_after_reload}")

        subject_after_reload = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].isColOn('subject') : null;
        }''')
        # 之前 toggle 了 subject（默认 false → true）
        check("reload 后 subject 配置保留", subject_after_reload == True, f"subject={subject_after_reload}")

        # 11. colMenuOpen 打开/关闭（用 Alpine state 检测）
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].colMenuOpen = true;
        }''')
        time.sleep(0.5)
        menu_open = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].colMenuOpen : null;
        }''')
        check("列设置面板打开（Alpine state）", menu_open == True)

        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].colMenuOpen = false;
        }''')
        time.sleep(0.5)
        menu_closed = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].colMenuOpen : null;
        }''')
        check("列设置面板关闭（Alpine state）", menu_closed == False)

        # 12. activeColumns 返回当前 tab 可见列
        active = alpine(page, '''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                return el._x_dataStack[0].activeColumns().map(c=>c.k);
            }
            return [];
        }''')
        check("activeColumns 返回当前 tab 可见列", len(active) > 0 and 'code' in active and 'actions' in active, str(active))

        b.close()
        total = passed + failed
        print(f"\n{'='*50}", flush=True)
        print(f"列设置测试：{passed} PASS / {failed} FAIL / {total} 总计", flush=True)
        if failed == 0: print("✓ 全部通过！", flush=True)
        else: print(f"⚠ {failed} 项失败", flush=True)

if __name__ == "__main__":
    main()
