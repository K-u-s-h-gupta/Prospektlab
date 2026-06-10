# IKG Scraper/Graph Worker Deployment

This deploys only the always-on scraping, graph build, and retrieval-indexing
runtime. It does not deploy the FastAPI app or frontend.

Qdrant is self-hosted in Docker Compose. It does not use Qdrant Cloud and does
not require a Qdrant API key. Workers reach it through Docker networking at
`http://qdrant:6333`; the host port is bound to `127.0.0.1` only for local
debugging.

## Local Or Single-VM Docker Compose

From `D:\PROSPEKTLAB`:

```powershell
docker compose -f deployment/docker-compose.ikg.yml up -d --build --scale celery-worker=10
```

That starts:

- Redis broker/result backend
- Self-hosted Qdrant vector database with persistent volume
- 10 Celery worker containers, each with `--concurrency=10`
- One APScheduler container

Total worker slots: `10 replicas * 10 threads = 100`.

Check health:

```powershell
docker compose -f deployment/docker-compose.ikg.yml ps
docker compose -f deployment/docker-compose.ikg.yml logs -f scheduler
docker compose -f deployment/docker-compose.ikg.yml logs -f celery-worker
```

Submit a manual Nifty 100 run:

```powershell
docker compose -f deployment/docker-compose.ikg.yml exec scheduler `
  python -m finagent.ikg.pipeline.celery_app --submit-nifty500 --max-companies 100 --years-back 3
```

Rebuild Qdrant from existing Supabase data:

```powershell
docker compose -f deployment/docker-compose.ikg.yml exec scheduler `
  python -m finagent.ikg.pipeline.orchestrator --phase qdrant_index
```

Run the watchdog once:

```powershell
bash deployment/ikg_watchdog.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File deployment\ikg_watchdog.ps1
```

If Docker Desktop is not available, you can still run a direct local pipeline
task without Docker by calling the orchestrator through `uv`:

```powershell
uv run python -m finagent.ikg.pipeline.orchestrator --phase nifty500_parallel --max-companies 5 --years-back 3
```

## Required Environment

Fill `finagent/.env` before deployment:

```dotenv
IKG_BACKEND=postgres
IKG_DATABASE_URL=<supabase-direct-or-pooler-postgres-url>
DATABASE_URL=<same-url>
SUPABASE_DB_URL=<same-url>

OPENAI_API_KEY=<already-present-key>
AZURE_DI_ENDPOINT=<document-intelligence-endpoint>
AZURE_DI_KEY=<document-intelligence-key>

FINAGENT_RETRIEVAL_BACKEND=qdrant_postgres
FINAGENT_DISABLE_AZURE_SEARCH=1
QDRANT_COLLECTION=ikg_document_sections
QDRANT_API_KEY=

FINAGENT_SCHEDULER_USE_CELERY=1
FINAGENT_ANNUAL_REPORT_EXTRACT_MODE=targeted_top100_mcap
FINAGENT_ANNUAL_REPORT_TARGETED_TOP_N=100
```

## Production Notes

- Run exactly one scheduler replica.
- Scale Celery workers horizontally.
- Keep Redis and Qdrant on persistent storage.
- Add a host cron or scheduled task that runs `deployment/ikg_watchdog.sh`
  every 5 minutes on Linux, or `deployment\ikg_watchdog.ps1` on Windows.
- A good Linux cron line is:

```cron
*/5 * * * * /opt/prospektlab/deployment/ikg_watchdog.sh >> /var/log/ikg-watchdog.log 2>&1
```

- Do not expose Qdrant ports publicly. The compose file binds Qdrant to
  localhost; production workers should keep using the internal Docker hostname
  `qdrant`.
- Keep Supabase as the canonical source of truth.
- Qdrant can be rebuilt from Supabase `document_sections`, so Supabase remains authoritative.
- If official sites start throttling, reduce `--scale celery-worker` first, not data quality.
