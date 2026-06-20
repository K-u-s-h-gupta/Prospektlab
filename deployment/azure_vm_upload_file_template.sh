#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
if [ ! -d "$ROOT/backend/finagent" ]; then
  CANDIDATE="$(find /home -maxdepth 5 -path '*/backend/finagent' -type d 2>/dev/null | head -n 1 || true)"
  if [ -n "$CANDIDATE" ]; then
    ROOT="$(dirname "$(dirname "$CANDIDATE")")"
  fi
fi

TARGET="$ROOT/__TARGET_REL_PATH__"
mkdir -p "$(dirname "$TARGET")"
printf '%s' '__FILE_B64__' | base64 -d > "$TARGET"
echo "uploaded=$TARGET"

