-- IGS Phase A — failure_events label set (the predictive keystone).
--
-- The positive class for governance-failure prediction. Without failed/delisted/
-- struck-off companies, a model only sees survivors (survivorship bias) and cannot
-- learn failure patterns. The MCA master already holds ~975k failure-class rows in
-- its `status` column (Strike Off 895k, Under Liquidation 8.5k, Dissolved/Liquidated
-- 12k, Under CIRP 1.9k, Amalgamated 40k, ...) — mined here at zero new scraping cost.
--
-- Idempotent: safe to re-run. Mining is done by finagent.ikg.scrapers.failure_labels.

create table if not exists failure_events (
    id            bigserial primary key,
    cin           text not null,
    event_type    text not null,           -- canonical class (see failure_labels.STATUS_MAP)
    event_subtype text,                     -- raw source label (e.g. exact MCA status)
    event_date    date,                     -- best-effort; many MCA rows carry no date
    is_failure    boolean not null default true,  -- true positive label vs weak/ambiguous
    source        text not null,            -- mca_master_status | sebi_enforcement | nse_bse_delisting | ibbi_nclt
    source_url    text,
    confidence    numeric not null default 0.80,
    evidence_text text,
    properties    jsonb not null default '{}'::jsonb,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    unique (cin, event_type, source)
);

create index if not exists idx_failure_events_cin        on failure_events (cin);
create index if not exists idx_failure_events_event_type on failure_events (event_type);
create index if not exists idx_failure_events_event_date on failure_events (event_date);
create index if not exists idx_failure_events_is_failure on failure_events (is_failure) where is_failure;
