"""Social-signal tools (viral / pump-and-dump verifier)."""

from finagent.tools.social.viral_verifier import (
    ViralAssessment,
    score_text_for_pump_and_dump,
)

__all__ = ["ViralAssessment", "score_text_for_pump_and_dump"]
