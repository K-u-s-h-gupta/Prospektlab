"""FinAgent configuration (environment-driven)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FinAgentSettings:
    openai_api_key: str | None
    prospektlab_mcp_url: str | None
    max_research_duration_hours: float
    checkpoint_interval_steps: int
    compression_interval_steps: int
    min_sources_for_material_claim: int
    # ── India-specific settings ──────────────────────────────────────────
    # Lock all entity resolution to India by default. Set to "" to allow global.
    default_geography: str
    # Override live FX rate (e.g. "84.5"). Leave blank to use live Yahoo rate.
    usd_inr_override: float | None
    # Preferred exchange suffix for unknown tickers: ".NS" for NSE, ".BO" for BSE
    preferred_exchange_suffix: str

    @classmethod
    def from_env(cls) -> "FinAgentSettings":
        usd_inr_raw = os.getenv("FINAGENT_USD_INR", "")
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            prospektlab_mcp_url=os.getenv("PROSPEKTLAB_MCP_URL"),
            max_research_duration_hours=float(os.getenv("MAX_RESEARCH_DURATION_HOURS", "4")),
            checkpoint_interval_steps=int(os.getenv("CHECKPOINT_INTERVAL_STEPS", "5")),
            compression_interval_steps=int(os.getenv("COMPRESSION_INTERVAL_STEPS", "20")),
            min_sources_for_material_claim=int(os.getenv("MIN_SOURCES_FOR_MATERIAL_CLAIM", "2")),
            # India defaults
            default_geography=os.getenv("FINAGENT_DEFAULT_GEO", "IN"),
            usd_inr_override=float(usd_inr_raw) if usd_inr_raw else None,
            preferred_exchange_suffix=os.getenv("FINAGENT_EXCHANGE_SUFFIX", ".NS"),
        )


def load_settings() -> FinAgentSettings:
    return FinAgentSettings.from_env()
