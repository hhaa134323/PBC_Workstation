"""回归测试：基于决策树 v2 验证所有功能点。"""
import urllib.request, urllib.parse, json, time, os, sys

results = []
base = "http://127.0.0.1:8111"
WD = r"D:/AgentProjects/IpoPBC/0"

def test(name, scenario, fn):
    try:
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
        icon = "(check)" if ok else "(x)"
        results.append((status, scenario, name, detail))
        print(f"  {icon} {name}: {detail}")
    except Exception as e:
        results.append(("FAIL", scenario, name, str(e)[:150]))
        print(f"  (x) {name}: {type(e).__name__}: {e}")

# ===== 场景 1: 首启 =====
print("=== 场景 1: 首启 ===")

def sc1_health():
    r = urllib.request.urlopen(base + "/health")
    d = json.loads(r.read())
    return d.get("status") == "ok", f"status={d.get('status')}"

def sc1_projects():
    r = urllib.request.urlopen(base + "/api/projects/list")
    d = json.loads(r.read())
    return d.get("count", 0) >= 1, f"count={d.get('count')}, name={d.get('projects',[{}])[0].get('name','')}"

def sc1_demo():
    r = urllib.request.urlopen(base + "/api/projects/demo")
    d = json.loads(r.read())
    p = d.get("project", {})
    return bool(p.get("project_id")), f"project_id={p.get('project_id')}, name={p.get('name')}"

def sc1_pbc_count():
    r = urllib.request.urlopen(base + "/api/pbc/demo/list")
    d = json.loads(r.read())
    cnt = d.get("count", 0)
    return cnt == 6, f"count={cnt} (expected 6)"

def sc1_pbc_status():
    r = urllib.request.urlopen(base + "/api/pbc/demo/list")
    items = json.loads(r.read()).get("items", [])
    statuses = {}
    for it in items:
        od = it.get("overdue_days", 0)
        try: od_int = int(str(od).replace("\u5929",""))
        except: od_int = 0
        statuses[it["item_id"]] = (it["status_raw"], od_int)
    has_overdue = any(od > 0 for _, od in statuses.values())
    item_list = ", ".join([f"{k}={v[0]}" for k,v in statuses.items()])
    return has_overdue, f"items={item_list}, has_overdue={has_overdue}"

test("health 接口", "首启", sc1_health)
test("项目列表(有demo)", "首启", sc1_projects)
test("demo 项目详情", "首启", sc1_demo)
test("PBC清单(6项)", "首启", sc1_pbc_count)
test("PBC清单状态分布", "首启", sc1_pbc_status)

# ===== 场景 2: 扫描 =====
print("\n=== 场景 2: 扫描 ===")

def sc2_folder_config():
    r = urllib.request.urlopen(base + "/api/files/demo/config/folder")
    d = json.loads(r.read())
    cur = d.get("current", {})
    cnt = cur.get("file_count", 0)
    return cnt > 0, f"path={str(cur.get('path',''))[:60]}, file_count={cnt}"

def sc2_scan():
    r = urllib.request.urlopen(
        urllib.request.Request(base + "/api/files/demo/scan-folder", method="POST")
    )
    d = json.loads(r.read())
    tid = d.get("task_id", "")
    return bool(tid), f"task_id={tid[:30]}"

def sc2_folder_bad():
    url = base + "/api/files/demo/config/folder"
    data = json.dumps({"client_folder": "Z:/not/exists"}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req)
    d = json.loads(r.read())
    sug = d.get("suggestion", "")
    return not d.get("ok") and len(sug) > 10, f"ok={d.get('ok')}, suggestion={sug[:50]}"

test("客户文件夹配置(有文件)", "扫描", sc2_folder_config)
test("扫描新文件(返回task)", "扫描", sc2_scan)
test("文件夹不存在友好提示", "扫描", sc2_folder_bad)

# 等 AI
print("\n等待 AI 处理(55秒)...")
time.sleep(55)
try:
    r = urllib.request.urlopen(base + "/api/files/demo/recent-tasks?limit=1")
    ts = json.loads(r.read())
    tasks = ts.get("tasks", ts if isinstance(ts, list) else [])
    if tasks:
        tid = tasks[0].get("task_id", "")
        if tid:
            def sc2_task():
                r = urllib.request.urlopen(base + f"/api/files/demo/task/{tid}")
                d = json.loads(r.read())
                st = d.get("status", "")
                prog = d.get("progress", 0)
                rj = d.get("results_json", "[]")
                if isinstance(rj, str):
                    try: rr = json.loads(rj)
                    except: rr = []
                else: rr = rj
                return st == "done", f"status={st}, progress={prog}%, results={len(rr)}"
            test("AI 处理任务完成", "扫描", sc2_task)

            def sc2_task_classify():
                r = urllib.request.urlopen(base + f"/api/files/demo/task/{tid}")
                d = json.loads(r.read())
                rj = d.get("results_json", "[]")
                if isinstance(rj, str):
                    try: rr = json.loads(rj)
                    except: rr = []
                else: rr = rj
                all_ok = all(r.get("ok") for r in rr)
                has_classify = any(r.get("classify", {}).get("item_id") for r in rr)
                return all_ok and has_classify, f"all_ok={all_ok}, has_classify={has_classify}"
            test("AI classify 返回结果", "扫描", sc2_task_classify)
except Exception as e:
    print(f"  task 查询异常: {e}")

# ===== 场景 3: 复核 =====
print("\n=== 场景 3: 复核 ===")

def sc3_reviewing():
    r = urllib.request.urlopen(base + "/api/pbc/demo/list")
    items = json.loads(r.read()).get("items", [])
    reviewing = [it for it in items if "\u5ba1\u6838\u4e2d" in (it.get("status_raw") or "")]
    return len(reviewing) >= 1, f"reviewing_count={len(reviewing)}"

def sc3_undo():
    encoded = urllib.parse.quote("\u501f-1")
    init_data = json.dumps({"status": "\u5df2\u63d0\u4f9b", "changed_by": "Senior", "note": "init"}).encode()
    init_req = urllib.request.Request(base + f"/api/pbc/demo/{encoded}/status", data=init_data,
                                      headers={"Content-Type": "application/json"}, method="PUT")
    try: urllib.request.urlopen(init_req)
    except: pass

    undo_data = json.dumps({"status": "\u5df2\u63d0\u4f9b\uff0c\u5ba1\u6838\u4e2d", "changed_by": "Manager",
                            "note": "\u64a4\u9500\u5f52\u6863"}).encode()
    undo_req = urllib.request.Request(base + f"/api/pbc/demo/{encoded}/status", data=undo_data,
                                      headers={"Content-Type": "application/json"}, method="PUT")
    try:
        r = urllib.request.urlopen(undo_req)
        d = json.loads(r.read())
        return d.get("ok") is True, f"ok={d.get('ok')}, new_status={d.get('item',{}).get('status_raw')}"
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return False, f"HTTP {e.code}: {body[:100]}"

test("清单有审核中项", "复核", sc3_reviewing)
test("撤销归档(已提供\u2192审核中)", "复核", sc3_undo)

# ===== 场景 4: 风险 =====
print("\n=== 场景 4: 风险化解 ===")

def sc4_dashboard():
    r = urllib.request.urlopen(base + "/api/risk/demo/dashboard")
    d = json.loads(r.read())
    overdue = d.get("overdue_summary", {})
    cells = d.get("risk_heatmap", {}).get("cells", [])
    hotspots = d.get("audit_risk_hotspots", [])
    return overdue.get("count", 0) >= 1 and len(cells) >= 1 and len(hotspots) >= 1, \
        f"overdue={overdue.get('count')}, cells={len(cells)}, hotspots={len(hotspots)}"

def sc4_heatmap():
    r = urllib.request.urlopen(base + "/api/risk/demo/heatmap")
    d = json.loads(r.read())
    return len(d.get("cells", [])) >= 1, f"entities={d.get('entities')}, cells={len(d.get('cells',[]))}"

def sc4_escalation():
    r = urllib.request.urlopen(base + "/api/risk/demo/escalation")
    d = json.loads(r.read())
    text = d.get("report_text", "")
    return len(text) > 500, f"report_text.len={len(text)}"

test("风险仪表盘(超期+热力图+热点)", "风险", sc4_dashboard)
test("独立热力图接口", "风险", sc4_heatmap)
test("升级缺口汇报文本", "风险", sc4_escalation)

# ===== 场景 5: 多项目 =====
print("\n=== 场景 5: 多项目 ===")

def sc5_create():
    data = json.dumps({"name": "\u5f52\u56de\u6d4b\u8bd5\u9879\u76ee", "client_name": "\u6d4b\u8bd5"}).encode()
    req = urllib.request.Request(base + "/api/projects/create", data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    r = urllib.request.urlopen(req)
    d = json.loads(r.read())
    pid = d.get("project", {}).get("project_id", "")
    return bool(pid), f"project_id={pid}, name={d.get('project',{}).get('name','')}"

test("创建新项目", "多项目", sc5_create)

# 检查新项目的 PBC 清单
r = urllib.request.urlopen(base + "/api/projects/list")
projs = json.loads(r.read()).get("projects", [])
new_pid = None
for p in projs:
    if p.get("project_id") != "demo":
        new_pid = p.get("project_id")
        r2 = urllib.request.urlopen(base + f"/api/pbc/{new_pid}/list")
        d2 = json.loads(r2.read())
        cnt2 = d2.get("count", 0)
        def sc5_new_pbc():
            return cnt2 == 0, f"project={new_pid}, pbc_count={cnt2} (new project, should be 0)"
        test("新项目PBC清单(空)", "多项目", sc5_new_pbc)
        break

if new_pid:
    r = urllib.request.urlopen(base + f"/api/projects/{new_pid}?soft=false",
                               method="DELETE" if hasattr(urllib.request, 'method') else None)
    # 用直接构造 DELETE 请求
    del_req = urllib.request.Request(base + f"/api/projects/{new_pid}?soft=false", method="DELETE")
    try:
        del_resp = urllib.request.urlopen(del_req)
        del_d = json.loads(del_resp.read())
        def sc5_delete_ok():
            return del_d.get("ok") is True, f"ok={del_d.get('ok')}"
        test("删除新项目", "多项目", sc5_delete_ok)
    except Exception as e:
        print(f"  (x) 删除新项目: {e}")

# 设置按钮
with open(os.path.join(WD, "app/static/index.html"), "r", encoding="utf-8") as f:
    idx_html = f.read()
has_settings = "\u2699 \u8bbe\u7f6e" in idx_html or "⚙ 设置" in idx_html
has_folderConfig = "folderConfig" in idx_html
def sc5_settings():
    return has_settings and has_folderConfig, f"has_settings={has_settings}, has_folderConfig={has_folderConfig}"
test("前端设置按钮存在", "多项目", sc5_settings)

# ===== 场景 6: 异常 =====
print("\n=== 场景 6: 异常 ===")

def sc6_startup_log():
    log_path = os.path.join(WD, "data/logs/regression.log")
    if not os.path.exists(log_path): return False, "log not found"
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()
    has_key = "API Key" in content
    has_watchdog = "watchdog" in content.lower()
    return has_key and has_watchdog, f"has_key={has_key}, has_watchdog={has_watchdog}"

def sc6_tailwind():
    css = os.path.join(WD, "app/static/css/tailwind-local.css")
    return os.path.exists(css), f"exists={os.path.exists(css)}"

test("启动日志(API Key+watchdog)", "异常", sc6_startup_log)
test("CDN fallback CSS 存在", "异常", sc6_tailwind)

# ===== 场景 7: 边界 =====
print("\n=== 场景 7: 边界 ===")
def sc7_pbc_not_empty():
    r = urllib.request.urlopen(base + "/api/pbc/demo/list")
    d = json.loads(r.read())
    return d.get("count", 0) > 0, f"count={d.get('count')}"
test("PBC 清单非空(6项)", "边界", sc7_pbc_not_empty)

# ===== 总结 =====
print("\n" + "="*60)
print("回归测试 总结")
print("="*60)
pass_cnt = len([r for r in results if r[0] == "PASS"])
fail_cnt = len([r for r in results if r[0] == "FAIL"])
total = pass_cnt + fail_cnt
print(f"总计: {total} | 通过: {pass_cnt} | 失败: {fail_cnt}")
print(f"通过率: {pass_cnt*100//total if total else 0}%")
print()
print(f"{'结果':>6} {'场景':>8} {'测试项'}")
print("-"*60)
for s, sc, n, d in results:
    icon = "(check)" if s == "PASS" else "(x)"
    print(f"  {icon} [{sc}] {n}")

print(f"\n{'结果':>6} {'场景':>8} {'测试项'}")
print("-"*60)
for s, sc, n, d in results:
    print(f"{s:>6} [{sc:8}] {n}: {d}")
