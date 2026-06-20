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

OPENAI_KEY="$(printf '%s' '__OPENAI_KEY_B64__' | base64 -d)"
ENV_FILE="$ROOT/backend/finagent/.env"

python3 - <<PY
from pathlib import Path

env_path = Path("$ENV_FILE")
key = """$OPENAI_KEY""".strip()
if not env_path.exists():
    raise SystemExit(f"Missing env file: {env_path}")

lines = env_path.read_text(encoding="utf-8").splitlines()
updated = False
for idx, line in enumerate(lines):
    if line.startswith("OPENAI_API_KEY="):
        lines[idx] = f"OPENAI_API_KEY={key}"
        updated = True
        break
if not updated:
    lines.append(f"OPENAI_API_KEY={key}")
env_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("openai_key_updated", str(env_path))
PY

cd "$ROOT/deployment"
docker compose -f docker-compose.ikg.yml up -d --force-recreate scheduler celery-worker
docker compose -f docker-compose.ikg.yml ps scheduler celery-worker
