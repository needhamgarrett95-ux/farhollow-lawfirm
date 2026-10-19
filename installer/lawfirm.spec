# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for LawFirmServer.exe

Build on Windows with:
    pip install pyinstaller
    pyinstaller installer/lawfirm.spec

Output: dist/LawFirmServer/LawFirmServer.exe (onedir) — copy the whole
LawFirmServer folder, or use the Inno Setup installer for a proper install.
"""

import os

BASE = os.path.abspath(os.path.join(SPECPATH, ".."))

a = Analysis(
    [os.path.join(BASE, "app.py")],
    pathex=[BASE],
    binaries=[],
    datas=[
        (os.path.join(BASE, "templates"), "templates"),
        (os.path.join(BASE, "static"), "static"),
    ],
    hiddenimports=[],
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
    [],
    exclude_binaries=True,
    name="LawFirmServer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # console window shows the startup banner + LAN IP
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="LawFirmServer",
)
