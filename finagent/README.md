# FinAgent Runtime Notes

## Playwright / Chromium

Install the Python package and browser once in the same environment that runs
the gateway:

```bash
pip install -r finagent/requirements-finagent.txt
playwright install chromium
```

Chromium is reused through a small async pool. Useful knobs:

- `FINAGENT_BROWSER_FALLBACK=1` retries thin, blocked, or erroring search
  result pages through Chromium.
- `FINAGENT_BROWSER_FALLBACK_HTTP=1` retries blocked/erroring generic HTTP
  fetches through Chromium.
- `FINAGENT_BROWSER_MAX_PAGES=3` caps concurrent rendered pages.
- `FINAGENT_FETCH_CONCURRENCY=6` caps concurrent page fetches after search.

Browser helpers are available from `finagent.tools.browser`:

- `browser_extract(url, selector=None)` for allowlisted JavaScript-heavy pages.
- `screenshot_page(url_or_path)` for PNG screenshots.

## Search Backends

DuckDuckGo and Bing run by default. To merge a private SearXNG instance, set:

```bash
FINAGENT_SEARXNG_URL=https://your-searxng.example
```

The URL should serve the standard `/search?q=...&format=json` API.

Tier-1 domain-pinned breadth queries are on by default. Disable them with:

```bash
FINAGENT_DOMAIN_PINNED_QUERIES=0
```

## Marathon Mode

The widget's Marathon button calls `/research/deep` with a four-hour wall-clock
budget, twelve passes, and heartbeat SSE events every twenty seconds. API
callers can set the same controls directly:

```json
{
  "target": "TCS",
  "passes": 12,
  "pass_depth": 120,
  "max_wall_seconds": 14400,
  "heartbeat_interval_s": 20
}
```

The agent emits `phase=stopped` with `reason=time_budget` when the budget is
reached and then finishes with the evidence collected so far.

## Cloud Chat Interface

Use `/chat/research` when FinAgent runs behind a chat UI. It starts a
background job and returns URLs for polling, SSE, and final result retrieval:

```json
{
  "target": "TCS",
  "message": "Deep research memo with risks, valuation, and competitors",
  "mode": "standard"
}
```

Response fields:

- `status`: poll this URL for job state and latest phase.
- `events`: poll with `?after=N` for replayable event history.
- `stream`: optional SSE for live UIs.
- `result`: fetch memo/final payload when done.

`/capabilities` describes the agent's currently available search, browser,
skill, chart, and marathon features for orchestrators.

Session events and metadata are also written under
`FINAGENT_HOME/sessions/{session_id}/`, so polling can recover after an SSE
disconnect or after the live in-memory queue has been removed. For multi-replica
cloud deployments, put `FINAGENT_HOME` on shared persistent storage or replace
that directory with an object-store/Redis adapter.
