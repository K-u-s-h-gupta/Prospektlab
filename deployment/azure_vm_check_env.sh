#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
if [ ! -f "$ROOT/deployment/docker-compose.ikg.yml" ]; then
  for candidate in /home/*/prospektlab /home/azureuser/ikg-worker-only /home/azureuser/worker_only_package; do
    if [ -f "$candidate/deployment/docker-compose.ikg.yml" ]; then
      ROOT="$candidate"
      break
    fi
  done
fi

cd "$ROOT/deployment"

docker compose -f docker-compose.ikg.yml exec -T scheduler /bin/sh -lc '
python - << "PY"
import os

keys = [
    "OPENAI_API_KEY",
    "AZURE_AI_FOUNDRY_API_KEY",
    "AZURE_AI_FOUNDRY_OPENAI_BASE_URL",
    "FINAGENT_EMBEDDING_MODEL",
    "FINAGENT_EMBEDDING_BATCH_SIZE",
    "FINAGENT_RETRIEVAL_BACKEND",
]
for key in keys:
    value = os.getenv(key, "")
    state = "SET" if value else "EMPTY"
    print(f"{key}={state} len={len(value)}")
PY
'
