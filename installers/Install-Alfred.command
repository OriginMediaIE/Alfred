#!/usr/bin/env bash
# Double-click installer for Alfred / OM Automate on macOS.
set -Eeuo pipefail

REPOSITORY="OriginMediaIE/Alfred"
INSTALL_DIR="${ALFRED_INSTALL_DIR:-$HOME/Library/Application Support/Alfred}"
REQUESTED_REF="${ALFRED_RELEASE_REF:-latest}"
DOWNLOAD_ROOT=""

pause_on_exit() {
  local status=$?
  if ((status == 0)); then
    printf '\nAlfred installation finished successfully.\n'
  else
    printf '\nAlfred was not installed. Read the error above, then run this installer again.\n' >&2
  fi
  if [[ -t 0 ]]; then
    printf 'Press Return to close this window.'
    IFS= read -r _ || true
  fi
  exit "$status"
}

cleanup() {
  [[ -z "$DOWNLOAD_ROOT" ]] || rm -rf -- "$DOWNLOAD_ROOT"
}

trap cleanup EXIT
trap pause_on_exit ERR

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; return 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This installer is for macOS. Use Install-Alfred.cmd on Windows."

step "Checking Docker Desktop"
if ! command -v docker >/dev/null 2>&1; then
  open "https://www.docker.com/products/docker-desktop/" >/dev/null 2>&1 || true
  fail "Docker Desktop is required. The download page has been opened. Install it, open it, then double-click this installer again."
fi

if ! docker info >/dev/null 2>&1; then
  open -a Docker >/dev/null 2>&1 || true
  printf 'Docker Desktop is starting'
  for _ in {1..60}; do
    if docker info >/dev/null 2>&1; then
      printf ' ready.\n'
      break
    fi
    printf '.'
    sleep 2
  done
  docker info >/dev/null 2>&1 || fail "Docker Desktop did not become ready. Open Docker Desktop, wait for it to finish starting, and run this installer again."
fi

step "Choosing the Alfred release"
RELEASE_REF="$REQUESTED_REF"
if [[ "$REQUESTED_REF" == "latest" ]]; then
  LATEST_URL="$(curl -fsSL -o /dev/null -w '%{url_effective}' "https://github.com/$REPOSITORY/releases/latest" || true)"
  RELEASE_REF="${LATEST_URL##*/}"
  if [[ -z "$RELEASE_REF" || "$RELEASE_REF" == "latest" ]]; then
    RELEASE_REF="main"
    printf 'No tagged release was found; using the main branch.\n'
  fi
fi
[[ "$RELEASE_REF" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && "$RELEASE_REF" != *".."* ]] || fail "The requested release name is not safe: $RELEASE_REF"
printf 'Installing release: %s\n' "$RELEASE_REF"

step "Downloading Alfred from GitHub"
DOWNLOAD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/alfred-installer.XXXXXX")"
mkdir -p "$DOWNLOAD_ROOT/source"
curl --fail --location --retry 3 --connect-timeout 20 \
  "https://github.com/$REPOSITORY/archive/$RELEASE_REF.tar.gz" \
  -o "$DOWNLOAD_ROOT/alfred.tar.gz"
tar -xzf "$DOWNLOAD_ROOT/alfred.tar.gz" -C "$DOWNLOAD_ROOT/source" --strip-components=1
[[ -f "$DOWNLOAD_ROOT/source/docker-compose.yml" ]] || fail "The downloaded release is incomplete."

step "Installing Alfred"
mkdir -p "$INSTALL_DIR" "$INSTALL_DIR/data" "$INSTALL_DIR/logs"
/usr/bin/rsync -a --delete \
  --exclude='.env' \
  --exclude='.env.bak.*' \
  --exclude='secrets.env' \
  --exclude='secrets.env.*' \
  --exclude='data/' \
  --exclude='logs/' \
  "$DOWNLOAD_ROOT/source/" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/install-om-automate.sh" "$INSTALL_DIR/Start-Alfred.command"
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env" 2>/dev/null || true
fi

step "Starting Alfred"
(
  cd "$INSTALL_DIR"
  ./install-om-automate.sh --pull
)

step "Creating the Alfred application icon"
"$INSTALL_DIR/scripts/install-docker-launcher.sh" --pin || printf 'The app is installed, but the optional Dock launcher could not be created.\n'

printf '\nInstalled files: %s\n' "$INSTALL_DIR"
printf 'Private data:    %s/data\n' "$INSTALL_DIR"
printf 'Open Alfred:     http://127.0.0.1:7000\n'

cleanup
DOWNLOAD_ROOT=""
trap - EXIT ERR
pause_on_exit
