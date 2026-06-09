-- Guarded Supabase cleanup after moving IKG data to worker Postgres.
--
-- Run deployment/migrate_ikg_supabase_to_worker_postgres.py first and verify
-- source/target row counts. This script is deliberately blocked until you set
-- really_prune := true.
--
-- Supabase should keep app/auth/product tables. IKG staging, graph, document,
-- and scheduler tables should live in worker Postgres.

do $$
declare
  really_prune boolean := false;
begin
  if not really_prune then
    raise exception 'Prune guard is OFF. Verify worker Postgres counts, then set really_prune := true.';
  end if;

  drop table if exists public.ikg_facts cascade;
  drop table if exists public.ikg_edges cascade;
  drop table if exists public.ikg_vertices cascade;
  drop table if exists public.document_sections cascade;
  drop table if exists public.annual_report_chunks cascade;
  drop table if exists public.annual_reports_raw cascade;
  drop table if exists public.corporate_xbrl_facts cascade;
  drop table if exists public.financial_results_xbrl cascade;
  drop table if exists public.corporate_event_xbrl cascade;
  drop table if exists public.xbrl_filings_raw cascade;
  drop table if exists public.corporate_actions_raw cascade;
  drop table if exists public.corporate_filings_raw cascade;
  drop table if exists public.sebi_corporate_filing_map cascade;
  drop table if exists public.enforcement_raw cascade;
  drop table if exists public.concall_transcripts_raw cascade;
  drop table if exists public.director_source_records cascade;
  drop table if exists public.directors_raw cascade;
  drop table if exists public.company_financials cascade;
  drop table if exists public.shp_raw cascade;
  drop table if exists public.daily_prices cascade;
  drop table if exists public.ikg_company_master cascade;
  drop table if exists public.ikg_pipeline_runs cascade;
  drop table if exists public.ikg_scheduler_locks cascade;
  drop table if exists public.runtime_controls cascade;
  drop table if exists public.spl_strategies cascade;
  drop table if exists public.compliance_ledger cascade;
end $$;
