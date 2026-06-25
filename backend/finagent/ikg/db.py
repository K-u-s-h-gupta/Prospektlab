"""IKG database configuration and bootstrap helpers."""

from __future__ import annotations

import os
import threading

from finagent.env import load_finagent_env

load_finagent_env()

_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAPPED_URLS: set[str] = set()


def _resolve_database_url_candidate(*keys: str) -> str:
    for key in keys:
        value = os.getenv(key, "").strip()
        if not value:
            continue
        if os.getenv("PROSPEKTLAB_ENV") == "production" and (
            "127.0.0.1" in value or "localhost" in value
        ):
            continue
        return value
    return ""


def get_database_url(explicit: str | None = None) -> str:
    """Return the configured Postgres-compatible IKG database URL.

    Supabase exposes a Postgres database, so the same URL is used by psycopg,
    graph storage, scraper staging tables, and scheduler observability.
    """
    return (
        (explicit or "").strip()
        or _resolve_database_url_candidate(
            "IKG_DATABASE_URL",
            "DATABASE_URL",
            "SUPABASE_DB_URL",
            "MEMORY_DATABASE_URL",
        )
    )


def is_supabase_database_url(database_url: str | None = None) -> bool:
    """Best-effort marker for health output only."""
    url = get_database_url(database_url).lower()
    return "supabase.co" in url or "supabase.com" in url or "pooler.supabase" in url


_IKG_RUNTIME_BOOTSTRAP_SQL = """
create extension if not exists pg_trgm;

-- ── Staging tables (populated by scrapers, read by graph build) ──────────────

create table if not exists ikg_company_master (
    id                      bigserial primary key,
    cin                     varchar(21) unique,
    nse_symbol              varchar(20) unique,
    bse_scrip_code          varchar(10),
    isin                    varchar(12),
    company_name            varchar(500) not null,
    registration_date       date,
    category                varchar(200),
    company_class           varchar(50),
    listing_status          varchar(50),
    authorized_capital      numeric(20,2),
    paidup_capital          numeric(20,2),
    roc                     varchar(100),
    address                 text,
    pin_code                varchar(10),
    state                   varchar(100),
    status                  varchar(50),
    sub_category            varchar(200),
    industrial_classification varchar(200),
    sector                  varchar(200),
    industry                varchar(200),
    created_at              timestamptz default now(),
    updated_at              timestamptz default now()
);
create index if not exists idx_ikg_company_master_cin on ikg_company_master(cin);
create index if not exists idx_ikg_company_master_nse on ikg_company_master(nse_symbol);
create index if not exists idx_ikg_company_master_isin on ikg_company_master(isin);
create index if not exists idx_ikg_company_master_bse on ikg_company_master(bse_scrip_code);
create index if not exists idx_ikg_company_master_name_trgm
    on ikg_company_master using gin (upper(company_name) gin_trgm_ops);

create table if not exists shp_raw (
    id                          bigserial primary key,
    scrip_code                  varchar(10) not null,
    cin                         varchar(21),
    quarter                     varchar(8) not null,
    total_promoter_holding_pct  numeric(6,2),
    total_pledge_pct            numeric(6,2),
    fii_holding_pct             numeric(6,2),
    dii_holding_pct             numeric(6,2),
    public_holding_pct          numeric(6,2),
    promoter_groups_json        jsonb default '[]'::jsonb,
    raw_json                    jsonb default '{}'::jsonb,
    source_url                  text,
    as_on_date                  date,
    fetched_at                  timestamptz default now(),
    unique (scrip_code, quarter)
);
create index if not exists idx_shp_raw_cin on shp_raw(cin);
create index if not exists idx_shp_raw_quarter on shp_raw(quarter);

create table if not exists directors_raw (
    id                  bigserial primary key,
    cin                 varchar(21) not null,
    din                 varchar(10) not null,
    name                varchar(300) not null,
    designation         varchar(200),
    appointment_date    date,
    cessation_date      date,
    source              varchar(80),
    source_url          text,
    quarter             varchar(20),
    nse_symbol          varchar(20),
    bse_scrip_code      varchar(10),
    confidence_score    numeric(5,2),
    fetched_at          timestamptz default now(),
    unique (cin, din)
);
create index if not exists idx_directors_raw_cin on directors_raw(cin);
create index if not exists idx_directors_raw_din on directors_raw(din);
create index if not exists idx_directors_raw_name on directors_raw(name);
create index if not exists idx_directors_raw_source on directors_raw(source, fetched_at desc);

create table if not exists director_source_records (
    id                  bigserial primary key,
    source              varchar(80) not null,
    cin                 varchar(21),
    nse_symbol          varchar(20),
    bse_scrip_code      varchar(10),
    quarter             varchar(20),
    filing_url          text not null,
    title               text,
    raw_json            jsonb default '{}'::jsonb,
    extracted_text      text,
    parser_version      varchar(80) default 'corporate_governance_directors_v1',
    status              varchar(40) not null,
    error               text,
    fetched_at          timestamptz default now(),
    unique (source, filing_url)
);
create index if not exists idx_director_source_records_cin
    on director_source_records(cin);
create index if not exists idx_director_source_records_status
    on director_source_records(status, fetched_at desc);

create table if not exists daily_prices (
    id              bigserial primary key,
    scrip_code      varchar(10) not null,
    isin            varchar(12),
    name            varchar(300),
    trade_date      date not null,
    open            numeric(12,2),
    high            numeric(12,2),
    low             numeric(12,2),
    close           numeric(12,2),
    prev_close      numeric(12,2),
    volume          bigint,
    value_lakh      numeric(20,4),
    created_at      timestamptz default now(),
    unique (scrip_code, trade_date)
);
create index if not exists idx_daily_prices_scrip on daily_prices(scrip_code);
create index if not exists idx_daily_prices_date on daily_prices(trade_date desc);
create index if not exists idx_daily_prices_isin on daily_prices(isin);

create table if not exists company_financials (
    id                      bigserial primary key,
    cin                     varchar(21),
    nse_symbol              varchar(20) unique,
    sources_used            text[],
    validated_metrics_json  jsonb default '{}'::jsonb,
    discrepancies_json      jsonb default '[]'::jsonb,
    income_statement_json   jsonb default '[]'::jsonb,
    balance_sheet_json      jsonb default '[]'::jsonb,
    cashflow_json           jsonb default '[]'::jsonb,
    fetched_at              timestamptz default now(),
    updated_at              timestamptz default now()
);
create index if not exists idx_company_financials_cin on company_financials(cin);
create index if not exists idx_company_financials_symbol on company_financials(nse_symbol);

create table if not exists enforcement_raw (
    id                  bigserial primary key,
    order_number        varchar(100) unique not null,
    regulator           varchar(20) default 'SEBI',
    violation_type      varchar(200),
    penalty_amount_inr  numeric(20,2),
    order_date          date,
    pdf_url             text,
    full_text           text,
    entities_json       jsonb default '[]'::jsonb,
    status              varchar(50) default 'active',
    fetched_at          timestamptz default now()
);
create index if not exists idx_enforcement_raw_date on enforcement_raw(order_date desc);
create index if not exists idx_enforcement_raw_regulator on enforcement_raw(regulator);

create table if not exists annual_reports_raw (
    report_uid          varchar(80) primary key,
    cin                 varchar(21),
    nse_symbol          varchar(20),
    scrip_code          varchar(10),
    company_name        varchar(500),
    report_year         varchar(10),
    pdf_url             text,
    source_url          text,
    extraction_status   varchar(40) default 'pending',
    extracted_model     varchar(80),
    page_count          integer,
    tables_count        integer,
    full_text_length    integer,
    fetched_at          timestamptz default now()
);
create index if not exists idx_annual_reports_raw_cin on annual_reports_raw(cin);
create index if not exists idx_annual_reports_raw_status on annual_reports_raw(extraction_status);

create table if not exists annual_report_chunks (
    id              bigserial primary key,
    report_uid      varchar(80) not null,
    chunk_index     integer not null,
    total_chunks    integer,
    chunk_id        varchar(120),
    chunk_text      text,
    char_count      integer,
    source_file     text,
    created_at      timestamptz default now(),
    unique (report_uid, chunk_index)
);
create index if not exists idx_annual_report_chunks_uid on annual_report_chunks(report_uid);

create table if not exists concall_transcripts_raw (
    id              bigserial primary key,
    cin             varchar(21),
    symbol          varchar(20),
    company_name    varchar(500),
    quarter_label   varchar(20),
    fiscal_year     varchar(10),
    announced_at    timestamptz,
    attachment_url  text,
    source_url      text,
    fetched_at      timestamptz default now(),
    unique (symbol, quarter_label, fiscal_year)
);
create index if not exists idx_concall_transcripts_cin on concall_transcripts_raw(cin);
create index if not exists idx_concall_transcripts_symbol on concall_transcripts_raw(symbol);

create table if not exists sebi_corporate_filing_map (
    id                  bigserial primary key,
    category            varchar(120) not null,
    exchange            varchar(20),
    title               text not null,
    url                 text not null unique,
    source_page         text not null,
    raw_json            jsonb default '{}'::jsonb,
    fetched_at          timestamptz default now()
);
create index if not exists idx_sebi_corp_filing_category
    on sebi_corporate_filing_map(category);

-- ── Runtime tables (pipeline runs, scheduler, graph, facts) ──────────────────

create table if not exists ikg_pipeline_runs (
    run_id              text primary key,
    task_name           varchar(120) not null,
    source_name         varchar(120),
    started_at          timestamptz,
    completed_at        timestamptz,
    duration_s          numeric(12,2),
    records_fetched     integer default 0,
    records_stored      integer default 0,
    records_failed      integer default 0,
    success             boolean default false,
    error               text,
    official_source_url text,
    http_status         integer,
    parser_version      varchar(80),
    metadata            jsonb default '{}'::jsonb,
    created_at          timestamptz default now()
);
create index if not exists idx_ikg_pipeline_runs_task_created
    on ikg_pipeline_runs(task_name, created_at desc);
create index if not exists idx_ikg_pipeline_runs_success
    on ikg_pipeline_runs(success, created_at desc);

create table if not exists ikg_scheduler_locks (
    job_id              varchar(120) primary key,
    locked_by           text not null,
    locked_until        timestamptz not null,
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_scheduler_locks_until
    on ikg_scheduler_locks(locked_until);

create table if not exists ikg_runtime_controls (
    control_key         varchar(120) primary key,
    enabled             boolean not null default true,
    control_group       varchar(80) default 'global',
    description         text,
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_runtime_controls_enabled
    on ikg_runtime_controls(enabled);
insert into ikg_runtime_controls (control_key, enabled, control_group, description)
values
    ('pipeline_enabled', true, 'global', 'Master switch for the IKG worker pipeline'),
    ('bse_enabled', true, 'scraping', 'Controls BSE scrapers and BSE-hosted documents'),
    ('nse_enabled', true, 'scraping', 'Controls NSE scrapers and transcripts'),
    ('mca_enabled', true, 'scraping', 'Controls MCA company master refresh jobs'),
    ('sebi_enabled', true, 'scraping', 'Controls SEBI enforcement and filing jobs'),
    ('documents_enabled', true, 'documents', 'Controls attachment hydration and document ingestion'),
    ('financials_enabled', true, 'scraping', 'Controls financial refresh jobs'),
    ('graph_enabled', true, 'graph', 'Controls graph build and vector indexing jobs'),
    ('healthcheck_enabled', true, 'observability', 'Controls scheduler health checks'),
    ('official_monitor_enabled', true, 'content', 'Controls the 24/7 official-source content monitor'),
    ('dreaming_enabled', false, 'graph', 'Controls the nightly dreaming layer')
on conflict (control_key) do nothing;

create table if not exists ikg_vertices (
    vertex_id           varchar(200) primary key,
    label               varchar(50) not null,
    properties          jsonb default '{}'::jsonb,
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_vertices_label on ikg_vertices(label);
create index if not exists idx_ikg_vertices_props on ikg_vertices using gin (properties);

create table if not exists ikg_edges (
    id                  bigserial primary key,
    from_vertex_id      varchar(200) not null references ikg_vertices(vertex_id) on delete cascade,
    to_vertex_id        varchar(200) not null references ikg_vertices(vertex_id) on delete cascade,
    label               varchar(50) not null,
    properties          jsonb default '{}'::jsonb,
    created_at          timestamptz default now(),
    updated_at          timestamptz default now(),
    unique (from_vertex_id, to_vertex_id, label)
);
create index if not exists idx_ikg_edges_from on ikg_edges(from_vertex_id);
create index if not exists idx_ikg_edges_to on ikg_edges(to_vertex_id);
create index if not exists idx_ikg_edges_label on ikg_edges(label);
create index if not exists idx_ikg_edges_from_label on ikg_edges(from_vertex_id, label);

create table if not exists ikg_canonical_entities (
    entity_id           varchar(160) primary key,
    entity_type         varchar(50) not null,
    display_name        text not null,
    primary_identifier  text,
    properties          jsonb default '{}'::jsonb,
    confidence          numeric(4,3) default 1.000,
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_canonical_entities_type
    on ikg_canonical_entities(entity_type);
create index if not exists idx_ikg_canonical_entities_props
    on ikg_canonical_entities using gin (properties);

create table if not exists ikg_entity_aliases (
    alias_id            bigserial primary key,
    entity_id           varchar(160) not null references ikg_canonical_entities(entity_id) on delete cascade,
    alias               text not null,
    alias_type          varchar(50) default 'name',
    source_citation     text,
    confidence          numeric(4,3) default 0.900,
    created_at          timestamptz default now(),
    unique (entity_id, alias, alias_type)
);
create index if not exists idx_ikg_entity_aliases_alias
    on ikg_entity_aliases using gin (alias gin_trgm_ops);

create table if not exists ikg_facts (
    fact_id             varchar(220) primary key,
    subject_entity_id   varchar(200) not null,
    predicate           varchar(80) not null,
    object_entity_id    varchar(200),
    object_value        text,
    value_numeric       numeric,
    valid_from          date,
    valid_to            date,
    as_of_date          date,
    event_date          date,
    confidence          numeric(4,3) default 1.000,
    source_table        varchar(80),
    source_uid          text,
    source_url          text,
    evidence_text       text,
    properties          jsonb default '{}'::jsonb,
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_facts_subject_predicate
    on ikg_facts(subject_entity_id, predicate, as_of_date desc);
create index if not exists idx_ikg_facts_object
    on ikg_facts(object_entity_id, predicate, as_of_date desc);
create index if not exists idx_ikg_facts_props
    on ikg_facts using gin (properties);

create table if not exists ikg_ownership_summary (
    company_vertex_id   varchar(200) not null,
    owner_vertex_id     varchar(200) not null,
    owner_name          text,
    quarter             varchar(20),
    holding_pct         numeric,
    pledge_pct          numeric,
    source_table        varchar(80) default 'shp_raw',
    source_uid          text,
    updated_at          timestamptz default now(),
    primary key (company_vertex_id, owner_vertex_id, quarter)
);
create index if not exists idx_ikg_ownership_summary_company
    on ikg_ownership_summary(company_vertex_id, quarter desc);
create index if not exists idx_ikg_ownership_summary_owner
    on ikg_ownership_summary(owner_vertex_id, holding_pct desc);

create table if not exists xbrl_filings_raw (
    id                  bigserial primary key,
    exchange            varchar(20) not null,
    source_uid          text not null,
    category            varchar(120) not null,
    symbol              varchar(20),
    scrip_code          varchar(10),
    cin                 varchar(21),
    isin                varchar(12),
    company_name        varchar(500),
    announced_at        timestamptz,
    attachment_url      text,
    source_url          text,
    taxonomy_namespaces jsonb default '[]'::jsonb,
    contexts_json       jsonb default '{}'::jsonb,
    facts_count         integer default 0,
    period_start        date,
    period_end          date,
    as_of_date          date,
    summary_json        jsonb default '{}'::jsonb,
    raw_xml             text,
    parser_version      varchar(80) default 'corporate_xbrl_v1',
    fetched_at          timestamptz default now(),
    unique (exchange, source_uid)
);
create index if not exists idx_xbrl_filings_cin
    on xbrl_filings_raw(cin, as_of_date desc);
create index if not exists idx_xbrl_filings_category
    on xbrl_filings_raw(category, as_of_date desc);

create table if not exists corporate_xbrl_facts (
    id                  bigserial primary key,
    exchange            varchar(20) not null,
    source_uid          text not null,
    category            varchar(120) not null,
    cin                 varchar(21),
    symbol              varchar(20),
    scrip_code          varchar(10),
    fact_name           text not null,
    fact_key            text,
    namespace           text,
    context_ref         text,
    unit_ref            text,
    decimals            text,
    value_text          text,
    value_numeric       numeric,
    period_start        date,
    period_end          date,
    instant             date,
    entity_identifier   text,
    attributes_json     jsonb default '{}'::jsonb,
    attachment_url      text,
    source_url          text,
    parser_version      varchar(80) default 'corporate_xbrl_v1',
    fetched_at          timestamptz default now()
);
create index if not exists idx_corporate_xbrl_facts_cin
    on corporate_xbrl_facts(cin, category, period_end desc);
create index if not exists idx_corporate_xbrl_facts_fact_key
    on corporate_xbrl_facts(fact_key);
create unique index if not exists idx_corporate_xbrl_facts_unique
    on corporate_xbrl_facts (
      exchange, source_uid, fact_name, coalesce(context_ref, ''),
      coalesce(unit_ref, ''), left(coalesce(value_text, ''), 500)
    );

create table if not exists financial_results_xbrl (
    id                      bigserial primary key,
    exchange                varchar(20) not null,
    source_uid              text not null,
    cin                     varchar(21),
    symbol                  varchar(20),
    scrip_code              varchar(10),
    company_name            varchar(500),
    announced_at            timestamptz,
    period_start            date,
    period_end              date,
    as_of_date              date,
    revenue_from_operations numeric,
    total_income            numeric,
    profit_before_tax       numeric,
    profit_after_tax        numeric,
    eps_basic               numeric,
    eps_diluted             numeric,
    net_worth               numeric,
    summary_json            jsonb default '{}'::jsonb,
    attachment_url          text,
    source_url              text,
    parser_version          varchar(80) default 'corporate_xbrl_v1',
    fetched_at              timestamptz default now(),
    unique (exchange, source_uid)
);
create index if not exists idx_financial_results_xbrl_cin
    on financial_results_xbrl(cin, period_end desc);

create table if not exists corporate_event_xbrl (
    id                  bigserial primary key,
    exchange            varchar(20) not null,
    source_uid          text not null,
    category            varchar(120) not null,
    cin                 varchar(21),
    symbol              varchar(20),
    scrip_code          varchar(10),
    company_name        varchar(500),
    announced_at        timestamptz,
    period_start        date,
    period_end          date,
    as_of_date          date,
    summary_json        jsonb default '{}'::jsonb,
    attachment_url      text,
    source_url          text,
    parser_version      varchar(80) default 'corporate_xbrl_v1',
    fetched_at          timestamptz default now(),
    unique (exchange, source_uid, category)
);
create index if not exists idx_corporate_event_xbrl_cin
    on corporate_event_xbrl(cin, category, as_of_date desc);

create table if not exists corporate_actions_raw (
    id                  bigserial primary key,
    exchange            varchar(20) not null,
    source_uid          text not null,
    cin                 varchar(21),
    symbol              varchar(20),
    scrip_code          varchar(10),
    company_name        varchar(500),
    announced_at        timestamptz,
    action_type         varchar(80) not null,
    ratio               varchar(80),
    record_date_raw     text,
    title               text,
    attachment_url      text,
    source_url          text,
    parser_version      varchar(80) default 'corporate_actions_v1',
    raw_json            jsonb default '{}'::jsonb,
    fetched_at          timestamptz default now(),
    unique (exchange, source_uid, action_type)
);
create index if not exists idx_corporate_actions_raw_cin
    on corporate_actions_raw(cin, announced_at desc);
create index if not exists idx_corporate_actions_raw_type
    on corporate_actions_raw(action_type, announced_at desc);

create table if not exists auditor_history_raw (
    id                  bigserial primary key,
    cin                 varchar(21) not null,
    auditor_name        text not null,
    role                varchar(80) default 'statutory_auditor',
    fiscal_year         varchar(20),
    source_table        varchar(80),
    source_uid          text,
    source_url          text,
    evidence_text       text,
    confidence          numeric(4,3) default 0.700,
    parser_version      varchar(80) default 'auditor_history_v1',
    fetched_at          timestamptz default now()
);
create index if not exists idx_auditor_history_raw_cin
    on auditor_history_raw(cin, fiscal_year desc);
create index if not exists idx_auditor_history_raw_name
    on auditor_history_raw using gin (auditor_name gin_trgm_ops);
create unique index if not exists idx_auditor_history_raw_unique
    on auditor_history_raw (cin, auditor_name, coalesce(fiscal_year, ''), coalesce(source_uid, ''));

create table if not exists document_sections (
    id                  bigserial primary key,
    document_uid        varchar(80) not null,
    source_table        varchar(80) not null,
    source_uid          varchar(80) not null,
    document_type       varchar(80) not null,
    section_type        varchar(120) not null,
    title               text,
    page_start          integer,
    page_end            integer,
    text                text,
    text_length         integer default 0,
    tables_markdown     text,
    confidence          numeric(4,3) default 0.800,
    source_url          text,
    metadata            jsonb default '{}'::jsonb,
    fetched_at          timestamptz default now(),
    updated_at          timestamptz default now(),
    unique (document_uid, section_type, page_start, page_end)
);
create index if not exists idx_document_sections_doc
    on document_sections(document_uid, page_start);
create index if not exists idx_document_sections_type
    on document_sections(document_type, section_type);
create index if not exists idx_document_sections_metadata
    on document_sections using gin (metadata);
create index if not exists idx_document_sections_text_fts
    on document_sections
    using gin (
      to_tsvector(
        'english',
        coalesce(document_uid, '') || ' ' ||
        coalesce(source_table, '') || ' ' ||
        coalesce(source_uid, '') || ' ' ||
        coalesce(document_type, '') || ' ' ||
        coalesce(section_type, '') || ' ' ||
        coalesce(title, '') || ' ' ||
        coalesce(text, '') || ' ' ||
        coalesce(tables_markdown, '') || ' ' ||
        coalesce(metadata::text, '')
      )
    );
create index if not exists idx_document_sections_source
    on document_sections(source_table, source_uid);

create table if not exists ikg_candidate_facts (
    id                  bigserial primary key,
    subject_entity_id   varchar(200) not null,
    predicate           varchar(80) not null,
    object_entity_id    varchar(200),
    object_value        text,
    value_numeric       numeric,
    confidence          numeric(4,3) default 0.500,
    candidate_status    varchar(30) default 'candidate',
    validation_state    varchar(30) default 'pending',
    source_type         varchar(50) default 'dreaming',
    source_url          text,
    evidence_text       text,
    metadata            jsonb default '{}'::jsonb,
    extracted_at        timestamptz default now(),
    promoted_at         timestamptz
);
create index if not exists idx_ikg_candidate_facts_subject
    on ikg_candidate_facts(subject_entity_id, predicate, extracted_at desc);
create index if not exists idx_ikg_candidate_facts_status
    on ikg_candidate_facts(candidate_status, validation_state, extracted_at desc);

create table if not exists ikg_refresh_hints (
    id                  bigserial primary key,
    entity_id           varchar(200),
    reason              text not null,
    priority            varchar(20) default 'normal',
    source_type         varchar(50) default 'dreaming',
    metadata            jsonb default '{}'::jsonb,
    status              varchar(20) default 'open',
    created_at          timestamptz default now(),
    updated_at          timestamptz default now()
);
create index if not exists idx_ikg_refresh_hints_status
    on ikg_refresh_hints(status, priority, created_at desc);
create index if not exists idx_ikg_refresh_hints_entity
    on ikg_refresh_hints(entity_id, created_at desc);
"""


def ensure_ikg_runtime_tables(database_url: str | None = None) -> bool:
    """Ensure core IKG runtime tables exist in Postgres/Supabase.

    This is intentionally idempotent and lightweight, so scrapers and scheduler
    can self-heal when a fresh Supabase database is used before full bootstrap
    SQL has been executed manually.
    """
    db_url = get_database_url(database_url)
    if not db_url:
        return False

    with _BOOTSTRAP_LOCK:
        if db_url in _BOOTSTRAPPED_URLS:
            return True
        try:
            import psycopg

            with psycopg.connect(db_url, connect_timeout=10) as conn:
                with conn.cursor() as cur:
                    cur.execute(_IKG_RUNTIME_BOOTSTRAP_SQL)
                conn.commit()
            _BOOTSTRAPPED_URLS.add(db_url)
            return True
        except Exception:
            return False


def connect_postgres(
    database_url: str | None = None,
    *,
    row_factory: object | None = None,
    connect_timeout: int = 10,
):
    """Create a psycopg connection compatible with Supabase PgBouncer poolers.

    Supabase pooler endpoints use transaction/session pooling where server-side
    prepared statements can collide across reused backend sessions. Setting
    `prepare_threshold=None` keeps psycopg in simple-query mode and avoids
    `prepared statement ... already exists` runtime failures.
    """
    import psycopg

    db_url = get_database_url(database_url)
    kwargs: dict[str, object] = {
        "connect_timeout": connect_timeout,
        "prepare_threshold": None,
    }
    if row_factory is not None:
        kwargs["row_factory"] = row_factory
    return psycopg.connect(db_url, **kwargs)
