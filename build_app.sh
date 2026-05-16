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

# macOS Gatekeeper rejects bundles whose ad-hoc signature is broken — the
# user sees "Bedown.app is damaged" on first launch. PyInstaller's built-in
# signing pass fails when the build directory has com.apple.FinderInfo or
# com.apple.fileprovider xattrs (iCloud Drive auto-adds these to anything
# under ~/Documents). Strip every xattr, then re-sign ad-hoc.
echo "==> Stripping extended attributes"
xattr -cr "$APP"

echo "==> Ad-hoc signing"
rm -rf "$APP/Contents/_CodeSignature"
codesign --force --deep --sign - "$APP"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -3

echo "==> Done: $APP"
du -sh "$APP"
