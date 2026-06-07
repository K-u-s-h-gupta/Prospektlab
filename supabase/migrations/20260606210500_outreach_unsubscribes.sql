begin;

create schema if not exists public;

create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create table if not exists public.outreach_unsubscribes (
  email text primary key,
  reason text not null default 'unsubscribe',
  source text not null default 'public_page',
  note text not null default '',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.outreach_unsubscribes add column if not exists email text;
alter table public.outreach_unsubscribes add column if not exists reason text not null default 'unsubscribe';
alter table public.outreach_unsubscribes add column if not exists source text not null default 'public_page';
alter table public.outreach_unsubscribes add column if not exists note text not null default '';
alter table public.outreach_unsubscribes add column if not exists created_at timestamptz not null default now();
alter table public.outreach_unsubscribes add column if not exists updated_at timestamptz not null default now();

update public.outreach_unsubscribes
set
  reason = coalesce(nullif(reason, ''), 'unsubscribe'),
  source = coalesce(nullif(source, ''), 'public_page'),
  note = coalesce(note, '')
where
  reason is null
  or source is null
  or note is null;

alter table public.outreach_unsubscribes
  alter column email set not null;

drop trigger if exists trg_outreach_unsubscribes_updated_at on public.outreach_unsubscribes;
create trigger trg_outreach_unsubscribes_updated_at
before update on public.outreach_unsubscribes
for each row
execute function public.set_updated_at();

alter table public.outreach_unsubscribes enable row level security;

drop policy if exists outreach_unsubscribes_service_role_access on public.outreach_unsubscribes;
create policy outreach_unsubscribes_service_role_access on public.outreach_unsubscribes
for all to service_role
using (true)
with check (true);

grant usage on schema public to service_role;
grant select, insert, update on table public.outreach_unsubscribes to service_role;

commit;
