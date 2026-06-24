# Proxy rotation layer (local)

Gives NSE/BSE/SEBI fetchers a rotating egress IP to dodge datacenter-IP WAF bans.
Sources free proxies from [TheSpeedX/PROXY-List](https://github.com/TheSpeedX/PROXY-List),
rotates them with [mubeng](https://github.com/mubeng/mubeng).

> ⚠️ Free public proxies are unreliable, slow, mostly datacenter, low live ratio.
> Zero-cost starting layer. For real WAF bypass swap `SOURCES` in
> `backend/finagent/tools/web/proxy_pool.py` for a paid residential endpoint
> (point `PROSPEKT_PROXY_URL` at it and skip the free pool).

## Components
- `backend/finagent/tools/web/proxy_pool.py` — fetch lists, health-check, rotation.
- `scripts/proxy_rotator.py` — CLI: `refresh | check | run | all`.
- `.proxy/bin/mubeng.exe` — rotator binary (v0.23.0, gitignored).
- `.proxy/proxies_raw.txt`, `.proxy/live.txt` — proxy pools (gitignored).

## Run (local)
```bash
# 1. pull + health-check, then launch rotator on 127.0.0.1:8089
python scripts/proxy_rotator.py all --max 2500 --addr 127.0.0.1:8089 --rotate 5

# or step-by-step
python scripts/proxy_rotator.py refresh
python scripts/proxy_rotator.py check --max 2500 --timeout 7
python scripts/proxy_rotator.py run --addr 127.0.0.1:8089 --rotate 5 --method random
```

## Turn it on for the fetchers
```bash
export PROSPEKT_PROXY_ENABLED=1
export PROSPEKT_PROXY_URL=http://127.0.0.1:8089   # the local mubeng rotator
```
- `PROSPEKT_PROXY_ENABLED` unset/false → fetchers go direct (default, unchanged).
- `PROSPEKT_PROXY_URL` set → all fetchers hop through that single address (mubeng rotates upstream).
- enabled but no URL → fetchers pick a random live proxy from `live.txt` themselves (Python-side rotation, no mubeng).

## Wired into
- `exchange_fetcher.py` — NSE/BSE warm httpx clients (T1) + patchright stealth browser (T2).
- `http_fetcher.py` — shared httpx pool + crawl4ai browser.

## Refresh cadence
Free lists rot fast. Re-run `refresh` + `check` every few hours (cron/scheduler)
to keep `live.txt` fresh; mubeng `--watch` hot-reloads the file.
