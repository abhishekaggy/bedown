#!/usr/bin/env bash
# Build Bedown.app — runs PyInstaller and then copies the local Playwright
# Chromium cache into the bundle so the app is self-contained.
#
# PyInstaller can't include Chromium via the spec because its binary processor
# tries to re-sign the nested 'Google Chrome for Testing.app' Mach-O and
# breaks. Doing the copy here side-steps that.
#
# Usage:
#     ./build_app.sh
# Result:
#     dist/Bedown.app

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY="${PY:-$ROOT/.venv/bin/python}"
PYINSTALLER="${PYINSTALLER:-$ROOT/.venv/bin/pyinstaller}"

if [[ ! -x "$PYINSTALLER" ]]; then
    echo "PyInstaller not found at $PYINSTALLER. Install dev deps with:"
    echo "  pip install -r requirements-dev.txt"
    exit 1
fi

CHROMIUM_CACHE="$HOME/Library/Caches/ms-playwright"
# Bedown always launches with headless=True. Playwright >=1.49 routes headless
# launches through chromium_headless_shell, so we only need to bundle that
# binary — the full ~280 MB Chromium directory is not used at runtime.
HEADLESS_DIR="$(ls -1d "$CHROMIUM_CACHE"/chromium_headless_shell-[0-9]* 2>/dev/null | sort | tail -n 1 || true)"
if [[ -z "$HEADLESS_DIR" ]]; then
    echo "Missing Playwright headless-shell in $CHROMIUM_CACHE."
    echo "Run: $ROOT/.venv/bin/playwright install chromium"
    exit 1
fi

echo "==> Cleaning previous build"
rm -rf build dist

echo "==> Running PyInstaller"
"$PYINSTALLER" bedown.spec --noconfirm

APP="dist/Bedown.app"
if [[ ! -d "$APP" ]]; then
    echo "Build failed: $APP not produced."
    exit 1
fi

BROWSERS_DEST="$APP/Contents/Resources/ms-playwright"
mkdir -p "$BROWSERS_DEST"

NAME="$(basename "$HEADLESS_DIR")"
echo "==> Copying $NAME → $BROWSERS_DEST/$NAME"
cp -Rp "$HEADLESS_DIR" "$BROWSERS_DEST/"

# Belt-and-braces: ensure executable is still +x after copy.
HEADLESS_BIN="$BROWSERS_DEST/$NAME/chrome-headless-shell-mac-arm64/chrome-headless-shell"
[[ -f "$HEADLESS_BIN" ]] && chmod +x "$HEADLESS_BIN"

echo "==> Done: $APP"
du -sh "$APP"
