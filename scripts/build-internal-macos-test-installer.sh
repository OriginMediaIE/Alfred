#!/bin/bash
set -euo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
OUTPUT_DMG="$DIST_DIR/OM Automate Internal Test.dmg"
INSTALL_LOCATION="~/Library/Application Support/OM Automate/app"
WORK_DIR="$(mktemp -d)"
PAYLOAD_DIR="$WORK_DIR/payload"
DMG_ROOT="$WORK_DIR/dmg"
INSTALL_RESOURCES="$DMG_ROOT/.om-install"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "This internal installer must be built on an Apple Silicon Mac." >&2
  exit 1
fi

for command_name in xcrun hdiutil rsync plutil codesign; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required macOS build command: $command_name" >&2
    exit 1
  }
done

mkdir -p "$PAYLOAD_DIR" "$INSTALL_RESOURCES" "$DIST_DIR"

echo "Staging sanitized application payload"
/usr/bin/rsync -a \
  --exclude '.git/' \
  --exclude '.env' \
  --include '.env.example' \
  --exclude '.env.*' \
  --exclude '/data/' \
  --exclude '/logs/' \
  --exclude '/venv/' \
  --exclude '/.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '*.pyo' \
  --exclude '*.log' \
  --exclude '*.db' \
  --exclude '*.sqlite' \
  --exclude '*.sqlite3' \
  --exclude '/.build/' \
  --exclude '/build/' \
  --exclude '/dist/' \
  --exclude '/tests/' \
  --exclude '/tmp_pytest_probe/' \
  --exclude '/.coverage' \
  --exclude '/htmlcov/' \
  --exclude '.pytest_cache/' \
  --exclude '.mypy_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.DS_Store' \
  "$ROOT_DIR/" "$PAYLOAD_DIR/"

chmod 755 "$PAYLOAD_DIR/start-macos.sh"

echo "Building relocatable native app"
OM_INSTALL_DIRECTORY="$INSTALL_LOCATION" OM_SKIP_DMG=1 "$ROOT_DIR/build-macos-app.sh"
/usr/bin/ditto "$DIST_DIR/OM Automate.app" "$INSTALL_RESOURCES/OM Automate.app"
/usr/bin/ditto "$PAYLOAD_DIR" "$INSTALL_RESOURCES/payload"
/usr/bin/ditto "$ROOT_DIR/scripts/install-internal-macos-test.command" "$DMG_ROOT/Install OM Automate.command"
chmod 755 "$DMG_ROOT/Install OM Automate.command"

echo "Verifying payload hygiene"
for forbidden in .git .env __pycache__; do
  if find "$INSTALL_RESOURCES/payload" -name "$forbidden" -print -quit | grep -q .; then
    echo "Forbidden path found in installer payload: $forbidden" >&2
    exit 1
  fi
done
for forbidden in data logs venv tests tmp_pytest_probe dist build .build .coverage htmlcov; do
  if [ -e "$INSTALL_RESOURCES/payload/$forbidden" ]; then
    echo "Forbidden top-level path found in installer payload: $forbidden" >&2
    exit 1
  fi
done
if find "$INSTALL_RESOURCES/payload" -type f \( -name '*.log' -o -name '*.db' -o -name '*.sqlite' -o -name '*.sqlite3' \) -print -quit | grep -q .; then
  echo "Generated logs or databases were found in the installer payload." >&2
  exit 1
fi
if rg -F -l "$HOME" "$INSTALL_RESOURCES" >/dev/null 2>&1; then
  echo "The build machine's home path was found in the installer." >&2
  exit 1
fi

/usr/bin/plutil -lint "$INSTALL_RESOURCES/OM Automate.app/Contents/Info.plist" >/dev/null
test -x "$INSTALL_RESOURCES/OM Automate.app/Contents/MacOS/OM Automate"
test -x "$DMG_ROOT/Install OM Automate.command"

echo "Creating $OUTPUT_DMG"
rm -f "$OUTPUT_DMG"
/usr/bin/hdiutil create \
  -volname "OM Automate Internal Test" \
  -srcfolder "$DMG_ROOT" \
  -ov -format UDZO \
  "$OUTPUT_DMG" >/dev/null
chmod 644 "$OUTPUT_DMG"

echo "Built: $OUTPUT_DMG"
echo "Launcher status: not_requested (the installer creates ~/Applications/OM Automate.app)."
