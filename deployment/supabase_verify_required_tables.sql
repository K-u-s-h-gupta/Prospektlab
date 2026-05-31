-- ProspektLab Supabase required table verification
-- Run after deployment/supabase_bootstrap.sql.

with required(table_name) as (
  values
    ('profiles'),
    ('portfolio_mirrors'),
    ('facts'),
    ('session_summaries'),
    ('rate_limits'),
    ('verification_codes'),
    ('pending_extractions'),
    ('revoked_tokens'),
    ('token_usage')
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
