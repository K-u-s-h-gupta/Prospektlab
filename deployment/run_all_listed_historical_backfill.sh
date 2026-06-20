#!/usr/bin/env bash
set -euo pipefail

# Run complete historical IKG build for all listed NSE/BSE companies.
# Historical knobs:
# - annual reports: 3 years
# - shareholding pattern: 5 years (20 quarters)

docker compose -f deployment/docker-compose.ikg.yml up -d --build scheduler celery-worker

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
  deployment-scheduler-1 \
  python -m finagent.ikg.pipeline.orchestrator --phase historical_backfill --years-back 3
