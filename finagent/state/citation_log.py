"""Full citation audit trail."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Citation:
    url: str
    title: str
    date_accessed: str
    kind: str  # primary / secondary / tertiary


@dataclass
class CitationLog:
    entries: list[Citation] = field(default_factory=list)

    def add(
        self,
        *,
        url: str,
        title: str,
        kind: str = "secondary",
    ) -> None:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.entries.append(Citation(url=url, title=title, date_accessed=now, kind=kind))

    def as_markdown_table_rows(self) -> list[str]:
        rows = []
        for c in self.entries:
            rows.append(f"| {c.title} | {c.url} | {c.date_accessed} | {c.kind} |")
        return rows
