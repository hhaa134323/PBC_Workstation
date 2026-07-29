# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = ['app.api.routes_pbc', 'app.api.routes_files', 'app.api.routes_risk', 'app.api.routes_config', 'app.api.routes_projects', 'app.api.routes_briefing', 'app.core.db', 'app.core.ai_client', 'app.core.excel_io', 'app.core.file_parser', 'app.core.watcher', 'app.core.archive', 'app.core.knowledge_base', 'app.utils.path_utils', 'app.utils.retry', 'uvicorn.logging', 'uvicorn.loops.auto', 'uvicorn.loops.http11', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.httptools', 'uvicorn.lifespan.on', 'pdfplumber', 'pdfminer.high_level', 'pdfminer.pdfdocument', 'pdfminer.pdfpage', 'watchdog.observers', 'watchdog.observers.polling', 'PIL._typing', 'httpx', 'httpx._transports', 'httpx._transports.default', 'anyio', 'anyio._backends', 'anyio._backends._asyncio']
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('pdfplumber')
hiddenimports += collect_submodules('pdfminer')
hiddenimports += collect_submodules('watchdog')
hiddenimports += collect_submodules('uvicorn')
hiddenimports += collect_submodules('fastapi')
hiddenimports += collect_submodules('starlette')
hiddenimports += collect_submodules('anyio')
hiddenimports += collect_submodules('httpx')


a = Analysis(
    ['..\\app\\main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('..\\app\\static', 'app/static'),
        ('..\\mock_data', 'mock_data'),
        ('..\\config', 'config'),
        ('..\\projects', 'projects'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'pytest_asyncio', 'IPython', 'jupyter', 'notebook', 'matplotlib', 'numpy', 'scipy', 'sklearn', 'tensorflow', 'torch', 'websockets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PBC-Agent-v10',
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
    name='PBC-Agent-v10',
)
