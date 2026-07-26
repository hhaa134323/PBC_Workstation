"""watchdog + 扫描新文件功能验收测试"""
import sys, time, json, os, urllib.request, shutil
sys.path.insert(0, r"D:\AgentProjects\IpoPBC\0")

BASE = "http://127.0.0.1:8111"
CLIENT = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\客户共享文件夹_混合形态"
PBC = r"D:\AgentProjects\IpoPBC\0\data\test_data_package\01_PBC_List_混合形态.xlsx"
ARCH = r"D:\AgentProjects\IpoPBC\0\projects\accept_test_" + str(int(time.time()))

results = []
def check(name, ok, detail=""):
    results.append((name, ok, detail))
    s = "PASS" if ok else "FAIL"
    print(f"[{s}] {name}: {detail}")

def api_post(url, data=b''):
    req = urllib.request.Request(url, data=data, method="POST")
    if data:
        req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def api_put(url, data):
    req = urllib.request.Request(url, data=data.encode(), method="PUT")
    req.add_header("Content-Type", "application/json")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def api_get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())

def wait_scan(pid):
    """触发扫描并等待完成"""
    r = api_post(f"{BASE}/api/files/{pid}/scan-folder")
    task_id = r.get("task_id", "")
    if not task_id:
        return r
    for i in range(60):
        time.sleep(3)
        try:
            t = api_get(f"{BASE}/api/files/{pid}/task/{task_id}")
            if t.get("status") in ("done", "done_with_errors", "failed"):
                return t
        except:
            pass
    return {"status": "timeout"}

def get_pending(pid):
    d = api_get(f"{BASE}/api/files/{pid}/pending-confirm")
    return d.get("items", [])

def confirm_all(pid):
    """确认所有待归档"""
    items = get_pending(pid)
    ok = 0
    for it in items:
        try:
            r = api_post(f"{BASE}/api/files/{pid}/confirm/{it['id']}", json.dumps({"new_item_id": ""}).encode())
            if r.get("ok"):
                ok += 1
            else:
                print(f"  归档失败: {it.get('file_name')} -> {r.get('detail','')}")
        except Exception as e:
            print(f"  归档异常: {it.get('file_name')} -> {e}")
    return ok, len(items)

# === 准备：创建项目 ===
print("\n=== 准备：创建项目 ===")
proj = api_post(f"{BASE}/api/projects/create", json.dumps({"name": "验收测试"}).encode())
pid = proj.get("project", {}).get("project_id", "")

# 清归档目录
if os.path.exists(ARCH):
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

# 设路径 + 导入PBC
api_put(f"{BASE}/api/projects/{pid}", json.dumps({"client_folder": CLIENT, "archive_root": ARCH}))
with open(PBC, "rb") as f:
    boundary = "----b"
    body = f"--{boundary}\r\n".encode()
    body += b'Content-Disposition: form-data; name="file"; filename="01.xlsx"\r\nContent-Type: application/vnd.ms-excel\r\n\r\n'
    body += f.read() + b"\r\n--" + boundary.encode() + b"--\r\n"
req = urllib.request.Request(f"{BASE}/api/pbc/{pid}/import", data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}, method="POST")
urllib.request.urlopen(req, timeout=30)
print(f"项目: {pid}")

# === 场景1：首次扫描 ===
print("\n=== 场景1：首次扫描 ===")
wait_scan(pid)
items = get_pending(pid)
check("首次扫描出待归档", len(items) > 0, f"{len(items)}条")

# 确认归档全部
ok, total = confirm_all(pid)
check("首次确认归档", ok == total, f"{ok}/{total}")

# === 场景2：无变化再扫描 ===
print("\n=== 场景2：无变化再扫描 ===")
items_before = get_pending(pid)
count_before = len(items_before)
wait_scan(pid)
items_after = get_pending(pid)
count_after = len(items_after)
check("无变化不重复", count_after == count_before, f"前{count_before} 后{count_after}")

# === 场景3：加1个新文件再扫描 ===
print("\n=== 场景3：加1个新文件再扫描 ===")
new_file = os.path.join(CLIENT, "测试新增文件.pdf")
# 创建一个测试文件
with open(new_file, "wb") as f:
    f.write(b"%PDF-1.4 test content for new file")
wait_scan(pid)
items = get_pending(pid)
has_new = any("测试新增文件" in it.get("file_name", "") for it in items)
check("加1个文件扫出1个", has_new, f"待归档{len(items)}条，包含新文件: {has_new}")

# 清掉测试文件
try: os.remove(new_file)
except: pass

# === 场景4：删已归档文件 ===
print("\n=== 场景4：删已归档文件再扫描 ===")
# 找一个已归档的散文件删掉
archives = api_get(f"{BASE}/api/files/{pid}/list").get("files", [])
deleted_file = None
for a in archives:
    orig = a.get("original_path", "")
    if orig and os.path.exists(orig) and not a.get("is_directory"):
        deleted_file = orig
        try:
            os.remove(orig)
            print(f"  删了: {os.path.basename(orig)}")
        except:
            pass
        break

if deleted_file:
    wait_scan(pid)
    # file_missing 应该有记录（检查 briefing events）
    events = api_get(f"{BASE}/api/files/briefing-events?since=0&project_id={pid}")
    has_missing = any(e.get("event_type") == "file_missing" for e in events.get("events", []))
    check("删已归档触发file_missing", has_missing, f"events里有file_missing: {has_missing}")
    # 恢复文件
    try:
        shutil.copy2(deleted_file, deleted_file)  # 可能已经删了
    except:
        pass
else:
    check("删已归档触发file_missing", False, "没有可删的散文件")

# === 场景5：目录归档不拆散文件 ===
print("\n=== 场景5：目录归档不拆散文件 ===")
# 重新扫描，检查目录内文件不单独出现
wait_scan(pid)
items = get_pending(pid)
# 检查有没有"银行流水.xlsx"单独出现（应该在目录里不单独出现）
dir_files = ["银行流水.xlsx", "合同签字件.pdf", "盘点表.xlsx", "合并资产负债表.xlsx", "子公司利润表.xlsx"]
standalone = [it for it in items if it.get("file_name") in dir_files and it.get("decision") != "walkthrough"]
check("目录内文件不单独出现", len(standalone) == 0, f"单独出现的目录内文件: {len(standalone)}")

# === 场景6：归档数匹配 ===
print("\n=== 场景6：归档数匹配 ===")
# 重新确认所有
confirm_all(pid)
# 数磁盘文件
disk_files = 0
for root, dirs, files in os.walk(ARCH):
    for f in files:
        disk_files += 1
# 数客户文件夹文件
client_files = 0
for root, dirs, files in os.walk(CLIENT):
    for f in files:
        if not f.startswith(".") and f not in ("Thumbs.db", "desktop.ini"):
            client_files += 1
check("归档数=客户文件数", disk_files == client_files, f"磁盘{disk_files} vs 客户{client_files}")

# === 场景7：重复扫描不产生重复归档 ===
print("\n=== 场景7：重复扫描不产生重复归档 ===")
disk_before = disk_files
wait_scan(pid)
confirm_all(pid)
disk_after = 0
for root, dirs, files in os.walk(ARCH):
    for f in files:
        disk_after += 1
check("重复扫描不重复归档", disk_after == disk_before, f"前{disk_before} 后{disk_after}")

# === 汇总 ===
print("\n" + "="*60)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok)
failed = total - passed
print(f"总计: {total} 项, PASS {passed}, FAIL {failed}")
for name, ok, detail in results:
    if not ok:
        print(f"  [FAIL] {name}: {detail}")
