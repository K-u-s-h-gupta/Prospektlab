"""ProspektLab content generation — v2 (flash + deep pipeline)."""
from finagent.content.flash_engine import (
    FlashGenerationRequest,
    FlashIngestRequest,
    FlashIngestResult,
    generate_flash_article,
    ingest_events_flash,
    build_insights_hub_html,
)

__all__ = [
    "FlashGenerationRequest",
    "FlashIngestRequest",
    "FlashIngestResult",
    "generate_flash_article",
    "ingest_events_flash",
    "build_insights_hub_html",
]
