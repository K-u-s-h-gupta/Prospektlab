-- Drop legacy Supabase memory tables after successful Prospekt tiered memory migration.
--
-- Run deployment/migrate_supabase_memory_to_prospekt_memory.py first and verify
-- memory recall/API parity before enabling this guard.

do $$
declare
  really_drop boolean := false;
begin
  if not really_drop then
    raise exception 'Drop guard is OFF. Verify Prospekt tiered memory migration, then set really_drop := true.';
  end if;

  drop table if exists public.facts cascade;
  drop table if exists public.session_summaries cascade;
end $$;

notify pgrst, 'reload schema';
