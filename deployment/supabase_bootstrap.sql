-- ProspektLab Supabase bootstrap schema
-- Run this entire script once in Supabase SQL Editor.
-- It is idempotent and safe to re-run.

begin;

create schema if not exists public;

-- Flexible coercion helpers for live schema upgrades.
create or replace function public._to_epoch_seconds(v text)
returns double precision
language plpgsql
immutable
as $$
declare
  trimmed text;
begin
  if v is null then
    return extract(epoch from now());
  end if;
  trimmed := btrim(v);
  if trimmed = '' then
    return extract(epoch from now());
  end if;
  if trimmed ~ '^-?[0-9]+(\.[0-9]+)?$' then
    return trimmed::double precision;
  end if;
  return extract(epoch from trimmed::timestamptz);
exception
  when others then
    return extract(epoch from now());
end;
$$;

create or replace function public._to_timestamptz(v text)
returns timestamptz
language plpgsql
immutable
as $$
declare
  trimmed text;
begin
  if v is null then
    return now();
  end if;
  trimmed := btrim(v);
  if trimmed = '' then
    return now();
  end if;
  if trimmed ~ '^-?[0-9]+(\.[0-9]+)?$' then
    return to_timestamp(trimmed::double precision);
  end if;
  return trimmed::timestamptz;
exception
  when others then
    return now();
end;
$$;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- -----------------------------------------------------------------------------
-- Core auth profile table
-- -----------------------------------------------------------------------------
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null,
  full_name text not null default '',
  mobile text not null default '',
  auth_provider text not null default 'email',
  avatar_url text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.profiles add column if not exists full_name text not null default '';
alter table public.profiles add column if not exists mobile text not null default '';
alter table public.profiles add column if not exists auth_provider text not null default 'email';
alter table public.profiles add column if not exists avatar_url text not null default '';
alter table public.profiles add column if not exists created_at timestamptz not null default now();
alter table public.profiles add column if not exists updated_at timestamptz not null default now();

create unique index if not exists idx_profiles_email_unique on public.profiles (lower(email));
create index if not exists idx_profiles_email on public.profiles (email);

drop trigger if exists trg_profiles_updated_at on public.profiles;
create trigger trg_profiles_updated_at
before update on public.profiles
for each row
execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Portfolio mirrors
-- -----------------------------------------------------------------------------
create table if not exists public.portfolio_mirrors (
  id bigserial primary key,
  tenant_id uuid not null references auth.users(id) on delete cascade,
  symbol text not null,
  exchange text not null default 'NSE',
  quantity double precision not null default 0,
  market_value double precision not null default 0,
  cost_basis double precision not null default 0,
  active integer not null default 1 check (active in (0, 1)),
  updated_at timestamptz not null default now(),
  name text,
  isin text,
  amfi text,
  kind text not null default 'equity',
  sector text,
  industry text,
  avg_cost double precision not null default 0,
  last_price double precision not null default 0,
  as_of text
);

alter table public.portfolio_mirrors add column if not exists exchange text not null default 'NSE';
alter table public.portfolio_mirrors add column if not exists quantity double precision not null default 0;
alter table public.portfolio_mirrors add column if not exists market_value double precision not null default 0;
alter table public.portfolio_mirrors add column if not exists cost_basis double precision not null default 0;
alter table public.portfolio_mirrors add column if not exists active integer not null default 1;
alter table public.portfolio_mirrors add column if not exists updated_at timestamptz not null default now();
alter table public.portfolio_mirrors add column if not exists name text;
alter table public.portfolio_mirrors add column if not exists isin text;
alter table public.portfolio_mirrors add column if not exists amfi text;
alter table public.portfolio_mirrors add column if not exists kind text not null default 'equity';
alter table public.portfolio_mirrors add column if not exists sector text;
alter table public.portfolio_mirrors add column if not exists industry text;
alter table public.portfolio_mirrors add column if not exists avg_cost double precision not null default 0;
alter table public.portfolio_mirrors add column if not exists last_price double precision not null default 0;
alter table public.portfolio_mirrors add column if not exists as_of text;

create index if not exists idx_portfolio_mirrors_tenant_active
  on public.portfolio_mirrors (tenant_id, active, symbol);

drop trigger if exists trg_portfolio_mirrors_updated_at on public.portfolio_mirrors;
create trigger trg_portfolio_mirrors_updated_at
before update on public.portfolio_mirrors
for each row
execute function public.set_updated_at();

-- -----------------------------------------------------------------------------
-- Memory / session tables
-- -----------------------------------------------------------------------------
create table if not exists public.facts (
  id bigserial primary key,
  target_key text not null,
  kind text not null,
  body text not null,
  confidence text not null,
  source_url text,
  session_id text,
  user_email text not null,
  created_at double precision not null default extract(epoch from now())
);

alter table public.facts add column if not exists source_url text;
alter table public.facts add column if not exists session_id text;
alter table public.facts add column if not exists user_email text not null default '';
alter table public.facts add column if not exists created_at double precision not null default extract(epoch from now());

create index if not exists idx_facts_target on public.facts (target_key, created_at desc);
create index if not exists idx_facts_kind on public.facts (target_key, kind);
create index if not exists idx_facts_user on public.facts (user_email, target_key, created_at desc);

create table if not exists public.session_summaries (
  session_id text primary key,
  target_key text not null,
  target_display text,
  summary text not null,
  metrics_json text,
  citation_count integer,
  quality_score double precision,
  user_email text not null,
  created_at double precision not null default extract(epoch from now())
);

alter table public.session_summaries add column if not exists target_display text;
alter table public.session_summaries add column if not exists metrics_json text;
alter table public.session_summaries add column if not exists citation_count integer;
alter table public.session_summaries add column if not exists quality_score double precision;
alter table public.session_summaries add column if not exists user_email text not null default '';
alter table public.session_summaries add column if not exists created_at double precision not null default extract(epoch from now());

create index if not exists idx_summaries_target on public.session_summaries (target_key, created_at desc);
create index if not exists idx_summaries_user on public.session_summaries (user_email, target_key, created_at desc);

-- -----------------------------------------------------------------------------
-- State / auth support tables
-- -----------------------------------------------------------------------------
create table if not exists public.rate_limits (
  key text primary key,
  count integer not null default 0,
  window_start double precision not null
);

alter table public.rate_limits add column if not exists count integer not null default 0;
alter table public.rate_limits add column if not exists window_start double precision not null default extract(epoch from now());

create table if not exists public.verification_codes (
  email text not null,
  code text not null,
  type text not null default 'signup',
  created_at timestamptz not null default now(),
  primary key (email, type)
);

alter table public.verification_codes add column if not exists code text not null default '';
alter table public.verification_codes add column if not exists type text not null default 'signup';
alter table public.verification_codes add column if not exists created_at timestamptz not null default now();

create table if not exists public.pending_extractions (
  review_id text primary key,
  tenant_id uuid not null,
  payload_json text not null,
  created_at timestamptz not null default now()
);

alter table public.pending_extractions add column if not exists tenant_id uuid;
alter table public.pending_extractions add column if not exists payload_json text not null default '{}';
alter table public.pending_extractions add column if not exists created_at timestamptz not null default now();

create index if not exists idx_pending_tenant on public.pending_extractions (tenant_id);

create table if not exists public.revoked_tokens (
  jti text primary key,
  revoked_at timestamptz not null default now(),
  expires_at timestamptz not null
);

alter table public.revoked_tokens add column if not exists revoked_at timestamptz not null default now();
alter table public.revoked_tokens add column if not exists expires_at timestamptz not null default now() + interval '1 day';

create index if not exists idx_revoked_tokens_expires_at on public.revoked_tokens (expires_at);

create table if not exists public.token_usage (
  id bigserial primary key,
  user_email text not null,
  session_id text not null default '',
  prompt_tokens integer not null default 0,
  completion_tokens integer not null default 0,
  total_tokens integer not null default 0,
  model text not null default '',
  created_at timestamptz not null default now()
);

alter table public.token_usage add column if not exists user_email text not null default '';
alter table public.token_usage add column if not exists session_id text not null default '';
alter table public.token_usage add column if not exists prompt_tokens integer not null default 0;
alter table public.token_usage add column if not exists completion_tokens integer not null default 0;
alter table public.token_usage add column if not exists total_tokens integer not null default 0;
alter table public.token_usage add column if not exists model text not null default '';
alter table public.token_usage add column if not exists created_at timestamptz not null default now();

create index if not exists idx_token_usage_email on public.token_usage (user_email, created_at);

-- -----------------------------------------------------------------------------
-- Schema normalization for existing deployments
-- -----------------------------------------------------------------------------
do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'rate_limits' and column_name = 'window_start'
      and data_type <> 'double precision'
  ) then
    execute $sql$
      alter table public.rate_limits
      alter column window_start type double precision
      using public._to_epoch_seconds(window_start::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'facts' and column_name = 'created_at'
      and data_type <> 'double precision'
  ) then
    execute $sql$
      alter table public.facts
      alter column created_at type double precision
      using public._to_epoch_seconds(created_at::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'session_summaries' and column_name = 'created_at'
      and data_type <> 'double precision'
  ) then
    execute $sql$
      alter table public.session_summaries
      alter column created_at type double precision
      using public._to_epoch_seconds(created_at::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'verification_codes' and column_name = 'created_at'
      and data_type <> 'timestamp with time zone'
  ) then
    execute $sql$
      alter table public.verification_codes
      alter column created_at type timestamptz
      using public._to_timestamptz(created_at::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'pending_extractions' and column_name = 'created_at'
      and data_type <> 'timestamp with time zone'
  ) then
    execute $sql$
      alter table public.pending_extractions
      alter column created_at type timestamptz
      using public._to_timestamptz(created_at::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'revoked_tokens' and column_name = 'revoked_at'
      and data_type <> 'timestamp with time zone'
  ) then
    execute $sql$
      alter table public.revoked_tokens
      alter column revoked_at type timestamptz
      using public._to_timestamptz(revoked_at::text)
    $sql$;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public' and table_name = 'revoked_tokens' and column_name = 'expires_at'
      and data_type <> 'timestamp with time zone'
  ) then
    execute $sql$
      alter table public.revoked_tokens
      alter column expires_at type timestamptz
      using public._to_timestamptz(expires_at::text)
    $sql$;
  end if;
end $$;

-- -----------------------------------------------------------------------------
-- RLS + policies for tenant/user isolation
-- -----------------------------------------------------------------------------
alter table public.profiles enable row level security;
alter table public.portfolio_mirrors enable row level security;
alter table public.facts enable row level security;
alter table public.session_summaries enable row level security;
alter table public.rate_limits enable row level security;
alter table public.verification_codes enable row level security;
alter table public.pending_extractions enable row level security;
alter table public.revoked_tokens enable row level security;
alter table public.token_usage enable row level security;

drop policy if exists profiles_select_own on public.profiles;
drop policy if exists profiles_insert_own on public.profiles;
drop policy if exists profiles_update_own on public.profiles;
drop policy if exists profiles_delete_own on public.profiles;
create policy profiles_select_own on public.profiles
for select to authenticated
using (id::text = auth.uid()::text);
create policy profiles_insert_own on public.profiles
for insert to authenticated
with check (id::text = auth.uid()::text);
create policy profiles_update_own on public.profiles
for update to authenticated
using (id::text = auth.uid()::text)
with check (id::text = auth.uid()::text);
create policy profiles_delete_own on public.profiles
for delete to authenticated
using (id::text = auth.uid()::text);

drop policy if exists portfolio_mirrors_tenant_isolation on public.portfolio_mirrors;
create policy portfolio_mirrors_tenant_isolation on public.portfolio_mirrors
for all to authenticated
using (tenant_id::text = auth.uid()::text)
with check (tenant_id::text = auth.uid()::text);

drop policy if exists facts_user_isolation on public.facts;
create policy facts_user_isolation on public.facts
for all to authenticated
using (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists session_summaries_user_isolation on public.session_summaries;
create policy session_summaries_user_isolation on public.session_summaries
for all to authenticated
using (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists pending_extractions_tenant_isolation on public.pending_extractions;
create policy pending_extractions_tenant_isolation on public.pending_extractions
for all to authenticated
using (tenant_id::text = auth.uid()::text)
with check (tenant_id::text = auth.uid()::text);

drop policy if exists token_usage_user_isolation on public.token_usage;
create policy token_usage_user_isolation on public.token_usage
for all to authenticated
using (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(user_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

-- Backend service role permissions.
grant usage on schema public to service_role;
grant select, insert, update, delete on table
  public.profiles,
  public.portfolio_mirrors,
  public.facts,
  public.session_summaries,
  public.rate_limits,
  public.verification_codes,
  public.pending_extractions,
  public.revoked_tokens,
  public.token_usage
to service_role;

grant usage, select on all sequences in schema public to service_role;

commit;

notify pgrst, 'reload schema';
