"""Self-improvement / reflection loop.

After the breadth-survey + initial deep-dive, run the quality scorer.
If the score is below the threshold:
  1. Take the top gaps + suggested_queries from the report.
  2. Mint *additional* targeted queries from the gaps (mixing in
     domain-specific operators like `site:nseindia.com` and
     `site:bseindia.com` for primary tier.
  3. Re-run the deep-dive with that query set, feeding new docs back
     into the citation log.
  4. Score again; loop until passes OR `max_rounds` reached OR no
     new docs surfaced.

This is the "self-improvement" part — the agent is grading its own work
and continuing until it has the receipts. Designed to support **long
runs** because every round is incremental and checkpointed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from finagent.analysis.quality import QualityReport, score_research

logger = logging.getLogger("finagent.reflection")


@dataclass
class ReflectionResult:
    rounds_run: int
    final_score: float
    initial_score: float
    new_docs_total: int
    histories: list[QualityReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "rounds_run": self.rounds_run,
            "final_score": round(self.final_score, 1),
            "initial_score": round(self.initial_score, 1),
            "delta": round(self.final_score - self.initial_score, 1),
            "new_docs_total": self.new_docs_total,
            "history": [h.to_dict() for h in self.histories],
        }


# Domain-specific operator decoration. We don't want to drown DuckDuckGo
# with site: operators it sometimes ignores, so we sprinkle them only on
# the queries that are likely to benefit.
_PRIMARY_BOOST = " site:nseindia.com OR site:bseindia.com OR site:sebi.gov.in OR site:moneycontrol.com OR site:screener.in OR site:trendlyne.com"
_TIER2_BOOST = " (Reuters OR \"Economic Times\" OR Livemint OR \"Business Standard\" OR NDTV Profit)"
_TIER3_BOOST = " (moneycontrol.com OR tickertape.in OR valueresearchonline.com OR trendlyne.com)"


def _decorate(query: str, kind: str) -> str:
    q = (query or "").strip()
    if not q:
        return q
    if kind == "primary":
        return q + _PRIMARY_BOOST
    if kind == "tier2":
        return q + _TIER2_BOOST
    if kind == "tier3":
        return q + _TIER3_BOOST
    return q


def _build_round_queries(
    target: str,
    report: QualityReport,
    round_idx: int,
    *,
    country_code: str = "GLOBAL",
) -> list[tuple[str, str]]:
    """Convert the gap report into a set of (query, kind) pairs.

    The kind is one of "primary" / "tier2" / "tier3" / "general" and
    drives operator decoration above.
    """
    out: list[tuple[str, str]] = []
    # Always pull whatever the scorer already suggested
    for q in report.suggested_queries:
        q_lower = q.lower()
        kind = "primary" if any(token in q_lower for token in ("sebi", "lodr", "nse", "bse", "annual report")) else "tier2"
        out.append((q, kind))

    # Per-dimension fill-ins
    dims = report.dimensions
    if not dims.get("filing_narrative", {}).get("ok"):
        out.append((f"{target} annual report risk factors management discussion SEBI LODR", "primary"))
        out.append((f"{target} NSE BSE corporate announcements annual report", "primary"))
    if not dims.get("financials", {}).get("ok"):
        out.append((f"{target} quarterly earnings report Q3 Q4 revenue", "tier2"))
        out.append((f"{target} gross margin operating margin segment breakdown", "tier2"))
    if not dims.get("history", {}).get("ok"):
        out.append((f"{target} 5 year revenue history growth", "tier2"))
    if not dims.get("press_coverage", {}).get("ok"):
        out.append((f"{target} latest news this week", "tier2"))
        out.append((f"{target} downgrade upgrade analyst rating target price", "tier2"))
    if not dims.get("community", {}).get("ok"):
        out.append((f"{target} discussion forum analysis", "tier3"))
    if not dims.get("competitive", {}).get("ok"):
        out.append((f"{target} top competitors comparison market share", "tier2"))
        out.append((f"alternatives to {target} peers", "tier2"))
    if not dims.get("citation_tiering", {}).get("ok"):
        out.append((f"{target} annual report PDF NSE BSE SEBI filing", "primary"))

    # Round-specific deepening — every round adds a different angle so we
    # cover different parts of the surface area on subsequent passes.
    angle_packs = [
        [
            (f"{target} earnings call transcript Q&A", "tier2"),
            (f"{target} guidance forward outlook fiscal year", "tier2"),
        ],
        [
            (f"{target} short interest float institutional ownership", "tier2"),
            (f"{target} options unusual activity put call", "tier2"),
        ],
        [
            (f"{target} promoter shareholding insider trading exchange filing Regulation 31", "primary"),
            (f"{target} CEO CFO interview podcast", "tier2"),
        ],
        [
            (f"{target} supply chain dependency customers concentration", "tier2"),
            (f"{target} R&D capex capital allocation buyback dividend", "tier2"),
        ],
        [
            (f"{target} ESG controversy lawsuit settlement investigation", "tier2"),
            (f"{target} SEBI regulatory action exchange surveillance penalty", "tier2"),
        ],
    ]
    pack = angle_packs[round_idx % len(angle_packs)]
    out.extend(pack)

    # De-duplicate
    seen = set()
    deduped: list[tuple[str, str]] = []
    for q, k in out:
        if q in seen:
            continue
        seen.add(q)
        deduped.append((q, k))
    return deduped[:8]  # at most 8 queries per round


class ReflectionLoop:
    def __init__(
        self,
        *,
        target: str,
        session_id: str,
        max_rounds: int = 4,
        score_threshold: float = 75.0,
        per_query_limit: int = 6,
        per_query_timeout: float = 25.0,
        max_total_new_docs: int = 80,
    ) -> None:
        self.target = target
        self.session_id = session_id
        self.max_rounds = max_rounds
        self.score_threshold = score_threshold
        self.per_query_limit = per_query_limit
        self.per_query_timeout = per_query_timeout
        self.max_total_new_docs = max_total_new_docs

    async def run(
        self,
        *,
        bundle,
        docs: list,
        checkpoint,
        entity=None,
        conflicts_callable: Callable[[list], list],
        search_callable: Callable[[str, int], Awaitable[list]],
        process_doc_callable: Callable[[Any, int], Awaitable[None]],
        emit_callable: Callable[..., None] | None = None,
        budget_exceeded: Callable[[], bool] | None = None,
    ) -> ReflectionResult:
        """Run the reflection loop in place.

        - `bundle`: EnrichmentBundle (frozen for the duration of reflection)
        - `docs`: mutable list of ScrapedDoc — new docs are appended
        - `checkpoint`: state.Checkpoint — citation_log grows as we process
        - `conflicts_callable(docs) -> list[ConflictReport]`
        - `search_callable(query, max_results) -> list[ScrapedDoc]`
        - `process_doc_callable(doc, step) -> None` — same _process_doc the
          main loop uses, so all source / confidence events still fire
        - `emit_callable(event_type, **payload)` — defaults to no-op
        - `budget_exceeded()` — optional; return True to stop reflection early (wall-clock budget).
        """

        def _emit(event: str, **payload) -> None:
            if emit_callable is None:
                return
            try:
                emit_callable(event, **payload)
            except Exception:
                pass

        initial_conflicts = conflicts_callable(docs)
        initial_report = score_research(
            target=self.target,
            bundle=bundle,
            docs=docs,
            checkpoint=checkpoint,
            entity=entity,
            conflicts=initial_conflicts,
        )
        _emit("quality_score", phase="initial", **initial_report.to_dict())

        histories = [initial_report]
        if initial_report.passes:
            logger.info("reflection skipped — initial score %.1f >= %.1f", initial_report.score, self.score_threshold)
            return ReflectionResult(
                rounds_run=0,
                initial_score=initial_report.score,
                final_score=initial_report.score,
                new_docs_total=0,
                histories=histories,
            )

        seen_urls = {(d.final_url or d.url or "").split("#", 1)[0] for d in docs}
        new_docs_total = 0
        current_report = initial_report
        rounds_done = 0

        for round_idx in range(self.max_rounds):
            if budget_exceeded is not None and budget_exceeded():
                break
            rounds_done = round_idx + 1
            queries = _build_round_queries(
                self.target,
                current_report,
                round_idx,
                country_code=getattr(entity, "country_code", "GLOBAL"),
            )
            decorated = [(_decorate(q, k), q, k) for q, k in queries]
            _emit(
                "reflection",
                round=rounds_done,
                gaps=current_report.gaps[:6],
                planned_queries=[q for _, q, _ in decorated],
            )

            async def _one(decorated_q: str, original_q: str) -> list:
                _emit("query", query=original_q, status="running", count=0)
                try:
                    results = await asyncio.wait_for(
                        search_callable(decorated_q, self.per_query_limit),
                        timeout=self.per_query_timeout,
                    )
                    _emit("query", query=original_q, status="done", count=len(results))
                    return results
                except asyncio.TimeoutError:
                    _emit("query", query=original_q, status="timeout", count=0)
                    return []
                except Exception as exc:
                    logger.warning("reflection query %r failed: %s", original_q, exc)
                    _emit("query", query=original_q, status="error", count=0)
                    return []

            batches = await asyncio.gather(
                *(_one(dq, oq) for dq, oq, _ in decorated)
            )
            round_new = 0
            for batch in batches:
                if budget_exceeded is not None and budget_exceeded():
                    break
                for doc in batch:
                    if budget_exceeded is not None and budget_exceeded():
                        break
                    key = (doc.final_url or doc.url or "").split("#", 1)[0]
                    if not key or key in seen_urls:
                        continue
                    seen_urls.add(key)
                    docs.append(doc)
                    round_new += 1
                    new_docs_total += 1
                    # step number is just for telemetry; the outer loop
                    # owns the real step counter
                    await process_doc_callable(doc, len(docs))
                    if new_docs_total >= self.max_total_new_docs:
                        break
                if new_docs_total >= self.max_total_new_docs:
                    break

            new_conflicts = conflicts_callable(docs)
            new_report = score_research(
                target=self.target,
                bundle=bundle,
                docs=docs,
                checkpoint=checkpoint,
                entity=entity,
                conflicts=new_conflicts,
            )
            histories.append(new_report)
            _emit(
                "quality_score",
                phase=f"reflection_round_{rounds_done}",
                round=rounds_done,
                new_docs_this_round=round_new,
                **new_report.to_dict(),
            )
            current_report = new_report

            if new_report.passes:
                logger.info("reflection passed at round %d with score %.1f", rounds_done, new_report.score)
                break
            if round_new == 0:
                logger.info("reflection round %d returned no new docs, stopping", rounds_done)
                break
            if new_docs_total >= self.max_total_new_docs:
                logger.info("reflection hit max_total_new_docs=%d, stopping", self.max_total_new_docs)
                break

        return ReflectionResult(
            rounds_run=rounds_done,
            initial_score=initial_report.score,
            final_score=current_report.score,
            new_docs_total=new_docs_total,
            histories=histories,
        )
