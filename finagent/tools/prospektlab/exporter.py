"""CSV export — only after human gate."""

from __future__ import annotations

from typing import Any, Protocol


class ExportClient(Protocol):
    async def export_to_csv(self, dataset_id: str, path: str) -> str: ...
