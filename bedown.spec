# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bedown.

Builds a macOS .app. The scraper is pure-Python (httpx + Pillow), so the
bundle no longer carries Chromium or Node.js — the .app is tiny and the
user does not need any post-install setup.

Onedir layout (NOT onefile): onefile extracts to a temp dir on every
launch, which is slow and trips macOS Gatekeeper on signed bundles.

Build:
    pyinstaller bedown.spec
Output:
    dist/Bedown.app
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


datas = []
datas += collect_data_files("customtkinter")

hiddenimports = [
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageTk",
    "tqdm",
    "darkdetect",
]
hiddenimports += collect_submodules("customtkinter")


block_cipher = None

a = Analysis(
    ["src/bedown/gui_main.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Keep the bundle lean — these aren't needed.
        "pytest",
        "tkinter.test",
        "playwright",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Bedown",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,           # no terminal window when launching the .app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Bedown",
)

app = BUNDLE(
    coll,
    name="Bedown.app",
    icon=None,
    bundle_identifier="capital.appreciate.bedown",
    info_plist={
        "CFBundleName": "Bedown",
        "CFBundleDisplayName": "Bedown",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)
