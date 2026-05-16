# Marathon runs and Chromium (Playwright)

## Wall-clock budget and heartbeats

- Set `max_wall_seconds` on `POST /research/start` or `POST /research/deep` (up to 24h).
- `heartbeat_interval_s` (default 20) emits SSE `heartbeat` events so proxies and browsers do not drop long-lived connections.
- When the budget is exhausted, the agent emits `phase: stopped` with `reason: time_budget` and finishes synthesis from evidence collected so far.

## Deep / marathon entrypoints

- `POST /research/deep` — chained passes (`passes`, `pass_depth`, optional `max_wall_seconds`).
- `POST /chat/research` with `mode: "marathon"` — high default depth and 4h wall clock unless overridden.

## Chromium

1. Install: `pip install -r finagent/requirements-finagent.txt` then `playwright install chromium`.
2. Optional env:
   - `FINAGENT_BROWSER_HEADLESS=1` (default) — set `0` for headed debugging.
   - `FINAGENT_BROWSER_MAX_PAGES=3` — concurrent Playwright contexts.
   - `FINAGENT_BROWSER_FALLBACK=1` — after a failed or blocked HTTP response, retry via Chromium once.
   - `FINAGENT_BROWSER_FALLBACK=1` (same) is also honored from the scraper path for thin/empty pages when `FINAGENT_BROWSER_FALLBACK` is set.
3. Programmatic extraction: `finagent.tools.browser.browser_extract` (allowlisted hosts only).

## Search extras

- `FINAGENT_SEARXNG_URL` — optional SearXNG base URL; results merge with DuckDuckGo and Bing.
- `FINAGENT_FETCH_CONCURRENCY` — cap parallel page fetches (default 6).

## Self-generated skills

Skills are written under `$FINAGENT_HOME/skills/auto/` when the objective asks to learn/save a skill, or when quality stays low with a stable reflection gap pattern. Loaded into the system prompt via keyword overlap (`prompt_builder.system_prompt_for_request`).
