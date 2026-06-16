"""Ten specialist research agents run in parallel waves.

Each agent produces a curated research memo for the synthesis layer. Agents are
provider-agnostic: callers inject an async LLM callable so unit tests can drive
the wave without real network IO.

Coverage of the ten dimensions feeds the Quality Score (0-100) used by the
publish gate. Missing dimensions degrade the score deterministically — a wave
where only Financials and Risk return content cannot publish.

Pure orchestration: no model resolution, no DB, no IO of its own.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger("finagent.content.specialist_agents")

LLMCallable = Callable[[str, str], Awaitable[str]]

# Ordered: keep stable for downstream consumers and Quality Score weights.
SPECIALIST_KINDS: tuple[str, ...] = (
    "financials",
    "risk",
    "news",
    "technical",
    "community",
    "competitor",
    "valuation",
    "accounting",
    "macro",
    "governance",
)

# Wave grouping — agents inside a wave run concurrently. Two waves keep peak
# concurrency at five even on small accounts while preserving parallelism.
_WAVES: tuple[tuple[str, ...], ...] = (
    ("financials", "risk", "news", "technical", "community"),
    ("competitor", "valuation", "accounting", "macro", "governance"),
)

_BRIEFS: dict[str, tuple[str, str]] = {
    "financials": (
        "Specialist: Financials",
        "Extract income statement (revenue, EBITDA, PAT, margins), balance sheet (debt, cash, "
        "equity, working capital), and cash flow (OCF, FCF, capex) from official filings, "
        "XBRL, and annual reports. Compute YoY and QoQ change for each. Flag any inferred "
        "figure explicitly. Cite the exact filing for every number.",
    ),
    "risk": (
        "Specialist: Risk",
        "Map operational, financial, and regulatory exposure: covenant headroom, customer or "
        "supplier concentration, FX exposure, contingent liabilities, pending litigation, "
        "ongoing SEBI/RBI proceedings. Quantify where possible; cite filings.",
    ),
    "news": (
        "Specialist: News",
        "Catalogue verified disclosures since the last reporting cycle. For each item, score "
        "source tier (official > tier-1 financial press > tier-2 > blog), tag material vs "
        "routine, and capture the disclosure date and primary URL. Skip Livemint entirely.",
    ),
    "technical": (
        "Specialist: Technical",
        "Price action read-through from exchange data: 50-DMA and 200-DMA position, RSI, MACD, "
        "20-day average volume vs current, volatility, delivery percentage. State observed "
        "behaviour only — no buy/sell calls, no target prices.",
    ),
    "community": (
        "Specialist: Community",
        "Sentiment signal from public retail forums (Reddit r/IndiaInvestments, StockTwits, "
        "Hacker News finance threads). Summarise net tone, top concerns, and any factual "
        "claims that contradict official disclosures. Never treat forum chatter as evidence.",
    ),
    "competitor": (
        "Specialist: Competitor",
        "Peer comparison on revenue scale, margin profile, growth rate, ROE, and market share. "
        "Identify the two or three closest listed peers and compute relative position on each "
        "metric. Anchor peer data in their own filings.",
    ),
    "valuation": (
        "Specialist: Valuation",
        "Compute trailing P/E, EV/EBITDA, P/B, dividend yield, the Graham fair-value range, the "
        "Piotroski quality screen, and a one-stage discounted cash flow grounded in disclosed "
        "cash flows. Report inputs and ranges only; no buy, sell, or target-price language.",
    ),
    "accounting": (
        "Specialist: Accounting",
        "Disclosure-quality read: earnings quality indicators, accruals trend, receivable days "
        "versus revenue growth, contingent liability movement, auditor continuity, related-party "
        "transaction concentration, going-concern notes. Cite the filing for every observation.",
    ),
    "macro": (
        "Specialist: Macro",
        "Macro backdrop: latest RBI policy rate stance, CPI/WPI prints, GDP growth, USD-INR, "
        "commodity moves relevant to the sector, fiscal and monetary signals. Connect each macro "
        "point to a specific transmission channel for this company or sector.",
    ),
    "governance": (
        "Specialist: Governance",
        "Board composition and independence ratio, promoter holding and pledge trend over the "
        "last eight quarters, related-party transactions, auditor tenure and changes, regulatory "
        "compliance history, ESG and disclosure quality. Cite filings for each finding.",
    ),
}


@dataclass
class SpecialistMemo:
    """Curated research memo from one specialist agent."""

    kind: str
    headline: str
    body: str
    bullets: list[str] = field(default_factory=list)
    metrics: list[dict[str, str]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    error: str = ""

    @property
    def has_content(self) -> bool:
        if self.error:
            return False
        body_words = len(re.findall(r"\b[\w%-]+\b", self.body or ""))
        return body_words >= 40 or len(self.bullets) >= 3 or bool(self.metrics)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "headline": self.headline,
            "body": self.body,
            "bullets": list(self.bullets),
            "metrics": list(self.metrics),
            "sources": list(self.sources),
            "error": self.error,
            "has_content": self.has_content,
        }


def _build_prompt(kind: str, target: str, context: str) -> tuple[str, str]:
    role, brief = _BRIEFS[kind]
    system = (
        f"{role}. You are a senior financial researcher producing a curated memo for the "
        "editorial synthesis layer. Ground every claim in official Indian financial sources "
        "(NSE, BSE, SEBI, RBI, MCA), company filings, audited annual reports, and trusted "
        "financial wire services. Exclude livemint.com from your source list. Return JSON only."
    )
    user = (
        f"TARGET: {target}\n\n"
        f"BRIEF: {brief}\n\n"
        f"PIPELINE CONTEXT (use as background, not as primary evidence):\n{context[:4000]}\n\n"
        "Return JSON with keys: headline (str <=120 chars), body (str 80-300 words of prose), "
        "bullets (list[str], 3-6, factual), metrics (list of {label, value, period, source}), "
        "sources (list of {title, url, source_type}). Do not include Livemint URLs."
    )
    return system, user


async def _run_agent(
    kind: str,
    target: str,
    context: str,
    llm: LLMCallable,
    timeout_s: float,
) -> SpecialistMemo:
    system, user = _build_prompt(kind, target, context)
    try:
        raw = await asyncio.wait_for(llm(system, user), timeout=timeout_s)
    except asyncio.TimeoutError:
        return SpecialistMemo(kind=kind, headline="", body="", error="timeout")
    except Exception as exc:
        logger.warning("Specialist %s failed: %s", kind, exc)
        return SpecialistMemo(kind=kind, headline="", body="", error=f"llm_error: {exc}")

    return _parse_memo(kind, raw)


def _parse_memo(kind: str, raw: str) -> SpecialistMemo:
    import json

    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text) if text else {}
    except json.JSONDecodeError:
        return SpecialistMemo(kind=kind, headline="", body=text[:1200], error="non_json_response")
    if not isinstance(data, dict):
        return SpecialistMemo(kind=kind, headline="", body="", error="non_object_response")

    sources_raw = data.get("sources") or []
    sources: list[dict[str, str]] = []
    for item in sources_raw if isinstance(sources_raw, list) else []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if "livemint.com" in url.lower():
            continue
        sources.append(
            {
                "title": str(item.get("title") or "")[:220],
                "url": url[:1200],
                "source_type": str(item.get("source_type") or "")[:60],
            }
        )

    metrics_raw = data.get("metrics") or []
    metrics: list[dict[str, str]] = []
    for item in metrics_raw if isinstance(metrics_raw, list) else []:
        if not isinstance(item, dict):
            continue
        metrics.append(
            {
                "label": str(item.get("label") or "")[:120],
                "value": str(item.get("value") or "")[:120],
                "period": str(item.get("period") or "")[:60],
                "source": str(item.get("source") or "")[:200],
            }
        )

    bullets_raw = data.get("bullets") or []
    bullets = [str(b)[:400] for b in bullets_raw if str(b).strip()][:8] if isinstance(bullets_raw, list) else []

    return SpecialistMemo(
        kind=kind,
        headline=str(data.get("headline") or "")[:200],
        body=str(data.get("body") or "")[:4000],
        bullets=bullets,
        metrics=metrics,
        sources=sources,
    )


async def run_specialist_wave(
    target: str,
    context: str,
    llm: LLMCallable,
    *,
    timeout_s: float = 35.0,
    kinds: tuple[str, ...] = SPECIALIST_KINDS,
) -> dict[str, SpecialistMemo]:
    """Run the ten specialists in two concurrent waves.

    `llm(system, user) -> str` is injected. On individual agent failure the memo
    is returned with an error tag so the publish gate can degrade the quality
    score deterministically without aborting the run.
    """
    results: dict[str, SpecialistMemo] = {}
    for wave in _WAVES:
        wave_kinds = [k for k in wave if k in kinds]
        if not wave_kinds:
            continue
        coros = [_run_agent(k, target, context, llm, timeout_s) for k in wave_kinds]
        memos = await asyncio.gather(*coros, return_exceptions=False)
        for memo in memos:
            results[memo.kind] = memo
    return results


def compute_quality_score(memos: dict[str, SpecialistMemo]) -> int:
    """Aggregate research coverage from the ten specialists on a 0-100 scale.

    Each specialist contributes equal weight (10 points) when its memo has
    real content. Partial content (some bullets or metrics but thin body) is
    counted at half weight. Errors or empty memos contribute zero.
    """
    if not memos:
        return 0
    total = 0.0
    for kind in SPECIALIST_KINDS:
        memo = memos.get(kind)
        if memo is None:
            continue
        if memo.error:
            continue
        if memo.has_content:
            total += 10.0
        elif memo.bullets or memo.metrics:
            total += 5.0
    return int(round(min(total, 100.0)))


def summarise_wave(memos: dict[str, SpecialistMemo]) -> dict[str, Any]:
    """Compact summary suitable for embedding in the synthesis prompt and gate metrics."""
    covered = [k for k, m in memos.items() if m.has_content]
    failed = [k for k, m in memos.items() if m.error]
    return {
        "kinds_covered": covered,
        "kinds_failed": failed,
        "quality_score": compute_quality_score(memos),
        "memo_count": sum(1 for m in memos.values() if m.has_content),
    }


def wave_to_prompt_block(memos: dict[str, SpecialistMemo], *, max_chars: int = 9000) -> str:
    """Render the ten specialist memos as a prompt block for the synthesis pass."""
    parts: list[str] = ["[SPECIALIST RESEARCH WAVE — curated memos]"]
    for kind in SPECIALIST_KINDS:
        memo = memos.get(kind)
        if memo is None or not memo.has_content:
            parts.append(f"\n## {kind.upper()}: not available")
            continue
        block = [f"\n## {kind.upper()}: {memo.headline}".rstrip(":")]
        if memo.body:
            block.append(memo.body)
        if memo.bullets:
            block.append("\n".join(f"- {b}" for b in memo.bullets))
        if memo.metrics:
            metric_lines = [
                f"  {m.get('label', '')}: {m.get('value', '')} ({m.get('period', '')}) — {m.get('source', '')}"
                for m in memo.metrics[:6]
            ]
            block.append("Key metrics:\n" + "\n".join(metric_lines))
        if memo.sources:
            block.append("Sources: " + "; ".join(s.get("url", "") for s in memo.sources[:4]))
        parts.append("\n".join(block))
    rendered = "\n".join(parts)
    if len(rendered) > max_chars:
        rendered = rendered[:max_chars] + "\n[truncated]"
    return rendered
