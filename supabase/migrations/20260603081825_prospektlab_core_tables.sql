create table if not exists public.contacts (
  id uuid primary key default gen_random_uuid(),
  name text,
  email text,
  raw_email text,
  email_status text,
  email_confidence double precision,
  email_normalized text,
  email_rejection_reason text,
  phone text,
  fax text,
  linkedin_url text,
  twitter_handle text,
  youtube_channel_id text,
  website text,
  designation text,
  organisation text,
  contact_person text,
  address text,
  correspondence_address text,
  city text,
  state text,
  validity text,
  areas_of_expertise text,
  sebi_reg_number text,
  sebi_reg_type text,
  amfi_arn text,
  nse_member_code text,
  bse_member_code text,
  priority_score double precision,
  extraction_confidence double precision,
  intent_signals jsonb default '{}'::jsonb,
  primary_source text,
  opted_out boolean default false,
  opted_out_at timestamptz,
  data_basis text,
  data_sources jsonb default '[]'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
create index if not exists idx_contacts_primary_source on public.contacts(primary_source);
create index if not exists idx_contacts_email_normalized on public.contacts(email_normalized);
create index if not exists idx_contacts_sebi_reg_number on public.contacts(sebi_reg_number);

create table if not exists public.scrape_jobs (
  id uuid primary key default gen_random_uuid(),
  source text not null,
  status text not null default 'pending',
  metadata jsonb default '{}'::jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  heartbeat_at timestamptz,
  last_checkpoint_at timestamptz,
  error_message text,
  records_scraped integer default 0,
  records_new integer default 0,
  records_updated integer default 0,
  records_duplicate integer default 0,
  records_failed integer default 0,
  records_email_filtered integer default 0,
  pages_done integer default 0,
  pages_total integer default 0,
  progress_pct double precision default 0,
  created_at timestamptz default now()
);
create index if not exists idx_scrape_jobs_source on public.scrape_jobs(source);
create index if not exists idx_scrape_jobs_status on public.scrape_jobs(status);

create table if not exists public.scrape_checkpoints (
  source text primary key,
  job_id uuid,
  cursor jsonb default '{}'::jsonb,
  updated_at timestamptz default now()
);

create table if not exists public.extraction_rules (
  id uuid primary key default gen_random_uuid(),
  domain text unique not null,
  rule_config jsonb default '{}'::jsonb,
  last_successful_at timestamptz,
  consecutive_failures integer default 0,
  version integer default 0,
  is_active boolean default true,
  healing_in_progress boolean default false,
  healing_flagged_at timestamptz,
  updated_at timestamptz default now()
);

create table if not exists public.export_jobs (
  id uuid primary key default gen_random_uuid(),
  status text default 'pending',
  format text,
  output_path text,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  completed_at timestamptz
);

alter table public.contacts enable row level security;
alter table public.scrape_jobs enable row level security;
alter table public.scrape_checkpoints enable row level security;
alter table public.extraction_rules enable row level security;
alter table public.export_jobs enable row level security;

drop policy if exists contacts_service_all on public.contacts;
create policy contacts_service_all on public.contacts for all to service_role using (true) with check (true);
drop policy if exists scrape_jobs_service_all on public.scrape_jobs;
create policy scrape_jobs_service_all on public.scrape_jobs for all to service_role using (true) with check (true);
drop policy if exists scrape_checkpoints_service_all on public.scrape_checkpoints;
create policy scrape_checkpoints_service_all on public.scrape_checkpoints for all to service_role using (true) with check (true);
drop policy if exists extraction_rules_service_all on public.extraction_rules;
create policy extraction_rules_service_all on public.extraction_rules for all to service_role using (true) with check (true);
drop policy if exists export_jobs_service_all on public.export_jobs;
create policy export_jobs_service_all on public.export_jobs for all to service_role using (true) with check (true);;
