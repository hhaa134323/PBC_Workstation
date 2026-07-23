# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['app.api.routes_pbc', 'app.api.routes_files', 'app.api.routes_risk', 'app.api.routes_config', 'app.api.routes_projects', 'app.api.routes_briefing', 'app.core.db', 'app.core.ai_client', 'app.core.excel_io', 'app.core.file_parser', 'app.core.watcher', 'app.core.archive', 'app.utils.path_utils', 'app.utils.retry']
hiddenimports += collect_submodules('app')


a = Analysis(
    ['..\\app\\main.py'],
    pathex=[],
    binaries=[],
    datas=[('D:/AgentProjects/IpoPBC/0/app/static', 'app/static'), ('D:/AgentProjects/IpoPBC/0/mock_data', 'mock_data'), ('D:/AgentProjects/IpoPBC/0/config', 'config'), ('D:/AgentProjects/IpoPBC/0/projects', 'projects')],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'matplotlib', 'numpy', 'scipy', 'tensorflow', 'torch', 'websockets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PBC-Agent-v7',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PBC-Agent-v7',
)
