#!/usr/bin/env bash
set -euo pipefail

container="${IKG_POSTGRES_CONTAINER:-deployment-postgres-1}"

docker exec "$container" psql -U ikg_user -d ikg -tAc "
select 'ikg_company_master=' || count(1) from ikg_company_master union all
select 'corporate_filings_raw=' || count(1) from corporate_filings_raw union all
select 'corporate_filings_with_text=' || count(1) from corporate_filings_raw where coalesce(attachment_text_length, 0) > 0 union all
select 'xbrl_filings_raw=' || count(1) from xbrl_filings_raw union all
select 'corporate_xbrl_facts=' || count(1) from corporate_xbrl_facts union all
select 'financial_results_xbrl=' || count(1) from financial_results_xbrl union all
select 'corporate_event_xbrl=' || count(1) from corporate_event_xbrl union all
select 'corporate_actions_raw=' || count(1) from corporate_actions_raw union all
select 'company_financials=' || count(1) from company_financials union all
select 'shp_raw=' || count(1) from shp_raw union all
select 'annual_reports_raw=' || count(1) from annual_reports_raw union all
select 'document_sections=' || count(1) from document_sections union all
select 'concall_transcripts_raw=' || count(1) from concall_transcripts_raw union all
select 'enforcement_raw=' || count(1) from enforcement_raw union all
select 'ikg_vertices=' || count(1) from ikg_vertices union all
select 'ikg_edges=' || count(1) from ikg_edges union all
select 'ikg_facts=' || count(1) from ikg_facts;
"

docker exec "$container" psql -U ikg_user -d ikg -tAc "
select task_name || ' success=' || success || ' fetched=' || records_fetched ||
       ' stored=' || records_stored || ' failed=' || records_failed ||
       ' completed=' || coalesce(completed_at::text, '')
from ikg_pipeline_runs
order by started_at desc
limit 12;
"
