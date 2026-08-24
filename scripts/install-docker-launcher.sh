#!/usr/bin/env bash
# Create a native macOS app wrapper for the Docker installation.
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
APP_DIR="${ALFRED_LAUNCHER_DIR:-$HOME/Applications}/Alfred.app"
PIN=0
REPLACE=0

while (($#)); do
  case "$1" in
    --pin) PIN=1 ;;
    --replace) REPLACE=1 ;;
    --help|-h)
      printf 'Usage: %s [--pin] [--replace]\n' "$0"
      exit 0
      ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

[[ "$(uname -s)" == "Darwin" ]] || { printf 'This launcher installer is for macOS.\n' >&2; exit 1; }

if [[ -e "$APP_DIR" && $REPLACE -eq 0 ]]; then
  printf 'Launcher already exists: %s\n' "$APP_DIR"
  if ((PIN)) && defaults read com.apple.dock persistent-apps 2>/dev/null | grep -Fq "$APP_DIR"; then
    printf 'pin_status=already_pinned\n'
  elif ((PIN)); then
    printf 'pin_status=manual_pin_required\n'
  else
    printf 'pin_status=not_requested\n'
  fi
  exit 0
fi

PARENT_DIR="$(dirname "$APP_DIR")"
mkdir -p "$PARENT_DIR"
TEMP_APP="$PARENT_DIR/.Alfred.app.new.$$"
rm -rf -- "$TEMP_APP"
mkdir -p "$TEMP_APP/Contents/MacOS" "$TEMP_APP/Contents/Resources"

PROJECT_QUOTED="$(printf '%q' "$PROJECT_DIR")"
cat > "$TEMP_APP/Contents/MacOS/alfred" <<EOF
#!/bin/zsh
set -u
log_dir="\$HOME/Library/Logs/Alfred"
mkdir -p "\$log_dir"
cd -- $PROJECT_QUOTED
exec ./Start-Alfred.command >>"\$log_dir/docker-launcher.log" 2>&1
EOF
chmod 755 "$TEMP_APP/Contents/MacOS/alfred"

cat > "$TEMP_APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Alfred</string>
  <key>CFBundleDisplayName</key><string>Alfred</string>
  <key>CFBundleIdentifier</key><string>ie.originmedia.alfred.docker</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>alfred</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

ICON_SOURCE="$PROJECT_DIR/static/brand/om-icon-512.png"
if [[ -f "$ICON_SOURCE" ]]; then
  sips -s format icns "$ICON_SOURCE" --out "$TEMP_APP/Contents/Resources/AppIcon.icns" >/dev/null 2>&1 || true
fi
/usr/bin/plutil -lint "$TEMP_APP/Contents/Info.plist" >/dev/null

if [[ -e "$APP_DIR" ]]; then
  rm -rf -- "$APP_DIR"
fi
mv "$TEMP_APP" "$APP_DIR"
touch "$APP_DIR"

PIN_STATUS="not_requested"
if ((PIN)); then
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -Fq "$APP_DIR"; then
    PIN_STATUS="already_pinned"
  elif command -v dockutil >/dev/null 2>&1; then
    if dockutil --add "$APP_DIR" --no-restart >/dev/null 2>&1; then
      killall Dock >/dev/null 2>&1 || true
      PIN_STATUS="pinned"
    else
      PIN_STATUS="manual_pin_required"
    fi
  elif [[ "$APP_DIR" != *'&'* && "$APP_DIR" != *'<'* && "$APP_DIR" != *'>'* ]]; then
    TILE="<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP_DIR</string><key>_CFURLStringType</key><integer>0</integer></dict></dict></dict>"
    if defaults write com.apple.dock persistent-apps -array-add "$TILE"; then
      killall Dock >/dev/null 2>&1 || true
      PIN_STATUS="pinned"
    else
      PIN_STATUS="manual_pin_required"
    fi
  else
    PIN_STATUS="manual_pin_required"
  fi
fi

printf 'launcher=%s\n' "$APP_DIR"
printf 'icon_source=%s\n' "$ICON_SOURCE"
printf 'pin_status=%s\n' "$PIN_STATUS"
