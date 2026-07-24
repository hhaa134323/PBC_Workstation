"""自动化端到端测试：用 API + Playwright 模拟审计员完整流程。

流程：
1. 用 API 创建项目
2. 用 API 导入混合版 PBC 清单
3. 用 API 配置客户文件夹
4. 用 API 启动扫描
5. 轮询等待扫描完成
6. 检查归档结果 + PBC 清单状态
"""
import sys
import time
import json
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
PBC_LIST = str(Path(__file__).resolve().parent.parent / "data" / "test_data_package" / "01_PBC_List_混合形态.xlsx")
CLIENT_FOLDER = str(Path(__file__).resolve().parent.parent / "data" / "test_data_package" / "客户共享文件夹_混合形态")

def run():
    print("=" * 60)
    print("PBC 工作站自动化端到端测试")
    print("=" * 60)

    # 1. 创建项目
    print("\n1. 创建项目...")
    resp = requests.post(f"{BASE}/api/projects/create", json={
        "name": "自动化测试",
        "client_name": "ABC集团",
        "note": "自动化端到端测试"
    })
    proj = resp.json()
    # 兼容两种返回格式
    if "project" in proj:
        proj = proj["project"]
    proj_id = proj.get("project_id", "")
    print(f"   项目ID: {proj_id}")
    if not proj_id:
        print(f"   创建失败: {proj}")
        return

    # 2. 导入 PBC 清单
    print("\n2. 导入 PBC 清单...")
    with open(PBC_LIST, "rb") as f:
        resp = requests.post(
            f"{BASE}/api/pbc/{proj_id}/import",
            files={"file": ("01_PBC_List.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        )
    import_result = resp.json() if resp.headers.get("content-type","").startswith("application/json") else {"ok": False, "error": resp.text[:200]}
    print(f"   导入结果: {import_result}")
    if not import_result.get("ok") and resp.status_code != 200:
        print(f"   HTTP {resp.status_code}: {resp.text[:300]}")
        print("   导入失败，终止")
        return

    # 验证清单可读
    resp = requests.get(f"{BASE}/api/pbc/{proj_id}/list")
    pbc_items = resp.json().get("items", [])
    print(f"   清单可读: {len(pbc_items)} 项")

    # 3. 配置客户文件夹
    print(f"\n3. 配置客户文件夹: {CLIENT_FOLDER}")
    resp = requests.post(f"{BASE}/api/files/{proj_id}/config/folder", json={"client_folder": CLIENT_FOLDER})
    print(f"   结果: {resp.json().get('ok')}")

    # 4. 启动扫描
    print("\n4. 启动扫描...")
    resp = requests.post(f"{BASE}/api/files/{proj_id}/scan-folder")
    scan_result = resp.json()
    print(f"   扫描启动: files_found={scan_result.get('files_found', 0)}")
    task_id = scan_result.get("task_id")
    if not task_id:
        print("   错误：没有 task_id")
        return

    # 5. 等待完成
    print("\n5. 等待扫描完成...")
    start_time = time.time()
    results = []
    for i in range(180):
        resp = requests.get(f"{BASE}/api/files/{proj_id}/task-status?task_id={task_id}")
        status = resp.json()
        prog = status.get("progress", 0)
        done = status.get("done_count", 0)
        total = status.get("total", 0)
        st = status.get("status", "")

        elapsed = int(time.time() - start_time)
        if i % 5 == 0 or st in ("completed", "done", "done_with_errors", "failed"):
            print(f"   [{elapsed}s] progress={prog}% done={done}/{total} status={st}")

        if st in ("completed", "done", "done_with_errors"):
            raw = status.get("results_json", [])
            if isinstance(raw, str):
                results = json.loads(raw) if raw else []
            else:
                results = raw
            print(f"   扫描完成: {st}，处理了 {len(results)} 个文件")
            break

        if st == "failed":
            print(f"   扫描失败: {status}")
            break

        time.sleep(1)

    # 6. 打印每个文件的分类结果
    print(f"\n6. 分类结果明细 ({len(results)} 个文件):")
    print(f"   {'文件名':<40s} {'匹配模型':<22s} {'item_id':<8s} {'置信度':<8s} {'dedup':<6s} {'事件':<20s}")
    print("   " + "-" * 110)
    for r in results:
        name = (r.get("name") or r.get("file_name") or "")[:38]
        classify = r.get("classify", {})
        model = classify.get("model", "")[:20]
        item_id = str(classify.get("item_id", ""))
        conf = classify.get("confidence", 0)
        dedup = r.get("dedup", False)
        events = r.get("events", [])
        evt_str = ",".join([e.get("type","") for e in events]) if events else ""
        print(f"   {name:<40s} {model:<22s} {item_id:<8s} {conf:<8.2f} {str(dedup):<6s} {evt_str:<20s}")

    # 7. 检查归档目录树
    print(f"\n7. 归档目录树:")
    resp = requests.get(f"{BASE}/api/files/{proj_id}/archive-tree")
    tree = resp.json()
    for cat in tree:
        cat_name = cat.get("category", "")
        cat_count = cat.get("count", 0)
        print(f"  📁 {cat_name} ({cat_count} 文件)")
        for sd in cat.get("subdirs", []):
            print(f"    📁 {sd.get('name', '')} ({sd.get('count', 0)} 文件)")
            for f in sd.get("files", []):
                print(f"      📄 {f.get('name', '')}")

    # 8. PBC 清单状态
    print(f"\n8. PBC 清单状态:")
    resp = requests.get(f"{BASE}/api/pbc/{proj_id}/list")
    pbc_items = resp.json().get("items", [])
    for item in pbc_items:
        item_id = item.get("item_id", "")
        doc_name = item.get("doc_name", "")
        status = item.get("status_normalized", "")
        file_path = item.get("file_path", "")
        conf = item.get("confidence", 0) or 0
        mark = "✅" if file_path else "❌"
        print(f"  {mark} {item_id:<8s} {doc_name:<20s} status={status:<20s} conf={conf:.2f}")

    # 9. 验证结果
    print(f"\n9. 验证结果:")
    expected_matches = {
        "历-1": "历-1_股权架构图.pdf",
        "销-1": "销-1_销售合同台账.xlsx",
        "财-1": "合并资产负债表.xlsx",
        "财-2": "子公司利润表.xlsx",
        "存-1": "盘点表.xlsx",
        "存-4": "盘点计划.pdf",
        "货-1": "银行流水.xlsx",
        "货-2": "DEF银行对账单.pdf",
        "综-1": "新建文档(1).pdf",
        "历-2": "ABC集团章程_修订版.pdf",
        "穿-1": "穿行测试",
    }

    all_pass = True
    for item_id, expected_file in expected_matches.items():
        found = False
        for item in pbc_items:
            if item.get("item_id") == item_id and item.get("file_path"):
                found = True
                break
        mark = "✅" if found else "❌"
        if not found:
            all_pass = False
        print(f"  {mark} {item_id} ({expected_file}) → {'已归档' if found else '未归档'}")

    # 检查未分类
    unclassified_cat = [c for c in tree if c.get("category") == "未分类"]
    if unclassified_cat:
        unclassified_count = unclassified_cat[0].get("count", 0)
        if unclassified_count > 2:  # 扫描件001 + 新建文档(1) 是正常的
            print(f"  ⚠️ 未分类有 {unclassified_count} 个文件（预期 ≤2）")
            all_pass = False
        else:
            print(f"  ✅ 未分类 {unclassified_count} 个文件（合理）")
    else:
        print(f"  ✅ 没有未分类文件")

    print(f"\n{'='*60}")
    if all_pass:
        print("✅ 全部通过")
    else:
        print("❌ 有未通过项")
    print(f"{'='*60}")

if __name__ == "__main__":
    run()
