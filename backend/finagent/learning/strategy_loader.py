"""Strategy Loader — injects top SPL strategies into agent context at session start.

Loads the top-3 strategies by (confidence × times_applied) for the given
sector and research_type, then formats them for injection into agent prompts.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("finagent.learning.strategy_loader")


def load_top_strategies(
    sector: str | None = None,
    research_type: str | None = None,
    limit: int = 3,
    database_url: str | None = None,
) -> list[dict[str, Any]]:
    """Load top strategies from spl_strategies table.

    Ranked by: confidence_score × sqrt(times_applied + 1)
    Filtered by: sector (exact or NULL match) + research_type

    Args:
        sector: SEBI sector to filter by (NULL rows always included).
        research_type: Research focus to filter by.
        limit: Maximum strategies to load.
        database_url: PostgreSQL connection string.

    Returns:
        List of strategy dicts with keys: id, strategy_text, confidence_score, times_applied
    """
    db_url = database_url or os.getenv("IKG_DATABASE_URL") or os.getenv("DATABASE_URL", "")
    if not db_url:
        return []

    try:
        import psycopg
        from psycopg.rows import dict_row

        where_clauses = ["times_applied >= 1 OR confidence_score > 0.7"]
        params: list[Any] = []

        if research_type:
            where_clauses.append("(research_type = %s OR research_type IS NULL)")
            params.append(research_type)

        if sector:
            where_clauses.append("(sector = %s OR sector IS NULL)")
            params.append(sector)

        where_sql = " AND ".join(where_clauses)
        params.append(limit)

        sql = f"""
            select id, strategy_text, sector, research_type,
                   confidence_score, times_applied, times_successful
            from spl_strategies
            where {where_sql}
            order by (confidence_score * sqrt(times_applied + 1)) desc
            limit %s
        """

        with psycopg.connect(db_url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                return [dict(r) for r in cur.fetchall()]

    except Exception as exc:
        logger.debug("[STRATEGY_LOADER] Failed to load strategies: %s", exc)
        return []


def format_strategies_for_context(strategies: list[dict[str, Any]]) -> str:
    """Format strategies as a context injection block for agent prompts.

    Args:
        strategies: List of strategy dicts from load_top_strategies().

    Returns:
        Formatted string ready for injection into agent system prompt.
    """
    if not strategies:
        return ""

    lines = [
        "## Learned Research Strategies",
        "Apply these strategies when relevant to this research session:",
        "",
    ]
    for i, s in enumerate(strategies, 1):
        conf = float(s.get("confidence_score") or 0.5)
        applied = int(s.get("times_applied") or 0)
        lines.append(f"{i}. {s.get('strategy_text', '')}")
        lines.append(f"   _(confidence: {conf:.0%}, applied {applied}x)_")
        lines.append("")

    return "\n".join(lines)


async def inject_strategies_into_session(
    sector: str | None = None,
    research_type: str | None = None,
    database_url: str | None = None,
) -> str:
    """Load and format top strategies for injection into the current session.

    Args:
        sector: SEBI sector classification.
        research_type: Research focus (governance/valuation/risk/etc).
        database_url: PostgreSQL connection string.

    Returns:
        Context block string (empty string if no strategies found).
    """
    import asyncio

    strategies = await asyncio.to_thread(
        load_top_strategies,
        sector=sector,
        research_type=research_type,
        database_url=database_url,
    )

    if strategies:
        logger.info(
            "[STRATEGY_LOADER] Loaded %d strategies for sector=%s research_type=%s",
            len(strategies), sector, research_type,
        )
    return format_strategies_for_context(strategies)
