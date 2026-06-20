from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

import finagent.gateway.run as gateway


class FakeScreenerService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        self.calls.append(("search", (query, limit)))
        return {"query": query, "limit": limit, "items": []}

    async def company_snapshot(self, identifier: str, *, period: str = "1Y") -> dict[str, Any]:
        self.calls.append(("snapshot", (identifier, period)))
        return {"endpoint": "snapshot", "identifier": identifier, "period": period}

    async def company_financials(self, identifier: str) -> dict[str, Any]:
        self.calls.append(("financials", (identifier,)))
        return {"endpoint": "financials", "identifier": identifier}

    async def company_technicals(self, identifier: str, *, period: str = "1Y") -> dict[str, Any]:
        self.calls.append(("technicals", (identifier, period)))
        return {"endpoint": "technicals", "identifier": identifier, "period": period}

    async def company_events(self, identifier: str, *, limit: int = 25) -> dict[str, Any]:
        self.calls.append(("events", (identifier, limit)))
        return {"endpoint": "events", "identifier": identifier, "limit": limit}

    async def analyze(self, identifier: str) -> dict[str, Any]:
        self.calls.append(("analyze", (identifier,)))
        return {"endpoint": "analyze", "identifier": identifier}

    async def query_screen(
        self,
        query: str,
        *,
        limit: int = 25,
        universe: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(("query", (query, limit, universe)))
        return {"query": query, "limit": limit, "universe": universe or []}


def _client_with_fake_service(monkeypatch) -> tuple[TestClient, FakeScreenerService]:
    fake_service = FakeScreenerService()
    monkeypatch.setattr(gateway, "get_screener_service", lambda: fake_service)
    return TestClient(gateway.app, raise_server_exceptions=False), fake_service


def test_screener_search_limit_is_clamped(monkeypatch):
    client, fake_service = _client_with_fake_service(monkeypatch)

    high = client.get("/screener/search", params={"q": "INFY", "limit": 999})
    low = client.get("/screener/search", params={"q": "INFY", "limit": 0})

    assert high.status_code == 200
    assert high.json()["limit"] == 50
    assert low.status_code == 200
    assert low.json()["limit"] == 1
    assert fake_service.calls[0] == ("search", ("INFY", 50))
    assert fake_service.calls[1] == ("search", ("INFY", 1))


def test_screener_company_routes_delegate_to_service(monkeypatch):
    client, fake_service = _client_with_fake_service(monkeypatch)

    snapshot = client.get("/screener/company/RELIANCE/snapshot", params={"period": "6M"})
    financials = client.get("/screener/company/RELIANCE/financials")
    technicals = client.get("/screener/company/RELIANCE/technicals", params={"period": "3M"})
    events = client.get("/screener/company/RELIANCE/events", params={"limit": 1000})
    analyze = client.get("/screener/company/RELIANCE/analyze")

    assert snapshot.status_code == 200
    assert snapshot.json() == {"endpoint": "snapshot", "identifier": "RELIANCE", "period": "6M"}
    assert financials.status_code == 200
    assert financials.json() == {"endpoint": "financials", "identifier": "RELIANCE"}
    assert technicals.status_code == 200
    assert technicals.json() == {"endpoint": "technicals", "identifier": "RELIANCE", "period": "3M"}
    assert events.status_code == 200
    assert events.json() == {"endpoint": "events", "identifier": "RELIANCE", "limit": 100}
    assert analyze.status_code == 200
    assert analyze.json() == {"endpoint": "analyze", "identifier": "RELIANCE"}

    assert fake_service.calls == [
        ("snapshot", ("RELIANCE", "6M")),
        ("financials", ("RELIANCE",)),
        ("technicals", ("RELIANCE", "3M")),
        ("events", ("RELIANCE", 100)),
        ("analyze", ("RELIANCE",)),
    ]


def test_screener_query_sanitizes_universe(monkeypatch):
    client, fake_service = _client_with_fake_service(monkeypatch)

    with_symbols = client.post(
        "/screener/query",
        json={
            "query": "quality stocks with roe > 15",
            "limit": 12,
            "universe": ["INFY", " ", "", "RELIANCE"],
        },
    )
    no_symbols = client.post(
        "/screener/query",
        json={
            "query": "quality stocks with roe > 15",
            "limit": 12,
            "universe": [" ", ""],
        },
    )

    assert with_symbols.status_code == 200
    assert no_symbols.status_code == 200
    assert fake_service.calls[0] == ("query", ("quality stocks with roe > 15", 12, ["INFY", "RELIANCE"]))
    assert fake_service.calls[1] == ("query", ("quality stocks with roe > 15", 12, None))
