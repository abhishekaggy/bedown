#!/usr/bin/env bash
# Build Bedown.app — runs PyInstaller, signs ad-hoc, and produces a clean
# Bedown.app.zip ready to upload to a GitHub release.
#
# Usage:
#     ./build_app.sh
# Result:
#     dist/Bedown.app
#     dist/Bedown.app.zip

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
ZIP="dist/Bedown.app.zip"
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
codesign --verify --deep --strict --verbose=2 "$APP"

# ditto produces a zip with no AppleDouble `._*` entries and no __MACOSX/
# directory, which `zip -r` would otherwise create when xattrs are present.
echo "==> Packaging Bedown.app.zip"
(cd dist && /usr/bin/ditto -c -k --keepParent Bedown.app Bedown.app.zip)

echo "==> Verifying zip is clean (no AppleDouble files)"
if unzip -l "$ZIP" | awk '{print $NF}' | grep -E '(^|/)\._|^__MACOSX/' >/dev/null; then
    echo "Zip contains AppleDouble or __MACOSX entries — failing."
    exit 1
fi

echo "==> Done"
du -sh "$APP" "$ZIP"
