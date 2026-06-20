#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
if [ ! -f "$ROOT/backend/finagent/ikg/scrapers/sebi_corporate_filings.py" ]; then
  CANDIDATE="$(find /home -maxdepth 5 -path '*/backend/finagent/ikg/scrapers/sebi_corporate_filings.py' 2>/dev/null | head -n 1 || true)"
  if [ -n "$CANDIDATE" ]; then
    ROOT="$(dirname "$(dirname "$(dirname "$(dirname "$(dirname "$CANDIDATE")")")")")"
  fi
fi

echo "ROOT=$ROOT"
grep -n "_sanitize_pg_text" "$ROOT/backend/finagent/ikg/scrapers/sebi_corporate_filings.py" | head -n 5 || true
grep -n "_embedding_provider_configs" "$ROOT/backend/finagent/graphrag/qdrant_store.py" | head -n 5 || true

