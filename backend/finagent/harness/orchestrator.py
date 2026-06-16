"""Harness orchestration around the core agent loop."""

from __future__ import annotations

from dataclasses import dataclass

from finagent.paths import finagent_data_path
from finagent.settings import FinAgentSettings, load_settings
from finagent.state.checkpoint import Checkpoint, serialize_checkpoint
from finagent.state.research_state import ResearchStateStore


@dataclass
class HarnessConfig:
    session_id: str
    db_path: str | None = None


class Harness:
    """Checkpoint cadence, compression triggers, footprint — wired from run_agent."""

    def __init__(self, config: HarnessConfig, settings: FinAgentSettings | None = None) -> None:
        self.config = config
        self.settings = settings or load_settings()
        from pathlib import Path

        db = Path(config.db_path) if config.db_path else finagent_data_path("research_state.sqlite3")
        self.store = ResearchStateStore(db)

    def maybe_persist_checkpoint(self, step: int, cp: Checkpoint) -> None:
        if step > 0 and step % self.settings.checkpoint_interval_steps == 0:
            self.store.init_db()
            self.store.save_checkpoint(self.config.session_id, step, serialize_checkpoint(cp))

    def should_compress(self, step: int) -> bool:
        return step > 0 and step % self.settings.compression_interval_steps == 0
