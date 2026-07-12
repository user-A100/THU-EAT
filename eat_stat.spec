# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for THU-EAT — 清华校园卡消费统计 单文件 EXE。"""

import sys
from pathlib import Path

# 需要打包进 EXE 的数据目录（格式: ('源路径', '目标路径')）
# Windows 分隔符用 ;（不用 :）
# ⚠️ 不打包 data/：那是用户私人数据（cookie/学号/消费记录）。运行时改读写
# EXE 同目录的 data/（见 config.py 的 sys.frozen 分支），打包进去会泄露开发者本机数据。
datas = [
    ('static', 'static'),
]

# 动态导入（PyInstaller 静态分析发现不了）
hiddenimports = [
    'scraper',          # app.py 内 do_sync() 延迟导入
    'Crypto',           # pycryptodome
    'Crypto.Cipher',
    'Crypto.Cipher.AES',
    'Crypto.Util',
    'Crypto.Util.Padding',
    'playwright',       # auth.py 内延迟导入
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='THUeat',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,          # 保留控制台窗口（显示启动信息 + 允许 Ctrl+C 停止）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='gogo.ico',       # 程序图标（gogo 吉祥物，多分辨率 16~256）
)
