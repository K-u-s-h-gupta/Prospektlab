#!/usr/bin/env bash
set -euo pipefail

SYMBOL="MAPMYINDIA"
CIN="L74899DL1995PLC065551"
BSE_SCRIP="543425"
COMPANY_NAME="C.E. INFO SYSTEMS LIMITED"

echo "[1/4] Running one-company IKG build (fast verification profile) for ${SYMBOL}"
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
  --qdrant-limit 30

echo "[2/4] Verifying finance freshness"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select
  'financials_rows=' || count(*)
from company_financials
where upper(coalesce(nse_symbol,'')) = '${SYMBOL}';
select
  'financials_last_fetched=' || coalesce(to_char(max(fetched_at), 'YYYY-MM-DD HH24:MI:SS'), 'null')
from company_financials
where upper(coalesce(nse_symbol,'')) = '${SYMBOL}';
select
  'financials_last_updated=' || coalesce(to_char(max(updated_at), 'YYYY-MM-DD HH24:MI:SS'), 'null')
from company_financials
where upper(coalesce(nse_symbol,'')) = '${SYMBOL}';
"

echo "[3/4] Verifying filing extraction error profile"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select 'corp_failed=' || count(*)
from corporate_filings_raw
where (cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}')
  and coalesce(attachment_extraction_status,'')='failed';
select 'corp_404_dash=' || count(*)
from corporate_filings_raw
where (cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}')
  and coalesce(attachment_extraction_error,'') ilike '%404%'
  and coalesce(attachment_url,'') ilike '%nseindia.com/-%';
select 'corp_nul_errors=' || count(*)
from corporate_filings_raw
where (cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}')
  and coalesce(attachment_extraction_error,'') ilike '%NUL%';
"

echo "[4/4] Verifying coverage counts"
docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select 'annual_reports=' || count(*) from annual_reports_raw where cin='${CIN}' or upper(coalesce(nse_symbol,''))='${SYMBOL}'
union all
select 'corp_filings=' || count(*) from corporate_filings_raw where cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}'
union all
select 'corp_filings_with_text=' || count(*) from corporate_filings_raw where (cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}') and coalesce(attachment_text_length,0)>0
union all
select 'concalls=' || count(*) from concall_transcripts_raw where cin='${CIN}' or upper(coalesce(symbol,''))='${SYMBOL}'
union all
select 'directors=' || count(*) from directors_raw where cin='${CIN}' or upper(coalesce(nse_symbol,''))='${SYMBOL}'
union all
select 'sections=' || count(*) from document_sections where coalesce(metadata->>'cin','')='${CIN}' or upper(coalesce(metadata->>'nse_symbol',''))='${SYMBOL}'
union all
select 'edges=' || count(*) from ikg_edges where from_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}') or to_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}');
"
