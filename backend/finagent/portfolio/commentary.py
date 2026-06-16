"""Proactive AI portfolio commentary.

Generates a short, grounded daily read of the user's book from the live analytics
bundle. Uses the configured LLM when available; always falls back to a deterministic
template built from the same real numbers, so the card never blanks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("finagent.portfolio.commentary")


def _fmt_money(value: float | None) -> str:
    """Format INR with crore/lakh suffixes."""
    if value is None:
        return "₹0"
    sign = "-" if value < 0 else ""
    v = abs(float(value))
    if v >= 1e7:
        return f"{sign}₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"{sign}₹{v / 1e5:.2f} L"
    if v >= 1e3:
        return f"{sign}₹{v / 1e3:.1f}k"
    return f"{sign}₹{v:.0f}"


def _day_driver(analytics: dict[str, Any]) -> dict[str, Any] | None:
    positions = analytics.get("positions") or []
    best = None
    for p in positions:
        dv = p.get("day_change_value")
        if dv is None:
            continue
        if best is None or abs(dv) > abs(best.get("day_change_value", 0)):
            best = p
    if best is None or not best.get("day_change_value"):
        return None
    return {
        "name": best.get("name") or best.get("symbol"),
        "symbol": best.get("symbol"),
        "day_change_pct": round((best.get("day_change_pct") or 0.0) * 100, 2),
        "day_change_value": best.get("day_change_value"),
    }


def build_highlights(analytics: dict[str, Any]) -> list[dict[str, Any]]:
    """Structured chips the UI can render alongside the prose."""
    risk = analytics.get("risk", {}) or {}
    health = analytics.get("health", {}) or {}
    total_value = analytics.get("total_market_value", 0) or 0
    var_pct = risk.get("historical_var_pct")
    highlights: list[dict[str, Any]] = []
    highlights.append({
        "label": "Today",
        "value": f"{_fmt_money(analytics.get('day_change_total'))} ({(analytics.get('day_change_pct') or 0) * 100:+.2f}%)",
        "tone": "up" if (analytics.get("day_change_total") or 0) >= 0 else "down",
    })
    highlights.append({
        "label": "Unrealized P&L",
        "value": f"{_fmt_money(analytics.get('unrealized_pnl'))} ({(analytics.get('unrealized_pnl_pct') or 0) * 100:+.2f}%)",
        "tone": "up" if (analytics.get("unrealized_pnl") or 0) >= 0 else "down",
    })
    if health.get("score") is not None:
        highlights.append({"label": "Health", "value": f"{health.get('score')}/100 · {health.get('band')}", "tone": "neutral"})
    if var_pct is not None and total_value:
        highlights.append({"label": "1-day VaR (95%)", "value": _fmt_money(total_value * var_pct / 100.0), "tone": "down"})
    return highlights


def template_commentary(analytics: dict[str, Any]) -> str:
    """Deterministic narrative from real numbers — the always-available fallback."""
    total_value = analytics.get("total_market_value", 0) or 0
    day_total = analytics.get("day_change_total") or 0.0
    day_pct = (analytics.get("day_change_pct") or 0.0) * 100
    pnl = analytics.get("unrealized_pnl") or 0.0
    pnl_pct = (analytics.get("unrealized_pnl_pct") or 0.0) * 100
    risk = analytics.get("risk", {}) or {}
    health = analytics.get("health", {}) or {}

    move_word = "up" if day_total >= 0 else "down"
    life_word = "up" if pnl >= 0 else "down"
    sentences = [
        f"Your {_fmt_money(total_value)} book is {move_word} {_fmt_money(abs(day_total))} ({day_pct:+.2f}%) today, "
        f"and sits {life_word} {_fmt_money(abs(pnl))} ({pnl_pct:+.2f}%) on cost."
    ]

    driver = _day_driver(analytics)
    if driver and driver.get("day_change_value"):
        dword = "lifting" if (driver["day_change_value"] or 0) >= 0 else "dragging"
        sentences.append(
            f"{driver['name']} is {dword} the book at {driver['day_change_pct']:+.2f}% "
            f"({_fmt_money(driver['day_change_value'])})."
        )

    beta = risk.get("beta_vs_nifty")
    var_pct = risk.get("historical_var_pct")
    sharpe = risk.get("sharpe")
    risk_bits = []
    if health.get("score") is not None:
        risk_bits.append(f"health {health['score']}/100 ({health.get('band')})")
    if beta:
        risk_bits.append(f"beta {beta}")
    if sharpe is not None:
        risk_bits.append(f"Sharpe {sharpe}")
    if var_pct is not None and total_value:
        risk_bits.append(f"1-day 95% VaR ≈ {_fmt_money(total_value * var_pct / 100.0)}")
    if risk_bits:
        sentences.append("Risk read: " + ", ".join(risk_bits) + ".")
    return " ".join(sentences)


def _facts_block(analytics: dict[str, Any]) -> str:
    risk = analytics.get("risk", {}) or {}
    health = analytics.get("health", {}) or {}
    sectors = analytics.get("sector_breakdown", {}) or {}
    top_sector = max(sectors.items(), key=lambda kv: kv[1]) if sectors else None
    contrib = (analytics.get("attribution", {}) or {}).get("top_contributors", [])
    detract = (analytics.get("attribution", {}) or {}).get("top_detractors", [])
    driver = _day_driver(analytics)
    lines = [
        f"Total value: {_fmt_money(analytics.get('total_market_value'))}",
        f"Today's move: {_fmt_money(analytics.get('day_change_total'))} ({(analytics.get('day_change_pct') or 0) * 100:+.2f}%)",
        f"Unrealized P&L: {_fmt_money(analytics.get('unrealized_pnl'))} ({(analytics.get('unrealized_pnl_pct') or 0) * 100:+.2f}%)",
        f"Holdings: {analytics.get('count')}",
        f"Health score: {health.get('score')}/100 ({health.get('band')})",
        f"Beta vs Nifty: {risk.get('beta_vs_nifty')}",
        f"Sharpe: {risk.get('sharpe')}, Sortino: {risk.get('sortino')}, Calmar: {risk.get('calmar')}",
        f"Annualized vol: {risk.get('annualized_volatility_pct')}%, Max drawdown: {risk.get('max_drawdown_pct')}%",
        f"1-day 95% historical VaR: {risk.get('historical_var_pct')}%, CVaR: {risk.get('cvar_pct')}%",
        f"Top-5 concentration: {risk.get('top5_weight_pct')}%, HHI: {round((risk.get('hhi') or 0), 3)}",
    ]
    if top_sector:
        lines.append(f"Largest sector: {top_sector[0]} ({top_sector[1] * 100:.1f}%)")
    if driver:
        lines.append(f"Biggest mover today: {driver['name']} {driver['day_change_pct']:+.2f}% ({_fmt_money(driver['day_change_value'])})")
    if contrib:
        lines.append("Top lifetime contributors: " + ", ".join(f"{c['name']} {c['contribution_pct']:+.2f}%" for c in contrib[:3]))
    if detract:
        lines.append("Top lifetime detractors: " + ", ".join(f"{c['name']} {c['contribution_pct']:+.2f}%" for c in detract[:3]))
    return "\n".join(lines)


_SYSTEM = (
    "You are Arthik, a sharp Indian-markets portfolio analyst. Write a punchy 2-3 sentence "
    "daily read of the user's portfolio using ONLY the numbers provided. Use INR with crore/lakh. "
    "Lead with today's move and its main driver, then one concrete strength or risk. "
    "No preamble, no bullet points, no investment advice, no disclaimers, no hedging filler."
)


async def generate_commentary(analytics: dict[str, Any]) -> dict[str, Any]:
    """Return {commentary, source, highlights, generated_at}. Never raises."""
    now = datetime.now(timezone.utc).isoformat()
    highlights = build_highlights(analytics)
    if not analytics or not analytics.get("count"):
        return {
            "commentary": "Add holdings to get Arthik's daily read on your book.",
            "source": "empty",
            "highlights": [],
            "generated_at": now,
        }

    facts = _facts_block(analytics)
    try:
        from finagent.runtime_provider import resolve_openai_config
        cfg = resolve_openai_config(complexity="simple")
        if cfg is not None:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
            resp = await client.chat.completions.create(
                model=cfg.model,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": f"Portfolio snapshot:\n{facts}\n\nWrite the daily read."},
                ],
                temperature=0.5,
                max_tokens=180,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return {"commentary": text, "source": "llm", "highlights": highlights, "generated_at": now}
    except Exception as exc:
        logger.info("Commentary LLM unavailable, using template: %s", exc)

    return {"commentary": template_commentary(analytics), "source": "template", "highlights": highlights, "generated_at": now}
