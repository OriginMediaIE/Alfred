#!/bin/bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_ROOT="$SCRIPT_DIR/.om-install"
SOURCE_APP="$SOURCE_ROOT/OM Automate.app"
SOURCE_PAYLOAD="$SOURCE_ROOT/payload"
INSTALL_ROOT="$HOME/Library/Application Support/OM Automate"
INSTALL_DIR="$INSTALL_ROOT/app"
DATA_DIR="$INSTALL_ROOT/data"
TARGET_APP="$HOME/Applications/OM Automate.app"

if [ "$(uname -s)" != "Darwin" ] || [ "$(uname -m)" != "arm64" ]; then
  echo "OM Automate Internal Test requires an Apple Silicon Mac."
  read -r -p "Press Return to close..." _
  exit 1
fi

if [ ! -d "$SOURCE_PAYLOAD" ] || [ ! -d "$SOURCE_APP" ]; then
  echo "The installer payload is incomplete. Download a fresh DMG and try again."
  read -r -p "Press Return to close..." _
  exit 1
fi

echo "Installing OM Automate Internal Test..."
mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$HOME/Applications"

# Keep user state and the Python environment across upgrades while replacing
# stale application files with the sanitized payload from this release.
/usr/bin/rsync -a --delete \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude 'venv/' \
  "$SOURCE_PAYLOAD/" "$INSTALL_DIR/"

if [ ! -f "$INSTALL_DIR/.env" ]; then
  /bin/cat > "$INSTALL_DIR/.env" <<ENV
AUTH_ENABLED=true
LOCALHOST_BYPASS=false
APP_BIND=127.0.0.1
APP_PORT=7860
ODYSSEUS_HOST=127.0.0.1
ODYSSEUS_DATA_DIR=$DATA_DIR
OM_AUTOMATE_INTERNAL_TEST_DEFAULTS=1
ODYSSEUS_ADMIN_USER=Admin
ODYSSEUS_ADMIN_PASSWORD=Admin
SEARXNG_INSTANCE=http://localhost:8080
ENV
  chmod 600 "$INSTALL_DIR/.env"
fi

mkdir -p "$TARGET_APP"
/usr/bin/rsync -a --delete "$SOURCE_APP/" "$TARGET_APP/"
chmod 755 "$INSTALL_DIR/start-macos.sh" "$TARGET_APP/Contents/MacOS/OM Automate"
/usr/bin/xattr -dr com.apple.quarantine "$TARGET_APP" 2>/dev/null || true

echo
echo "Installed: $TARGET_APP"
echo "Login: Admin / Admin"
echo "The first launch may take several minutes while local dependencies install."
echo
/usr/bin/open "$TARGET_APP"
