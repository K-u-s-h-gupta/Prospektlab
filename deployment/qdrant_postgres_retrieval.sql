-- Qdrant + Postgres full-text retrieval support for IKG document sections.
-- Run this in Supabase SQL Editor if the runtime bootstrap has not already
-- created the indexes automatically.

create extension if not exists pg_trgm;

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
