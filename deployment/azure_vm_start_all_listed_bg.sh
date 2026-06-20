#!/usr/bin/env bash
set -euo pipefail

ROOT="${IKG_ROOT:-/home/ar2108925/prospektlab}"
LOG_DIR="$ROOT/pipeline_logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/all_listed_historical_backfill_$(date +%Y%m%d_%H%M%S).log"

cd "$ROOT/deployment"
docker compose -f docker-compose.ikg.yml up -d scheduler celery-worker

# Run in background so SSH call returns immediately.
nohup bash -lc "
  docker exec \
    -e FINAGENT_LISTED_COMPANY_SCOPE=all_listed \
    -e FINAGENT_NSE_UNIVERSE=all_listed \
    -e FINAGENT_PIPELINE_YEARS_BACK=3 \
    -e FINAGENT_ANNUAL_REPORT_YEARS_BACK=3 \
    -e FINAGENT_ANNUAL_REPORTS_PER_COMPANY=3 \
    -e FINAGENT_ANNUAL_REPORT_EXTRACT_MODE=targeted \
    -e FINAGENT_SHP_QUARTERS=20 \
    -e FINAGENT_BSE_SHP_MAX_QUARTERS=20 \
    -e FINAGENT_CORP_FILINGS_EXTRACT_LIMIT=40 \
    -e FINAGENT_CORP_FILINGS_DOCLING_ENABLED=0 \
    deployment-scheduler-1 \
    python -m finagent.ikg.pipeline.orchestrator --phase historical_backfill --years-back 3
" > "$LOG_FILE" 2>&1 &

PID=$!
echo "started_pid=$PID"
echo "log_file=$LOG_FILE"
