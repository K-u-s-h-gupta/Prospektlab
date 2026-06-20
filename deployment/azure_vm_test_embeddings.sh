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
import asyncio
import os

from openai import AsyncOpenAI
from finagent.runtime_provider import resolve_openai_config

cfg = resolve_openai_config()
if not cfg:
    raise RuntimeError("No runtime provider config found")
model = os.getenv("FINAGENT_EMBEDDING_MODEL", "text-embedding-3-small")

async def main():
    client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=60.0)
    resp = await client.embeddings.create(model=model, input=["quick embedding probe for ikg qdrant"])
    print("embedding_ok", len(resp.data), len(resp.data[0].embedding))
    print("model_used", model)
    print("base_url", cfg.base_url or "default_openai")

asyncio.run(main())
PY
'

