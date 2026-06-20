#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
if [ ! -d "$ROOT/deployment" ]; then
  CANDIDATE="$(find /home -maxdepth 5 -path '*/prospektlab/deployment' -type d 2>/dev/null | head -n 1 || true)"
  if [ -n "$CANDIDATE" ]; then
    ROOT="$(dirname "$CANDIDATE")"
  fi
fi

cd "$ROOT/deployment"
echo "ROOT=$ROOT"
docker ps --format '{{.Names}} {{.Status}}' | grep -E 'deployment-(scheduler|celery-worker|postgres|redis|qdrant)-1' || true
docker exec deployment-scheduler-1 python -c 'import docling; print("docling_ok", docling.__version__)'
docker exec deployment-scheduler-1 python -m finagent.ikg.pipeline.orchestrator --phase health

