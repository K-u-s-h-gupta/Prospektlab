"""FinAgent configuration (environment-driven)."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class FinAgentSettings:
    anthropic_api_key: str | None
    prospektlab_mcp_url: str | None
    max_research_duration_hours: float
    checkpoint_interval_steps: int
    compression_interval_steps: int
    min_sources_for_material_claim: int

    @classmethod
    def from_env(cls) -> FinAgentSettings:
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            prospektlab_mcp_url=os.getenv("PROSPEKTLAB_MCP_URL"),
            max_research_duration_hours=float(os.getenv("MAX_RESEARCH_DURATION_HOURS", "4")),
            checkpoint_interval_steps=int(os.getenv("CHECKPOINT_INTERVAL_STEPS", "5")),
            compression_interval_steps=int(os.getenv("COMPRESSION_INTERVAL_STEPS", "20")),
            min_sources_for_material_claim=int(os.getenv("MIN_SOURCES_FOR_MATERIAL_CLAIM", "2")),
        )


def load_settings() -> FinAgentSettings:
    return FinAgentSettings.from_env()
