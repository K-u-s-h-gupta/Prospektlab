"""API session handles (persist via ResearchStateStore)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class SessionRecord:
    id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict = field(default_factory=dict)


def new_session(**metadata: str) -> SessionRecord:
    return SessionRecord(id=str(uuid4()), metadata=dict(metadata))
