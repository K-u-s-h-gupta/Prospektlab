# IKG Database Allocation

This worker deployment separates app data from IKG data.

## Allocation

- Supabase: app/auth/product data only.
- Local Postgres container: durable IKG source of truth.
- Memgraph container: optional graph-serving projection rebuilt from Postgres.
- Qdrant container: vectors for `document_sections`.
- Azure Blob Storage: raw PDFs, XML, ZIP, CSV, extracted long text.
- Redis: Celery broker/result backend.

## Table Allocation

Keep these in Supabase:

```text
profiles
portfolio_mirrors
pending_extractions
token_usage
referral_sources
auth.*
storage.*
```

Move these to worker Postgres:

```text
runtime_controls
ikg_scheduler_locks
ikg_pipeline_runs
ikg_company_master
daily_prices
shp_raw
company_financials
director_source_records
directors_raw
sebi_corporate_filing_map
corporate_filings_raw
xbrl_filings_raw
corporate_xbrl_facts
financial_results_xbrl
corporate_event_xbrl
corporate_actions_raw
annual_reports_raw
annual_report_chunks
document_sections
concall_transcripts_raw
enforcement_raw
ikg_vertices
ikg_edges
ikg_facts
spl_strategies
compliance_ledger
```

Memgraph (when enabled) stores only a projection of `ikg_vertices`/`ikg_edges`. Qdrant stores
only embeddings and payloads derived from `document_sections`.

## Local IKG Postgres

The compose file starts a private Postgres service:

```text
postgresql://ikg_user:<IKG_POSTGRES_PASSWORD>@postgres:5432/ikg
```

The database is initialized from `deployment/ikg_db_bootstrap.sql` when the
volume is first created.

Set the password on the VM before starting:

```bash
export IKG_POSTGRES_PASSWORD='<strong-password>'
docker compose -f deployment/docker-compose.ikg.worker-only.yml up -d --build --scale celery-worker=2
```

From inside containers, use host `postgres`. From the VM shell, use
`127.0.0.1:15432` unless you override `IKG_POSTGRES_BIND`.

## Memgraph (Optional)

Memgraph is disabled by default in current compose files to reduce storage and
compute overhead. If you need Memgraph projection, set:

```text
FINAGENT_ENABLE_MEMGRAPH_PROJECTION=1
```

Then run a compose variant that includes Memgraph services.

When enabled, Memgraph runs privately on the VM:

```text
MEMGRAPH_URI=bolt://memgraph:7687
```

From the VM shell, use:

```text
bolt://127.0.0.1:7688
```

The host Memgraph ports default to `127.0.0.1:7688` and `127.0.0.1:3001`
so the worker compose stack can run even if a standalone Memgraph instance
already occupies `7687`/`3000`. Inside Docker, worker services still use
`bolt://memgraph:7687`.

Open the bundled Memgraph Lab UI at:

```text
http://127.0.0.1:3001
```

When using that Lab UI, connect with:

```text
Host: memgraph
Port: 7687
Username: <empty>
Password: <empty>
SSL/TLS: off
```

When using a desktop graph client from the host machine, connect with:

```text
Host: 127.0.0.1
Port: 7688
Username: <empty>
Password: <empty>
SSL/TLS: off
```

Initialize and project:

```bash
docker compose -f deployment/docker-compose.ikg.worker-only.yml exec -T scheduler \
  python -m finagent.ikg.pipeline.memgraph_projector --init

docker compose -f deployment/docker-compose.ikg.worker-only.yml exec -T scheduler \
  python -m finagent.ikg.pipeline.memgraph_projector --rebuild --max-companies 500
```

## Full Worker Run

```bash
docker compose -f deployment/docker-compose.ikg.worker-only.yml exec -T scheduler \
  python -m finagent.ikg.pipeline.celery_app --submit-nifty500 --max-companies 500 --years-back 7
```

The Celery chain now runs:

```text
scrapers -> director/KMP enrichment -> Postgres IKG build -> Qdrant index
```

## Backups

Back up Postgres daily:

```bash
docker compose -f deployment/docker-compose.ikg.worker-only.yml exec -T postgres \
  pg_dump -U ikg_user -d ikg > ikg_backup_$(date +%F).sql
```

Back up Docker volumes or mount them to a dedicated Azure data disk for
production use:

```text
postgres_data
memgraph_data
qdrant_storage
redis_data
```

## Rule

Postgres is authoritative. Memgraph and Qdrant are projections and can be
rebuilt.

## Supabase To Worker Migration

Start the worker database services:

```bash
docker compose -f deployment/docker-compose.ikg.worker-only.yml up -d postgres redis qdrant memgraph
```

Copy IKG tables from Supabase to worker Postgres:

```bash
python deployment/migrate_ikg_supabase_to_worker_postgres.py --bootstrap --truncate-target
```

Verify counts later without copying:

```bash
python deployment/migrate_ikg_supabase_to_worker_postgres.py --verify-only
```

Only after row counts match, prune Supabase by opening
`deployment/supabase_prune_ikg_after_worker_migration.sql`, setting
`really_prune := true`, and running it in Supabase SQL Editor.
