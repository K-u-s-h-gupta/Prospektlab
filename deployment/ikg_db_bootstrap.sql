-- IKG Database Bootstrap SQL
-- Run this against the IKG PostgreSQL database BEFORE running any scrapers.
--
-- Creates all staging tables for the data pipeline plus the IKG adjacency-list
-- tables used by the PostgreSQL graph backend.
--
-- Usage:
--   psql $IKG_DATABASE_URL -f deployment/ikg_db_bootstrap.sql
--
-- Idempotent: all creates use IF NOT EXISTS.

-- Enable trigram extension for fuzzy name search
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================
-- 0. Runtime Controls (pause/resume and watchdog state)
-- ============================================================

CREATE TABLE IF NOT EXISTS ikg_runtime_controls (
    control_key         VARCHAR(120) PRIMARY KEY,
    enabled             BOOLEAN NOT NULL DEFAULT true,
    control_group       VARCHAR(80) DEFAULT 'global',
    description         TEXT,
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ikg_runtime_controls_enabled
    ON ikg_runtime_controls(enabled);

INSERT INTO ikg_runtime_controls (control_key, enabled, control_group, description)
VALUES
    ('pipeline_enabled', true, 'global', 'Master switch for the IKG worker pipeline'),
    ('bse_enabled', true, 'scraping', 'Controls BSE scrapers and BSE-hosted documents'),
    ('nse_enabled', true, 'scraping', 'Controls NSE scrapers and transcripts'),
    ('mca_enabled', true, 'scraping', 'Controls MCA company and director refresh jobs'),
    ('sebi_enabled', true, 'scraping', 'Controls SEBI enforcement and filing jobs'),
    ('documents_enabled', true, 'documents', 'Controls attachment hydration and document ingestion'),
    ('financials_enabled', true, 'scraping', 'Controls financial refresh jobs'),
    ('graph_enabled', true, 'graph', 'Controls graph build and vector indexing jobs'),
    ('healthcheck_enabled', true, 'observability', 'Controls scheduler health checks'),
    ('official_monitor_enabled', true, 'content', 'Controls the 24/7 official-source content monitor'),
    ('dreaming_enabled', false, 'graph', 'Controls the nightly dreaming layer')
ON CONFLICT (control_key) DO NOTHING;

-- ============================================================
-- 1. Company Master (populated from MCA bulk CSV + NSE API)
-- ============================================================

CREATE TABLE IF NOT EXISTS ikg_company_master (
    id                      BIGSERIAL PRIMARY KEY,
    cin                     VARCHAR(21) UNIQUE,
    nse_symbol              VARCHAR(20) UNIQUE,
    bse_scrip_code          VARCHAR(10),
    isin                    VARCHAR(12),
    company_name            VARCHAR(500) NOT NULL,
    registration_date       DATE,
    category                VARCHAR(200),
    company_class           VARCHAR(50),
    listing_status          VARCHAR(50),
    authorized_capital      NUMERIC(20,2),
    paidup_capital          NUMERIC(20,2),
    roc                     VARCHAR(100),
    address                 TEXT,
    pin_code                VARCHAR(10),
    state                   VARCHAR(100),
    status                  VARCHAR(50),
    sub_category            VARCHAR(200),
    industrial_classification VARCHAR(200),
    sector                  VARCHAR(200),
    industry                VARCHAR(200),
    created_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

-- Indexes for entity resolution
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_cin ON ikg_company_master(cin);
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_nse ON ikg_company_master(nse_symbol);
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_isin ON ikg_company_master(isin);
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_bse ON ikg_company_master(bse_scrip_code);

-- Trigram index for fuzzy company name search
CREATE INDEX IF NOT EXISTS idx_ikg_company_master_name_trgm
    ON ikg_company_master USING GIN (upper(company_name) gin_trgm_ops);

-- ============================================================
-- 2. Shareholding Pattern Staging (BSE quarterly data)
-- ============================================================

CREATE TABLE IF NOT EXISTS shp_raw (
    id                          BIGSERIAL PRIMARY KEY,
    scrip_code                  VARCHAR(10) NOT NULL,
    cin                         VARCHAR(21),
    quarter                     VARCHAR(8) NOT NULL,    -- YYYYMM format
    total_promoter_holding_pct  NUMERIC(6,2),
    total_pledge_pct            NUMERIC(6,2),
    fii_holding_pct             NUMERIC(6,2),
    dii_holding_pct             NUMERIC(6,2),
    public_holding_pct          NUMERIC(6,2),
    promoter_groups_json        JSONB DEFAULT '[]'::jsonb,
    raw_json                    JSONB DEFAULT '{}'::jsonb,
    fetched_at                  TIMESTAMPTZ DEFAULT now(),
    UNIQUE (scrip_code, quarter)
);

CREATE INDEX IF NOT EXISTS idx_shp_raw_cin ON shp_raw(cin);
CREATE INDEX IF NOT EXISTS idx_shp_raw_quarter ON shp_raw(quarter);

-- ============================================================
-- 3. Director Records Staging (MCA21 data)
-- ============================================================

CREATE TABLE IF NOT EXISTS directors_raw (
    id                  BIGSERIAL PRIMARY KEY,
    cin                 VARCHAR(21) NOT NULL,
    din                 VARCHAR(10) NOT NULL,
    name                VARCHAR(300) NOT NULL,
    designation         VARCHAR(200),
    appointment_date    DATE,
    cessation_date      DATE,
    source              VARCHAR(80),
    source_url          TEXT,
    quarter             VARCHAR(20),
    nse_symbol          VARCHAR(20),
    bse_scrip_code      VARCHAR(10),
    confidence_score    NUMERIC(5,2),
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (cin, din)
);

CREATE INDEX IF NOT EXISTS idx_directors_raw_cin ON directors_raw(cin);
CREATE INDEX IF NOT EXISTS idx_directors_raw_din ON directors_raw(din);
CREATE INDEX IF NOT EXISTS idx_directors_raw_name ON directors_raw(name);
CREATE INDEX IF NOT EXISTS idx_directors_raw_source ON directors_raw(source, fetched_at DESC);

CREATE TABLE IF NOT EXISTS director_source_records (
    id                  BIGSERIAL PRIMARY KEY,
    source              VARCHAR(80) NOT NULL,
    cin                 VARCHAR(21),
    nse_symbol          VARCHAR(20),
    bse_scrip_code      VARCHAR(10),
    quarter             VARCHAR(20),
    filing_url          TEXT NOT NULL,
    title               TEXT,
    raw_json            JSONB DEFAULT '{}'::jsonb,
    extracted_text      TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_governance_directors_v1',
    status              VARCHAR(40) NOT NULL,
    error               TEXT,
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (source, filing_url)
);

CREATE INDEX IF NOT EXISTS idx_director_source_records_cin
    ON director_source_records(cin);
CREATE INDEX IF NOT EXISTS idx_director_source_records_status
    ON director_source_records(status, fetched_at DESC);

-- ============================================================
-- 4. BSE EOD Daily Prices
-- ============================================================

CREATE TABLE IF NOT EXISTS daily_prices (
    id              BIGSERIAL PRIMARY KEY,
    scrip_code      VARCHAR(10) NOT NULL,
    isin            VARCHAR(12),
    name            VARCHAR(300),
    trade_date      DATE NOT NULL,
    open            NUMERIC(12,2),
    high            NUMERIC(12,2),
    low             NUMERIC(12,2),
    close           NUMERIC(12,2),
    prev_close      NUMERIC(12,2),
    volume          BIGINT,
    value_lakh      NUMERIC(20,4),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (scrip_code, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_prices_scrip ON daily_prices(scrip_code);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_daily_prices_isin ON daily_prices(isin);

-- ============================================================
-- 5. Financial Data (yfinance + Screener.in cross-validated)
-- ============================================================

CREATE TABLE IF NOT EXISTS company_financials (
    id                      BIGSERIAL PRIMARY KEY,
    cin                     VARCHAR(21),
    nse_symbol              VARCHAR(20) UNIQUE,
    sources_used            TEXT[],
    validated_metrics_json  JSONB DEFAULT '{}'::jsonb,
    discrepancies_json      JSONB DEFAULT '[]'::jsonb,
    income_statement_json   JSONB DEFAULT '[]'::jsonb,
    balance_sheet_json      JSONB DEFAULT '[]'::jsonb,
    cashflow_json           JSONB DEFAULT '[]'::jsonb,
    fetched_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_company_financials_cin ON company_financials(cin);
CREATE INDEX IF NOT EXISTS idx_company_financials_symbol ON company_financials(nse_symbol);

-- ============================================================
-- 6. SEBI Enforcement Orders Staging
-- ============================================================

CREATE TABLE IF NOT EXISTS enforcement_raw (
    id                  BIGSERIAL PRIMARY KEY,
    order_number        VARCHAR(100) UNIQUE NOT NULL,
    regulator           VARCHAR(20) DEFAULT 'SEBI',
    violation_type      VARCHAR(200),
    penalty_amount_inr  NUMERIC(20,2),
    order_date          DATE,
    pdf_url             TEXT,
    full_text           TEXT,
    entities_json       JSONB DEFAULT '[]'::jsonb,  -- extracted company/person mentions
    status              VARCHAR(50) DEFAULT 'active',
    fetched_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_enforcement_raw_date ON enforcement_raw(order_date DESC);
CREATE INDEX IF NOT EXISTS idx_enforcement_raw_regulator ON enforcement_raw(regulator);

-- ============================================================
-- 7. SEBI Corporate Filing Navigation Map
-- ============================================================

CREATE TABLE IF NOT EXISTS sebi_corporate_filing_map (
    id                  BIGSERIAL PRIMARY KEY,
    category            VARCHAR(120) NOT NULL,
    exchange            VARCHAR(20),
    title               TEXT NOT NULL,
    url                 TEXT NOT NULL UNIQUE,
    source_page         TEXT NOT NULL,
    raw_json            JSONB DEFAULT '{}'::jsonb,
    fetched_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sebi_corp_filing_category
    ON sebi_corporate_filing_map(category);
CREATE INDEX IF NOT EXISTS idx_sebi_corp_filing_exchange
    ON sebi_corporate_filing_map(exchange);

CREATE TABLE IF NOT EXISTS corporate_filings_raw (
    id                  BIGSERIAL PRIMARY KEY,
    category            VARCHAR(120) NOT NULL,
    exchange            VARCHAR(20) NOT NULL,
    symbol              VARCHAR(20),
    scrip_code          VARCHAR(10),
    cin                 VARCHAR(21),
    isin                VARCHAR(12),
    company_name        VARCHAR(500),
    announced_at        TIMESTAMPTZ,
    title               TEXT,
    description         TEXT,
    attachment_url      TEXT,
    attachment_text     TEXT,
    attachment_text_length INTEGER DEFAULT 0,
    attachment_sha256   VARCHAR(64),
    attachment_content_type VARCHAR(120),
    attachment_extracted_model VARCHAR(120),
    attachment_page_count INTEGER DEFAULT 0,
    attachment_extraction_status VARCHAR(30) DEFAULT 'pending',
    attachment_extraction_error TEXT,
    source_url          TEXT,
    source_uid          TEXT NOT NULL,
    source_map_url      TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_filings_documents_v1',
    raw_json            JSONB DEFAULT '{}'::jsonb,
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exchange, source_uid)
);

CREATE INDEX IF NOT EXISTS idx_corporate_filings_raw_category
    ON corporate_filings_raw(category, exchange);
CREATE INDEX IF NOT EXISTS idx_corporate_filings_raw_symbol
    ON corporate_filings_raw(symbol, announced_at DESC);
CREATE INDEX IF NOT EXISTS idx_corporate_filings_raw_cin
    ON corporate_filings_raw(cin, announced_at DESC);

-- ============================================================
-- 8. Concall transcripts (NSE corporate announcements)
-- ============================================================

CREATE TABLE IF NOT EXISTS concall_transcripts_raw (
    id                  BIGSERIAL PRIMARY KEY,
    symbol              VARCHAR(20) NOT NULL,
    company_name        VARCHAR(500),
    cin                 VARCHAR(21),
    isin                VARCHAR(12),
    exchange            VARCHAR(10) DEFAULT 'NSE',
    announced_at        TIMESTAMPTZ NOT NULL,
    quarter_label       VARCHAR(20),
    fiscal_year         INTEGER,
    subject             TEXT,
    description         TEXT,
    attachment_url      TEXT NOT NULL,
    attachment_size_mb  NUMERIC(12,4),
    transcript_text     TEXT,
    text_length         INTEGER DEFAULT 0,
    extracted_model     VARCHAR(120),
    extraction_status   VARCHAR(30) DEFAULT 'unknown',
    sentiment_label     VARCHAR(20),
    sentiment_score     NUMERIC(8,4),
    intent_tags_json    JSONB DEFAULT '[]'::jsonb,
    raw_json            JSONB DEFAULT '{}'::jsonb,
    source_url          TEXT,
    parser_version      VARCHAR(80),
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (symbol, announced_at, attachment_url)
);

CREATE INDEX IF NOT EXISTS idx_concall_symbol_announced
    ON concall_transcripts_raw(symbol, announced_at DESC);
CREATE INDEX IF NOT EXISTS idx_concall_cin_announced
    ON concall_transcripts_raw(cin, announced_at DESC);
CREATE INDEX IF NOT EXISTS idx_concall_quarter
    ON concall_transcripts_raw(quarter_label, fiscal_year);

-- ============================================================
-- 9. Annual reports + extracted chunks (BSE + Azure DI)
-- ============================================================

CREATE TABLE IF NOT EXISTS annual_reports_raw (
    id                      BIGSERIAL PRIMARY KEY,
    report_uid              VARCHAR(32) NOT NULL UNIQUE,
    scrip_code              VARCHAR(10) NOT NULL,
    cin                     VARCHAR(21),
    nse_symbol              VARCHAR(20),
    company_name            VARCHAR(500),
    report_year             VARCHAR(20) NOT NULL,
    pdf_url                 TEXT NOT NULL,
    pdf_local_path          TEXT,
    source_url              TEXT,
    parser_version          VARCHAR(80) DEFAULT 'bse_annual_reports_v2',
    extraction_status       VARCHAR(30) NOT NULL DEFAULT 'pending',
    extraction_error        TEXT,
    full_text               TEXT,
    full_text_length        INTEGER DEFAULT 0,
    tables_markdown         TEXT,
    tables_count            INTEGER DEFAULT 0,
    kv_pairs_count          INTEGER DEFAULT 0,
    page_count              INTEGER DEFAULT 0,
    extracted_model         VARCHAR(120),
    extraction_duration_s   NUMERIC(12,3),
    raw_json                JSONB DEFAULT '{}'::jsonb,
    fetched_at              TIMESTAMPTZ DEFAULT now(),
    updated_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE (scrip_code, report_year, pdf_url)
);

CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_cin
    ON annual_reports_raw(cin);
CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_symbol
    ON annual_reports_raw(nse_symbol, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_scrip
    ON annual_reports_raw(scrip_code, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_year
    ON annual_reports_raw(report_year);
CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_status
    ON annual_reports_raw(extraction_status, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_annual_reports_raw_fetched
    ON annual_reports_raw(fetched_at DESC);

CREATE TABLE IF NOT EXISTS annual_report_chunks (
    id                      BIGSERIAL PRIMARY KEY,
    report_uid              VARCHAR(32) NOT NULL REFERENCES annual_reports_raw(report_uid) ON DELETE CASCADE,
    chunk_index             INTEGER NOT NULL,
    total_chunks            INTEGER DEFAULT 0,
    chunk_id                VARCHAR(64),
    chunk_text              TEXT NOT NULL,
    char_count              INTEGER DEFAULT 0,
    source_file             TEXT,
    source_type             VARCHAR(40) DEFAULT 'annual_report',
    metadata                JSONB DEFAULT '{}'::jsonb,
    fetched_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE (report_uid, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_annual_report_chunks_report
    ON annual_report_chunks(report_uid, chunk_index);

-- ============================================================
-- 10. Pipeline observability and scheduler locks
-- ============================================================

CREATE TABLE IF NOT EXISTS ikg_pipeline_runs (
    run_id              TEXT PRIMARY KEY,
    task_name           VARCHAR(120) NOT NULL,
    source_name         VARCHAR(120),
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_s          NUMERIC(12,2),
    records_fetched     INTEGER DEFAULT 0,
    records_stored      INTEGER DEFAULT 0,
    records_failed      INTEGER DEFAULT 0,
    success             BOOLEAN DEFAULT false,
    error               TEXT,
    official_source_url TEXT,
    http_status         INTEGER,
    parser_version      VARCHAR(80),
    metadata            JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ikg_pipeline_runs_task_created
    ON ikg_pipeline_runs(task_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_pipeline_runs_success
    ON ikg_pipeline_runs(success, created_at DESC);

CREATE TABLE IF NOT EXISTS ikg_scheduler_locks (
    job_id              VARCHAR(120) PRIMARY KEY,
    locked_by           TEXT NOT NULL,
    locked_until        TIMESTAMPTZ NOT NULL,
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ikg_scheduler_locks_until
    ON ikg_scheduler_locks(locked_until);

-- ============================================================
-- 11. IKG Graph Tables (for PostgreSQL graph backend)
-- ============================================================

CREATE TABLE IF NOT EXISTS ikg_vertices (
    vertex_id       VARCHAR(200) PRIMARY KEY,
    label           VARCHAR(50) NOT NULL,
    properties      JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ikg_vertices_label ON ikg_vertices(label);
CREATE INDEX IF NOT EXISTS idx_ikg_vertices_props ON ikg_vertices USING GIN (properties);

CREATE TABLE IF NOT EXISTS ikg_edges (
    id              BIGSERIAL PRIMARY KEY,
    from_vertex_id  VARCHAR(200) NOT NULL REFERENCES ikg_vertices(vertex_id) ON DELETE CASCADE,
    to_vertex_id    VARCHAR(200) NOT NULL REFERENCES ikg_vertices(vertex_id) ON DELETE CASCADE,
    label           VARCHAR(50) NOT NULL,
    properties      JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE (from_vertex_id, to_vertex_id, label)
);

CREATE INDEX IF NOT EXISTS idx_ikg_edges_from ON ikg_edges(from_vertex_id);
CREATE INDEX IF NOT EXISTS idx_ikg_edges_to ON ikg_edges(to_vertex_id);
CREATE INDEX IF NOT EXISTS idx_ikg_edges_label ON ikg_edges(label);

CREATE TABLE IF NOT EXISTS ikg_canonical_entities (
    entity_id           VARCHAR(160) PRIMARY KEY,
    entity_type         VARCHAR(50) NOT NULL,
    display_name        TEXT NOT NULL,
    primary_identifier  TEXT,
    properties          JSONB DEFAULT '{}'::jsonb,
    confidence          NUMERIC(4,3) DEFAULT 1.000,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ikg_canonical_entities_type
    ON ikg_canonical_entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_ikg_canonical_entities_props
    ON ikg_canonical_entities USING GIN (properties);

CREATE TABLE IF NOT EXISTS ikg_entity_aliases (
    alias_id            BIGSERIAL PRIMARY KEY,
    entity_id           VARCHAR(160) NOT NULL REFERENCES ikg_canonical_entities(entity_id) ON DELETE CASCADE,
    alias               TEXT NOT NULL,
    alias_type          VARCHAR(50) DEFAULT 'name',
    source_citation     TEXT,
    confidence          NUMERIC(4,3) DEFAULT 0.900,
    created_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (entity_id, alias, alias_type)
);
CREATE INDEX IF NOT EXISTS idx_ikg_entity_aliases_alias
    ON ikg_entity_aliases USING GIN (alias gin_trgm_ops);

CREATE TABLE IF NOT EXISTS ikg_facts (
    fact_id             VARCHAR(220) PRIMARY KEY,
    subject_entity_id   VARCHAR(200) NOT NULL,
    predicate           VARCHAR(80) NOT NULL,
    object_entity_id    VARCHAR(200),
    object_value        TEXT,
    value_numeric       NUMERIC,
    valid_from          DATE,
    valid_to            DATE,
    as_of_date          DATE,
    event_date          DATE,
    confidence          NUMERIC(4,3) DEFAULT 1.000,
    source_table        VARCHAR(80),
    source_uid          TEXT,
    source_url          TEXT,
    evidence_text       TEXT,
    properties          JSONB DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ikg_facts_subject_predicate
    ON ikg_facts(subject_entity_id, predicate, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_facts_object
    ON ikg_facts(object_entity_id, predicate, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_facts_props
    ON ikg_facts USING GIN (properties);

CREATE TABLE IF NOT EXISTS ikg_ownership_summary (
    company_vertex_id   VARCHAR(200) NOT NULL,
    owner_vertex_id     VARCHAR(200) NOT NULL,
    owner_name          TEXT,
    quarter             VARCHAR(20),
    holding_pct         NUMERIC,
    pledge_pct          NUMERIC,
    source_table        VARCHAR(80) DEFAULT 'shp_raw',
    source_uid          TEXT,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (company_vertex_id, owner_vertex_id, quarter)
);
CREATE INDEX IF NOT EXISTS idx_ikg_ownership_summary_company
    ON ikg_ownership_summary(company_vertex_id, quarter DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_ownership_summary_owner
    ON ikg_ownership_summary(owner_vertex_id, holding_pct DESC);

-- ============================================================
-- 11a. Corporate XBRL normalized facts (official NSE/BSE filings)
-- ============================================================

CREATE TABLE IF NOT EXISTS xbrl_filings_raw (
    id                  BIGSERIAL PRIMARY KEY,
    exchange            VARCHAR(20) NOT NULL,
    source_uid          TEXT NOT NULL,
    category            VARCHAR(120) NOT NULL,
    symbol              VARCHAR(20),
    scrip_code          VARCHAR(10),
    cin                 VARCHAR(21),
    isin                VARCHAR(12),
    company_name        VARCHAR(500),
    announced_at        TIMESTAMPTZ,
    attachment_url      TEXT,
    source_url          TEXT,
    taxonomy_namespaces JSONB DEFAULT '[]'::jsonb,
    contexts_json       JSONB DEFAULT '{}'::jsonb,
    facts_count         INTEGER DEFAULT 0,
    period_start        DATE,
    period_end          DATE,
    as_of_date          DATE,
    summary_json        JSONB DEFAULT '{}'::jsonb,
    raw_xml             TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_xbrl_v1',
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exchange, source_uid)
);
CREATE INDEX IF NOT EXISTS idx_xbrl_filings_cin
    ON xbrl_filings_raw(cin, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_xbrl_filings_category
    ON xbrl_filings_raw(category, as_of_date DESC);

CREATE TABLE IF NOT EXISTS corporate_xbrl_facts (
    id                  BIGSERIAL PRIMARY KEY,
    exchange            VARCHAR(20) NOT NULL,
    source_uid          TEXT NOT NULL,
    category            VARCHAR(120) NOT NULL,
    cin                 VARCHAR(21),
    symbol              VARCHAR(20),
    scrip_code          VARCHAR(10),
    fact_name           TEXT NOT NULL,
    fact_key            TEXT,
    namespace           TEXT,
    context_ref         TEXT,
    unit_ref            TEXT,
    decimals            TEXT,
    value_text          TEXT,
    value_numeric       NUMERIC,
    period_start        DATE,
    period_end          DATE,
    instant             DATE,
    entity_identifier   TEXT,
    attributes_json     JSONB DEFAULT '{}'::jsonb,
    attachment_url      TEXT,
    source_url          TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_xbrl_v1',
    fetched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_corporate_xbrl_facts_cin
    ON corporate_xbrl_facts(cin, category, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_corporate_xbrl_facts_fact_key
    ON corporate_xbrl_facts(fact_key);
CREATE UNIQUE INDEX IF NOT EXISTS idx_corporate_xbrl_facts_unique
    ON corporate_xbrl_facts (
      exchange, source_uid, fact_name, coalesce(context_ref, ''),
      coalesce(unit_ref, ''), left(coalesce(value_text, ''), 500)
    );

CREATE TABLE IF NOT EXISTS financial_results_xbrl (
    id                      BIGSERIAL PRIMARY KEY,
    exchange                VARCHAR(20) NOT NULL,
    source_uid              TEXT NOT NULL,
    cin                     VARCHAR(21),
    symbol                  VARCHAR(20),
    scrip_code              VARCHAR(10),
    company_name            VARCHAR(500),
    announced_at            TIMESTAMPTZ,
    period_start            DATE,
    period_end              DATE,
    as_of_date              DATE,
    revenue_from_operations NUMERIC,
    total_income            NUMERIC,
    profit_before_tax       NUMERIC,
    profit_after_tax        NUMERIC,
    eps_basic               NUMERIC,
    eps_diluted             NUMERIC,
    net_worth               NUMERIC,
    summary_json            JSONB DEFAULT '{}'::jsonb,
    attachment_url          TEXT,
    source_url              TEXT,
    parser_version          VARCHAR(80) DEFAULT 'corporate_xbrl_v1',
    fetched_at              TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exchange, source_uid)
);
CREATE INDEX IF NOT EXISTS idx_financial_results_xbrl_cin
    ON financial_results_xbrl(cin, period_end DESC);

CREATE TABLE IF NOT EXISTS corporate_event_xbrl (
    id                  BIGSERIAL PRIMARY KEY,
    exchange            VARCHAR(20) NOT NULL,
    source_uid          TEXT NOT NULL,
    category            VARCHAR(120) NOT NULL,
    cin                 VARCHAR(21),
    symbol              VARCHAR(20),
    scrip_code          VARCHAR(10),
    company_name        VARCHAR(500),
    announced_at        TIMESTAMPTZ,
    period_start        DATE,
    period_end          DATE,
    as_of_date          DATE,
    summary_json        JSONB DEFAULT '{}'::jsonb,
    attachment_url      TEXT,
    source_url          TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_xbrl_v1',
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exchange, source_uid, category)
);
CREATE INDEX IF NOT EXISTS idx_corporate_event_xbrl_cin
    ON corporate_event_xbrl(cin, category, as_of_date DESC);

CREATE TABLE IF NOT EXISTS corporate_actions_raw (
    id                  BIGSERIAL PRIMARY KEY,
    exchange            VARCHAR(20) NOT NULL,
    source_uid          TEXT NOT NULL,
    cin                 VARCHAR(21),
    symbol              VARCHAR(20),
    scrip_code          VARCHAR(10),
    company_name        VARCHAR(500),
    announced_at        TIMESTAMPTZ,
    action_type         VARCHAR(80) NOT NULL,
    ratio               VARCHAR(80),
    record_date_raw     TEXT,
    title               TEXT,
    attachment_url      TEXT,
    source_url          TEXT,
    parser_version      VARCHAR(80) DEFAULT 'corporate_actions_v1',
    raw_json            JSONB DEFAULT '{}'::jsonb,
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (exchange, source_uid, action_type)
);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_raw_cin
    ON corporate_actions_raw(cin, announced_at DESC);
CREATE INDEX IF NOT EXISTS idx_corporate_actions_raw_type
    ON corporate_actions_raw(action_type, announced_at DESC);

CREATE TABLE IF NOT EXISTS auditor_history_raw (
    id                  BIGSERIAL PRIMARY KEY,
    cin                 VARCHAR(21) NOT NULL,
    auditor_name        TEXT NOT NULL,
    role                VARCHAR(80) DEFAULT 'statutory_auditor',
    fiscal_year         VARCHAR(20),
    source_table        VARCHAR(80),
    source_uid          TEXT,
    source_url          TEXT,
    evidence_text       TEXT,
    confidence          NUMERIC(4,3) DEFAULT 0.700,
    parser_version      VARCHAR(80) DEFAULT 'auditor_history_v1',
    fetched_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_auditor_history_raw_cin
    ON auditor_history_raw(cin, fiscal_year DESC);
CREATE INDEX IF NOT EXISTS idx_auditor_history_raw_name
    ON auditor_history_raw USING GIN (auditor_name gin_trgm_ops);
CREATE UNIQUE INDEX IF NOT EXISTS idx_auditor_history_raw_unique
    ON auditor_history_raw (cin, auditor_name, coalesce(fiscal_year, ''), coalesce(source_uid, ''));

CREATE TABLE IF NOT EXISTS document_sections (
    id                  BIGSERIAL PRIMARY KEY,
    document_uid        VARCHAR(80) NOT NULL,
    source_table        VARCHAR(80) NOT NULL,
    source_uid          VARCHAR(80) NOT NULL,
    document_type       VARCHAR(80) NOT NULL,
    section_type        VARCHAR(120) NOT NULL,
    title               TEXT,
    page_start          INTEGER,
    page_end            INTEGER,
    text                TEXT,
    text_length         INTEGER DEFAULT 0,
    tables_markdown     TEXT,
    confidence          NUMERIC(4,3) DEFAULT 0.800,
    source_url          TEXT,
    metadata            JSONB DEFAULT '{}'::jsonb,
    fetched_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now(),
    UNIQUE (document_uid, section_type, page_start, page_end)
);
CREATE INDEX IF NOT EXISTS idx_document_sections_doc
    ON document_sections(document_uid, page_start);
CREATE INDEX IF NOT EXISTS idx_document_sections_type
    ON document_sections(document_type, section_type);
CREATE INDEX IF NOT EXISTS idx_document_sections_metadata
    ON document_sections USING GIN (metadata);
CREATE INDEX IF NOT EXISTS idx_document_sections_text_fts
    ON document_sections
    USING GIN (
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
CREATE INDEX IF NOT EXISTS idx_document_sections_source
    ON document_sections(source_table, source_uid);

CREATE TABLE IF NOT EXISTS ikg_candidate_facts (
    id                  BIGSERIAL PRIMARY KEY,
    subject_entity_id   VARCHAR(200) NOT NULL,
    predicate           VARCHAR(80) NOT NULL,
    object_entity_id    VARCHAR(200),
    object_value        TEXT,
    value_numeric       NUMERIC,
    confidence          NUMERIC(4,3) DEFAULT 0.500,
    candidate_status    VARCHAR(30) DEFAULT 'candidate',
    validation_state    VARCHAR(30) DEFAULT 'pending',
    source_type         VARCHAR(50) DEFAULT 'dreaming',
    source_url          TEXT,
    evidence_text       TEXT,
    metadata            JSONB DEFAULT '{}'::jsonb,
    extracted_at        TIMESTAMPTZ DEFAULT now(),
    promoted_at         TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ikg_candidate_facts_subject
    ON ikg_candidate_facts(subject_entity_id, predicate, extracted_at DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_candidate_facts_status
    ON ikg_candidate_facts(candidate_status, validation_state, extracted_at DESC);

CREATE TABLE IF NOT EXISTS ikg_refresh_hints (
    id                  BIGSERIAL PRIMARY KEY,
    entity_id           VARCHAR(200),
    reason              TEXT NOT NULL,
    priority            VARCHAR(20) DEFAULT 'normal',
    source_type         VARCHAR(50) DEFAULT 'dreaming',
    metadata            JSONB DEFAULT '{}'::jsonb,
    status              VARCHAR(20) DEFAULT 'open',
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ikg_refresh_hints_status
    ON ikg_refresh_hints(status, priority, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ikg_refresh_hints_entity
    ON ikg_refresh_hints(entity_id, created_at DESC);

-- ============================================================
-- 12. Self-Learning Stack (Phase 3)
-- ============================================================

CREATE TABLE IF NOT EXISTS spl_strategies (
    id                  BIGSERIAL PRIMARY KEY,
    strategy_text       TEXT NOT NULL,
    sector              VARCHAR(200),
    company_type        VARCHAR(100),  -- 'large_cap', 'mid_cap', 'psu', etc.
    research_type       VARCHAR(100),  -- 'governance', 'valuation', 'risk', etc.
    confidence_score    NUMERIC(4,3) DEFAULT 0.5,
    times_applied       INTEGER DEFAULT 0,
    times_successful    INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_spl_sector_type ON spl_strategies(sector, research_type);
CREATE INDEX IF NOT EXISTS idx_spl_confidence ON spl_strategies(confidence_score DESC, times_applied DESC);

-- ============================================================
-- 13. Compliance Ledger (Phase 6, write-only append)
-- ============================================================

CREATE TABLE IF NOT EXISTS compliance_ledger (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          UUID NOT NULL,
    query_text          TEXT,
    entity_name         VARCHAR(500),
    entity_cin          VARCHAR(21),
    blueprint_spec_json JSONB,
    data_sources_json   JSONB,
    output_hash         VARCHAR(64),  -- SHA-256 of final memo
    grader_score        INTEGER,
    sebi_violations     INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT now()
    -- NO update or delete allowed on this table (append-only)
);

CREATE INDEX IF NOT EXISTS idx_compliance_ledger_session ON compliance_ledger(session_id);
CREATE INDEX IF NOT EXISTS idx_compliance_ledger_entity ON compliance_ledger(entity_cin);
CREATE INDEX IF NOT EXISTS idx_compliance_ledger_created ON compliance_ledger(created_at DESC);

-- Revoke UPDATE/DELETE on compliance_ledger (run as superuser)
-- REVOKE UPDATE, DELETE ON compliance_ledger FROM finagent_app;

-- ============================================================
-- Pipeline monitoring view
-- ============================================================

CREATE OR REPLACE VIEW pipeline_health AS
SELECT
    'company_master' AS table_name,
    count(*) AS record_count,
    max(updated_at) AS last_updated,
    CASE WHEN max(updated_at) > now() - interval '32 days' THEN 'fresh' ELSE 'stale' END AS freshness
FROM ikg_company_master

UNION ALL

SELECT
    'daily_prices',
    count(*),
    max(created_at),
    CASE WHEN max(trade_date) > current_date - 3 THEN 'fresh' ELSE 'stale' END
FROM daily_prices

UNION ALL

SELECT
    'shp_raw',
    count(*),
    max(fetched_at),
    CASE WHEN max(fetched_at) > now() - interval '95 days' THEN 'fresh' ELSE 'stale' END
FROM shp_raw

UNION ALL

SELECT
    'directors_raw',
    count(*),
    max(fetched_at),
    CASE WHEN max(fetched_at) > now() - interval '32 days' THEN 'fresh' ELSE 'stale' END
FROM directors_raw

UNION ALL

SELECT
    'concall_transcripts_raw',
    count(*),
    max(announced_at),
    CASE WHEN max(announced_at) > now() - interval '100 days' THEN 'fresh' ELSE 'stale' END
FROM concall_transcripts_raw

UNION ALL

SELECT
    'annual_reports_raw',
    count(*),
    max(fetched_at),
    CASE WHEN max(fetched_at) > now() - interval '380 days' THEN 'fresh' ELSE 'stale' END
FROM annual_reports_raw

UNION ALL

SELECT
    'ikg_vertices',
    count(*),
    max(updated_at),
    CASE WHEN count(*) > 100 THEN 'bootstrapped' ELSE 'empty' END
FROM ikg_vertices;

-- Supabase service role permissions for backend/scheduler direct API usage.
-- Plain worker Postgres does not have this role, so keep the grants optional.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    GRANT USAGE ON SCHEMA public TO service_role;
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE
        ikg_company_master,
        shp_raw,
        directors_raw,
        daily_prices,
        company_financials,
        enforcement_raw,
        sebi_corporate_filing_map,
        corporate_filings_raw,
        concall_transcripts_raw,
        annual_reports_raw,
        annual_report_chunks,
        document_sections,
        ikg_pipeline_runs,
        ikg_scheduler_locks,
        ikg_vertices,
        ikg_edges,
        ikg_canonical_entities,
        ikg_entity_aliases,
        ikg_facts,
        spl_strategies,
        compliance_ledger
    TO service_role;

    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
  END IF;
END $$;

-- Done
SELECT 'IKG database bootstrap complete' AS status;
