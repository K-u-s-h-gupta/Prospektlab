"""Typed helpers for Screener payloads."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ScreenerFilter:
    """Parsed natural-language filters for stock screening."""

    min_roce: float | None = None
    min_roe: float | None = None
    max_pe: float | None = None
    min_pe: float | None = None
    max_debt_to_equity: float | None = None
    min_promoter_holding: float | None = None
    max_promoter_pledge: float | None = None
    require_no_pledge: bool = False
    require_above_200dma: bool = False
    min_rsi: float | None = None
    max_rsi: float | None = None
    min_price: float | None = None
    max_price: float | None = None
    keywords: list[str] = field(default_factory=list)
    parse_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_roce": self.min_roce,
            "min_roe": self.min_roe,
            "max_pe": self.max_pe,
            "min_pe": self.min_pe,
            "max_debt_to_equity": self.max_debt_to_equity,
            "min_promoter_holding": self.min_promoter_holding,
            "max_promoter_pledge": self.max_promoter_pledge,
            "require_no_pledge": self.require_no_pledge,
            "require_above_200dma": self.require_above_200dma,
            "min_rsi": self.min_rsi,
            "max_rsi": self.max_rsi,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "keywords": self.keywords,
            "parse_notes": self.parse_notes,
        }

