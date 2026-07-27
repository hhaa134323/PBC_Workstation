#!/usr/bin/env python3
"""用真实内容文件验证多文件归档不覆盖bug。"""
import urllib.request, json, sqlite3, shutil
from pathlib import Path
from app.core.db import insert_pending_confirm, update_project
from app.core.excel_io import _COLUMN_MAP, read_pbc_list
from app.config import PROJECTS_DIR
import openpyxl

base = 'http://127.0.0.1:8000'

# 清理
for d in ['data/test_bug_fix_client', 'projects/test_bug_fix_archive',
          'projects/project_test-bug-fix']:
    p = Path(d)
    if p.exists():
        shutil.rmtree(str(p))
conn = sqlite3.connect('data/pbc_workstation.db')
conn.execute('DELETE FROM file_archive WHERE project_id=?', ('test-bug-fix',))
conn.execute('DELETE FROM pending_confirm WHERE project_id=?', ('test-bug-fix',))
conn.execute('DELETE FROM file_change_log WHERE project_id=?', ('test-bug-fix',))
conn.commit()
conn.close()

# 创建项目
req = urllib.request.Request(base + '/api/projects/create',
    data=json.dumps({'name': 'test-bug-fix', 'client_name': 'BugFix验证'}).encode('utf-8'),
    headers={'Content-Type': 'application/json'}, method='POST')
pid = json.loads(urllib.request.urlopen(req).read())['project']['project_id']
print('1. 创建项目: %s' % pid)

# 配置
cf = Path('data/test_bug_fix_client').resolve()
ar = Path('projects/test_bug_fix_archive').resolve()
cf.mkdir(parents=True, exist_ok=True)
ar.mkdir(parents=True, exist_ok=True)
urllib.request.urlopen(urllib.request.Request(base + '/api/files/%s/config/folder' % pid,
    data=json.dumps({'client_folder': str(cf)}).encode('utf-8'),
    headers={'Content-Type': 'application/json'}, method='POST'))
urllib.request.urlopen(urllib.request.Request(base + '/api/files/%s/config/archive-root' % pid,
    data=json.dumps({'archive_root': str(ar)}).encode('utf-8'),
    headers={'Content-Type': 'application/json'}, method='POST'))
print('2. 配置文件夹+归档目录')

# PBC清单
pbc_path = PROJECTS_DIR / ('project_' + pid) / '01_PBC_List.xlsx'
pbc_path.parent.mkdir(parents=True, exist_ok=True)
wb = openpyxl.Workbook()
ws = wb.active
ws.append([tup[1] for tup in _COLUMN_MAP])
ws.append(['财务报表', 'test-1', '财务', '资产负债表', '多实体资产负债表',
           '2024年度', '', '', '', '2026-08-15', 0, '未提供', '', '集团合并', 0, ''])
wb.save(str(pbc_path))
update_project(pid, pbc_list_path=str(pbc_path))
print('3. PBC清单: 1个item (test-1, 资产负债表)')

# 创建文件——2个相同大小不同内容的文件（这才是之前的bug场景）
# 文件名不同，但归档后生成的文件名相同（都基于item_id+doc_name）
p1 = cf / 'ABC子公司提交.xlsx'
p2 = cf / 'DEF子公司提交.xlsx'
# 故意让size相同但内容不同
p1.write_bytes(b'AAA' * 200 + 'ABC子公司2024年度资产负债表 货币资金1200万 应收账款800万'.encode('utf-8'))
p2.write_bytes(b'BBB' * 200 + 'DEF子公司2024年度资产负债表 货币资金2500万 应收账款1200万'.encode('utf-8'))
print('4. 创建2个文件:')
print('   %s: %d bytes (%.1f KB)' % (p1.name, p1.stat().st_size, p1.stat().st_size/1024))
print('   %s: %d bytes (%.1f KB)' % (p2.name, p2.stat().st_size, p2.stat().st_size/1024))
print('   size相同: %s' % (p1.stat().st_size == p2.stat().st_size))
print('   content相同: %s' % (p1.read_bytes() == p2.read_bytes()))

# 写pending_confirm + 确认归档
print()
print('=== 逐个确认归档 ===')
for i, (f, label) in enumerate([(p1, 'ABC'), (p2, 'DEF')]):
    cid = insert_pending_confirm(
        project_id=pid, file_path=str(f), file_name=f.name,
        sha256='', suggested_item_id='test-1', confidence=0.95, decision='auto',
    )
    r = urllib.request.urlopen(urllib.request.Request(
        base + '/api/files/%s/confirm/%d' % (pid, cid),
        data=json.dumps({'new_item_id': ''}).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST'))
    print('  %s: ok=%s' % (label, json.loads(r.read()).get('ok')))

# 验证归档目录
print()
print('=== 验证结果 ===')
archived = [p for p in ar.rglob('*') if p.is_file() and not p.name.startswith('.')]
print('归档文件数: %d' % len(archived))
for f in sorted(archived, key=lambda x: x.name):
    content_preview = f.read_bytes()[:50].decode('utf-8', errors='replace')
    print('  %s (%d bytes, %.1f KB)' % (f.name, f.stat().st_size, f.stat().st_size/1024))
    print('    内容预览: %s...' % content_preview[:40])

if len(archived) == 2:
    print()
    print('>> BUG已修复: 2个文件都保留了, 自动升版本号 v1/v2')
    # 验证内容不同
    contents = [f.read_bytes() for f in archived]
    print('>> 两个文件内容不同: %s' % (contents[0] != contents[1]))
elif len(archived) == 1:
    print()
    print('>> BUG未修复: 只剩1个文件, 第二个覆盖了第一个!')
else:
    print()
    print('>> 异常: %d个文件' % len(archived))

# DB验证
print()
print('=== DB ===')
conn = sqlite3.connect('data/pbc_workstation.db')
conn.row_factory = sqlite3.Row
arcs = conn.execute('SELECT * FROM file_archive WHERE project_id=? AND item_id=?', (pid, 'test-1')).fetchall()
print('file_archive: %d条' % len(arcs))
for a in arcs:
    print('  id=%d path=%s' % (a['id'], a['archived_path'][-50:]))
conn.close()
