"""Persistent cross-session memory for the research agent.

Stores findings, prior memo summaries, recurring themes, and named entities
keyed by canonical target (ticker / CIK). On a new run we recall the most
relevant facts and inject them into the agent's working context so it
doesn't start from zero every time.
"""

from finagent.memory.store import MemoryFact, MemoryStore, get_memory_store

__all__ = ["MemoryFact", "MemoryStore", "get_memory_store"]
