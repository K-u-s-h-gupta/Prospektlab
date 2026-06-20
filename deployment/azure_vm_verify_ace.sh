#!/usr/bin/env bash
set -euo pipefail

SYMBOL="MAPMYINDIA"
CIN="L74899DL1995PLC065551"
BSE_SCRIP="543425"

docker exec deployment-postgres-1 psql -U ikg_user -d ikg -Atc "
select 'financials=' || count(*) from company_financials where upper(coalesce(nse_symbol,'')) = '${SYMBOL}'
union all
select 'shp=' || count(*) from shp_raw where cin = '${CIN}' or coalesce(scrip_code,'') = '${BSE_SCRIP}'
union all
select 'corp_filings=' || count(*) from corporate_filings_raw where cin = '${CIN}' or upper(coalesce(symbol,'')) = '${SYMBOL}' or coalesce(scrip_code,'') = '${BSE_SCRIP}'
union all
select 'corp_filings_with_text=' || count(*) from corporate_filings_raw where (cin = '${CIN}' or upper(coalesce(symbol,'')) = '${SYMBOL}' or coalesce(scrip_code,'') = '${BSE_SCRIP}') and coalesce(attachment_text_length,0) > 0
union all
select 'annual_reports=' || count(*) from annual_reports_raw where cin = '${CIN}' or upper(coalesce(nse_symbol,'')) = '${SYMBOL}' or coalesce(scrip_code,'') = '${BSE_SCRIP}'
union all
select 'concall=' || count(*) from concall_transcripts_raw where cin = '${CIN}' or upper(coalesce(symbol,'')) = '${SYMBOL}'
union all
select 'directors=' || count(*) from directors_raw where cin = '${CIN}' or upper(coalesce(nse_symbol,'')) = '${SYMBOL}' or coalesce(bse_scrip_code,'') = '${BSE_SCRIP}'
union all
select 'director_source_records=' || count(*) from director_source_records where cin = '${CIN}' or upper(coalesce(nse_symbol,'')) = '${SYMBOL}' or coalesce(bse_scrip_code,'') = '${BSE_SCRIP}'
union all
select 'sections=' || count(*) from document_sections where coalesce(metadata->>'cin','') = '${CIN}' or upper(coalesce(metadata->>'nse_symbol','')) = '${SYMBOL}' or coalesce(metadata->>'bse_scrip_code','') = '${BSE_SCRIP}'
union all
select 'vertices=' || count(*) from ikg_vertices where vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}')
union all
select 'edges=' || count(*) from ikg_edges where from_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}') or to_vertex_id in ('company:${CIN}','company:${SYMBOL}','company:${BSE_SCRIP}');
"
