#!/bin/bash
# Independent Apple Silicon build. Never touches dist/PulseReview.exe or releases.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo "Build requires native Apple Silicon macOS (no Rosetta/cross compilation)." >&2; exit 1;
}
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import platform,sys; assert platform.machine()=="arm64"; assert sys.version_info[:2]==(3,11), "Use arm64 Python 3.11"'
for tool in hdiutil iconutil sips codesign lipo; do command -v "$tool" >/dev/null; done

# Dedicated clean environment; keep the Windows .venv/build outputs untouched.
"$PYTHON" -m venv --clear "$ROOT/.venv-mac"
PY="$ROOT/.venv-mac/bin/python"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements-mac-test.txt
"$PY" -m playwright install chromium
"$PY" -m pip check
mkdir -p build/mac dist/mac
"$PY" -m pip freeze > build/mac/dependencies.txt
"$PY" -m pytest -q --junitxml=build/mac/tests.xml

# Convert the existing ZeroPulse icon; do not regenerate or change Windows assets.
mkdir -p build/mac/PulseReview.iconset
for size in 16 32 64 128 256 512; do
  sips -z "$size" "$size" dashboard/assets/icon.png --out "build/mac/PulseReview.iconset/icon_${size}x${size}.png" >/dev/null
done
for size in 16 32 128 256 512; do
  double=$((size * 2))
  sips -z "$double" "$double" dashboard/assets/icon.png --out "build/mac/PulseReview.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns build/mac/PulseReview.iconset -o build/mac/PulseReview.icns
"$PY" - <<'PY'
import json, os, re, subprocess
from pathlib import Path
version = os.environ.get('PULSEREVIEW_MAC_VERSION', '0.1.3')
assert re.fullmatch(r'\d+\.\d+\.\d+', version), 'Version must be numeric x.y.z'
commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], text=True).strip())
Path('build/mac/build-info.json').write_text(json.dumps({
    'product': 'PulseReview', 'platform': 'macOS-arm64', 'version': version,
    'channel': 'mac-beta', 'source_commit': commit, 'dirty': dirty,
    'signing': 'ad-hoc; not Developer ID signed or notarized',
}, indent=2))
PY
export MACOSX_DEPLOYMENT_TARGET=14.0
"$PY" -m PyInstaller --noconfirm --clean --distpath dist/mac --workpath build/mac/pyinstaller packaging/mac.spec
APP="$ROOT/dist/mac/PulseReview.app"
test -x "$APP/Contents/MacOS/PulseReview"
lipo -verify_arch arm64 "$APP/Contents/MacOS/PulseReview"
codesign --verify --deep --strict --verbose=2 "$APP"
"$PY" tools/smoke_mac.py "$APP"

# Staging preserves framework symlinks. hdiutil creates a compressed read-only DMG.
STAGE="$(mktemp -d "$ROOT/build/mac/dmg.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/PulseReview.app"
ln -s /Applications "$STAGE/Applications"
cp docs/MACOS_INSTALL.md "$STAGE/Read Me.txt"
DMG="$ROOT/dist/mac/PulseReview-macOS-arm64.dmg"
# Do not silently overwrite a prior locally reviewed installer.
[[ ! -e "$DMG" ]] || { echo "Move the existing DMG aside before rebuilding: $DMG" >&2; exit 1; }
hdiutil create -volname PulseReview -srcfolder "$STAGE" -format UDZO -ov "$DMG"
hdiutil verify "$DMG"
(cd dist/mac && shasum -a 256 PulseReview-macOS-arm64.dmg > PulseReview-macOS-arm64.dmg.sha256)
"$PY" tools/verify_mac_dmg.py "$DMG"
cp build/mac/build-info.json build/mac/dependencies.txt dist/mac/
echo "Built and verified: $DMG (ad-hoc signed, NOT notarized). Nothing published."
