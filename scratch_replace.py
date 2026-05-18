import os

file_path = "finagent/run_agent.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update docstring
old_doc = '''"""Core agent loop.

Pipeline:
1. identify   — resolve target to SEC ticker / CIK if it's a US-listed entity
2. enrichment — pull authoritative JSON APIs in parallel (SEC EDGAR companyfacts,
                Yahoo Finance chart, Wikipedia REST summary)
3. breadth-survey — layered DuckDuckGo search across 4 angles
4. deep-dive — iterative targeted second-pass queries to fill gaps
5. analysis — cross-source conflict detection, viral scoring
6. synthesis — OpenAI / template memo using the *facts*, not just excerpts
"""'''

new_doc = '''"""Core agent loop — India-focused FinAgent.

Pipeline:
1. intent-route — classify query complexity, select agents & tools
2. enrichment    — pull India data in parallel (NSE/BSE via Moneycontrol/Screener,
                   Yahoo Finance .NS/.BO, Wikipedia, Reddit, News)
3. breadth-survey — layered DuckDuckGo search across India-specific angles
4. deep-dive      — iterative gap-driven queries (rounds capped by intent complexity)
5. reflection     — Hermes-style self-critique (skipped for simple queries)
6. multi-agent    — parallel specialists filtered by intent (verifier ALWAYS runs)
7. blindspot      — coverage gap queries (skipped for simple/moderate)
8. synthesis      — streaming memo generation
"""'''
content = content.replace(old_doc, new_doc)

# 2. Add tool selector import
old_import = '''from finagent.router import route_objective
from finagent.output.intent_classifier import classify_output_mode, normalize_depth'''
new_import = '''from finagent.router import route_objective
from finagent.router.tool_selector import select_tools
from finagent.output.intent_classifier import classify_output_mode, normalize_depth'''
content = content.replace(old_import, new_import)

# 3. Data module imports
old_data_imports = '''from finagent.tools.data import (
    FilingNarrative,
    FxRate,
    HNStory,
    NewsItem,
    RedditPost,
    SECCompanySnapshot,
    SECTimeSeries,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    fetch_company_snapshot,
    fetch_filing_narrative,
    fetch_news,
    fetch_stocktwits,
    fetch_wikipedia_summary,
    fetch_yahoo_quote,
    get_usd_inr,
    search_hackernews,
    search_reddit,
)'''
new_data_imports = '''from finagent.tools.data import (
    FxRate,
    HNStory,
    IndiaCompanySnapshot,
    NewsItem,
    RedditPost,
    SEBIFiling,
    StockTwitsSnapshot,
    WikipediaSummary,
    YahooQuote,
    fetch_india_snapshot,
    fetch_news,
    fetch_sebi_filing,
    fetch_shareholding_pattern,
    fetch_stocktwits,
    fetch_wikipedia_summary,
    fetch_yahoo_quote,
    get_usd_inr,
    search_hackernews,
    search_reddit,
)'''
content = content.replace(old_data_imports, new_data_imports)

# 4. _run_enrichment function replacement
old_enrichment_start = 'async def _run_enrichment('
old_enrichment_end = '    return bundle\n\n'
start_idx = content.find(old_enrichment_start)
end_idx = content.find(old_enrichment_end, start_idx)
if start_idx != -1 and end_idx != -1:
    old_enrichment_block = content[start_idx:end_idx + len(old_enrichment_end)]
    
    new_enrichment_block = '''async def _run_enrichment(
    target: str,
    session_id: str,
    *,
    entity,
    news_timeout: float = 25.0,
    selected_tools: frozenset[str] | None = None,
) -> EnrichmentBundle:
    """Parallel India enrichment — Moneycontrol/Screener primary, NSE fallback."""
    tools = selected_tools or frozenset([
        "india_snap", "yahoo", "shareholding", "sebi_filing",
        "news", "reddit", "hackernews", "stocktwits", "wikipedia", "fx",
    ])
    BUS.emit(session_id, "phase", phase="enrichment",
             note=f"Parallel India data fetch ({', '.join(sorted(tools))})")

    ticker = entity.yahoo_ticker or (target.upper() if target.isalpha() and len(target) <= 10 else None)
    nse_sym = (ticker or "").replace(".NS", "").replace(".BO", "").upper() or target.upper()
    canonical_name = entity.canonical_name or target

    async def _india_snap() -> IndiaCompanySnapshot | None:
        if "india_snap" not in tools: return None
        BUS.emit(session_id, "agent_task", task="NSE/BSE", status="running", note=f"Screener → Moneycontrol → NSE → BSE for {nse_sym}")
        try:
            snap = await fetch_india_snapshot(nse_sym)
            if snap:
                BUS.emit(session_id, "agent_task", task="NSE/BSE", status="done", note=f"{snap.symbol} — {snap.company_name}")
            else:
                BUS.emit(session_id, "agent_task", task="NSE/BSE", status="warning", note="No match found")
            return snap
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="NSE/BSE", status="error", note=str(exc))
            return None

    async def _yahoo_fetch() -> YahooQuote | None:
        if "yahoo" not in tools or not ticker: return None
        BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="running", note=f"Fetching {ticker}")
        try:
            q = await fetch_yahoo_quote(ticker)
            if q is None or (q.price is None and not q.financial_metrics):
                BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="warning", note="No quote")
                return None
            BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="done", note=f"{q.currency or 'INR'} {q.price:,.2f}")
            return q
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="Yahoo Finance", status="error", note=str(exc))
            return None

    async def _wiki() -> WikipediaSummary | None:
        if "wikipedia" not in tools: return None
        BUS.emit(session_id, "agent_task", task="Wikipedia", status="running", note=f"Fetching profile for {canonical_name}")
        try:
            w = await fetch_wikipedia_summary(canonical_name)
            if w: BUS.emit(session_id, "agent_task", task="Wikipedia", status="done", note=f"{w.title}")
            return w
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="Wikipedia", status="warning", note=str(exc))
            return None

    async def _sebi_filing_fetch() -> SEBIFiling | None:
        if "sebi_filing" not in tools: return None
        BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="running", note=f"Pre-parsed analysis for {nse_sym}")
        try:
            fil = await fetch_sebi_filing(nse_sym)
            if fil and fil.has_any():
                BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="done", note="Analysis sections extracted")
                return fil
            BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="warning", note="No pre-parsed sections")
            return None
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="SEBI/Trendlyne", status="warning", note=str(exc))
            return None

    async def _shareholding_fetch() -> dict | None:
        if "shareholding" not in tools: return None
        BUS.emit(session_id, "agent_task", task="Shareholding", status="running", note=f"Pattern for {nse_sym}")
        try:
            sh = await fetch_shareholding_pattern(nse_sym)
            if sh:
                pct = {k: f"{v:.1f}%" if v is not None else "n/a" for k, v in sh.items() if k != "as_of"}
                BUS.emit(session_id, "agent_task", task="Shareholding", status="done", note=f"Promoter {pct.get('promoter','n/a')}")
            else:
                BUS.emit(session_id, "agent_task", task="Shareholding", status="warning", note="Not available")
            return sh
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="Shareholding", status="warning", note=str(exc))
            return None

    async def _fx() -> FxRate | None:
        BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="running", note="Fetching live rate")
        try:
            r = await get_usd_inr()
            BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="done", note=f"1 USD = ₹{r.rate:.4f}")
            return r
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="FX (USD/INR)", status="warning", note=str(exc))
            return None

    async def _reddit_fetch() -> list[RedditPost]:
        if "reddit" not in tools: return []
        query = canonical_name
        BUS.emit(session_id, "agent_task", task="Reddit", status="running", note=f"Reddit for {query!r}")
        try:
            posts = await asyncio.wait_for(search_reddit(query), timeout=20.0)
            if posts:
                BUS.emit(session_id, "agent_task", task="Reddit", status="done", note=f"{len(posts)} posts")
            return posts or []
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="Reddit", status="warning", note=str(exc))
            return []

    async def _hn() -> list:
        if "hackernews" not in tools: return []
        query = canonical_name
        try:
            stories = await asyncio.wait_for(search_hackernews(query), timeout=15.0)
            if stories:
                BUS.emit(session_id, "agent_task", task="Hacker News", status="done", note=f"{len(stories)} stories")
            return stories or []
        except Exception:
            return []

    async def _stocktwits_fetch() -> StockTwitsSnapshot | None:
        if "stocktwits" not in tools or not ticker: return None
        try:
            snap = await asyncio.wait_for(fetch_stocktwits(ticker), timeout=15.0)
            if snap:
                BUS.emit(session_id, "agent_task", task="StockTwits", status="done", note=f"net {snap.net_sentiment}")
            return snap
        except Exception:
            return None

    async def _news_fetch() -> list[NewsItem]:
        if "news" not in tools: return []
        query = canonical_name
        BUS.emit(session_id, "agent_task", task="News headlines", status="running", note=f"RSS for {query!r}")
        try:
            items = await asyncio.wait_for(fetch_news(query, hl=entity.profile.news_hl, gl=entity.profile.news_gl, ceid=entity.profile.news_ceid), timeout=news_timeout)
            if items:
                BUS.emit(session_id, "agent_task", task="News headlines", status="done", note=f"{len(items)} headlines")
            return items or []
        except Exception as exc:
            BUS.emit(session_id, "agent_task", task="News headlines", status="warning", note=str(exc))
            return []

    (
        india_snap, yahoo_quote, wiki, sebi_fil, shareholding_data,
        fx_rate, reddit_posts, hn_stories, stocktwits_snap, news_items,
    ) = await asyncio.gather(
        _india_snap(), _yahoo_fetch(), _wiki(), _sebi_filing_fetch(), _shareholding_fetch(),
        _fx(), _reddit_fetch(), _hn(), _stocktwits_fetch(), _news_fetch(),
        return_exceptions=False,
    )

    bundle = EnrichmentBundle(
        india_snap=india_snap, sebi_filing=sebi_fil, shareholding=shareholding_data,
        yahoo=yahoo_quote, wikipedia=wiki, fx=fx_rate,
        reddit=reddit_posts or [], hackernews=hn_stories or [], stocktwits=stocktwits_snap, news=news_items or [],
    )

    BUS.emit(
        session_id,
        "intel",
        india=_serialize_india(india_snap),
        yahoo=_serialize_yahoo(yahoo_quote),
        wikipedia=_serialize_wiki(wiki),
        sebi_filing=_serialize_sebi_filing(sebi_fil),
        shareholding=shareholding_data,
        fx=_serialize_fx(fx_rate),
        reddit=_serialize_reddit(reddit_posts or []),
        hackernews=_serialize_hn(hn_stories or []),
        stocktwits=_serialize_stocktwits(stocktwits_snap),
        news=_serialize_news(news_items or []),
    )
    return bundle\n\n'''
    content = content.replace(old_enrichment_block, new_enrichment_block)

# 5. Serialization functions
old_serialize_block = '''def _serialize_filing(f: FilingNarrative | None) -> dict | None:
    if not f:
        return None
    return {
        "form": f.form,
        "filed_date": f.filed_date,
        "source_url": f.source_url,
        "business": f.business,
        "risk_factors": f.risk_factors,
        "mdna": f.mdna,
    }


def _serialize_sec(snap: SECCompanySnapshot | None) -> dict | None:
    if not snap:
        return None
    return {
        "ticker": snap.ticker,
        "name": snap.name,
        "cik": snap.cik,
        "sic_description": snap.sic_description,
        "exchanges": snap.exchanges,
        "metrics": {
            k: {
                "label": m.label,
                "display": m.display_value(),
                "value": m.value,
                "unit": m.unit,
                "end": m.end,
                "fy": m.fy,
                "fp": m.fp,
                "form": m.form,
                "accn": m.accn,
            }
            for k, m in snap.metrics.items()
        },
        "history": {
            k: {
                "concept": s.concept,
                "label": s.label,
                "unit": s.unit,
                "annual": [
                    {"end": p.end, "value": p.value, "fy": p.fy, "fp": p.fp, "form": p.form}
                    for p in s.annual
                ],
                "quarterly": [
                    {"end": p.end, "value": p.value, "fy": p.fy, "fp": p.fp, "form": p.form}
                    for p in s.quarterly
                ],
            }
            for k, s in (snap.history or {}).items()
        },
        "recent_filings": [
            {"form": f.form, "filed": f.filing_date, "report": f.report_date, "url": f.url, "accession": f.accession}
            for f in snap.recent_filings
        ],
    }'''

new_serialize_block = '''def _serialize_india(snap: IndiaCompanySnapshot | None) -> dict | None:
    if not snap: return None
    return {
        "symbol": snap.symbol, "company_name": snap.company_name, "exchange": snap.exchange,
        "sector": snap.sector, "industry": snap.industry,
        "current_price": snap.current_price, "market_cap_cr": snap.market_cap_cr,
        "pe_ratio": snap.pe_ratio, "pb_ratio": snap.pb_ratio, "eps": snap.eps,
        "roe": snap.roe, "roce": snap.roce, "dividend_yield": snap.dividend_yield,
        "debt_to_equity": snap.debt_to_equity,
        "source": snap.source, "source_url": snap.source_url, "metrics": snap.metrics,
    }

def _serialize_sebi_filing(f: SEBIFiling | None) -> dict | None:
    if not f: return None
    return {
        "filing_type": f.filing_type, "company": f.company, "period": f.period,
        "filed_date": f.filed_date, "source_url": f.source_url,
        "business_overview": f.business_overview, "risk_factors": f.risk_factors,
    }'''
content = content.replace(old_serialize_block, new_serialize_block)

# 6. Routing flags wiring
old_routing_config = '''    if routing.deep_research:
        cfg.max_steps = max(cfg.max_steps, 80)
        cfg.reflection_max_rounds = max(cfg.reflection_max_rounds, 6)
        cfg.blindspot_max_queries = max(cfg.blindspot_max_queries, 10)

    BUS.emit(session_id, "session_started"'''

new_routing_config = '''    if routing.deep_research:
        cfg.max_steps = max(cfg.max_steps, 80)
        cfg.reflection_max_rounds = max(cfg.reflection_max_rounds, 6)
        cfg.blindspot_max_queries = max(cfg.blindspot_max_queries, 10)

    if routing.skip_reflection:
        cfg.enable_reflection = False
    if routing.skip_blindspot:
        cfg.enable_blindspot = False
    if routing.skip_deep_dive:
        cfg.enable_deep_dive = False
    _selected_tools = select_tools(objective, routing)

    BUS.emit(session_id, "session_started"'''
content = content.replace(old_routing_config, new_routing_config)

old_routing_emit = '''    BUS.emit(
        session_id,
        "routing",
        selected_agents=routing.selected_agents,
        country_code=entity.country_code,
        preferred_domains=preferred_domains[:8],
        deep_research=routing.deep_research,
    )'''
new_routing_emit = '''    BUS.emit(
        session_id,
        "routing",
        selected_agents=routing.selected_agents,
        country_code=entity.country_code,
        preferred_domains=preferred_domains[:8],
        deep_research=routing.deep_research,
        query_complexity=routing.query_complexity,
        skip_reflection=routing.skip_reflection,
        skip_blindspot=routing.skip_blindspot,
        skip_deep_dive=routing.skip_deep_dive,
        max_deep_dive_rounds=routing.max_deep_dive_rounds,
        selected_tools=sorted(list(_selected_tools)),
    )'''
content = content.replace(old_routing_emit, new_routing_emit)

# 7. Enrichment call and canonical label
old_enrichment_call = '''    bundle = EnrichmentBundle()
    if cfg.enable_enrichment:
        bundle = await _run_enrichment(target, session_id, entity=entity, news_timeout=cfg.news_timeout)

    # ── Phase 3: breadth survey ───────────────────────────────────────────
    canonical_label = bundle.sec.name if bundle.sec else (bundle.yahoo.name if bundle.yahoo and bundle.yahoo.name else entity.canonical_name or target)
    if cfg.enable_scraping:'''

new_enrichment_call = '''    bundle = EnrichmentBundle()
    if cfg.enable_enrichment:
        bundle = await _run_enrichment(
            target, session_id,
            entity=entity,
            news_timeout=cfg.news_timeout,
            selected_tools=_selected_tools,
        )

    # ── Phase 3: breadth survey ───────────────────────────────────────────
    canonical_label = (
        bundle.india_snap.company_name if bundle.india_snap and bundle.india_snap.company_name
        else (bundle.yahoo.name if bundle.yahoo and bundle.yahoo.name else entity.canonical_name or target)
    )
    if cfg.enable_scraping:'''
content = content.replace(old_enrichment_call, new_enrichment_call)

# 8. Enrichment corroborates var
old_enrichment_corr = '''    enrichment_present = bundle.sec is not None'''
new_enrichment_corr = '''    enrichment_present = bundle.india_snap is not None'''
content = content.replace(old_enrichment_corr, new_enrichment_corr)

# 9. Deep dive loops capping
old_deep_dive_loop = '''            if rounds >= 3:
                break'''
new_deep_dive_loop = '''            if rounds >= routing.max_deep_dive_rounds:
                break'''
content = content.replace(old_deep_dive_loop, new_deep_dive_loop)

# 10. Memory persistence fixing (remove SEC identity facts, use India)
old_persist = '''def _persist_session_memory(
    memory_store,
    *,
    session_id: str,
    target: str,
    canonical_label: str,
    bundle: EnrichmentBundle,
    docs: list[ScrapedDoc],
    cp: Checkpoint,
    conflicts: list,
    quality_score: float,
) -> None:
    """Extract durable facts from this run and store them under the
    canonical target key so the next run starts smarter.

    We deliberately store *structured* facts (e.g. "FY2026 revenue =
    $215.94B per 10-K filed 2026-02-25") rather than full prose so
    recall is cheap and unambiguous.
    """
    new_facts: list[MemoryFact] = []
    sec = bundle.sec
    if sec:
        # Identity fact
        identity_bits = [f"ticker={sec.ticker}", f"cik={sec.cik}", f"name={sec.name}"]
        if sec.sic_description:
            identity_bits.append(f"sic={sec.sic_description}")
        if sec.exchanges:
            identity_bits.append(f"exchanges={'/'.join(sec.exchanges)}")
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="identity",
                body="; ".join(identity_bits),
                confidence="HIGH",
                source_url=f"https://data.sec.gov/submissions/CIK{sec.cik}.json",
                session_id=session_id,
            )
        )
        # Financial facts from the latest metrics
        for k, m in (sec.metrics or {}).items():
            line = f"{m.label} = {m.display_value()} (form {m.form}, period ending {m.end})"
            new_facts.append(
                MemoryFact(
                    target_key=target,
                    kind="financial",
                    body=line,
                    confidence="HIGH",
                    source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={sec.cik}",
                    session_id=session_id,
                )
            )
    if bundle.filing and getattr(bundle.filing, "risk_factors", None):
        rf = bundle.filing.risk_factors.strip()
        # First ~600 chars of risk factors as a memorable digest
        new_facts.append(
            MemoryFact(
                target_key=target,
                kind="risk",
                body=f"Item 1A digest from {bundle.filing.form} filed {bundle.filing.filed_date}: {rf[:600]}",
                confidence="HIGH",
                source_url=bundle.filing.source_url,
                session_id=session_id,
            )
        )'''

new_persist = '''def _persist_session_memory(
    memory_store,
    *,
    session_id: str,
    target: str,
    canonical_label: str,
    bundle: EnrichmentBundle,
    docs: list[ScrapedDoc],
    cp: Checkpoint,
    conflicts: list,
    quality_score: float,
) -> None:
    """Extract durable facts from this run and store them under the
    canonical target key so the next run starts smarter.
    """
    new_facts: list[MemoryFact] = []
    snap = bundle.india_snap
    if snap:
        identity_bits = [f"symbol={snap.symbol}", f"name={snap.company_name}"]
        if snap.sector:
            identity_bits.append(f"sector={snap.sector}")
        new_facts.append(
            MemoryFact(
                target_key=target, kind="identity", body="; ".join(identity_bits),
                confidence="HIGH", source_url=snap.source_url, session_id=session_id,
            )
        )
        for k, v in (snap.metrics or {}).items():
            new_facts.append(
                MemoryFact(
                    target_key=target, kind="financial", body=f"{k} = {v}",
                    confidence="HIGH", source_url=snap.source_url, session_id=session_id,
                )
            )
    if bundle.sebi_filing and getattr(bundle.sebi_filing, "risk_factors", None):
        rf = bundle.sebi_filing.risk_factors.strip()
        new_facts.append(
            MemoryFact(
                target_key=target, kind="risk", body=f"Risk factor digest: {rf[:600]}",
                confidence="HIGH", source_url=bundle.sebi_filing.source_url, session_id=session_id,
            )
        )'''
content = content.replace(old_persist, new_persist)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Replace complete.")
