from __future__ import annotations


AGENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "financials": ("financial", "revenue", "margin", "balance sheet", "cash flow", "valuation", "forecast", "guidance", "outlook"),
    "risk": ("risk", "lawsuit", "investigation", "fraud", "headwind"),
    "technical": ("technical", "chart", "momentum", "breakout", "moving average"),
    "news": ("news", "headline", "update", "earnings", "deal", "commentary", "forecast", "outlook", "catalyst"),
    "community": ("sentiment", "retail", "community", "buzz"),
    "competitor": ("compare", "competitor", "peer", "vs", "versus", "market share"),
    "macro": ("macro", "rates", "inflation", "fx", "commodity", "sector", "forecast", "outlook"),
    "governance": ("governance", "board", "management", "insider", "compensation"),
    "valuation": ("valuation", "dcf", "intrinsic value", "target price", "upside", "undervalued", "overvalued"),
    "accounting": ("accounting", "anomaly", "forensic", "earnings quality", "restatement", "red flag", "manipulation"),
}
