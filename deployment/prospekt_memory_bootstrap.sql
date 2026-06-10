-- ProspektLab dedicated memory database bootstrap.
--
-- Run this against the separate Postgres database referenced by
-- MEMORY_DATABASE_URL. Do not run it in Supabase unless Supabase is also your
-- private memory database, because Supabase should remain user/ops only.
--
-- Default vector dimension is 1536. If MEMORY_VECTOR_DIM differs, update the
-- two vector(1536) columns before running this script.

begin;

create extension if not exists vector;

create or replace function public.set_memory_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- Tier 1: Core Memory. Always-in-context summaries, not the canonical holdings
-- store. Uploaded holdings remain in Supabase portfolio_mirrors.
create table if not exists public.core_memory_blocks (
  id bigserial primary key,
  user_email text not null,
  tenant_id text not null default '',
  block_type text not null,
  label text not null,
  text text not null default '',
  value_json jsonb not null default '{}'::jsonb,
  priority integer not null default 0,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_email, tenant_id, block_type, label)
);

create index if not exists idx_core_memory_user_active
  on public.core_memory_blocks (lower(user_email), active, priority desc);

drop trigger if exists trg_core_memory_blocks_updated_at on public.core_memory_blocks;
create trigger trg_core_memory_blocks_updated_at
before update on public.core_memory_blocks
for each row
execute function public.set_memory_updated_at();

-- Tier 2: Recall Memory. Verified facts from research sessions.
create table if not exists public.recall_memories (
  id bigserial primary key,
  user_email text not null,
  tenant_id text not null default '',
  target_key text not null,
  cin text,
  isin text,
  symbol text,
  kind text not null default 'other',
  body text not null,
  body_hash text not null,
  confidence text not null default 'MEDIUM',
  source_url text,
  session_id text,
  session_key text not null default '',
  metadata_json jsonb not null default '{}'::jsonb,
  legacy_source text,
  legacy_id text,
  embedding vector(1536),
  expires_at timestamptz,
  expires_at_epoch double precision,
  created_at timestamptz not null default now(),
  created_at_epoch double precision not null default extract(epoch from now())
);

alter table public.recall_memories
  add column if not exists expires_at timestamptz;

alter table public.recall_memories
  add column if not exists expires_at_epoch double precision;

update public.recall_memories
set expires_at_epoch = extract(epoch from expires_at)
where expires_at is not null and expires_at_epoch is null;

create unique index if not exists uq_recall_memories_runtime_dedupe
  on public.recall_memories (lower(user_email), target_key, kind, session_key, body_hash);

create unique index if not exists uq_recall_memories_legacy
  on public.recall_memories (legacy_source, legacy_id)
  where legacy_source is not null and legacy_id is not null;

create index if not exists idx_recall_memories_target_kind
  on public.recall_memories (lower(user_email), target_key, kind, created_at_epoch desc);

create index if not exists idx_recall_memories_cin_kind
  on public.recall_memories (lower(user_email), cin, kind)
  where cin is not null;

create index if not exists idx_recall_memories_session
  on public.recall_memories (lower(user_email), session_key)
  where session_key <> '';

create index if not exists idx_recall_memories_fts
  on public.recall_memories using gin (to_tsvector('english', body));

create index if not exists idx_recall_memories_embedding
  on public.recall_memories using ivfflat (embedding vector_cosine_ops)
  with (lists = 100)
  where embedding is not null;

-- Tier 3: Archival Memory. Session summaries, historical snapshots,
-- consolidated patterns, and future Dreaming Layer outputs.
create table if not exists public.archival_memories (
  id bigserial primary key,
  user_email text not null,
  tenant_id text not null default '',
  target_key text not null default '',
  archive_type text not null default 'session_summary',
  target_display text not null default '',
  body text not null,
  body_hash text not null,
  metrics_json jsonb not null default '{}'::jsonb,
  citation_count integer not null default 0,
  quality_score double precision not null default 0,
  confidence text not null default 'MEDIUM',
  evidence_refs jsonb not null default '[]'::jsonb,
  session_id text,
  session_key text not null default '',
  created_by text not null default 'runtime',
  status text not null default 'active',
  legacy_source text,
  legacy_id text,
  embedding vector(1536),
  created_at timestamptz not null default now(),
  created_at_epoch double precision not null default extract(epoch from now())
);

create unique index if not exists uq_archival_memories_runtime_dedupe
  on public.archival_memories (lower(user_email), archive_type, session_key, target_key, body_hash);

create unique index if not exists uq_archival_memories_legacy
  on public.archival_memories (legacy_source, legacy_id)
  where legacy_source is not null and legacy_id is not null;

create index if not exists idx_archival_memories_target_type
  on public.archival_memories (lower(user_email), target_key, archive_type, created_at_epoch desc);

create index if not exists idx_archival_memories_session
  on public.archival_memories (lower(user_email), session_key)
  where session_key <> '';

create index if not exists idx_archival_memories_dreaming
  on public.archival_memories (created_by, status, created_at_epoch desc);

create index if not exists idx_archival_memories_fts
  on public.archival_memories using gin (to_tsvector('english', body));

create index if not exists idx_archival_memories_embedding
  on public.archival_memories using ivfflat (embedding vector_cosine_ops)
  with (lists = 100)
  where embedding is not null;

commit;
