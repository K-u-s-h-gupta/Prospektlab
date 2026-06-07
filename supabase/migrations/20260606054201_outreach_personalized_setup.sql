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

create table if not exists public.outreach_campaigns (
  id bigserial primary key,
  owner_email text not null,
  name text not null,
  sender_profile text not null default 'aryan',
  sender_address text not null default '',
  reply_to_email text not null default '',
  status text not null default 'draft',
  audience_query text not null default '',
  subject_template text not null default '',
  body_template text not null default '',
  scheduled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.outreach_campaigns add column if not exists owner_email text not null default '';
alter table public.outreach_campaigns add column if not exists name text not null default '';
alter table public.outreach_campaigns add column if not exists sender_profile text not null default 'aryan';
alter table public.outreach_campaigns add column if not exists sender_address text not null default '';
alter table public.outreach_campaigns add column if not exists reply_to_email text not null default '';
alter table public.outreach_campaigns add column if not exists status text not null default 'draft';
alter table public.outreach_campaigns add column if not exists audience_query text not null default '';
alter table public.outreach_campaigns add column if not exists subject_template text not null default '';
alter table public.outreach_campaigns add column if not exists body_template text not null default '';
alter table public.outreach_campaigns add column if not exists scheduled_at timestamptz;
alter table public.outreach_campaigns add column if not exists created_at timestamptz not null default now();
alter table public.outreach_campaigns add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_outreach_campaigns_owner
  on public.outreach_campaigns (owner_email, status, created_at desc);

drop trigger if exists trg_outreach_campaigns_updated_at on public.outreach_campaigns;
create trigger trg_outreach_campaigns_updated_at
before update on public.outreach_campaigns
for each row
execute function public.set_updated_at();

create table if not exists public.outreach_leads (
  id bigserial primary key,
  owner_email text not null,
  email text not null,
  first_name text not null default '',
  last_name text not null default '',
  company_name text not null default '',
  title text not null default '',
  linkedin_url text not null default '',
  website_url text not null default '',
  personalization_json text not null default '{}',
  status text not null default 'new',
  assigned_profile text not null default '',
  last_contacted_at timestamptz,
  unsubscribed_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.outreach_leads add column if not exists owner_email text not null default '';
alter table public.outreach_leads add column if not exists email text not null default '';
alter table public.outreach_leads add column if not exists first_name text not null default '';
alter table public.outreach_leads add column if not exists last_name text not null default '';
alter table public.outreach_leads add column if not exists company_name text not null default '';
alter table public.outreach_leads add column if not exists title text not null default '';
alter table public.outreach_leads add column if not exists linkedin_url text not null default '';
alter table public.outreach_leads add column if not exists website_url text not null default '';
alter table public.outreach_leads add column if not exists personalization_json text not null default '{}';
alter table public.outreach_leads add column if not exists status text not null default 'new';
alter table public.outreach_leads add column if not exists assigned_profile text not null default '';
alter table public.outreach_leads add column if not exists last_contacted_at timestamptz;
alter table public.outreach_leads add column if not exists unsubscribed_at timestamptz;
alter table public.outreach_leads add column if not exists created_at timestamptz not null default now();
alter table public.outreach_leads add column if not exists updated_at timestamptz not null default now();

create unique index if not exists idx_outreach_leads_owner_email_unique
  on public.outreach_leads (lower(owner_email), lower(email));
create index if not exists idx_outreach_leads_owner_status
  on public.outreach_leads (owner_email, status, created_at desc);

drop trigger if exists trg_outreach_leads_updated_at on public.outreach_leads;
create trigger trg_outreach_leads_updated_at
before update on public.outreach_leads
for each row
execute function public.set_updated_at();

create table if not exists public.outreach_suppressions (
  id bigserial primary key,
  owner_email text not null,
  email text not null,
  reason text not null default 'manual',
  source text not null default 'app',
  note text not null default '',
  created_at timestamptz not null default now()
);

alter table public.outreach_suppressions add column if not exists owner_email text not null default '';
alter table public.outreach_suppressions add column if not exists email text not null default '';
alter table public.outreach_suppressions add column if not exists reason text not null default 'manual';
alter table public.outreach_suppressions add column if not exists source text not null default 'app';
alter table public.outreach_suppressions add column if not exists note text not null default '';
alter table public.outreach_suppressions add column if not exists created_at timestamptz not null default now();

create unique index if not exists idx_outreach_suppressions_owner_email_unique
  on public.outreach_suppressions (lower(owner_email), lower(email));

create table if not exists public.outreach_messages (
  id bigserial primary key,
  owner_email text not null,
  campaign_id bigint references public.outreach_campaigns(id) on delete set null,
  lead_id bigint references public.outreach_leads(id) on delete set null,
  sender_profile text not null default '',
  sender_address text not null default '',
  reply_to_email text not null default '',
  to_email text not null,
  subject_rendered text not null default '',
  body_rendered text not null default '',
  provider text not null default '',
  provider_message_id text not null default '',
  status text not null default 'queued',
  last_error text not null default '',
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

alter table public.outreach_messages add column if not exists owner_email text not null default '';
alter table public.outreach_messages add column if not exists campaign_id bigint references public.outreach_campaigns(id) on delete set null;
alter table public.outreach_messages add column if not exists lead_id bigint references public.outreach_leads(id) on delete set null;
alter table public.outreach_messages add column if not exists sender_profile text not null default '';
alter table public.outreach_messages add column if not exists sender_address text not null default '';
alter table public.outreach_messages add column if not exists reply_to_email text not null default '';
alter table public.outreach_messages add column if not exists to_email text not null default '';
alter table public.outreach_messages add column if not exists subject_rendered text not null default '';
alter table public.outreach_messages add column if not exists body_rendered text not null default '';
alter table public.outreach_messages add column if not exists provider text not null default '';
alter table public.outreach_messages add column if not exists provider_message_id text not null default '';
alter table public.outreach_messages add column if not exists status text not null default 'queued';
alter table public.outreach_messages add column if not exists last_error text not null default '';
alter table public.outreach_messages add column if not exists sent_at timestamptz;
alter table public.outreach_messages add column if not exists created_at timestamptz not null default now();
alter table public.outreach_messages add column if not exists updated_at timestamptz not null default now();

create index if not exists idx_outreach_messages_owner_status
  on public.outreach_messages (owner_email, status, created_at desc);
create index if not exists idx_outreach_messages_campaign
  on public.outreach_messages (campaign_id, lead_id);
create index if not exists idx_outreach_messages_provider_message
  on public.outreach_messages (provider_message_id);

drop trigger if exists trg_outreach_messages_updated_at on public.outreach_messages;
create trigger trg_outreach_messages_updated_at
before update on public.outreach_messages
for each row
execute function public.set_updated_at();

create table if not exists public.outreach_events (
  id bigserial primary key,
  owner_email text not null,
  message_id bigint references public.outreach_messages(id) on delete cascade,
  event_type text not null,
  provider text not null default '',
  event_payload text not null default '{}',
  occurred_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table public.outreach_events add column if not exists owner_email text not null default '';
alter table public.outreach_events add column if not exists message_id bigint references public.outreach_messages(id) on delete cascade;
alter table public.outreach_events add column if not exists event_type text not null default '';
alter table public.outreach_events add column if not exists provider text not null default '';
alter table public.outreach_events add column if not exists event_payload text not null default '{}';
alter table public.outreach_events add column if not exists occurred_at timestamptz not null default now();
alter table public.outreach_events add column if not exists created_at timestamptz not null default now();

create index if not exists idx_outreach_events_message
  on public.outreach_events (message_id, occurred_at desc);
create index if not exists idx_outreach_events_owner_type
  on public.outreach_events (owner_email, event_type, occurred_at desc);

create table if not exists public.outreach_replies (
  id bigserial primary key,
  owner_email text not null,
  message_id bigint references public.outreach_messages(id) on delete set null,
  from_email text not null,
  to_email text not null default '',
  subject text not null default '',
  body_preview text not null default '',
  received_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

alter table public.outreach_replies add column if not exists owner_email text not null default '';
alter table public.outreach_replies add column if not exists message_id bigint references public.outreach_messages(id) on delete set null;
alter table public.outreach_replies add column if not exists from_email text not null default '';
alter table public.outreach_replies add column if not exists to_email text not null default '';
alter table public.outreach_replies add column if not exists subject text not null default '';
alter table public.outreach_replies add column if not exists body_preview text not null default '';
alter table public.outreach_replies add column if not exists received_at timestamptz not null default now();
alter table public.outreach_replies add column if not exists created_at timestamptz not null default now();

create index if not exists idx_outreach_replies_owner_received
  on public.outreach_replies (owner_email, received_at desc);

alter table public.outreach_campaigns enable row level security;
alter table public.outreach_leads enable row level security;
alter table public.outreach_suppressions enable row level security;
alter table public.outreach_messages enable row level security;
alter table public.outreach_events enable row level security;
alter table public.outreach_replies enable row level security;

drop policy if exists outreach_campaigns_owner_isolation on public.outreach_campaigns;
create policy outreach_campaigns_owner_isolation on public.outreach_campaigns
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists outreach_leads_owner_isolation on public.outreach_leads;
create policy outreach_leads_owner_isolation on public.outreach_leads
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists outreach_suppressions_owner_isolation on public.outreach_suppressions;
create policy outreach_suppressions_owner_isolation on public.outreach_suppressions
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists outreach_messages_owner_isolation on public.outreach_messages;
create policy outreach_messages_owner_isolation on public.outreach_messages
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists outreach_events_owner_isolation on public.outreach_events;
create policy outreach_events_owner_isolation on public.outreach_events
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

drop policy if exists outreach_replies_owner_isolation on public.outreach_replies;
create policy outreach_replies_owner_isolation on public.outreach_replies
for all to authenticated
using (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')))
with check (lower(owner_email) = lower(coalesce(auth.jwt() ->> 'email', '')));

grant usage on schema public to service_role;
grant select, insert, update, delete on table
  public.outreach_campaigns,
  public.outreach_leads,
  public.outreach_suppressions,
  public.outreach_messages,
  public.outreach_events,
  public.outreach_replies
to service_role;

grant usage, select on all sequences in schema public to service_role;

commit;
