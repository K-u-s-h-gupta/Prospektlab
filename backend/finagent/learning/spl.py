"""System Prompt Learning (SPL) — extract reusable research strategies.

After the grader produces a quality score, SPL extracts ONE reusable strategy
from the session and stores it in the spl_strategies table.

Strategy format: IF [condition] THEN [specific action]
Example: "IF promoter pledge > 40% THEN cross-check with SEBI enforcement orders
          for pledged share sale patterns before quoting pledge data"

Strategies are:
  - Sector-tagged (e.g., "banking", "pharma")
  - Research-type-tagged (e.g., "governance", "valuation")
  - Scored by confidence (how often they produce quality improvement)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("finagent.learning.spl")


@dataclass
class ExtractedStrategy:
    """A reusable research strategy extracted from a grader session."""
    strategy_text: str
    sector: str | None = None
    company_type: str | None = None   # 'large_cap', 'mid_cap', 'psu', 'startup'
    research_type: str | None = None  # 'governance', 'valuation', 'risk', 'news'
    confidence_score: float = 0.5
    source_session_id: str | None = None


async def extract_strategy_from_session(
    synthesis_output: str,
    grader_flags: list[dict[str, Any]],
    *,
    entity_name: str = "",
    sector: str | None = None,
    research_type: str | None = None,
    session_id: str | None = None,
    quality_score: int = 0,
) -> ExtractedStrategy | None:
    """Extract a single reusable research strategy from a session.

    Only runs when quality_score >= 70 (good sessions produce learnable patterns)
    or when critical flags are present (failures teach the most).

    Args:
        synthesis_output: The final synthesis text.
        grader_flags: Flags from the grader (code, severity, message).
        entity_name: Company researched.
        sector: SEBI sector.
        research_type: Primary research focus.
        session_id: Session identifier.
        quality_score: Grader total score.

    Returns:
        ExtractedStrategy or None if no strategy worth extracting.
    """
    # Only extract from notably good or notably bad sessions
    has_critical_flags = any(f.get("severity") == "critical" for f in grader_flags)
    if quality_score < 70 and not has_critical_flags:
        return None

    # Build a short prompt to extract one strategy
    flag_summary = "\n".join(
        f"- [{f.get('severity', 'info').upper()}] {f.get('code')}: {f.get('message', '')}"
        for f in grader_flags[:5]
    )
    prompt_parts = [
        f"Research quality score: {quality_score}/100",
        f"Entity: {entity_name or 'unknown'}",
        f"Sector: {sector or 'unknown'}",
        f"Research type: {research_type or 'unknown'}",
        "",
        "Grader flags:",
        flag_summary or "(none)",
        "",
        "Based on this quality assessment, write ONE concise reusable research strategy "
        "in the format: IF [specific condition] THEN [specific action]",
        "The strategy should help future research sessions of this type.",
        "Keep it under 150 characters. Output ONLY the strategy text.",
    ]

    strategy_text = await _call_llm_for_strategy("\n".join(prompt_parts))
    if not strategy_text or len(strategy_text) < 20:
        return None

    # Determine confidence based on grader score
    confidence = min(0.9, max(0.3, quality_score / 100.0))

    return ExtractedStrategy(
        strategy_text=strategy_text.strip(),
        sector=sector,
        research_type=research_type,
        confidence_score=confidence,
        source_session_id=session_id,
    )


async def _call_llm_for_strategy(prompt: str) -> str:
    """Call LLM to extract strategy text. Returns empty string on failure."""
    from finagent.runtime_provider import resolve_openai_config

    cfg = resolve_openai_config(complexity="simple")
    if not cfg:
        return ""

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url, timeout=8.0)
        resp = await client.chat.completions.create(
            model=cfg.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract concise, reusable research strategies for Indian equity research. "
                        "Output ONLY the strategy text in IF-THEN format. No explanation."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_completion_tokens=80,
        )
        return resp.choices[0].message.content or ""
    except Exception as exc:
        logger.debug("SPL LLM call failed: %s", exc)
        return ""


def store_strategy(
    strategy: ExtractedStrategy,
    database_url: str | None = None,
) -> bool:
    """Store extracted strategy in spl_strategies PostgreSQL table.

    Args:
        strategy: ExtractedStrategy to store.
        database_url: PostgreSQL connection string.

    Returns:
        True if stored successfully.
    """
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.warning("No database URL configured, strategy not persisted")
        return False

    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    insert into spl_strategies (
                      strategy_text, sector, company_type, research_type,
                      confidence_score, times_applied, created_at
                    )
                    values (%s, %s, %s, %s, %s, 0, now())
                    on conflict do nothing
                    returning id
                    """,
                    (
                        strategy.strategy_text,
                        strategy.sector,
                        strategy.company_type,
                        strategy.research_type,
                        strategy.confidence_score,
                    ),
                )
                inserted = cur.fetchone()
            conn.commit()

        if inserted:
            logger.info("[SPL] Stored new strategy: %.80s...", strategy.strategy_text)
            return True
        return False

    except Exception as exc:
        logger.warning("[SPL] Failed to store strategy: %s", exc)
        return False


def update_strategy_success(
    strategy_id: int,
    success: bool,
    database_url: str | None = None,
) -> None:
    """Update a strategy's success count after it was applied."""
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        return

    try:
        import psycopg

        with psycopg.connect(db_url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    update spl_strategies
                    set times_applied = times_applied + 1,
                        times_successful = times_successful + %s,
                        confidence_score = (times_successful + %s)::numeric /
                                           greatest(times_applied + 1, 1),
                        updated_at = now()
                    where id = %s
                    """,
                    (1 if success else 0, 1 if success else 0, strategy_id),
                )
            conn.commit()
    except Exception as exc:
        logger.debug("[SPL] Failed to update strategy success: %s", exc)
