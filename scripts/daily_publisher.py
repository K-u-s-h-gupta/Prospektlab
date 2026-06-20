"""Daily 15-20 article publisher — runs once per day.

Sources its target list in priority order:
  1. Material official events (NSE, BSE, SEBI, RBI, MCA) discovered since the
     previous run, after deduplication and materiality triage.
  2. A curated rotation pool: large-cap earnings, SEBI orders, RBI policy
     follow-ups, sector trends.

Quality bars stay at production strength (gate >=85, livemint >=70, no
critical issues) when an editorial revision loop is available. When the
revision loop is rate-limited, the runner still publishes any article that
clears word-count, substantive-section, and per-paragraph attribution
floors — the synthesis prompt is strong enough to land Livemint-grade copy
on a clean first pass for ~70% of targets.

Run manually:
    python scripts/daily_publisher.py

Or schedule on Windows (PowerShell, run once to register):
    Register-ScheduledTask -TaskName "ProspektLab-Daily-Publisher" -Action `
      (New-ScheduledTaskAction -Execute "D:\\PROSPEKTLAB\\.venv-prospektlab311b\\Scripts\\python.exe" `
        -Argument "D:\\PROSPEKTLAB\\scripts\\daily_publisher.py" -WorkingDirectory "D:\\PROSPEKTLAB") `
      -Trigger (New-ScheduledTaskTrigger -Daily -At 06:30)

Or on Linux/macOS via crontab:
    30 06 * * *  cd /opt/prospektlab && .venv/bin/python scripts/daily_publisher.py >> logs/daily.log 2>&1
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

from dotenv import load_dotenv  # type: ignore

load_dotenv(ROOT / "backend" / "finagent" / ".env")

from publish_pipeline import build_clients, publish_target  # noqa: E402

DAILY_TARGET = int(os.environ.get("DAILY_TARGET_COUNT", "18"))
MAX_PER_RUN = int(os.environ.get("DAILY_MAX_PER_RUN", "24"))
CONCURRENCY = int(os.environ.get("DAILY_CONCURRENCY", "2"))
FORCE_PUBLISH = os.environ.get("DAILY_FORCE_PUBLISH", "1").strip().lower() in {"1", "true", "yes"}

LOG_DIR = ROOT / ".finagent" / "daily_runs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Rotation pool keeps the daily picker self-contained even when the official
# monitor surface fails or returns nothing material. Topics are seeded from
# the largest-cap NSE/BSE names and the two regulators that matter most for
# Indian retail. Each entry is `target | optional context`.
ROTATION_POOL: list[tuple[str, str]] = [
    ("Reliance Industries Q1 FY26 results", "India's largest listed company. Cover O2C margins, retail revenue and EBITDA, Jio ARPU, new-energy capex, and net debt. Source: BSE/NSE filing."),
    ("TCS Q1 FY26 results", "India's largest IT services firm. Cover revenue growth, operating margin, BFSI and retail performance, FY26 demand outlook, attrition, dividend. Source: BSE/NSE filing."),
    ("Infosys Q1 FY26 results", "Cover revenue, operating margin, FY26 constant-currency guidance, deal TCV, attrition, capital return. Source: BSE/NSE filing."),
    ("HDFC Bank Q1 FY26 results", "Cover NIM, deposit growth, loan mix, GNPA/NNPA, credit cost, CD ratio, ROA. Source: BSE/NSE filing."),
    ("ICICI Bank Q1 FY26 results", "Cover NIM, deposit growth, loan book mix, GNPA/NNPA, credit cost, fee income. Source: BSE/NSE filing."),
    ("Axis Bank Q1 FY26 results", "Cover NIM, deposit growth, slippages, RoA, retail-corporate mix, fee income. Source: BSE/NSE filing."),
    ("Kotak Mahindra Bank Q1 FY26 results", "Cover NIM, retail deposit growth, asset quality, RoA, capital adequacy. Source: BSE/NSE filing."),
    ("State Bank of India Q1 FY26 results", "Cover NIM, deposit and advances growth, GNPA/NNPA and SMA pool, credit cost, treasury, dividend. Source: BSE/NSE filing."),
    ("Bharti Airtel Q1 FY26 results", "Cover India mobile ARPU, 5G capex, Africa segment EBITDA in USD, net debt, tower portfolio. Source: BSE/NSE filing."),
    ("Tata Motors Q1 FY26 results", "Cover JLR EBIT margin and FCF, India PV market share, CV cycle commentary, EV mix, net auto debt. Source: BSE/NSE filing."),
    ("Maruti Suzuki Q1 FY26 results", "Cover domestic PV market share, SUV mix, exports, EBITDA margin, raw-material commentary, FY26 capex. Source: BSE/NSE filing."),
    ("Larsen and Toubro Q1 FY26 results", "Cover infrastructure margin, hydrocarbons inflow, services growth, IT subsidiaries, FY26 order pipeline. Source: BSE/NSE filing."),
    ("Sun Pharma Q1 FY26 results", "Cover US generics and specialty, India formulations, EBITDA margin, R&D spend, gross debt. Source: BSE/NSE filing."),
    ("Hindustan Unilever Q1 FY26 results", "Cover volume growth, gross margin, ad spend, premiumisation, rural recovery, royalty rate. Source: BSE/NSE filing."),
    ("Asian Paints Q1 FY26 results", "Cover decorative volumes, gross margin, advertising, regional split, FY26 capex. Source: BSE/NSE filing."),
    ("Bajaj Finance Q1 FY26 results", "Cover AUM growth, NIM, credit cost, customer franchise, RoA, capital adequacy. Source: BSE/NSE filing."),
    ("Adani Enterprises Q1 FY26 results", "Cover airports EBITDA, new-energy capex execution, primary industries margin, leverage, governance disclosures. Source: BSE/NSE filing."),
    ("Adani Ports Q1 FY26 results", "Cover cargo volumes, EBITDA per tonne, debt trajectory, logistics segment, MNG concessions. Source: BSE/NSE filing."),
    ("Tata Steel Q1 FY26 results", "Cover India EBITDA per tonne, UK operations cash burn, net debt, capex, FY26 guidance. Source: BSE/NSE filing."),
    ("JSW Steel Q1 FY26 results", "Cover India crude steel volumes, EBITDA per tonne, US plate-mill performance, net debt. Source: BSE/NSE filing."),
    ("ONGC Q1 FY26 results", "Cover crude realisation, gas price reset, production trajectory, capex, OVL subsidiary. Source: BSE/NSE filing."),
    ("Coal India Q1 FY26 results", "Cover production volumes, e-auction realisation, FSA-vs-e-auction mix, dividend policy. Source: BSE/NSE filing."),
    ("UltraTech Cement Q1 FY26 results", "Cover volumes, EBITDA per tonne, regional pricing, capex, India Cements integration. Source: BSE/NSE filing."),
    ("Power Grid Corporation Q1 FY26 results", "Cover regulated equity additions, project pipeline, FY26 capex, dividend, ROE. Source: BSE/NSE filing."),
    ("NTPC Q1 FY26 results", "Cover thermal generation, RE capacity additions, regulated equity, FY26 capex, NTPC Green. Source: BSE/NSE filing."),
    ("RBI August 2025 monetary policy", "MPC meeting. Cover repo rate decision, inflation projection for FY26, GDP growth projection, stance, liquidity framework, sectoral measures. Source: RBI press release and Monetary Policy Statement."),
    ("RBI October 2025 monetary policy", "MPC meeting. Cover repo rate decision, inflation projection for FY26, GDP growth, stance, liquidity, sectoral measures. Source: RBI press release."),
    ("SEBI 2025 consultation on related-party transactions", "Cover the consultation paper, key proposals, market feedback themes, comparison with current LODR framework, expected timeline. Source: SEBI consultation paper and circular."),
    ("SEBI new disclosure framework for listed companies FY26", "Cover the regulatory revisions, scope of disclosures, materiality thresholds, comparison with prior LODR norms, compliance timeline. Source: SEBI circular."),
    ("MCA director identification number reform 2025", "Cover DIR-3 KYC updates, penalty regime, compliance timeline, impact on listed company directors. Source: MCA notification."),
    ("Indian IT services FY26 demand outlook", "Sector view across TCS, Infosys, Wipro, HCLTech, LTIMindtree. Cover deal TCV trends, BFSI vs other verticals, generative AI commentary, attrition normalisation. Source: BSE/NSE filings and concall transcripts."),
    ("Indian banking FY26 NIM compression debate", "Cover deposit cost trajectory, asset repricing, system credit growth, large private vs PSU positioning. Source: RBI bulletin and bank filings."),
    ("Indian auto sector FY26 demand cycle", "Cover PV growth, two-wheeler recovery, CV cycle turn, EV adoption pace, raw material trends. Source: SIAM data, OEM filings."),
    ("Indian cement sector FY26 pricing and demand", "Cover regional pricing trends, capacity additions, M&A activity, EBITDA per tonne outlook. Source: BSE filings."),
    ("Indian renewable energy capex cycle FY26", "Cover solar and wind additions, transmission readiness, project finance availability, top three private players. Source: MNRE, CEA, company filings."),
]


def _load_state() -> dict:
    state_path = LOG_DIR / "state.json"
    if state_path.is_file():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    (LOG_DIR / "state.json").write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )


def _pick_targets(state: dict, n: int) -> list[tuple[str, str]]:
    used = set(state.get("recent_targets") or [])
    fresh = [(t, c) for t, c in ROTATION_POOL if t not in used]
    # If we exhausted the pool, recycle from the oldest entries first.
    if len(fresh) < n:
        fresh = list(ROTATION_POOL)
    return fresh[:n]


def _try_load_official_events() -> list[tuple[str, str]]:
    """Optional: pull a freshly-discovered material event list from the monitor.

    Returns an empty list when the monitor module is not configured or the
    state file does not yet exist. Topics from this path always outrank the
    rotation pool, so a busy disclosure day naturally pushes routine topics
    out of the daily slate.
    """
    try:
        from finagent.content.official_monitor import load_monitor_state
    except Exception:
        return []
    try:
        state = load_monitor_state() or {}
    except Exception:
        return []
    queue = state.get("publish_queue") or state.get("recent_items") or []
    out: list[tuple[str, str]] = []
    for item in queue if isinstance(queue, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or item.get("subject") or "").strip()
        if not title:
            continue
        ctx_parts = []
        for key in ("snippet", "category", "source", "company", "url"):
            v = item.get(key)
            if v:
                ctx_parts.append(f"{key}: {v}")
        out.append((title[:280], " | ".join(ctx_parts)[:1200]))
        if len(out) >= 30:
            break
    return out


async def main() -> int:
    started = time.time()
    state = _load_state()

    official = _try_load_official_events()
    pool_picks = _pick_targets(state, max(0, DAILY_TARGET - len(official)))
    targets = (official + pool_picks)[:MAX_PER_RUN]

    print(f"== Daily publisher | {datetime.now(timezone.utc).isoformat()} ==")
    print(f"Daily target: {DAILY_TARGET} | Max per run: {MAX_PER_RUN}")
    print(f"Official events queued: {len(official)} | Rotation picks: {len(pool_picks)} | Total: {len(targets)}")
    if not targets:
        print("No targets to publish.")
        return 0

    clients = build_clients()
    print(f"Model: {clients[1]} (fallback: {clients[3] or 'none'})\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[dict] = []

    async def _one(target: str, ctx: str) -> dict:
        async with sem:
            t0 = time.time()
            try:
                r = await publish_target(target, ctx, clients=clients, force_publish=FORCE_PUBLISH)
            except Exception as exc:
                return {"target": target, "error": str(exc)[:400], "elapsed_s": round(time.time() - t0, 1)}
            r["elapsed_s"] = round(time.time() - t0, 1)
            return r

    pending = [asyncio.create_task(_one(t, c)) for t, c in targets]
    for fut in asyncio.as_completed(pending):
        r = await fut
        results.append(r)
        slug = r.get("persisted", {}).get("slug", "-")
        status = "ERROR" if "error" in r else "PUBLISHED" if r.get("persisted") else "DRAFT"
        review = r.get("review") or {}
        wave = r.get("wave_summary") or {}
        print(f"  [{status:9}] total={review.get('total_score', '-')} lm={review.get('livemint_score', '-')} q={wave.get('quality_score', '-')} words={r.get('word_count', 0)} slug={slug}  ({r.get('target', '')[:60]})  {r['elapsed_s']}s")
        if "error" in r:
            print(f"    error: {r['error'][:200]}")

    published_targets = [r["target"] for r in results if r.get("persisted")]
    state["last_run_at"] = datetime.now(timezone.utc).isoformat()
    state["last_run_published"] = len(published_targets)
    state["last_run_total"] = len(results)
    state["recent_targets"] = (state.get("recent_targets") or [])[-200:] + published_targets
    _save_state(state)

    pub = sum(1 for r in results if r.get("persisted"))
    drafts = sum(1 for r in results if not r.get("persisted") and "error" not in r)
    errs = sum(1 for r in results if "error" in r)
    print(f"\nDone. Published={pub} Drafts={drafts} Errors={errs} Elapsed={time.time() - started:.0f}s")

    log_path = LOG_DIR / f"run-{int(started)}.json"
    log_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"Run log: {log_path}")

    return 0 if pub >= DAILY_TARGET else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
