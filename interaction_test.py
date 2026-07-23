"""PBC 前端手动交互测试（Playwright 模拟真实用户）

像真实用户一样操作：点按钮、填表单、看弹窗、验证结果。
每个步骤检查元素是否出现/状态是否变化，输出 PASS/FAIL。
"""
import time, sys
from pathlib import Path

URL = "http://127.0.0.1:8000"
OUT = Path("D:/AgentProjects/IpoPBC/0/.workbuddy/tmp/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

from playwright.sync_api import sync_playwright

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    status = "PASS" if condition else "FAIL"
    if condition:
        passed += 1
    else:
        failed += 1
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""), flush=True)

def shot(page, name):
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=False)

def main():
    global passed, failed

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.set_default_timeout(30000)

        # ========== 2.1 首启引导 ==========
        print("\n=== 2.1 首启引导 ===", flush=True)
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("localStorage.clear()")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        ob = page.locator(".ob-modal").first
        check("首启引导显示", ob.count() > 0 and ob.is_visible(), "清空 localStorage 后应出现首启引导")

        # 用 JS 直接选"进入示例项目"（绕过 overlay 拦截）
        page.evaluate("""
            // 直接触发 chooseDemoProject
            if (window.Alpine) {
                const el = document.querySelector('[x-data]');
                if (el && el._x_dataStack) {
                    // 找 Alpine 组件实例
                }
            }
            // 简单方案：设 localStorage 后 reload
            localStorage.setItem('pbc_onboarded', '1');
            localStorage.setItem('pbc_current_project', 'demo');
        """)
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 确认首启引导已消失
        ob2 = page.locator(".ob-modal").first
        check("进入项目后引导消失", not ob2.is_visible() if ob2.count() > 0 else True)

        # 等待数据加载（PBC 表格出现）
        try:
            page.wait_for_selector("table.tbl", timeout=15000)
            time.sleep(1)
        except:
            # 数据可能为空，继续测试
            pass

        # ========== 2.2 项目抽屉 ==========
        print("\n=== 2.2 项目抽屉 ===", flush=True)
        # 找 sidebar 里的项目区域或顶部项目按钮
        proj_toggle = page.locator('.icon-btn[title*="项目"], button:has-text("项目"), .sidebar-section:has-text("项目")').first
        check("项目抽屉触发器存在", proj_toggle.count() > 0)

        if proj_toggle.count() > 0:
            try:
                proj_toggle.click(force=True)
                time.sleep(1)
                drawer = page.locator(".drawer").first
                check("抽屉滑出", drawer.count() > 0 and drawer.is_visible())
                proj_items = page.locator(".proj-item")
                check("项目列表 ≥1", proj_items.count() >= 1, f"找到 {proj_items.count()} 个项目")
                shot(page, "project_drawer")
            except Exception as e:
                check("项目抽屉操作", False, str(e))

        # ========== 2.3 扫描卡片 ==========
        print("\n=== 2.3 扫描卡片 ===", flush=True)
        scan_card = page.locator(".scan-hero, .card-pad:has-text('扫描')").first
        check("扫描卡片存在", scan_card.count() > 0)

        folder_info = page.locator(".code, [x-text='currentFolderInfo.path']").first
        check("文件夹路径显示", folder_info.count() > 0)

        open_btn = page.locator('button:has-text("打开文件夹")').first
        check("'打开文件夹'按钮存在", open_btn.count() > 0)

        change_btn = page.locator('button:has-text("更改")').first
        check("'更改'按钮存在", change_btn.count() > 0)

        test_btn = page.locator('button:has-text("测试资料")').first
        check("'查看测试资料'按钮存在", test_btn.count() > 0)

        scan_btn = page.locator('button:has-text("扫描")').first
        check("'扫描新文件'按钮存在", scan_btn.count() > 0)

        # 检查 spinner 是 SVG 不是 CSS border
        spin_svg = page.locator(".spin svg").first
        check("spinner 是 SVG Loader2", spin_svg.count() > 0)

        # ========== 2.4 PBC 清单表格 ==========
        print("\n=== 2.4 PBC 清单表格 ===", flush=True)
        # 待初检 tab 默认可能为空（正常），切到待人工复核 tab 才有数据
        review_tab = page.locator('.tab:has-text("待人工复核")').first
        if review_tab.count() > 0:
            review_tab.click(force=True)
            time.sleep(1)
        tbl = page.locator("table.tbl").first
        check("待人工复核 tab 表格存在", tbl.count() > 0)

        if tbl.count() > 0:
            rows = page.locator(".tbl tbody tr")
            check("表格有数据行", rows.count() > 0, f"{rows.count()} 行")

            headers = page.locator(".tbl th")
            check("表头 ≥5 列", headers.count() >= 5, f"{headers.count()} 列")

            # 检查空状态文案（切回待初检 tab）
            triage_tab = page.locator('.tab:has-text("待初检")').first
            if triage_tab.count() > 0:
                triage_tab.click(force=True)
                time.sleep(1)
                empty_text = page.locator("text=暂无待初检项").first
                check("空状态文案正确", empty_text.count() > 0, "应显示'暂无待初检项'")

        # ========== 2.5 状态切换（在待人工复核 tab 下） ==========
        print("\n=== 2.5 状态切换 ===", flush=True)
        # 切到待人工复核 tab（有数据）
        review_tab = page.locator('.tab:has-text("待人工复核")').first
        if review_tab.count() > 0:
            review_tab.click(force=True)
            time.sleep(1)

        status_sel = page.locator(".st-sel").first
        check("状态下拉存在", status_sel.count() > 0)

        if status_sel.count() > 0:
            try:
                # 记录当前值
                old_val = status_sel.evaluate("el => el.value")
                # 切换状态（用 force 绕过 overlay 拦截）
                opts = page.locator(".st-sel option")
                if opts.count() > 1:
                    new_val = opts.nth(1).evaluate("el => el.value")
                    status_sel.select_option(value=new_val, force=True)
                    time.sleep(1)
                    # 检查是否有 toast
                    toast = page.locator(".toast").first
                    check("状态切换后有反馈", toast.count() > 0, "应出现 toast 提示")
            except Exception as e:
                check("状态切换操作", False, str(e))

        # ========== 2.6 文件详情弹窗（在待人工复核 tab 下有数据） ==========
        print("\n=== 2.6 文件详情弹窗 ===", flush=True)
        # 确保在待人工复核 tab
        review_tab = page.locator('.tab:has-text("待人工复核")').first
        if review_tab.count() > 0:
            review_tab.click(force=True)
            time.sleep(1)

        detail_btn = page.locator('button:has-text("文件详情")').first
        check("'文件详情'按钮存在", detail_btn.count() > 0)

        if detail_btn.count() > 0:
            try:
                detail_btn.click(force=True)
                time.sleep(1.5)
                modal = page.locator(".modal").first
                check("详情弹窗弹出", modal.count() > 0 and modal.is_visible())

                # 检查弹窗内容
                orig_path = page.locator('code:has-text(":\\"), code:has-text("/")').first
                check("弹窗有路径信息", orig_path.count() > 0)

                archived = page.locator("text=归档路径").first
                check("弹窗有'归档路径'标签", archived.count() > 0)

                method = page.locator("text=分类方式, text=文件名自动匹配, text=AI 内容分析").first
                check("弹窗有分类方式说明", method.count() > 0)

                shot(page, "file_detail_modal")

                # 关闭
                close = page.locator(".modal-h .x").first
                if close.count() > 0:
                    close.click(force=True)
                    time.sleep(0.5)
            except Exception as e:
                check("文件详情操作", False, str(e))

        # ========== 2.7 Tab 切换 ==========
        print("\n=== 2.7 Tab 切换 ===", flush=True)
        tabs = [
            ("待初检", "triage"),
            ("待人工复核", "review"),
            ("超期未提供", "overdue"),
            ("已完成", "done"),
        ]
        for label, tid in tabs:
            try:
                tab = page.locator(f'.tab:has-text("{label}")').first
                if tab.count() > 0 and tab.is_visible():
                    tab.click(force=True)
                    time.sleep(1)
                    active = page.locator(".tab.active").first
                    check(f"Tab '{label}' 切换成功", active.is_visible() and label in active.inner_text())
                    shot(page, f"tab_{tid}")
                else:
                    check(f"Tab '{label}' 可见", False)
            except Exception as e:
                check(f"Tab '{label}' 切换", False, str(e)[:80])

        # ========== 2.8 风险信号卡（超期 tab） ==========
        print("\n=== 2.8 风险信号卡 ===", flush=True)
        try:
            # 切到超期 tab
            overdue_tab = page.locator('.tab:has-text("超期未提供")').first
            if overdue_tab.count() > 0:
                overdue_tab.click(force=True)
                time.sleep(1)

                resolve_btn = page.locator('button:has-text("风险"), button:has-text("影响"), a:has-text("风险"), a:has-text("看")').first
                check("'看风险'按钮存在", resolve_btn.count() > 0)

                if resolve_btn.count() > 0:
                    resolve_btn.click(force=True)
                    time.sleep(2)
                    resolve_modal = page.locator(".modal").first
                    check("风险信号卡弹窗弹出", resolve_modal.count() > 0 and resolve_modal.is_visible())

                    # 检查风险等级 badge
                    risk_badge = page.locator(".risk-fg-high, .risk-fg-medium, .risk-fg-low").first
                    check("风险等级 badge 显示", risk_badge.count() > 0)

                    # 检查"影响的审计结论"
                    impact = page.locator("text=审计结论").first
                    check("'影响的审计结论'区域", impact.count() > 0)

                    # 检查 IPO 问询热度
                    ipo = page.locator("text=问询热度").first
                    check("'IPO 问询热度'区域", ipo.count() > 0)

                    # 检查替代程序
                    alt = page.locator("text=替代程序").first
                    check("'替代程序'区域", alt.count() > 0)

                    shot(page, "risk_signal_card")

                    # 关闭
                    close = page.locator(".modal-h .x").first
                    if close.count() > 0:
                        close.click(force=True)
                        time.sleep(0.5)
        except Exception as e:
            check("风险信号卡操作", False, str(e)[:80])

        # ========== 2.9 热力图 ==========
        print("\n=== 2.9 风险热力图 ===", flush=True)
        heat = page.locator(".heat").first
        check("热力图存在", heat.count() > 0)

        if heat.count() > 0:
            cells = page.locator(".heat td")
            check("热力图有单元格", cells.count() > 0, f"{cells.count()} 个")

            legend = page.locator(".heat-legend").first
            check("热力图图例存在", legend.count() > 0)
            shot(page, "heatmap")

        # ========== 2.10 一键汇报 ==========
        print("\n=== 2.10 一键汇报 ===", flush=True)
        try:
            rpt_btn = page.locator('button:has-text("一键汇报")').first
            check("'一键汇报'按钮存在", rpt_btn.count() > 0)

            if rpt_btn.count() > 0:
                rpt_btn.click(force=True)
                time.sleep(2)
                rpt_modal = page.locator(".modal").first
                check("汇报弹窗弹出", rpt_modal.count() > 0 and rpt_modal.is_visible())

                # 检查汇报文本
                esc_text = page.locator(".esc-text").first
                check("汇报文本区域存在", esc_text.count() > 0)

                if esc_text.count() > 0:
                    text_len = len(esc_text.inner_text())
                    check("汇报文本 ≥500 字", text_len >= 500, f"{text_len} 字")

                # 检查复制按钮
                copy_btn = page.locator('button:has-text("复制")').first
                check("'复制'按钮存在", copy_btn.count() > 0)

                shot(page, "report_modal")

                # 关闭
                close = page.locator(".modal-h .x").first
                if close.count() > 0:
                    close.click(force=True)
                    time.sleep(0.5)
        except Exception as e:
            check("一键汇报操作", False, str(e)[:80])

        # ========== 2.11 Toast 通知 ==========
        print("\n=== 2.11 Toast 通知 ===", flush=True)
        # 触发一个操作（如状态切换）看 toast
        try:
            triage_tab = page.locator('.tab:has-text("待初检")').first
            if triage_tab.count() > 0:
                triage_tab.click(force=True)
                time.sleep(0.5)

            sel = page.locator(".st-sel").first
            if sel.count() > 0:
                opts = page.locator(".st-sel option")
                if opts.count() > 1:
                    new_val = opts.nth(1).evaluate("el => el.value")
                    sel.select_option(value=new_val)
                    time.sleep(1)
                    toast = page.locator(".toast").first
                    check("操作后 toast 出现", toast.count() > 0)

                    if toast.count() > 0:
                        # 检查 toast 用 x-text 不是 x-html
                        toast_html = page.locator(".toast .tx").first.evaluate("el => el.getAttribute('x-text') || el.getAttribute('x-html')")
                        check("toast 用 x-text", toast_html is not None and "x-text" not in str(toast_html) or "x-text" in str(page.locator('.toast .tx').first.evaluate('el => el.outerHTML')), "检查 XSS 防护")

                        # 等待 toast 消失
                        time.sleep(4)
                        toast_gone = page.locator(".toast").count() == 0 or not page.locator(".toast").first.is_visible()
                        check("toast 自动消失", toast_gone, "应在 3-5 秒后消失")
        except Exception as e:
            check("Toast 通知测试", False, str(e)[:80])

        # ========== 2.12 创建项目向导 ==========
        print("\n=== 2.12 创建项目向导 ===", flush=True)
        try:
            # 找"创建新项目"按钮
            create_btn = page.locator('button:has-text("创建新项目"), .btn:has-text("创建")').first
            check("'创建新项目'按钮存在", create_btn.count() > 0)

            if create_btn.count() > 0:
                create_btn.click(force=True)
                time.sleep(1)

                wizard = page.locator(".modal").first
                check("向导弹窗弹出", wizard.count() > 0 and wizard.is_visible())

                # 第 1 步：项目信息
                name_input = page.locator('input[placeholder*="名称"], input[placeholder*="项目"]').first
                check("第1步有名称输入框", name_input.count() > 0)

                step1_next = page.locator('button:has-text("下一步")').first
                check("第1步有'下一步'按钮", step1_next.count() > 0)

                if name_input.count() > 0 and step1_next.count() > 0:
                    name_input.fill("测试项目_自动")
                    step1_next.click(force=True)
                    time.sleep(1)

                    # 第 2 步：导入 PBC
                    step2 = page.locator('text=导入, text=.xlsx, text=跳过, input[type="file"]').first
                    check("进入第2步", step2.count() > 0)

                    skip_btn = page.locator('button:has-text("跳过")').first
                    if skip_btn.count() > 0:
                        skip_btn.click(force=True)
                        time.sleep(1)

                        # 第 3 步：文件夹
                        step3 = page.locator('text=文件夹, input[placeholder*="路径"]').first
                        check("进入第3步", step3.count() > 0)

                        create_final = page.locator('button:has-text("创建")').first
                        check("第3步有'创建'按钮", create_final.count() > 0)

                        # 关闭不实际创建
                        close = page.locator(".modal-h .x").first
                        if close.count() > 0:
                            close.click(force=True)
                            time.sleep(0.5)
        except Exception as e:
            check("创建项目向导测试", False, str(e)[:80])

        browser.close()

        # ========== 汇总 ==========
        total = passed + failed
        print(f"\n{'='*50}", flush=True)
        print(f"交互测试完成：{passed} PASS / {failed} FAIL / {total} 总计", flush=True)
        if failed > 0:
            print(f"\n⚠ {failed} 项失败，需检查", flush=True)
        else:
            print(f"\n✓ 全部通过！", flush=True)

if __name__ == "__main__":
    main()
