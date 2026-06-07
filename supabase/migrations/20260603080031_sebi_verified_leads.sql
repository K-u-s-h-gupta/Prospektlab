create table if not exists public.sebi_verified_leads (
  id uuid primary key default gen_random_uuid(),
  contact_id uuid,
  source text not null,
  sebi_category text not null,
  sebi_label text,
  intm_id text,
  sebi_reg_number text,
  entity_name text,
  contact_name text,
  email text,
  email_normalized text,
  email_status text,
  email_confidence double precision,
  phone text,
  address text,
  city text,
  state text,
  organisation text,
  raw_payload jsonb default '{}'::jsonb,
  scraped_at timestamptz default now(),
  verified_at timestamptz default now(),
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  unique (source, sebi_reg_number, email_normalized)
);
create index if not exists idx_sebi_verified_leads_source on public.sebi_verified_leads(source);
create index if not exists idx_sebi_verified_leads_category on public.sebi_verified_leads(sebi_category);
alter table public.sebi_verified_leads enable row level security;
drop policy if exists sebi_verified_leads_service_all on public.sebi_verified_leads;
create policy sebi_verified_leads_service_all on public.sebi_verified_leads for all to service_role using (true) with check (true);;
