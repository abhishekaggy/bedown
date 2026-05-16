#!/usr/bin/env bash
# Build Bedown.app — runs PyInstaller. The scraper is pure-Python, so the
# bundle has no Chromium / Node.js / Playwright assets to copy in afterwards.
#
# Usage:
#     ./build_app.sh
# Result:
#     dist/Bedown.app

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYINSTALLER="${PYINSTALLER:-$ROOT/.venv/bin/pyinstaller}"

if [[ ! -x "$PYINSTALLER" ]]; then
    echo "PyInstaller not found at $PYINSTALLER. Install dev deps with:"
    echo "  pip install -r requirements-dev.txt"
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

echo "==> Done: $APP"
du -sh "$APP"
