"""ProspektLab event triggers — verify externally before acting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class ProspektEvent:
    kind: str
    payload: dict
    detected_at: datetime


def is_stale_for_trigger(ev: ProspektEvent, days: int = 90) -> bool:
    now = datetime.now(timezone.utc)
    dt = ev.detected_at
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days > days
