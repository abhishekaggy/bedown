# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Bedown.

Builds a macOS .app that bundles its own Chromium and Playwright driver, so
the user does not need to run `playwright install` after downloading.

Onedir layout (NOT onefile): Playwright launches a separate Node-based
driver process plus Chromium itself, and onefile's _MEIPASS extraction
races those subprocesses. Onedir is the only reliable choice.

Build:
    pyinstaller bedown.spec
Output:
    dist/Bedown.app
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


# --- Locate Playwright assets that must be bundled --------------------------

import playwright  # noqa: E402  (intentional: spec runs at build time)

_playwright_pkg = Path(playwright.__file__).parent
_playwright_driver = _playwright_pkg / "driver"
if not _playwright_driver.is_dir():
    raise SystemExit(
        f"Playwright driver not found at {_playwright_driver}. "
        "Reinstall the playwright package."
    )

# Chromium is NOT included via `datas`. PyInstaller's binary processor
# tries to re-sign/strip every Mach-O it encounters, which blows up on the
# nested 'Google Chrome for Testing.app' inside chromium-NNNN. Instead, the
# build_app.sh wrapper copies both chromium-NNNN and chromium_headless_shell-NNNN
# into Bedown.app/Contents/Resources/ms-playwright/ AFTER PyInstaller finishes.
# The runtime.py helper finds them there.

# --- Datas / hidden imports -------------------------------------------------

datas = [
    (str(_playwright_driver), "playwright/driver"),
]
datas += collect_data_files("customtkinter")

hiddenimports = [
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageTk",
    "tqdm",
    "darkdetect",
]
hiddenimports += collect_submodules("customtkinter")
hiddenimports += collect_submodules("playwright")


# --- Analysis / build graph -------------------------------------------------

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
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)
