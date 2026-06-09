-- Supabase IKG runtime table bootstrap (idempotent)
-- Run in Supabase SQL Editor if graph/runtime tables are missing.

create extension if not exists pg_trgm;

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
