-- IPO intelligence tables for DRHP pipeline (Tier 1 live + Tier 2 backfill)

create table if not exists public.ipo_filings (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null,
  company_name text not null,
  sector text,
  exchange text,
  doc_type text not null default 'drhp',
  status text not null default 'upcoming',
  filing_date date,
  issue_size_cr numeric,
  fresh_issue_cr numeric,
  ofs_cr numeric,
  price_band_low numeric,
  price_band_high numeric,
  subscription_open date,
  subscription_close date,
  listing_date date,
  pdf_url text,
  pdf_cache_path text,
  gmp numeric,
  gmp_updated_at timestamptz,
  subscription_status text,
  composite_score numeric,
  source text,
  metadata jsonb default '{}'::jsonb,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_ipo_filings_status on public.ipo_filings(status);
create index if not exists idx_ipo_filings_listing_date on public.ipo_filings(listing_date desc);

create table if not exists public.ipo_analyses (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null references public.ipo_filings(slug) on delete cascade,
  parsed_sections jsonb default '{}'::jsonb,
  business_synthesis text,
  analyzed_at timestamptz default now()
);

create table if not exists public.ipo_scores (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null references public.ipo_filings(slug) on delete cascade,
  composite_score numeric not null,
  business_quality numeric,
  valuation_fairness numeric,
  management_credibility numeric,
  financial_health numeric,
  risk_profile numeric,
  score_breakdown jsonb default '{}'::jsonb,
  scored_at timestamptz default now()
);

create table if not exists public.ipo_post_listing (
  id uuid primary key default gen_random_uuid(),
  slug text unique not null references public.ipo_filings(slug) on delete cascade,
  issue_price numeric,
  listing_price numeric,
  listing_gain_pct numeric,
  current_price numeric,
  current_return_pct numeric,
  drhp_promises jsonb default '[]'::jsonb,
  actual_performance jsonb default '{}'::jsonb,
  on_track boolean,
  updated_at timestamptz default now()
);

alter table public.ipo_filings enable row level security;
alter table public.ipo_analyses enable row level security;
alter table public.ipo_scores enable row level security;
alter table public.ipo_post_listing enable row level security;

drop policy if exists ipo_filings_service_all on public.ipo_filings;
create policy ipo_filings_service_all on public.ipo_filings for all to service_role using (true) with check (true);
drop policy if exists ipo_analyses_service_all on public.ipo_analyses;
create policy ipo_analyses_service_all on public.ipo_analyses for all to service_role using (true) with check (true);
drop policy if exists ipo_scores_service_all on public.ipo_scores;
create policy ipo_scores_service_all on public.ipo_scores for all to service_role using (true) with check (true);
drop policy if exists ipo_post_listing_service_all on public.ipo_post_listing;
create policy ipo_post_listing_service_all on public.ipo_post_listing for all to service_role using (true) with check (true);

-- Public read for SEO IPO pages (anon key)
drop policy if exists ipo_filings_public_read on public.ipo_filings;
create policy ipo_filings_public_read on public.ipo_filings for select to anon, authenticated using (true);
drop policy if exists ipo_analyses_public_read on public.ipo_analyses;
create policy ipo_analyses_public_read on public.ipo_analyses for select to anon, authenticated using (true);
drop policy if exists ipo_scores_public_read on public.ipo_scores;
create policy ipo_scores_public_read on public.ipo_scores for select to anon, authenticated using (true);
drop policy if exists ipo_post_listing_public_read on public.ipo_post_listing;
create policy ipo_post_listing_public_read on public.ipo_post_listing for select to anon, authenticated using (true);
