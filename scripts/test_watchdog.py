"""watchdog 验收测试：客户加文件/改文件/删文件，watchdog 是否自动追踪+前端展示"""
import sys, time, json, os, urllib.request, shutil as _sh
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")

BASE = "http://127.0.0.1:8111"
CLIENT = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
PBC = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
ARCH = r"D:\AgentProjects\IpoPBC\0\projects\watchdog_test_" + str(int(time.time()))

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    s = "PASS" if ok else "FAIL"
    print(f"[{s}] {name}: {detail}")

def api_post(url, data=b''):
    req = urllib.request.Request(url, data=data, method="POST")
    if data: req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def api_put(url, data):
    req = urllib.request.Request(url, data=data.encode(), method="PUT")
    req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def api_get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())

def get_pending_count(pid):
    return api_get(f"{BASE}/api/files/{pid}/pending-count").get("pending_count", 0)

def get_briefing_events(pid, since=0):
    return api_get(f"{BASE}/api/files/briefing-events?since={since}&project_id={pid}").get("events", [])

def safe_remove(path):
    import subprocess
    try: subprocess.run(["powershell","-Command",f"Remove-Item -Force '{path}'"],check=True,timeout=10,capture_output=True)
    except:
        try: os.remove(path)
        except: pass

# === 准备项目 ===
print("\n=== 准备项目 ===")
proj = api_post(f"{BASE}/api/projects/create", json.dumps({"name": "watchdog测试"}).encode())
pid = proj.get("project", {}).get("project_id", "")
os.makedirs(ARCH, exist_ok=True)
api_put(f"{BASE}/api/projects/{pid}", json.dumps({"client_folder": CLIENT, "archive_root": ARCH}))
with open(PBC, "rb") as f:
    boundary = "----b"
    body = f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="01.xlsx"\r\nContent-Type: application/vnd.ms-excel\r\n\r\n'
    body += f.read() + b"\r\n--" + boundary.encode() + b"--\r\n"
req = urllib.request.Request(f"{BASE}/api/pbc/{pid}/import", data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}, method="POST")
urllib.request.urlopen(req, timeout=30)
print(f"项目: {pid}")

# 先扫描一次把现有文件归档
print("\n=== 先扫描+归档所有 ===")
r = api_post(f"{BASE}/api/files/{pid}/scan-folder")
task_id = r.get("task_id", "")
if task_id:
    for i in range(60):
        time.sleep(3)
        t = api_get(f"{BASE}/api/files/{pid}/task/{task_id}")
        if t.get("status") in ("done","done_with_errors","failed"):
            break
items = api_get(f"{BASE}/api/files/{pid}/pending-confirm").get("items", [])
for it in items:
    try:
        api_post(f"{BASE}/api/files/{pid}/confirm/{it['id']}", json.dumps({"new_item_id": it.get("suggested_item_id","")}).encode())
    except: pass
print(f"已归档 {len(items)} 条")

# === 场景1：客户加新文件 → watchdog 是否自动检测到 ===
print("\n=== 场景1：客户加新文件 ===")
new_file = os.path.join(CLIENT, f"watchdog测试_新增_{int(time.time())}.xlsx")
_sh.copy2(os.path.join(CLIENT, "销-1_销售合同台账.xlsx"), new_file)
print(f"  加了: {os.path.basename(new_file)}")

# 等 watchdog 检测（最多30秒）
detected = False
for i in range(15):
    time.sleep(2)
    pc = get_pending_count(pid)
    events = get_briefing_events(pid)
    if pc > 0 or any("watchdog测试" in e.get("summary","") for e in events):
        detected = True
        print(f"  {i*2}秒后检测到: pending_count={pc}, events={len(events)}")
        break
check("watchdog自动检测新文件", detected, f"{'检测到' if detected else '30秒没检测到'}")

# === 场景2：客户改文件 → watchdog 是否检测到 ===
print("\n=== 场景2：客户改文件 ===")
# 找一个已归档的散文件，修改它
archives = api_get(f"{BASE}/api/files/{pid}/list").get("files", [])
modified = False
for a in archives:
    orig = a.get("original_path", "")
    if orig and os.path.exists(orig) and not a.get("is_directory") and orig.endswith(".pdf"):
        # 修改文件内容
        with open(orig, "ab") as f:
            f.write(b"\nmodified by watchdog test")
        print(f"  改了: {os.path.basename(orig)}")
        modified = True
        break

if modified:
    detected = False
    for i in range(15):
        time.sleep(2)
        events = get_briefing_events(pid)
        pc = get_pending_count(pid)
        # watchdog 检测到修改应该标 pending 或有事件
        if pc > 0:
            detected = True
            print(f"  {i*2}秒后检测到: pending_count={pc}")
            break
    check("watchdog自动检测文件修改", detected, f"{'检测到' if detected else '30秒没检测到'}")

# === 场景3：客户删文件 → watchdog 是否检测到 ===
print("\n=== 场景3：客户删文件 ===")
# 找一个已归档的散文件删掉
deleted = False
for a in archives:
    orig = a.get("original_path", "")
    if orig and os.path.exists(orig) and not a.get("is_directory"):
        safe_remove(orig)
        print(f"  删了: {os.path.basename(orig)}")
        deleted = True
        break

if deleted:
    detected = False
    for i in range(15):
        time.sleep(2)
        events = get_briefing_events(pid)
        has_missing = any(e.get("event_type") == "file_missing" for e in events)
        if has_missing:
            detected = True
            print(f"  {i*2}秒后检测到 file_missing 事件")
            break
    check("watchdog自动检测文件删除", detected, f"{'检测到' if detected else '30秒没检测到'}")

# === 场景4：前端是否能看到变化 ===
print("\n=== 场景4：前端展示 ===")
# 看 pending_count 是否反映了变化
pc = get_pending_count(pid)
print(f"  pending_count={pc}")
check("前端pending_count更新", pc > 0, f"pending_count={pc}")

# 清理
safe_remove(new_file)

# === 汇总 ===
print("\n" + "="*60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"总计: {total} 项, PASS {passed}, FAIL {failed}")
for name, ok, detail in results:
    if not ok:
        print(f"  [FAIL] {name}: {detail}")
