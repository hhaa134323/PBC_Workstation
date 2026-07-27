#!/usr/bin/env python3
"""真实文件全链路验证：sync-changes → scan → confirm → 验证所有数据源。"""
import urllib.request, json, sqlite3
from pathlib import Path
from app.core.manifest import load_manifest

pid = '27-10'
base = 'http://127.0.0.1:8000'

def api_get(path):
    r = urllib.request.urlopen(f'{base}{path}')
    return json.loads(r.read())

def api_post(path, data=b'{}'):
    req = urllib.request.Request(f'{base}{path}', data=data,
                                  headers={'Content-Type': 'application/json'}, method='POST')
    r = urllib.request.urlopen(req)
    return json.loads(r.read())

# 1. 归档树
print('=== 归档树 ===')
tree = api_get(f'/api/files/{pid}/archive-tree')['tree']
total_files = 0
for cat in tree:
    cat_files = sum(len(sd.get('files', [])) for sd in cat.get('subdirs', []))
    total_files += cat_files
    print(f'  {cat["category"]}: {cat_files} files in {len(cat.get("subdirs",[]))} subdirs')
print(f'归档树总文件数: {total_files}')

# 2. 文件计数
print('\n=== 文件计数 ===')
paths = api_get(f'/api/files/{pid}/paths')
print(f'客户文件夹: {paths["client_folder"]["file_count"]} files')
print(f'归档目录: {paths["archive_root"]["file_count"]} files')

# 3. new-file-count
nfc = api_get(f'/api/files/{pid}/new-file-count')
print(f'new-file-count: {nfc["new_file_count"]}')

# 4. PBC清单状态
print('\n=== PBC清单状态 ===')
items = api_get(f'/api/pbc/{pid}/list')['items']
empty_fp = []
for it in items:
    st = it.get('status_normalized', '')
    fp = it.get('file_path', '')
    if st == '已提供' and not fp:
        empty_fp.append(it['item_id'])
    if st != '已提供' and st != '不适用':
        print(f'  {it["item_id"]}: {st} (file_path={"有" if fp else "空"})')
if empty_fp:
    print(f'  ERROR: 已提供但file_path为空: {empty_fp}')
else:
    print('  所有已提供项都有file_path OK')

# 5. DB验证
print('\n=== DB验证 ===')
conn = sqlite3.connect('data/pbc_workstation.db')
conn.row_factory = sqlite3.Row

arcs = conn.execute('SELECT count(*) as c FROM file_archive WHERE project_id=?', (pid,)).fetchone()
print(f'file_archive记录数: {arcs["c"]}')

pc = conn.execute('SELECT count(*) as c FROM pending_confirm WHERE project_id=? AND confirmed=0', (pid,)).fetchone()
print(f'pending_confirm未确认数: {pc["c"]}')

cl = conn.execute('SELECT change_type, count(*) as c FROM file_change_log WHERE project_id=? GROUP BY change_type', (pid,)).fetchall()
print('change_log:')
for r in cl:
    print(f'  {r["change_type"]}: {r["c"]}')

dup = conn.execute('SELECT archived_path, count(*) as c FROM file_archive WHERE project_id=? GROUP BY archived_path HAVING c > 1', (pid,)).fetchall()
if dup:
    print('WARNING: 重复archived_path:')
    for r in dup:
        print(f'  {r["archived_path"][:60]}: {r["c"]}')
else:
    print('无重复archived_path OK')

conn.close()

# 6. manifest
print('\n=== manifest ===')
m = load_manifest(pid)
pending = sum(1 for v in m.values() if v.get('status') == 'pending')
processed = sum(1 for v in m.values() if v.get('status') == 'processed')
print(f'manifest: total={len(m)} pending={pending} processed={processed}')

# 7. 归档目录物理文件
print('\n=== 归档目录物理文件 ===')
ar = Path(f'projects/{pid}')
if ar.exists():
    physical = [p for p in ar.rglob('*') if p.is_file() and not p.name.startswith('.') and not p.name.startswith('~$')]
    print(f'物理文件数(排除隐藏/锁文件): {len(physical)}')
    # 检查重复文件名
    names = [p.name for p in physical]
    from collections import Counter
    dupes = {n: c for n, c in Counter(names).items() if c > 1}
    if dupes:
        print(f'WARNING: 重复文件名: {dupes}')
    else:
        print('无重复文件名 OK')
else:
    print('归档目录不存在!')

# 8. 物理文件 vs DB记录
print('\n=== 一致性检查 ===')
print(f'归档树文件数({total_files}) == 物理文件数({len(physical)}): {"OK" if total_files == len(physical) else "MISMATCH"}')
print(f'客户文件夹({paths["client_folder"]["file_count"]}) == 归档目录({paths["archive_root"]["file_count"]}): {"OK" if paths["client_folder"]["file_count"] == paths["archive_root"]["file_count"] else "MISMATCH"}')
print(f'new-file-count==0: {"OK" if nfc["new_file_count"] == 0 else "MISMATCH(" + str(nfc["new_file_count"]) + ")"}')
print(f'pending_confirm全确认: {"OK" if pc["c"] == 0 else "MISMATCH(" + str(pc["c"]) + ")"}')
print(f'manifest全processed: {"OK" if pending == 0 else "MISMATCH(pending=" + str(pending) + ")"}')
