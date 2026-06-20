#!/usr/bin/env bash
set -euo pipefail

SYMBOL="MAPMYINDIA"
CIN="L74899DL1995PLC065551"
BSE_SCRIP="543425"
COMPANY_NAME="C.E. INFO SYSTEMS LIMITED"

echo "[1/3] Running one-company historical IKG build for ${SYMBOL} (${CIN})"
docker exec \
  -e FINAGENT_ANNUAL_REPORT_EXTRACT_MODE=targeted \
  -e FINAGENT_CORP_FILINGS_EXTRACT_LIMIT=40 \
  -e FINAGENT_ANNUAL_REPORTS_PER_COMPANY=3 \
  deployment-scheduler-1 python -m finagent.ikg.pipeline.target_company_smoke \
  --symbol "${SYMBOL}" \
  --cin "${CIN}" \
  --bse-scrip "${BSE_SCRIP}" \
  --company-name "${COMPANY_NAME}" \
  --years-back 3 \
  --reports-per-company 3 \
  --qdrant-limit 80

echo "[2/3] Verifying director coverage for ${SYMBOL}"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select
  'directors_raw=' || count(*)
from directors_raw
where cin = '${CIN}';
"

echo "[3/3] Verifying staging + graph coverage for ${SYMBOL}"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select 'financials=' || count(*) from company_financials where upper(coalesce(nse_symbol,'')) = '${SYMBOL}'
union all
select 'shp=' || count(*) from shp_raw where cin = '${CIN}'
union all
select 'corp_filings=' || count(*) from corporate_filings_raw where cin = '${CIN}' or upper(coalesce(symbol,'')) = '${SYMBOL}'
union all
select 'annual_reports=' || count(*) from annual_reports_raw where cin = '${CIN}' or upper(coalesce(nse_symbol,'')) = '${SYMBOL}'
union all
select 'concall=' || count(*) from concall_transcripts_raw where cin = '${CIN}' or upper(coalesce(symbol,'')) = '${SYMBOL}'
union all
select 'sections=' || count(*) from document_sections where coalesce(metadata->>'cin','') = '${CIN}' or upper(coalesce(metadata->>'nse_symbol','')) = '${SYMBOL}'
union all
select 'vertices=' || count(*) from ikg_vertices where vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}')
union all
select 'edges=' || count(*) from ikg_edges where from_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}') or to_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}');
"
