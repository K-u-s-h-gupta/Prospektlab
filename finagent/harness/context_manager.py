"""Token counting and compression triggers."""

from __future__ import annotations

from dataclasses import dataclass

from finagent.state.checkpoint import Checkpoint
from finagent.state.citation_log import Citation
from finagent.state.compression import compress_facts_stub


@dataclass
class CompressedContext:
    key_facts: list[str]
    citations: list[Citation]
    confidence_map: dict[str, float]
    pending_step_names: list[str]


async def compress_context_stub(
    history_snippets: list[str],
    checkpoint: Checkpoint,
) -> CompressedContext:
    facts = compress_facts_stub(history_snippets)
    return CompressedContext(
        key_facts=facts.bullets,
        citations=list(checkpoint.citation_log),
        confidence_map=dict(checkpoint.confidence_summary),
        pending_step_names=[s.name for s in checkpoint.pending_steps],
    )


def should_compress(step_count: int, every: int) -> bool:
    return step_count > 0 and step_count % every == 0
