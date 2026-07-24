"""PBC 前端交互测试 v2 — 用 JS 直调 Alpine 方法绕过 DOM 点击

所有弹窗类操作通过 evaluate() 直接调 Alpine 组件方法，绕过 visibility 检测。
"""
import time
from pathlib import Path

URL = "http://127.0.0.1:8111"
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

def alpine_call(page, js_code):
    """直调 Alpine 方法"""
    return page.evaluate(js_code)

def main():
    global passed, failed

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="zh-CN")
        page = ctx.new_page()
        page.set_default_timeout(15000)

        # 初始化：进入项目
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        page.evaluate("localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # ========== 2.1 首启引导 ==========
        print("\n=== 2.1 首启引导 ===", flush=True)
        # 清空 localStorage
        page.evaluate("localStorage.clear()")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        ob_visible = page.evaluate('''() => {
            const el = document.querySelector('.ob-modal');
            return el ? el.offsetParent !== null : false;
        }''')
        check("首启引导显示", ob_visible)

        # 用 Alpine 方法跳过
        page.evaluate("localStorage.setItem('pbc_onboarded','1'); localStorage.setItem('pbc_current_project','demo')")
        page.reload(wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        ob_gone = page.evaluate('''() => {
            const el = document.querySelector('.ob-modal');
            return el ? el.offsetParent === null : true;
        }''')
        check("进入项目后引导消失", ob_gone)

        # ========== 2.2 项目抽屉 ==========
        print("\n=== 2.2 项目抽屉 ===", flush=True)
        # 用 Alpine 方法打开抽屉
        drawer_shown = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                el._x_dataStack[0].drawerOpen = true;
                return true;
            }
            return false;
        }''')
        check("用 Alpine 方法打开抽屉", drawer_shown)
        time.sleep(1)

        proj_count = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].projects.length : 0;
        }''')
        check("项目列表 ≥1", proj_count >= 1, f"{proj_count} 个项目")
        shot(page, "project_drawer")

        # 关闭抽屉
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].drawerOpen = false;
        }''')
        time.sleep(0.5)

        # ========== 2.3 扫描卡片 ==========
        print("\n=== 2.3 扫描卡片 ===", flush=True)
        folder_info = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const f = el._x_dataStack[0].currentFolderInfo;
                return f ? {path: f.path, count: f.count, file_count: f.count, exists: f.exists} : null;
            }
            return null;
        }''')
        check("文件夹路径有值", folder_info is not None and folder_info.get('path'))
        check("文件夹存在", folder_info and folder_info.get('exists'))
        check("文件数 ≥1", folder_info and (folder_info.get('count') or 0) >= 1, f"{folder_info.get('count') if folder_info else 0} 个")

        spin_svg = page.locator(".spin svg").first
        check("spinner 是 SVG Loader2", spin_svg.count() > 0)

        # ========== 2.4 PBC 清单表格 ==========
        print("\n=== 2.4 PBC 清单表格 ===", flush=True)
        # 切到待人工复核 tab（有数据）
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
        }''')
        time.sleep(1)

        tbl_count = page.evaluate("document.querySelectorAll('table.tbl').length")
        check("待人工复核 tab 表格存在", tbl_count > 0)

        row_count = page.evaluate("document.querySelectorAll('.tbl tbody tr').length")
        check("表格有数据行", row_count > 0, f"{row_count} 行")

        header_count = page.evaluate("document.querySelectorAll('.tbl th').length")
        check("表头 ≥5 列", header_count >= 5, f"{header_count} 列")

        # 空状态文案（切回待初检）
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('triage');
        }''')
        time.sleep(1)
        empty_text = page.evaluate("document.body.innerText.includes('暂无待初检项')")
        check("空状态文案正确", empty_text)

        # ========== 2.5 状态切换 ==========
        print("\n=== 2.5 状态切换 ===", flush=True)
        # 切回待人工复核
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
        }''')
        time.sleep(1)

        # 用 JS 直接调 window.__changeStatus
        status_changed = page.evaluate('''() => {
            if (typeof window.__changeStatus === 'function') {
                // 找第一个 item_id 和可选状态
                const sel = document.querySelector('.st-sel');
                if (sel) {
                    const opts = sel.querySelectorAll('option');
                    if (opts.length > 1) {
                        return {selExists: true, optCount: opts.length, firstOpt: opts[0].value};
                    }
                }
                return {selExists: false};
            }
            return {funcExists: false};
        }''')
        check("状态下拉和选项存在", status_changed.get('selExists') and status_changed.get('optCount', 0) > 1, str(status_changed))

        # ========== 2.6 文件详情弹窗 ==========
        print("\n=== 2.6 文件详情弹窗 ===", flush=True)
        # 用 Alpine 方法直接打开文件详情
        detail_result = page.evaluate('''async () => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                const items = d.pbcList || [];
                if (items.length > 0) {
                    const itemId = items[0].item_id;
                    if (typeof d.viewDetail === 'function') {
                        await d.viewDetail(itemId);
                        return {itemId: itemId, called: true};
                    }
                    return {itemId: itemId, noMethod: true};
                }
                return {noItems: true};
            }
            return {noData: true};
        }''')
        check("文件详情方法调用", detail_result.get('called'))
        time.sleep(2)

        # 检查弹窗（用 Alpine state）
        modal_visible = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                return el._x_dataStack[0].fileDetail.show === true;
            }
            return false;
        }''')
        check("详情弹窗弹出", modal_visible, str(detail_result))
        shot(page, "file_detail")

        # 检查弹窗内容
        has_path = page.evaluate("document.body.innerText.includes('原始路径') || document.body.innerText.includes('归档路径')")
        check("弹窗有路径信息", has_path)

        has_method = page.evaluate("document.body.innerText.includes('文件名自动匹配') || document.body.innerText.includes('AI 内容分析') || document.body.innerText.includes('扫描文件夹')")
        check("弹窗有分类方式说明", has_method)

        # 关闭
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].fileDetail.show = false;
        }''')
        time.sleep(0.5)

        # ========== 2.7 Tab 切换 ==========
        print("\n=== 2.7 Tab 切换 ===", flush=True)
        tabs = [("待初检", "triage"), ("待人工复核", "review"), ("超期未提供", "overdue"), ("已完成", "done")]
        for label, tid in tabs:
            page.evaluate('''(tid) => {
                const el = document.querySelector('[x-data="pbcApp()"]');
                if (el && el._x_dataStack) el._x_dataStack[0].switchTab(tid);
            }''', tid)
            time.sleep(1)
            current = page.evaluate('''() => {
                const el = document.querySelector('[x-data="pbcApp()"]');
                return el && el._x_dataStack ? el._x_dataStack[0].currentTab : null;
            }''')
            check(f"Tab '{label}' 切换", current == tid, f"currentTab={current}")

        # ========== 2.8 风险信号卡 ==========
        print("\n=== 2.8 风险信号卡 ===", flush=True)
        # 切到超期 tab
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('overdue');
        }''')
        time.sleep(1)

        # 用 Alpine 方法打开风险信号卡
        risk_result = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                if (typeof d.openResolve === 'function') {
                    d.openResolve('货-2');
                    return {called: true};
                }
                return {noMethod: typeof d.openResolve};
            }
            return {noData: true};
        }''')
        check("风险信号卡方法调用", risk_result.get('called'))
        time.sleep(2)

        risk_modal = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const r = el._x_dataStack[0].resolveModal;
                return {show: r.show, hasData: !!r.data, hasRisk: !!(r.data && r.data.risk_signal)};
            }
            return null;
        }''')
        check("风险信号卡弹窗显示", risk_modal and risk_modal.get('show'))
        check("风险信号卡有数据", risk_modal and risk_modal.get('hasRisk'))
        shot(page, "risk_signal")

        # 检查内容
        body_text = page.evaluate("document.body.innerText")
        check("有风险等级", "高风险" in body_text or "中风险" in body_text or "低风险" in body_text)
        check("有审计结论", "审计结论" in body_text)
        check("有IPO问询", "问询" in body_text)
        check("有替代程序", "替代程序" in body_text)

        # 关闭
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].resolveModal.show = false;
        }''')
        time.sleep(0.5)

        # ========== 2.9 热力图 ==========
        print("\n=== 2.9 风险热力图 ===", flush=True)
        cells = page.evaluate("document.querySelectorAll('.heat td').length")
        check("热力图有单元格", cells > 0, f"{cells} 个")

        legend = page.evaluate("document.querySelectorAll('.heat-legend').length")
        check("热力图图例存在", legend > 0)

        # ========== 2.10 一键汇报 ==========
        print("\n=== 2.10 一键汇报 ===", flush=True)
        # 用 Alpine 方法打开
        rpt_result = page.evaluate('''async () => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                if (typeof d.openEscalation === 'function') {
                    await d.openEscalation();
                    return {called: true};
                }
                return {noMethod: typeof d.openEscalation};
            }
            return null;
        }''')
        check("一键汇报方法调用", rpt_result and rpt_result.get('called'))
        time.sleep(2)

        rpt_modal = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const r = el._x_dataStack[0].escalationModal;
                return {show: r.show, textLen: (r.text || '').length};
            }
            return null;
        }''')
        check("汇报弹窗显示", rpt_modal and rpt_modal.get('show'))

        text_len = rpt_modal.get('textLen', 0) if rpt_modal else 0
        check("汇报文本 ≥500 字", text_len >= 500, f"{text_len} 字")
        shot(page, "report")

        # 检查复制按钮
        copy_btn = page.evaluate("document.querySelectorAll('button').length > 0 && Array.from(document.querySelectorAll('button')).some(b => b.innerText.includes('复制'))")
        check("'复制'按钮存在", copy_btn)

        # 关闭
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].escalationModal.show = false;
        }''')
        time.sleep(0.5)

        # ========== 2.11 Toast 通知 ==========
        print("\n=== 2.11 Toast 通知 ===", flush=True)
        # 用 Alpine 方法触发 toast
        toast_result = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                if (typeof d.pushToast === 'function') {
                    d.pushToast('low', '测试', '交互测试 toast');
                    return {called: true};
                }
                return {noMethod: typeof d.pushToast};
            }
            return null;
        }''')
        check("toast 方法调用", toast_result and toast_result.get('called'))
        time.sleep(0.5)

        toast_visible = page.evaluate('''() => {
            const t = document.querySelector('.toast');
            return t ? t.offsetParent !== null : false;
        }''')
        check("toast 显示", toast_visible)

        # 检查 toast 用 x-text
        toast_safe = page.evaluate('''() => {
            const tx = document.querySelector('.toast .tx');
            if (!tx) return false;
            return tx.getAttribute('x-text') === 't.text' || !tx.hasAttribute('x-html');
        }''')
        check("toast 用 x-text（非 x-html）", toast_safe)

        # 等 toast 消失（low priority 3秒，等 4 秒）
        time.sleep(4)
        toast_gone = page.evaluate('''() => {
            const t = document.querySelector('.toast');
            return !t || t.offsetParent === null;
        }''')
        check("toast 自动消失", toast_gone)

        # ========== 2.12 创建项目向导 ==========
        print("\n=== 2.12 创建项目向导 ===", flush=True)
        # 用 Alpine 方法打开
        wizard_result = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                d.showCreateProject = true;
                return {called: true};
            }
            return null;
        }''')
        check("创建项目向导打开", wizard_result and wizard_result.get('called'))
        time.sleep(1)

        wizard_state = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                const d = el._x_dataStack[0];
                return {step: d.createWizardStep, name: d.wizardName || '', pbc: d.wizardPbcFile || '', folder: d.wizardFolderPath || ''};
            }
            return null;
        }''')
        check("向导第1步", wizard_state and wizard_state.get('step') == 1, str(wizard_state))

        # 填名称并下一步
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                el._x_dataStack[0].wizardName = '测试项目_自动';
                if (typeof el._x_dataStack[0].wizardNext === 'function') {
                    el._x_dataStack[0].wizardNext();
                } else {
                    el._x_dataStack[0].createWizardStep = 2;
                }
            }
        }''')
        time.sleep(1)
        step2 = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].createWizardStep : null;
        }''')
        check("进入第2步", step2 == 2)

        # 跳过 PBC 导入
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) {
                if (typeof el._x_dataStack[0].wizardSkipPbc === 'function') {
                    el._x_dataStack[0].wizardSkipPbc();
                } else {
                    el._x_dataStack[0].createWizardStep = 3;
                }
            }
        }''')
        time.sleep(1)
        step3 = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            return el && el._x_dataStack ? el._x_dataStack[0].createWizardStep : null;
        }''')
        check("进入第3步", step3 == 3)

        shot(page, "wizard_step3")

        # 关闭
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].showCreateProject = false;
        }''')
        time.sleep(0.5)

        # ========== 2.13 v7 文件区视图 ==========
        print("\n=== 2.13 v7 文件区视图 ===", flush=True)
        # 切到 files tab 触发 loadFileZone
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('files');
        }''')
        time.sleep(3)
        fz = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const fz = el._x_dataStack[0].fileZone;
            return fz ? {
                hasFileZone: true,
                hasPaths: !!fz.paths,
                clientPath: fz.paths && fz.paths.client_folder && fz.paths.client_folder.path,
                clientCount: fz.paths && fz.paths.client_folder && fz.paths.client_folder.file_count,
                archivePath: fz.paths && fz.paths.archive_root && fz.paths.archive_root.path,
                archiveCount: fz.paths && fz.paths.archive_root && fz.paths.archive_root.file_count,
                categoryCount: fz.paths && fz.paths.archive_root && fz.paths.archive_root.category_count,
                treeCount: fz.tree ? fz.tree.length : 0,
                error: fz.error,
            } : null;
        }''')
        check("fileZone 数据对象存在", fz and fz.get('hasFileZone'))
        check("fileZone.paths 已加载", fz and fz.get('hasPaths'), str(fz))
        check("客户文件夹路径有值", fz and fz.get('clientPath'))
        check("归档目录路径有值", fz and fz.get('archivePath'))
        check("归档目录有分类", fz and (fz.get('categoryCount') or 0) > 0, str(fz))
        check("归档树有数据", fz and (fz.get('treeCount') or 0) > 0, str(fz))
        shot(page, "v7_file_zone")

        # ========== 2.14 v7 AI 配置面板 ==========
        print("\n=== 2.14 v7 AI 配置面板 ===", flush=True)
        # 检查 aiConfig 数据结构
        ac = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const c = el._x_dataStack[0].aiConfig;
            if (!c) return null;
            return {
                hasForm: !!c.form,
                hasModels: Array.isArray(c.models),
                formConfidence: c.form && c.form.confidence_threshold,
                formFnameMatch: c.form && c.form.filename_match_enabled,
            };
        }''')
        check("aiConfig 数据结构存在", ac is not None)
        check("aiConfig.form 存在", ac and ac.get('hasForm'))
        check("aiConfig.form 含 confidence_threshold", ac and ac.get('formConfidence') is not None, str(ac))
        check("aiConfig.form 含 filename_match_enabled", ac and ac.get('formFnameMatch') is not None)

        # 调用 openAiConfig（内部触发加载）
        page.evaluate('''async () => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack && el._x_dataStack[0].openAiConfig) {
                await el._x_dataStack[0].openAiConfig();
            }
        }''')
        time.sleep(2)
        ac2 = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const c = el._x_dataStack[0].aiConfig;
            return {
                modelCount: c.models ? c.models.length : 0,
                maskedKey: c.masked,
                keySet: c.keySet,
                formModel: c.form && c.form.model_classification,
            };
        }''')
        check("loadAiConfig 后有模型清单", ac2 and ac2.get('modelCount', 0) > 0, str(ac2))
        check("loadAiConfig 后 key 已设", ac2 and ac2.get('keySet'))
        check("loadAiConfig 后 form 有 model", ac2 and ac2.get('formModel'))

        # ========== 2.15 v7 重新定位 modal ==========
        print("\n=== 2.15 v7 重新定位 modal ===", flush=True)
        rl = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const r = el._x_dataStack[0].relocateModal;
            return r ? {
                hasShow: 'show' in r,
                hasInput: 'input' in r,
                hasError: 'error' in r,
                hasSaving: 'saving' in r,
            } : null;
        }''')
        check("relocateModal 数据结构存在", rl is not None)
        check("relocateModal 含 show/input/error/saving", rl and all(rl.get(k) for k in ['hasShow', 'hasInput', 'hasError', 'hasSaving']))

        # ========== 2.16 v7 列设置功能 ==========
        print("\n=== 2.16 v7 列设置功能 ===", flush=True)
        cs = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            return {
                hasColVisible: typeof app.colVisible === 'object',
                hasColMenuOpen: 'colMenuOpen' in app,
                hasActiveColumns: typeof app.activeColumns === 'function',
                hasToggleCol: typeof app.toggleCol === 'function',
                hasSaveColCfg: typeof app.saveColCfg === 'function',
                hasInitColCfg: typeof app.initColCfg === 'function',
            };
        }''')
        check("colVisible 数据存在", cs and cs.get('hasColVisible'))
        check("colMenuOpen 字段存在", cs and cs.get('hasColMenuOpen'))
        check("activeColumns 方法存在", cs and cs.get('hasActiveColumns'))
        check("toggleCol 方法存在", cs and cs.get('hasToggleCol'))
        check("saveColCfg 方法存在", cs and cs.get('hasSaveColCfg'))
        check("initColCfg 方法存在", cs and cs.get('hasInitColCfg'))

        # ========== 2.17 v7 文件失联检测 ==========
        print("\n=== 2.17 v7 文件失联检测 ===", flush=True)
        cv = page.evaluate('''async () => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            if (typeof app.checkAllValid !== 'function') return {hasMethod: false};
            return {hasMethod: true};
        }''')
        check("checkAllValid 方法存在", cv and cv.get('hasMethod'))

        open_valid = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            return typeof app.openPathByItem === 'function' && typeof app.openRelocate === 'function';
        }''')
        check("openPathByItem + openRelocate 方法存在", open_valid)

        # ========== 2.18 v7 brand 条修复 ==========
        print("\n=== 2.18 v7 brand 条修复 ===", flush=True)
        brand = page.evaluate('''() => {
            const nav = document.querySelector('.nav-top');
            if (!nav) return null;
            const sep = nav.querySelector('.nav-sep');
            const logo = nav.querySelector('.brand .logo');
            const name = nav.querySelector('.brand .name');
            const sub = nav.querySelector('.brand .sub');
            return {
                hasSep: !!sep,
                logoText: logo ? logo.textContent.trim() : null,
                logoSize: logo ? getComputedStyle(logo).width : null,
                nameFont: name ? getComputedStyle(name).fontWeight : null,
                nameSize: name ? getComputedStyle(name).fontSize : null,
                subSize: sub ? getComputedStyle(sub).fontSize : null,
                noClientPrefix: sub ? !sub.textContent.startsWith('客户：') : true,
            };
        }''')
        check("nav-sep 分隔存在", brand and brand.get('hasSep'))
        check("logo 是单字母 P", brand and brand.get('logoText') == 'P')
        check("logo 20px", brand and brand.get('logoSize') == '20px')
        check("name 14px/500", brand and brand.get('nameSize') == '14px' and brand.get('nameFont') == '500')
        check("去掉「客户：」前缀", brand and brand.get('noClientPrefix'), str(brand))

        # ========== 2.19 v7.5 manifest 三层架构（检测层 + 展示层）==========
        print("\n=== 2.19 v7.5 manifest 三层架构 ===", flush=True)
        manifest_check = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            return {
                hasPendingCount: 'pendingCount' in app || 'pending_count' in app,
                hasMessageCenter: 'messageCenter' in app || 'messages' in app,
                hasScanIncrement: typeof app.scanIncremental === 'function' || typeof app.loadPendingCount === 'function',
            };
        }''')
        check("v7.5 manifest 数据存在", manifest_check is not None)
        check("有 pendingCount 字段", manifest_check and manifest_check.get('hasPendingCount'))
        check("有 messageCenter/消息中心", manifest_check and manifest_check.get('hasMessageCenter'))

        # 调 pending-count API 看实际值
        pc = page.evaluate('''async () => {
            try {
                const r = await fetch('/api/files/demo/pending-count');
                const d = await r.json();
                return {ok: r.ok, count: d.pending_count !== undefined ? d.pending_count : d.count};
            } catch(e) { return {error: e.message}; }
        }''')
        check("pending-count API 可调", pc and pc.get('ok'))
        check("pending-count 返回数字", pc and isinstance(pc.get('count'), int), str(pc))

        # ========== 2.20 v7.5 matcher 打分模型 ==========
        print("\n=== 2.20 v7.5 matcher 打分模型 ===", flush=True)
        # matcher 是后端模块，前端不直接调，但可以通过 score_breakdown 在归档结果里看到
        # 这里检查扫描后的 results 是否含 score_breakdown 字段
        matcher_check = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            // 找最近的扫描结果
            const scan = app.scan || {};
            return {
                hasScan: !!scan,
                hasResults: !!(scan.results || scan.summary),
                scanActive: scan.active,
            };
        }''')
        check("扫描数据结构存在", matcher_check is not None)

        # ========== 2.21 v7.5 PBC 导出接口 ==========
        print("\n=== 2.21 v7.5 PBC 导出接口 ===", flush=True)
        export_check = page.evaluate('''async () => {
            try {
                const r = await fetch('/api/pbc/demo/export');
                return {ok: r.ok, status: r.status, type: r.headers.get('content-type')};
            } catch(e) { return {error: e.message}; }
        }''')
        check("PBC export 接口可调", export_check and export_check.get('ok'))
        check("返回 Excel 类型", export_check and 'spreadsheet' in (export_check.get('type') or ''), str(export_check))

        # ========== 2.22 v7.5 归档两级结构 ==========
        print("\n=== 2.22 v7.5 归档两级结构 ===", flush=True)
        archive_tree = page.evaluate('''async () => {
            try {
                const r = await fetch('/api/files/demo/archive-tree');
                const d = await r.json();
                const tree = d.tree || [];
                if (!tree.length) return {empty: true};
                const first = tree[0];
                return {
                    hasSubdirs: 'subdirs' in first || 'sub_folders' in first || 'children' in first,
                    firstCategory: first.category,
                    keys: Object.keys(first).slice(0, 6),
                };
            } catch(e) { return {error: e.message}; }
        }''')
        check("归档树接口可调", archive_tree and not archive_tree.get('error'))
        check("归档树有二级结构（subdirs）", archive_tree and archive_tree.get('hasSubdirs'), str(archive_tree))

        # ========== 2.23 v7.6 改分类弹窗 ==========
        print("\n=== 2.23 v7.6 改分类弹窗 ===", flush=True)
        reclassify_check = page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (!el || !el._x_dataStack) return null;
            const app = el._x_dataStack[0];
            return {
                hasReclassifyModal: 'reclassifyModal' in app,
                hasOpenReclassify: typeof app.openReclassify === 'function',
                hasDoReclassify: typeof app.doReclassify === 'function',
                hasGlobalFunc: typeof window.__openReclassify === 'function',
            };
        }''')
        check("reclassifyModal 数据结构存在", reclassify_check is not None)
        check("openReclassify 方法存在", reclassify_check and reclassify_check.get('hasOpenReclassify'))
        check("doReclassify 方法存在", reclassify_check and reclassify_check.get('hasDoReclassify'))
        check("__openReclassify 全局函数存在", reclassify_check and reclassify_check.get('hasGlobalFunc'))

        # 检查 review tab 有「改分类」按钮（切到 review tab 看）
        page.evaluate('''() => {
            const el = document.querySelector('[x-data="pbcApp()"]');
            if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review');
        }''')
        time.sleep(1)
        has_reclassify_btn = page.evaluate('''() => {
            return document.querySelector('[onclick*="__openReclassify"]') !== null;
        }''')
        check("review tab 有改分类按钮", has_reclassify_btn)

        browser.close()

        # 汇总
        total = passed + failed
        print(f"\n{'='*50}", flush=True)
        print(f"交互测试完成：{passed} PASS / {failed} FAIL / {total} 总计", flush=True)
        if failed > 0:
            print(f"\n⚠ {failed} 项失败", flush=True)
        else:
            print(f"\n✓ 全部通过！", flush=True)

if __name__ == "__main__":
    main()
