# -*- coding: utf-8 -*-
'''
真驱动 UI 的前端冒烟测试。

为什么需要它:
  scripts/test_hitl_full_flow.py 名字叫 Playwright 交互测试, 但 11 个步骤的业务动作
  全部是 urllib 直连后端, page 对象只做 goto / screenshot / evaluate 塞变量,
  一次真实点击都没有。scripts/regression_v7.py 的前端检查是 'fileZone' in html
  这种纯字符串包含, 不执行 JS 不渲染 DOM。
  结果就是: 前端整个白屏, 两套测试依然全绿。

这个脚本相反, 只要前端 JS 报错 / 白屏 / Alpine 起不来 / tab 点了炸, 就会 FAIL。

用法 (Windows 11):
  pip install playwright
  playwright install chromium
  set PBC_TEST_BASE=http://127.0.0.1:8000
  set PBC_TEST_PROJECT=demo
  python scripts/smoke_frontend.py

想看着它点, 加 set PBC_TEST_HEADED=1
'''
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('PBC_TEST_BASE', 'http://127.0.0.1:8000').rstrip('/')
PROJECT = os.environ.get('PBC_TEST_PROJECT', 'demo')
HEADED = os.environ.get('PBC_TEST_HEADED', '0') == '1'

js_errors = []
console_errors = []
failed_requests = []
bad_responses = []
results = []


def check(name, ok, detail=''):
    results.append((name, bool(ok), detail))
    flag = 'PASS' if ok else 'FAIL'
    line = '  [' + flag + '] ' + name
    if detail:
        line = line + '  ->  ' + detail
    print(line)
    return bool(ok)


def _print_list(title, items):
    print(title + ': ' + str(len(items)) + ' 条')
    for i, e in enumerate(items, 1):
        print('  ' + str(i) + '. ' + str(e)[:500])


def dump():
    print('')
    print('=' * 68)
    _print_list('JS 运行时异常 pageerror', js_errors)
    _print_list('console.error', console_errors)
    _print_list('网络请求失败 requestfailed', failed_requests)
    _print_list('4xx / 5xx 响应', bad_responses)
    print('=' * 68)
    passed = sum(1 for r in results if r[1])
    print('用例 ' + str(passed) + ' / ' + str(len(results)) + ' 通过')
    if passed != len(results):
        print('')
        print('失败项:')
        for name, ok, detail in results:
            if not ok:
                print('  - ' + name + ('  ' + detail if detail else ''))


JS_ALPINE_STATE = '''() => {
  const el = document.querySelector('[x-data]');
  if (!el) return { found: false, inited: false, keys: [] };
  const st = el._x_dataStack;
  if (!st || !st[0]) return { found: true, inited: false, keys: [] };
  return { found: true, inited: true, keys: Object.keys(st[0]).slice(0, 80) };
}'''

JS_TAB_LABELS = '''() => {
  const out = [];
  document.querySelectorAll('button, a, div, li, span').forEach(el => {
    const at = el.getAttribute('@click') || el.getAttribute('x-on:click') || '';
    if (at.indexOf('switchTab') >= 0) {
      const t = (el.innerText || '').trim();
      if (t && t.length <= 20 && out.indexOf(t) < 0) out.push(t);
    }
  });
  return out;
}'''

JS_BODY_LEN = '''() => (document.body.innerText || '').trim().length'''


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not HEADED)
        page = browser.new_page(viewport={'width': 1600, 'height': 1000})

        page.on('pageerror', lambda e: js_errors.append(str(e)))
        page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)
        page.on('requestfailed', lambda r: failed_requests.append(r.url + ' :: ' + str(r.failure)))
        page.on('response', lambda r: bad_responses.append(str(r.status) + ' ' + r.url) if r.status >= 400 else None)

        print('BASE    = ' + BASE)
        print('PROJECT = ' + PROJECT)
        print('')

        # 1. 首页能不能打开
        try:
            page.goto(BASE, wait_until='networkidle', timeout=60000)
            check('首页可打开', True)
        except Exception as e:
            check('首页可打开', False, str(e))
            dump()
            browser.close()
            sys.exit(1)

        page.wait_for_timeout(3000)

        # 2. CDN 依赖有没有加载成功 (tailwind / alpine 挂了就整页白屏)
        cdn_failed = [u for u in failed_requests if 'tailwind' in u or 'alpinejs' in u or 'cdn' in u]
        check('CDN 依赖全部加载成功', len(cdn_failed) == 0, '; '.join(cdn_failed[:3]))

        # 3. 页面不是白屏
        body_len = page.evaluate(JS_BODY_LEN)
        check('页面有可见文本 (非白屏)', body_len > 200, 'innerText 长度 ' + str(body_len))

        # 4. Alpine 真的初始化了, 不是只在 HTML 里出现过字符串
        st = page.evaluate(JS_ALPINE_STATE)
        check('找到 x-data 根节点', bool(st.get('found')))
        alpine_ok = check('Alpine 组件真实初始化', bool(st.get('inited')))
        if alpine_ok:
            print('        state keys: ' + ', '.join(st.get('keys') or []))

        # 5. 按钮渲染出来了
        try:
            btn = page.locator('button:visible').count()
        except Exception:
            btn = 0
        check('有可见按钮渲染', btn >= 3, '可见按钮 ' + str(btn) + ' 个')

        # Alpine 没起来就别往下点了, 直接把报错倒出来
        if not alpine_ok:
            print('')
            print('Alpine 没有初始化, 后面的交互没有意义。下面是全部 JS 报错:')
            dump()
            try:
                page.screenshot(path='smoke_frontend_fail.png', full_page=True)
                print('截图已存 smoke_frontend_fail.png')
            except Exception:
                pass
            browser.close()
            sys.exit(1)

        # 6. 首屏加载完之后有没有攒下 JS 错误
        check('首屏无 JS 运行时异常', len(js_errors) == 0, '; '.join(js_errors[:2]))
        check('首屏无 console.error', len(console_errors) == 0, '; '.join(console_errors[:2]))
        first_bad = list(bad_responses)
        check('首屏无 4xx / 5xx 接口', len(first_bad) == 0, '; '.join(first_bad[:3]))

        # 7. 逐个点 tab, 比对点击前后的错误增量
        labels = page.evaluate(JS_TAB_LABELS)
        check('识别到 tab 入口', len(labels) > 0, '找到 ' + str(len(labels)) + ' 个: ' + ', '.join(labels))

        for label in labels:
            before_js = len(js_errors)
            before_console = len(console_errors)
            before_bad = len(bad_responses)
            try:
                page.click('text=' + label, timeout=8000)
                page.wait_for_timeout(1800)
            except Exception as e:
                check('点击 tab [' + label + ']', False, str(e)[:200])
                continue

            new_js = js_errors[before_js:]
            new_console = console_errors[before_console:]
            new_bad = bad_responses[before_bad:]
            detail = ''
            if new_js:
                detail = 'JS: ' + new_js[0][:200]
            elif new_console:
                detail = 'console: ' + new_console[0][:200]
            elif new_bad:
                detail = 'HTTP: ' + new_bad[0][:200]
            check('点击 tab [' + label + '] 无新增报错',
                  not new_js and not new_console and not new_bad, detail)

            # 切过去之后这块区域是不是真的渲染了东西
            seg = page.evaluate(JS_BODY_LEN)
            check('tab [' + label + '] 有内容渲染', seg > 200, 'innerText 长度 ' + str(seg))

        # 8. 留一张全页截图, 人眼过一遍
        try:
            page.screenshot(path='smoke_frontend.png', full_page=True)
            print('')
            print('全页截图已存 smoke_frontend.png')
        except Exception as e:
            print('截图失败: ' + str(e))

        dump()
        browser.close()

        if any(not r[1] for r in results):
            sys.exit(1)


if __name__ == '__main__':
    main()
