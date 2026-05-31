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

# iCloud Drive (the repo lives under ~/Documents) re-stamps
# com.apple.FinderInfo and com.apple.fileprovider xattrs on bundle files
# the moment we touch them, which makes `codesign --deep --strict` reject
# the result. Sign in a /tmp staging dir where iCloud can't reach, then
# move the cleaned bundle back into dist/.
STAGE="$(mktemp -d -t bedown-build)"
APP_STAGED="$STAGE/Bedown.app"
trap 'rm -rf "$STAGE"' EXIT

echo "==> Staging bundle in $STAGE"
cp -R "$APP" "$APP_STAGED"

echo "==> Stripping extended attributes"
xattr -cr "$APP_STAGED"

echo "==> Ad-hoc signing"
rm -rf "$APP_STAGED/Contents/_CodeSignature"
codesign --force --deep --sign - "$APP_STAGED"

echo "==> Verifying signature"
codesign --verify --deep --strict --verbose=2 "$APP_STAGED"

# --norsrc / --noextattr / --noacl tell ditto to omit metadata streams so
# the zip carries no AppleDouble `._*` sidecars. The embedded ad-hoc
# signature is preserved.
echo "==> Packaging Bedown.app.zip"
(cd "$STAGE" && /usr/bin/ditto -c -k --keepParent --norsrc --noextattr --noacl Bedown.app "$ROOT/$ZIP")

echo "==> Replacing $APP with cleaned, signed bundle"
rm -rf "$APP"
mv "$APP_STAGED" "$APP"

echo "==> Verifying zip is clean (no AppleDouble files)"
if unzip -l "$ZIP" | awk '{print $NF}' | grep -E '(^|/)\._|^__MACOSX/' >/dev/null; then
    echo "Zip contains AppleDouble or __MACOSX entries — failing."
    exit 1
fi

echo "==> Done"
du -sh "$APP" "$ZIP"
