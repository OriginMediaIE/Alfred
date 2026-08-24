#!/bin/bash
# Build OM Automate as a native macOS application backed by WKWebView.
#
# The app remains local-first: it starts this checkout's private Python service
# through start-macos.sh and presents the UI in a native AppKit window. Python,
# user data, and models remain outside the bundle so normal upgrades and backups
# continue to use the existing project layout.
# start-macos.sh installs the exact native dependency profile from
# requirements-om.lock when the target environment is first created.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIRECTORY="${OM_INSTALL_DIRECTORY:-$REPO_DIR}"
BRAND_MANIFEST="$REPO_DIR/static/manifest.json"
NATIVE_SOURCE="$REPO_DIR/native/macos/OMAutomateApp.m"
APP_NAME="$(/usr/bin/plutil -extract om_automate.native_labels.application raw -o - "$BRAND_MANIFEST" 2>/dev/null)" || {
  echo "Brand configuration is missing or invalid: $BRAND_MANIFEST" >&2
  exit 1
}
if [[ ! "$APP_NAME" =~ ^[[:alnum:]][[:alnum:]_.\ -]*$ ]]; then
  echo "Native application name is not safe for a macOS artifact: $APP_NAME" >&2
  exit 1
fi

PORT="${ODYSSEUS_PORT:-${APP_PORT:-7860}}"
DIST="$REPO_DIR/dist"
APP="$DIST/$APP_NAME.app"
CONTENTS="$APP/Contents"
EXECUTABLE="$CONTENTS/MacOS/$APP_NAME"
ICON_NAME="om-automate.icns"

command -v xcrun >/dev/null 2>&1 || {
  echo "Xcode Command Line Tools are required. Run: xcode-select --install" >&2
  exit 1
}
[ -f "$NATIVE_SOURCE" ] || {
  echo "Native application source is missing: $NATIVE_SOURCE" >&2
  exit 1
}
[ -x "$REPO_DIR/start-macos.sh" ] || {
  echo "start-macos.sh must be executable before packaging." >&2
  exit 1
}

echo "Building native $APP_NAME.app"
echo "  project: $REPO_DIR"
echo "  runtime: $INSTALL_DIRECTORY"
echo "  port:    $PORT"

rm -rf "$APP"
mkdir -p "$CONTENTS/MacOS" "$CONTENTS/Resources"

echo "  compiling AppKit + WKWebView shell"
mkdir -p "$REPO_DIR/.build/module-cache"
export CLANG_MODULE_CACHE_PATH="$REPO_DIR/.build/module-cache"
xcrun clang \
  -fobjc-arc \
  -O2 \
  -framework AppKit \
  -framework WebKit \
  "$NATIVE_SOURCE" \
  -o "$EXECUTABLE"
chmod 755 "$EXECUTABLE"

ICON_SOURCE="$REPO_DIR/static/brand/om-icon-512.png"
if [ -f "$ICON_SOURCE" ]; then
  sips -s format icns "$ICON_SOURCE" --out "$CONTENTS/Resources/$ICON_NAME" >/dev/null
  echo "  icon:     $ICON_NAME"
fi

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>$APP_NAME</string>
    <key>CFBundleIdentifier</key>
    <string>com.odysseus.launcher</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundleIconFile</key>
    <string>om-automate</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>OM Automate uses the microphone only when you choose voice input or record a meeting.</string>
    <key>NSCameraUsageDescription</key>
    <string>OM Automate uses the camera only when you choose a feature that captures camera media.</string>
    <key>NSAppTransportSecurity</key>
    <dict>
        <key>NSAllowsLocalNetworking</key>
        <true/>
    </dict>
    <key>OMInstallDirectory</key>
    <string>$INSTALL_DIRECTORY</string>
    <key>OMServerPort</key>
    <string>$PORT</string>
</dict>
</plist>
PLIST

plutil -lint "$CONTENTS/Info.plist" >/dev/null
codesign --force --deep --sign - "$APP" >/dev/null
touch "$APP"

if [ "${OM_SKIP_DMG:-0}" = "1" ]; then
  echo "Skipping DMG packaging (OM_SKIP_DMG=1)"
else
  echo "Packaging $APP_NAME.dmg"
  STAGE_ROOT="$(mktemp -d)"
  STAGE="$STAGE_ROOT/dmg"
  mkdir -p "$STAGE"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  rm -f "$DIST/$APP_NAME.dmg"
  hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DIST/$APP_NAME.dmg" >/dev/null
  rm -rf "$STAGE_ROOT"
fi

echo
echo "Done:"
echo "  $APP"
if [ "${OM_SKIP_DMG:-0}" != "1" ]; then
  echo "  $DIST/$APP_NAME.dmg"
fi
echo
echo "The app uses a native WKWebView window and does not require Chrome."
