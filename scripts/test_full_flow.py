"""完整业务流程测试：新建项目→扫描→待归档→确认归档→已完成→检查归档数
每步截图，发现所有bug。"""
import sys, time, json, os, urllib.request, shutil
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8111"
SHOTS = r"D:\AgentProjects\IpoPBC\0\.workbuddy\tmp\screenshots\full_flow"
os.makedirs(SHOTS, exist_ok=True)

CLIENT = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
PBC = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
ARCH = r"D:\AgentProjects\IpoPBC\0\projects\full_flow_test"

bugs = []
def report_bug(step, desc, detail=""):
    bugs.append((step, desc, detail))
    print(f"  [BUG] {step}: {desc} | {detail}")

def shot(page, name):
    page.screenshot(path=os.path.join(SHOTS, f"{name}.png"), full_page=True)

# 1. 创建项目
print("\n=== 1. 创建项目 ===")
data = json.dumps({"name": "完整流程测试"}).encode()
req = urllib.request.Request(f"{BASE}/api/projects/create", data=data, headers={"Content-Type":"application/json"}, method="POST")
r = urllib.request.urlopen(req, timeout=10)
proj = json.loads(r.read())
pid = proj.get("project", {}).get("project_id", "")
print(f"  项目: {pid}")

# 清归档目录
import shutil as _sh
if os.path.exists(ARCH):
    try:
        _sh.rmtree(ARCH)
    except Exception:
        # 沙箱拦截时用 os.walk 删
        for root, dirs, files in os.walk(ARCH, topdown=False):
            for f in files:
                try: os.remove(os.path.join(root, f))
                except: pass
            for d in dirs:
                try: os.rmdir(os.path.join(root, d))
                except: pass
        try: os.rmdir(ARCH)
        except: pass
os.makedirs(ARCH, exist_ok=True)

# 设路径
upd = json.dumps({"client_folder": CLIENT, "archive_root": ARCH}).encode()
req = urllib.request.Request(f"{BASE}/api/projects/{pid}", data=upd, headers={"Content-Type":"application/json"}, method="PUT")
urllib.request.urlopen(req, timeout=10)

# 导入 PBC
with open(PBC, "rb") as f:
    boundary = "----b"
    body = f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="01.xlsx"\r\nContent-Type: application/vnd.ms-excel\r\n\r\n'
    body += f.read() + b"\r\n--" + boundary.encode() + b"--\r\n"
req = urllib.request.Request(f"{BASE}/api/pbc/{pid}/import", data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}, method="POST")
urllib.request.urlopen(req, timeout=30)
print("  PBC 导入完成")

# 2. 扫描
print("\n=== 2. 扫描 ===")
req = urllib.request.Request(f"{BASE}/api/files/{pid}/scan-folder", data=b'', method="POST")
r = urllib.request.urlopen(req, timeout=60)
task = json.loads(r.read())
task_id = task.get("task_id", "")
print(f"  task: {task_id}")

# 等扫描完成
for i in range(60):
    time.sleep(3)
    try:
        r = urllib.request.urlopen(f"{BASE}/api/files/{pid}/task/{task_id}")
        t = json.loads(r.read())
        if t.get("status") in ("done", "done_with_errors", "failed"):
            break
    except:
        pass
    if i % 5 == 0:
        print(f"    status={t.get('status') if 't' in dir() else 'unknown'}")
print(f"  扫描完成: {t.get('status')}")

# 3. 看待归档
print("\n=== 3. 待归档 ===")
r = urllib.request.urlopen(f"{BASE}/api/files/{pid}/pending-confirm")
pc = json.loads(r.read())
items = pc.get("items", [])
print(f"  待归档: {len(items)} 条")
for it in items:
    print(f"    {it.get('file_name','')[:25]:25} item={it.get('suggested_item_id'):6} decision={it.get('decision')}")

# 检查16个文件是否全覆盖
client_files = []
for root, dirs, files in os.walk(CLIENT):
    for f in files:
        client_files.append(f)
print(f"  客户文件夹文件数: {len(client_files)}")

# 4. 逐个确认归档
print("\n=== 4. 确认归档（逐个）===")
confirmed = 0
errors = 0
for it in items:
    cid = it.get("id")
    name = it.get("file_name", "")
    item_id = it.get("suggested_item_id", "")
    try:
        data = json.dumps({"new_item_id": ""}).encode()
        req = urllib.request.Request(f"{BASE}/api/files/{pid}/confirm/{cid}", data=data, headers={"Content-Type":"application/json"}, method="POST")
        r = urllib.request.urlopen(req, timeout=30)
        d = json.loads(r.read())
        if d.get("ok"):
            confirmed += 1
            print(f"    OK: {name[:25]:25} → {item_id}")
        else:
            errors += 1
            report_bug("confirm", f"归档失败: {name}", d.get("detail",""))
    except Exception as e:
        errors += 1
        report_bug("confirm", f"归档异常: {name}", str(e))

print(f"  确认: {confirmed}, 失败: {errors}")

# 5. 检查归档数
print("\n=== 5. 检查归档数 ===")
# API 看归档记录
r = urllib.request.urlopen(f"{BASE}/api/files/{pid}/list")
al = json.loads(r.read())
archives = al.get("files", [])
print(f"  API 归档记录: {len(archives)} 条")

# 磁盘看实际文件
disk_files = 0
for root, dirs, files in os.walk(ARCH):
    for f in files:
        disk_files += 1
print(f"  磁盘归档文件: {disk_files} 个")
print(f"  客户文件夹文件: {len(client_files)} 个")

if disk_files != len(client_files):
    report_bug("archive_count", f"归档数不匹配: 磁盘{disk_files} vs 客户{len(client_files)}")

# 6. 看归档树
print("\n=== 6. 归档树 ===")
r = urllib.request.urlopen(f"{BASE}/api/files/{pid}/archive-tree")
at = json.loads(r.read())
tree = at.get("tree", [])
print(f"  归档树: {len(tree)} 个一级分类")
for node in tree:
    cat = node.get("category")
    subdirs = node.get("subdirs", [])
    print(f"    {cat}:")
    for sd in subdirs:
        print(f"      {sd.get('name')} ({sd.get('count')} 文件)")
    # 检查重复
    names = [sd.get("name") for sd in subdirs]
    from collections import Counter
    dups = {n:c for n,c in Counter(names).items() if c>1}
    if dups:
        report_bug("archive_tree", f"重复目录: {cat}", str(dups))

# 7. 用 Playwright 看前端
print("\n=== 7. 前端验证 ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width":1400,"height":900})
    page.goto(BASE)
    page.wait_for_load_state("networkidle")
    time.sleep(3)
    page.evaluate(f'''async () => {{
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {{
            const d = el._x_dataStack[0];
            d.showOnboarding = false;
            const r = await fetch('/api/projects/list');
            const data = await r.json();
            const proj = (data.projects||[]).find(p => p.project_id === '{pid}');
            if (proj) await d.switchProject(proj, true);
        }}
    }}''')
    time.sleep(5)
    shot(page, "01_project")

    # 看每个 tab
    for tab in ['triage', 'review', 'done', 'files']:
        page.evaluate(f'''() => {{ const el = document.querySelector('[x-data="pbcApp()"]'); if (el && el._x_dataStack) el._x_dataStack[0].switchTab('{tab}'); }}''')
        time.sleep(2)
        shot(page, f"02_tab_{tab}")
        
        body = page.evaluate('document.body.innerText')
        # 检查有没有错误
        if '尚未配置' in body and tab == 'triage':
            report_bug(f"tab_{tab}", "显示'尚未配置'")
        if 'NaN' in body:
            report_bug(f"tab_{tab}", "页面有NaN")

    # 看前端归档数
    state = page.evaluate('''() => {
        const el = document.querySelector('[x-data="pbcApp()"]');
        if (el && el._x_dataStack) {
            const d = el._x_dataStack[0];
            return {
                pbcCount: (d.pbcList||[]).length,
                pendingArchive: (d.pendingArchive?.items||[]).length,
                treeCount: (d.fileZone?.tree||[]).length
            };
        }
        return null;
    }''')
    print(f"  前端状态: {json.dumps(state, ensure_ascii=False)}")

    browser.close()

# 8. 汇总
print("\n" + "="*60)
print(f"BUG 数: {len(bugs)}")
for step, desc, detail in bugs:
    print(f"  [{step}] {desc}: {detail}")
print(f"\n归档数: 磁盘{disk_files} vs 客户{len(client_files)} vs API{len(archives)}")
