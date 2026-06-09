-- ProspektLab Supabase required table verification
-- Run after deployment/supabase_bootstrap.sql and deployment/ikg_db_bootstrap.sql.

with required(table_name) as (
  values
    ('profiles'),
    ('portfolio_mirrors'),
    ('rate_limits'),
    ('verification_codes'),
    ('pending_extractions'),
    ('revoked_tokens'),
    ('token_usage'),
    ('ikg_company_master'),
    ('shp_raw'),
    ('directors_raw'),
    ('director_source_records'),
    ('daily_prices'),
    ('company_financials'),
    ('enforcement_raw'),
    ('sebi_corporate_filing_map'),
    ('corporate_filings_raw'),
    ('concall_transcripts_raw'),
    ('annual_reports_raw'),
    ('annual_report_chunks'),
    ('document_sections'),
    ('ikg_vertices'),
    ('ikg_edges'),
    ('ikg_canonical_entities'),
    ('ikg_entity_aliases'),
    ('ikg_facts'),
    ('ikg_pipeline_runs'),
    ('ikg_scheduler_locks')
)
select
  r.table_name,
  case when t.table_name is null then 'missing' else 'ok' end as status,
  coalesce(c.relrowsecurity, false) as rls_enabled
from required r
left join information_schema.tables t
  on t.table_schema = 'public'
 and t.table_name = r.table_name
left join pg_class c
  on c.relname = r.table_name
 and c.relnamespace = 'public'::regnamespace
order by r.table_name;

notify pgrst, 'reload schema';
