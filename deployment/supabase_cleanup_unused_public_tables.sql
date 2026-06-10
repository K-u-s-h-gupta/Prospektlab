-- ProspektLab Supabase public-schema cleanup
--
-- Purpose:
--   Remove old/unrelated public tables and keep only the tables this backend uses.
--
-- Important:
--   This deletes data in dropped tables. Run the preview query first.
--   The DO block is guarded. Set really_drop := true only after reviewing output.

-- Preview tables that would be dropped.
select
  n.nspname as schema_name,
  c.relname as table_name,
  pg_total_relation_size(c.oid) as total_bytes
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where n.nspname = 'public'
  and c.relkind in ('r', 'p')
  and c.relname not in (
    'profiles',
    'portfolio_mirrors',
    'rate_limits',
    'verification_codes',
    'pending_extractions',
    'revoked_tokens',
    'token_usage'
  )
  and not exists (
    select 1
    from pg_depend d
    join pg_extension e on e.oid = d.refobjid
    where d.objid = c.oid
      and d.deptype = 'e'
  )
order by c.relname;

do $$
declare
  really_drop boolean := false;
  row record;
begin
  if not really_drop then
    raise exception 'Cleanup guard is OFF. Review the preview query, then set really_drop := true in this script.';
  end if;

  for row in
    select
      n.nspname as schema_name,
      c.relname as table_name
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
    where n.nspname = 'public'
      and c.relkind in ('r', 'p')
      and c.relname not in (
        'profiles',
        'portfolio_mirrors',
        'rate_limits',
        'verification_codes',
        'pending_extractions',
        'revoked_tokens',
        'token_usage'
      )
      and not exists (
        select 1
        from pg_depend d
        join pg_extension e on e.oid = d.refobjid
        where d.objid = c.oid
          and d.deptype = 'e'
      )
    order by c.relname
  loop
    execute format('drop table if exists %I.%I cascade', row.schema_name, row.table_name);
  end loop;
end $$;

notify pgrst, 'reload schema';
