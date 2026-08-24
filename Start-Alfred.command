#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$PROJECT_DIR"

if ! command -v docker >/dev/null 2>&1; then
  open "https://www.docker.com/products/docker-desktop/" >/dev/null 2>&1 || true
  printf 'Docker Desktop is required. Install it, then open Alfred again.\n' >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  open -a Docker >/dev/null 2>&1 || true
  printf 'Starting Docker Desktop'
  for _ in {1..60}; do
    if docker info >/dev/null 2>&1; then
      printf ' ready.\n'
      break
    fi
    printf '.'
    sleep 2
  done
  if ! docker info >/dev/null 2>&1; then
    printf '\nDocker Desktop did not become ready. Open Docker Desktop and try again.\n' >&2
    exit 1
  fi
fi

exec ./install-om-automate.sh --no-build "$@"
