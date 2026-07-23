"""PBC 前端交互测试 + 截图 v2

用 Playwright 模拟用户操作，截图验证关键页面。
选择器基于实际 HTML 结构，避免文本匹配歧义。
"""
import time, sys
from pathlib import Path

URL = "http://127.0.0.1:8000"
OUT = Path("D:/AgentProjects/IpoPBC/0/.workbuddy/tmp/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

from playwright.sync_api import sync_playwright

def shot(page, name, full_page=True):
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=full_page)
    print(f"  ✓ {name}", flush=True)
    return p

def click_tab(page, tab_text):
    """点 tab 按钮（用 .tab class + 内部文本）"""
    try:
        tab = page.locator('.tab:has-text("%s")' % tab_text).first
        if tab.count() > 0 and tab.is_visible():
            tab.click()
            time.sleep(1.5)
            return True
    except Exception as e:
        print(f"  Tab {tab_text} 失败: {e}", flush=True)
    return False

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.set_default_timeout(8000)

        # 1. 首页（先设 localStorage 跳过首启引导）
        print("1. 首页加载", flush=True)
        page.goto(URL, wait_until="domcontentloaded")
        # 清掉首启引导标记，让它不弹
        page.evaluate("localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo');")
        page.reload(wait_until="domcontentloaded")
        time.sleep(3)
        shot(page, "01_home")

        # 2. 已进入项目（localStorage 跳过首启引导）
        print("2. 已进入项目", flush=True)
        shot(page, "02_in_project")

        # 3. Tab 切换（4 个 tab）
        tabs = ["待初检", "待人工复核", "超期未提供", "已完成"]
        for i, tab_name in enumerate(tabs, 3):
            print(f"{i}. Tab: {tab_name}", flush=True)
            if click_tab(page, tab_name):
                shot(page, f"{i:02d}_tab_{tab_name}")
            else:
                print(f"  跳过", flush=True)

        # 7. 项目抽屉
        print("7. 项目抽屉", flush=True)
        try:
            # sidebar 里的"项目"section 或顶部按钮
            proj = page.locator('.sidebar-section:has-text("项目"), .icon-btn:has-text("项目")').first
            if proj.count() == 0:
                # 尝试点击项目相关元素
                proj = page.locator('text=项目').first
            if proj.count() > 0 and proj.is_visible():
                proj.click()
                time.sleep(1)
                shot(page, "07_project_drawer")
        except Exception as e:
            print(f"  {e}", flush=True)

        # 8. 文件详情弹窗
        print("8. 文件详情", flush=True)
        try:
            # 先回待初检 tab
            click_tab(page, "待初检")
            detail = page.locator('button:has-text("文件详情"), a:has-text("文件详情")').first
            if detail.count() > 0 and detail.is_visible():
                detail.click()
                time.sleep(1.5)
                shot(page, "08_file_detail")
                # 关闭
                page.locator(".modal-h .x").first.click()
                time.sleep(0.5)
        except Exception as e:
            print(f"  {e}", flush=True)

        # 9. 扫描卡片区域特写
        print("9. 扫描卡片", flush=True)
        try:
            scan = page.locator(".scan-hero").first
            if scan.count() > 0:
                # 截区域图
                scan.screenshot(path=str(OUT / "09_scan_card.png"))
                print(f"  ✓ 09_scan_card", flush=True)
        except Exception as e:
            print(f"  {e}", flush=True)

        # 10. 风险热力图（超期 tab 下）
        print("10. 热力图", flush=True)
        try:
            click_tab(page, "超期未提供")
            heat = page.locator(".heat").first
            if heat.count() > 0:
                heat.screenshot(path=str(OUT / "10_heatmap.png"))
                print(f"  ✓ 10_heatmap", flush=True)
        except Exception as e:
            print(f"  {e}", flush=True)

        # 11. 一键汇报
        print("11. 一键汇报", flush=True)
        try:
            rpt = page.locator('button:has-text("一键汇报")').first
            if rpt.count() > 0 and rpt.is_visible():
                rpt.click()
                time.sleep(2)
                shot(page, "11_report", full_page=False)
        except Exception as e:
            print(f"  {e}", flush=True)

        # 12. 整页（回到默认 tab）
        print("12. 整页截图", flush=True)
        try:
            click_tab(page, "待初检")
            shot(page, "12_full_page")
        except Exception as e:
            print(f"  {e}", flush=True)

        browser.close()
        print(f"\n✓ 全部完成，保存到 {OUT}", flush=True)

if __name__ == "__main__":
    main()
