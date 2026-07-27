#!/usr/bin/env python3
"""Debug manifest pending items."""
import json
from pathlib import Path

with open('projects/27-10/.pbc_manifest.json', 'r', encoding='utf-8') as f:
    m = json.load(f)

client_folder = Path('data/test_data_package/客户共享文件夹_混合形态')

pending_keys = [k for k, v in m.items() if v.get('status') == 'pending']
print('Pending keys in manifest:')
for k in pending_keys:
    full = client_folder / k
    exists = full.exists()
    print(f'  {k} -> exists={exists} item_id={m[k].get("item_id", "")}')

print()
print('Actual files not processed:')
for p in client_folder.rglob('*'):
    if not p.is_file():
        continue
    if p.name.startswith('.'):
        continue
    rel = str(p.relative_to(client_folder)).replace('\\', '/')
    rec = m.get(rel)
    if not rec or rec.get('status') == 'pending':
        print(f'  {rel} -> in_manifest={bool(rec)} status={rec.get("status") if rec else "N/A"}')
