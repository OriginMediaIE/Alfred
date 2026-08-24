#!/usr/bin/env bash
# Supported Docker installer/launcher for macOS and Linux.
set -Eeuo pipefail

APP_NAME="OM Automate"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CHECK_ONLY=0
NO_OPEN=0
NO_BUILD=0
TIMEOUT_SECONDS=240
ACCELERATOR="${OM_AUTOMATE_ACCELERATOR:-cpu}"

usage() {
  printf '%s\n' \
    "${APP_NAME} installer" \
    "" \
    "Usage: ./install-om-automate.sh [options]" \
    "" \
    "  --check             Validate the host/config without pulling or building" \
    "  --no-build          Start the already-built exact local image" \
    "  --no-open           Do not open a browser after the health gate" \
    "  --accelerator NAME  cpu (default), nvidia, or amd" \
    "  --timeout SECONDS   Health wait limit (default: 240)" \
    "  --help              Show this help"
}

while (($#)); do
  case "$1" in
    --check) CHECK_ONLY=1 ;;
    --no-build) NO_BUILD=1 ;;
    --no-open) NO_OPEN=1 ;;
    --accelerator)
      shift
      [[ $# -gt 0 ]] || { printf 'Missing accelerator value.\n' >&2; exit 2; }
      ACCELERATOR="$1"
      ;;
    --timeout)
      shift
      [[ "${1:-}" =~ ^[1-9][0-9]*$ ]] || { printf 'Timeout must be a positive integer.\n' >&2; exit 2; }
      TIMEOUT_SECONDS="$1"
      ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$ACCELERATOR" in
  cpu|nvidia|amd) ;;
  *) printf 'Unsupported accelerator %q (use cpu, nvidia, or amd).\n' "$ACCELERATOR" >&2; exit 2 ;;
esac

cd "$REPO_DIR"
umask 077

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "$2"; }
is_true() { case "${1:-}" in 1|true|TRUE|True|yes|YES|Yes|on|ON|On) return 0 ;; *) return 1 ;; esac; }
is_false() { case "${1:-}" in 0|false|FALSE|False|no|NO|No|off|OFF|Off) return 0 ;; *) return 1 ;; esac; }

read_env_value() {
  local key="$1" file="${2:-.env}"
  [[ -f "$file" ]] || return 0
  awk -F= -v wanted="$key" '
    $0 !~ /^[[:space:]]*#/ && $1 == wanted {
      sub(/^[^=]*=/, "")
      sub(/^[[:space:]]+/, ""); sub(/[[:space:]]+$/, "")
      first = substr($0, 1, 1); last = substr($0, length($0), 1)
      if (length($0) >= 2 && ((first == "\"" && last == "\"") || (first == "\047" && last == "\047"))) {
        $0 = substr($0, 2, length($0) - 2)
      }
      print; exit
    }
  ' "$file"
}

validate_data_path() {
  local raw="$1" resolved
  [[ -n "$raw" ]] || fail "APP_DATA_DIR cannot be empty."
  [[ "$raw" != "/" && "$raw" != "." && "$raw" != "./" ]] || fail "Refusing to use a broad data path: $raw"
  [[ "$raw" != *$'\n'* && "$raw" != *$'\r'* ]] || fail "APP_DATA_DIR contains a newline."
  if [[ -e "$raw" && -L "$raw" ]]; then
    fail "Refusing symlinked APP_DATA_DIR: $raw"
  fi
  mkdir -p -- "$raw"
  resolved="$(cd "$raw" && pwd -P)"
  [[ "$resolved" != "$REPO_DIR" && "$resolved" != "/" ]] || fail "APP_DATA_DIR resolves to an unsafe location: $resolved"
  chmod 700 "$resolved" 2>/dev/null || true
  printf '%s' "$resolved"
}

step "Preflight"
require_command docker "Docker Engine/Desktop with Compose v2 is required."
require_command curl "curl is required for the bounded health verification."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is unavailable (expected: docker compose)."
docker info >/dev/null 2>&1 || fail "Docker is installed but its daemon is not running."

case "$(uname -s)" in
  Darwin|Linux) ;;
  *) fail "This entry point supports macOS and Linux. On Windows run install-om-automate.cmd." ;;
esac

if [[ ! -f .env ]]; then
  step "Creating private environment file"
  cp .env.example .env
  chmod 600 .env 2>/dev/null || true
  printf 'Created .env without overwriting any existing configuration.\n'
else
  chmod 600 .env 2>/dev/null || true
  printf 'Using existing .env unchanged.\n'
fi

DATA_PATH_RAW="${APP_DATA_DIR:-$(read_env_value APP_DATA_DIR)}"
DATA_PATH_RAW="${DATA_PATH_RAW:-./data}"
DATA_PATH="$(validate_data_path "$DATA_PATH_RAW")"
printf 'Data path: %s\n' "$DATA_PATH"

BIND_VALUE="${APP_BIND:-$(read_env_value APP_BIND)}"
BIND_VALUE="${BIND_VALUE:-127.0.0.1}"
if [[ "$BIND_VALUE" != "127.0.0.1" && "$BIND_VALUE" != "localhost" ]]; then
  [[ "${OM_AUTOMATE_ALLOW_NETWORK:-0}" == "1" ]] || fail "APP_BIND=$BIND_VALUE is not loopback. Set OM_AUTOMATE_ALLOW_NETWORK=1 only after configuring authenticated HTTPS."
  AUTH_VALUE="${AUTH_ENABLED:-$(read_env_value AUTH_ENABLED)}"
  BYPASS_VALUE="${LOCALHOST_BYPASS:-$(read_env_value LOCALHOST_BYPASS)}"
  COOKIES_VALUE="${SECURE_COOKIES:-$(read_env_value SECURE_COOKIES)}"
  ORIGINS_VALUE="${ALLOWED_ORIGINS:-$(read_env_value ALLOWED_ORIGINS)}"
  is_true "${AUTH_VALUE:-true}" || fail "Network binding requires AUTH_ENABLED=true."
  is_false "${BYPASS_VALUE:-false}" || fail "Network binding requires LOCALHOST_BYPASS=false."
  is_true "${COOKIES_VALUE:-false}" || fail "Network binding requires SECURE_COOKIES=true behind HTTPS."
  [[ "$ORIGINS_VALUE" == *"https://"* ]] || fail "Network binding requires an exact HTTPS origin in ALLOWED_ORIGINS."
fi
PORT_VALUE="${APP_PORT:-$(read_env_value APP_PORT)}"
PORT_VALUE="${PORT_VALUE:-7000}"
[[ "$PORT_VALUE" =~ ^[0-9]+$ ]] && ((PORT_VALUE >= 1 && PORT_VALUE <= 65535)) || fail "APP_PORT must be between 1 and 65535."

COMPOSE_ARGS=(-f docker-compose.yml)
case "$ACCELERATOR" in
  nvidia) COMPOSE_ARGS+=(-f docker/gpu.nvidia.yml) ;;
  amd) COMPOSE_ARGS+=(-f docker/gpu.amd.yml) ;;
esac
docker compose "${COMPOSE_ARGS[@]}" config --quiet
printf 'Compose configuration: valid (%s profile).\n' "$ACCELERATOR"

if ((CHECK_ONLY)); then
  printf '\nPreflight passed. No images were pulled, built, or started.\n'
  exit 0
fi

LOCK_DIR="$REPO_DIR/.om-automate-install.lock"
mkdir "$LOCK_DIR" 2>/dev/null || fail "Another install appears to be running ($LOCK_DIR)."
cleanup() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

step "Starting exact OM Automate services"
if ((NO_BUILD)); then
  docker compose "${COMPOSE_ARGS[@]}" up -d
else
  docker compose "${COMPOSE_ARGS[@]}" up -d --build
fi

HEALTH_HOST="$BIND_VALUE"
[[ "$HEALTH_HOST" == "0.0.0.0" || "$HEALTH_HOST" == "::" ]] && HEALTH_HOST="127.0.0.1"
HEALTH_URL="http://${HEALTH_HOST}:${PORT_VALUE}/api/health"
READY_URL="http://${HEALTH_HOST}:${PORT_VALUE}/api/ready"
DEADLINE=$((SECONDS + TIMEOUT_SECONDS))

step "Waiting for the application readiness gate"
until curl --fail --silent --show-error --max-time 4 "$READY_URL" >/dev/null 2>&1; do
  if ((SECONDS >= DEADLINE)); then
    docker compose "${COMPOSE_ARGS[@]}" ps >&2 || true
    fail "Readiness verification timed out after ${TIMEOUT_SECONDS}s. Inspect with: docker compose logs --tail=200 odysseus"
  fi
  sleep 2
done

docker compose "${COMPOSE_ARGS[@]}" ps
printf '\n%s is live at %s and ready at %s\n' "$APP_NAME" "$HEALTH_URL" "$READY_URL"
printf 'Your existing .env and data directory were preserved.\n'

if ((NO_OPEN == 0)); then
  case "$(uname -s)" in
    Darwin) open "http://${HEALTH_HOST}:${PORT_VALUE}" >/dev/null 2>&1 || true ;;
    Linux) command -v xdg-open >/dev/null 2>&1 && xdg-open "http://${HEALTH_HOST}:${PORT_VALUE}" >/dev/null 2>&1 || true ;;
  esac
fi
