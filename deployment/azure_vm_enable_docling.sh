#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
REQ_FILE="$ROOT/deployment/requirements.ikg-worker.txt"

if [ ! -f "$REQ_FILE" ]; then
  echo "requirements file not found: $REQ_FILE" >&2
  exit 1
fi

if ! grep -q '^docling>=' "$REQ_FILE"; then
  # Insert after pypdf if present, else append.
  if grep -q '^pypdf>=' "$REQ_FILE"; then
    awk '
      { print }
      /^pypdf>=/ { print "docling>=2.0.0" }
    ' "$REQ_FILE" > "$REQ_FILE.tmp"
    mv "$REQ_FILE.tmp" "$REQ_FILE"
  else
    printf '\ndocling>=2.0.0\n' >> "$REQ_FILE"
  fi
fi

cd "$ROOT/deployment"
docker compose -f docker-compose.ikg.yml up -d --build scheduler celery-worker
docker exec deployment-scheduler-1 python -c 'import docling; print("docling_ok", docling.__version__)'

