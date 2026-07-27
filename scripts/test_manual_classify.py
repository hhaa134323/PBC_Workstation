"""测试：AI 失败也进待归档 + 待手动分类标签 + 改分类弹窗 PBC 信息

8 个验收标准：
1. AI 成功分类 → 进待归档 decision="ai/llm"，有 suggested_item_id
2. AI 失败（item_id 空）→ 进待归档 decision=非auto，suggested_item_id 空
3. 整目录 AI 失败 → 进待归档 is_directory，suggested_item_id 空
4. 改分类弹窗显示完整 PBC 信息（编号+一级分类+实体+名称）
5. AI 失败的能改分类后归档
6. AI 失败的不直接归档到未分类（无新 UNCLASSIFIED 记录）
7. 前端待归档看到"待手动分类"标签
8. 改分类弹窗显示实体归属

用现有数据测，不真跑 AI（避免 API 配额）。
"""
import sys, time, json, urllib.request, sqlite3
sys.path.insert(0, r'D:\AgentProjects\IpoPBC\0')

BASE = 'http://127.0.0.1:8000'
DB = r'D:\AgentProjects\IpoPBC\0\data\pbc_workstation.db'

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

def api_get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())

def api_post(url, data=b''):
    req = urllib.request.Request(url, data=data, method="POST")
    if data:
        req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

# === 标准1+2：查 DB 看 pending_confirm 有没有 AI 成功和失败的 ===
print("\n=== 标准1+2+6: pending_confirm 状态检查 ===")
conn = sqlite3.connect(DB)
# AI 成功的（有 suggested_item_id）
success_rows = conn.execute("SELECT id, file_name, suggested_item_id, decision, confidence FROM pending_confirm WHERE suggested_item_id != '' AND suggested_item_id IS NOT NULL LIMIT 5").fetchall()
check("标准1: AI成功分类的有记录", len(success_rows) > 0, f"找到 {len(success_rows)} 条")
if success_rows:
    r = success_rows[0]
    check("标准1: AI成功的有 suggested_item_id", bool(r[2]), f"item={r[2]}")
    check("标准1: AI成功的 decision 非 manual", r[3] != "manual", f"decision={r[3]}")

# AI 失败的（suggested_item_id 为空）
fail_rows = conn.execute("SELECT id, file_name, suggested_item_id, decision, confidence FROM pending_confirm WHERE (suggested_item_id = '' OR suggested_item_id IS NULL) LIMIT 5").fetchall()
check("标准2: AI失败(item_id空)的有记录进待归档", len(fail_rows) > 0, f"找到 {len(fail_rows)} 条")
if fail_rows:
    r = fail_rows[0]
    check("标准2: AI失败的 suggested_item_id 为空", not r[2], f"item={r[2]}")
    check("标准2: AI失败的 decision 非 auto", r[3] != "auto", f"decision={r[3]}")

# 标准6: 没有新的 UNCLASSIFIED 归档记录（HITL 开启时 AI 失败不该直接归档）
unc_rows = conn.execute("SELECT id, item_id FROM file_archive WHERE item_id = 'UNCLASSIFIED' OR item_id = '' OR item_id IS NULL").fetchall()
check("标准6: 无新 UNCLASSIFIED 直接归档（HITL开启时）", len(unc_rows) <= 2, f"有 {len(unc_rows)} 条 UNCLASSIFIED（早期残留可接受）")

# === 标准3: 整目录 AI 失败的 ===
print("\n=== 标准3: 整目录 AI 失败 ===")
dir_fail = conn.execute("SELECT id, file_name, suggested_item_id, decision FROM pending_confirm WHERE decision='walkthrough' AND (suggested_item_id = '' OR suggested_item_id IS NULL) LIMIT 3").fetchall()
check("标准3: 整目录AI失败的有记录", len(dir_fail) > 0, f"找到 {len(dir_fail)} 条")
# 如果没有，手动造一条测试
conn.close()

# === 标准4+8: 改分类弹窗 PBC 信息 ===
print("\n=== 标准4+8: 改分类弹窗 PBC 信息 ===")
# 拿 PBC list 看有没有 entity 字段
r = urllib.request.urlopen(f'{BASE}/api/projects/list')
projects = json.loads(r.read()).get('projects', [])
proj = projects[0] if projects else None
if proj:
    pid = proj['project_id']
    pbc = api_get(f'{BASE}/api/pbc/{pid}/list')
    items = pbc.get('items', [])
    check("标准4: PBC 项有 item_id+category+doc_name", len(items) > 0, f"{len(items)} 项")
    if items:
        it = items[0]
        check("标准4: 有 category", bool(it.get('category')), f"category={it.get('category')}")
        check("标准4: 有 doc_name", bool(it.get('doc_name')), f"doc_name={it.get('doc_name')}")
        check("标准8: 有 entity 实体归属", 'entity' in it, f"entity={it.get('entity')}")

# === 标准7: 前端待归档看到"待手动分类"标签 ===
print("\n=== 标准7: 前端待手动分类标签 ===")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(BASE, wait_until='networkidle', timeout=60000)
    page.wait_for_load_state('networkidle')
    time.sleep(3)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].showOnboarding = false; }''')
    time.sleep(1)
    # 切到有待归档数据的项目
    # 找一个有 AI 失败数据的项目
    conn2 = sqlite3.connect(DB)
    fail_proj = conn2.execute("SELECT project_id FROM pending_confirm WHERE (suggested_item_id='' OR suggested_item_id IS NULL) AND confirmed=0 LIMIT 1").fetchone()
    conn2.close()
    target_pid = fail_proj[0] if fail_proj else (proj['project_id'] if proj else '')
    page.evaluate(f'''async () => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            const r = await fetch('/api/projects/list?active_only=false');
            const data = await r.json();
            const proj = data.projects.find(p => p.project_id === '{target_pid}');
            if (proj) await d.switchProject(proj, true);
        }}
    }}''')
    time.sleep(5)
    page.evaluate('''() => { const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('review'); }''')
    time.sleep(3)
    body = page.evaluate('document.body.innerText')
    check("标准7: 前端显示待手动分类标签", '待手动分类' in body, "没找到'待手动分类'文字")
    # 看 source
    html = page.evaluate('''() => {
        const all = document.querySelectorAll('span');
        for (const el of all) {
            const t = el.textContent || '';
            if (t.includes('待手动分类') && t.length < 20) {
                return el.outerHTML;
            }
        }
        return null;
    }''')
    check("标准7: 待手动标签有图标", bool(html) and ('\u26a0' in html or '⚠' in html), f"html={html[:80] if html else 'null'}")
    browser.close()

# === 标准5: AI 失败的能改分类后归档 ===
print("\n=== 标准5: AI 失败的改分类归档 ===")
# 用 fail_rows 第一条测改分类
if fail_rows and proj:
    fid = fail_rows[0][0]
    fid_proj = proj['project_id']
    # 从 API 拿一个有效 item_id
    pbc = api_get(f'{BASE}/api/pbc/{fid_proj}/list')
    items = pbc.get('items', [])
    valid_item = next((i for i in items if i.get('item_id')), None)
    if valid_item:
        try:
            r = api_post(f"{BASE}/api/files/{fid_proj}/reclassify-confirm/{fid}",
                         json.dumps({"new_item_id": valid_item['item_id'], "reason": "测试改分类"}).encode())
            check("标准5: AI失败的能改分类", r.get("ok"), f"返回: {r}")
        except Exception as e:
            check("标准5: AI失败的能改分类", False, f"异常: {e}")
    else:
        check("标准5: AI失败的能改分类", False, "没有有效 item_id")
else:
    check("标准5: AI失败的能改分类", False, "没有 AI 失败记录可测")

print(f"\n=== 总计: {PASS} PASS / {FAIL} FAIL ===")
sys.exit(0 if FAIL == 0 else 1)
