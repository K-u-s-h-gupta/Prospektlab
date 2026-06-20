from __future__ import annotations

import asyncio
import time
from datetime import date, timedelta
from types import SimpleNamespace

import finagent.screener.service as screener_service_module
import finagent.tools.data.india as india_data_module
from finagent.screener.service import ScreenerService, _ResolvedIdentity, _normalize_financial_payload


def test_company_snapshot_merges_sources(monkeypatch):
    async def fake_fetch_india_snapshot(symbol: str):
        return SimpleNamespace(
            symbol=symbol,
            isin="INE000A01011",
            company_name="Test Industries",
            sector="Industrials",
            industry="Capital Goods",
            current_price=512.25,
            change_pct=1.8,
            pe_ratio=24.2,
            pb_ratio=3.8,
            roe=16.3,
            roce=19.7,
            debt_to_equity=0.42,
            dividend_yield=1.2,
            book_value=132.0,
            market_cap_cr=145000,
            promoter_holding=54.0,
            fii_holding=19.0,
            dii_holding=16.0,
            public_holding=11.0,
            promoter_pledge_pct=0.0,
            source="NSE",
            source_url="https://example.com/quote",
        )

    async def fake_fetch_shareholding_pattern(symbol: str):
        return {"promoter": 54.0, "fii": 19.0, "dii": 16.0, "public": 11.0, "as_of": "2026-06-01"}

    async def fake_fetch_news(query: str, limit: int = 14):
        return [
            SimpleNamespace(
                title="Test Industries wins major order",
                link="https://news.example.com/test-order",
                source="Example News",
                published="2026-06-17T12:00:00Z",
                description="Large order inflow announced.",
                image="",
            )
        ]

    async def fake_fetch_yahoo_quote(symbol: str, timeout_s: float = 18.0, cache_ttl_s: float | None = None):
        return SimpleNamespace(
            ticker=symbol,
            name="Test Industries Ltd",
            currency="INR",
            exchange="NSE",
            price=512.25,
            previous_close=503.2,
            change_pct=1.8,
            market_cap=1450000000000,
            fifty_two_week_high=610.0,
            fifty_two_week_low=402.0,
            series_dates=[f"2026-01-{(idx % 28) + 1:02d}" for idx in range(260)],
            series_closes=[380.0 + idx * 0.55 for idx in range(260)],
            source_url="https://finance.yahoo.com/quote/TEST.NS",
            financial_metrics={
                "free_cashflow": 32000000000,
                "operating_cashflow": 41000000000,
                "trailing_pe": 24.2,
                "price_to_book": 3.8,
                "return_on_equity": 16.3,
                "debt_to_equity": 0.42,
                "total_revenue": 95000000000,
            },
            annual_revenue=[70000000000, 76000000000, 82000000000, 89000000000, 95000000000],
            annual_revenue_dates=["2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"],
            annual_net_income=[7000000000, 7600000000, 8200000000, 9100000000, 9800000000],
            annual_net_income_dates=["2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"],
            business_summary="Test Industries manufactures engineered components for energy and transport customers.",
        )

    def fake_fetch_announcements(identifier: str, max_results: int = 14):
        return [
            {
                "title": "Board Meeting Intimation",
                "url": "https://nse.example.com/board-meeting",
                "snippet": "Board meeting scheduled.",
                "source": "nseindia.com",
                "published": "2026-06-16T10:00:00Z",
                "category": "corporate_action",
            }
        ]

    async def fake_fetch_delivery(symbol: str):
        return {"status": "ok", "delivery_pct": 42.5, "as_of": "2026-06-16", "source": "unit_test"}

    monkeypatch.setattr(screener_service_module, "fetch_india_snapshot", fake_fetch_india_snapshot)
    monkeypatch.setattr(screener_service_module, "fetch_shareholding_pattern", fake_fetch_shareholding_pattern)
    monkeypatch.setattr(screener_service_module, "fetch_news", fake_fetch_news)
    monkeypatch.setattr(screener_service_module, "fetch_yahoo_quote", fake_fetch_yahoo_quote)
    monkeypatch.setattr(screener_service_module, "fetch_nse_delivery_snapshot", fake_fetch_delivery)
    monkeypatch.setattr(screener_service_module, "fetch_nse_announcements", fake_fetch_announcements)

    service = ScreenerService()
    service._graph = SimpleNamespace(
        get_promoter_chain=lambda cin: asyncio.sleep(0, result={"cin": cin, "promoter_chain": []}),
        get_enforcement_actions=lambda cin: asyncio.sleep(0, result=[]),
    )

    async def fake_resolve_identity(_identifier: str):
        return _ResolvedIdentity(
            query="TEST",
            symbol="TEST",
            cin="L00000MH2000PLC000001",
            isin="INE000A01011",
            company_name="Test Industries",
            sector="Industrials",
            confidence=0.9,
            source="unit_test",
        )

    async def empty_payload(_cin: str | None):
        return {}

    monkeypatch.setattr(service, "_resolve_identity", fake_resolve_identity)
    monkeypatch.setattr(service, "_governance_payload", empty_payload)
    monkeypatch.setattr(service, "_network_payload", empty_payload)
    monkeypatch.setattr(service, "_provenance_payload", empty_payload)
    monkeypatch.setattr(service, "_health_payload", empty_payload)
    monkeypatch.setattr(service, "_staleness_payload", empty_payload)
    monkeypatch.setattr(service, "_promoter_chain_payload", empty_payload)
    monkeypatch.setattr(service, "_enforcement_payload", lambda _cin: asyncio.sleep(0, result=[]))

    snapshot = asyncio.run(service.company_snapshot("TEST"))

    assert snapshot["resolved"]["symbol"] == "TEST"
    assert snapshot["fundamentals"]["metrics"]["pe_ratio"] == 24.2
    assert snapshot["technicals"]["status"] == "ok"
    assert snapshot["events"]["news"][0]["headline"] == "Test Industries wins major order"
    assert "score" in snapshot and "prospekt_score" in snapshot["score"]


def test_query_screen_returns_ranked_matches(monkeypatch):
    async def fake_fetch_india_snapshot(symbol: str):
        return SimpleNamespace(
            symbol=symbol,
            isin="INE000A01011",
            company_name=f"{symbol} Ltd",
            sector="Industrials",
            industry="Capital Goods",
            pe_ratio=18.0 if symbol == "AAA" else 26.0,
            roe=17.0 if symbol == "AAA" else 11.0,
            roce=20.0 if symbol == "AAA" else 9.0,
            debt_to_equity=0.4 if symbol == "AAA" else 1.8,
            current_price=200.0 if symbol == "AAA" else 120.0,
            promoter_holding=55.0 if symbol == "AAA" else 38.0,
            promoter_pledge_pct=0.0 if symbol == "AAA" else 12.0,
            source="NSE",
            source_url="https://example.com",
        )

    async def fake_fetch_yahoo_quote(symbol: str, timeout_s: float = 18.0, cache_ttl_s: float | None = None):
        raw = symbol.split(".")[0]
        up = raw == "AAA"
        base = 100.0 if up else 180.0
        slope = 0.7 if up else -0.4
        prices = [base + idx * slope for idx in range(260)]
        start = date(2025, 6, 1)
        dates = [(start + timedelta(days=idx)).isoformat() for idx in range(260)]
        return SimpleNamespace(
            ticker=symbol,
            name=f"{raw} Ltd",
            price=prices[-1],
            change_pct=2.3 if up else -1.7,
            series_dates=dates,
            series_closes=prices,
            source_url="https://finance.yahoo.com",
            financial_metrics={"free_cashflow": 1000 if up else -500, "debt_to_equity": 0.4 if up else 1.8},
            annual_revenue=[1000, 1200, 1400, 1600] if up else [1000, 980, 960, 940],
            annual_net_income=[100, 120, 140, 160] if up else [100, 90, 80, 70],
            business_summary="",
        )

    monkeypatch.setattr(screener_service_module, "fetch_india_snapshot", fake_fetch_india_snapshot)
    monkeypatch.setattr(screener_service_module, "fetch_yahoo_quote", fake_fetch_yahoo_quote)

    service = ScreenerService()
    result = asyncio.run(
        service.query_screen(
            "quality stocks with roce > 15 and roe > 12 and pe < 25 and above 200 dma",
            limit=10,
            universe=["AAA", "BBB"],
        )
    )

    assert result["match_count"] >= 1
    assert result["matches"][0]["symbol"] == "AAA"


def test_normalize_financial_payload_applies_precedence_and_units():
    snapshot = {
        "fundamentals": {
            "metrics": {
                "pe_ratio": 21.5,
                "pb_ratio": 3.2,
                "roe": 15.1,
                "roce": 18.4,
                "debt_to_equity": 0.41,
                "revenue_growth_pct": 11.2,
                "net_income_growth_pct": 9.8,
                "free_cashflow": 32_000_000_000,
                "operating_cashflow": 41_000_000_000,
                "market_cap": 150000.0,
            },
            "financial_trends": {
                "annual_revenue": {
                    "dates": ["2024-03-31", "2025-03-31", "2026-03-31"],
                    "values": [110_000_000_000, 125_000_000_000, 140_000_000_000],
                },
                "annual_net_income": {
                    "dates": ["2024-03-31", "2025-03-31", "2026-03-31"],
                    "values": [12_000_000_000, 14_000_000_000, 17_000_000_000],
                },
            },
            "sources": {"snapshot": "NSE", "yahoo_url": "https://finance.yahoo.com/quote/TEST.NS"},
        }
    }

    cache_row = {
        "updated_at": "2026-06-01T00:00:00Z",
        "income_statement_json": {
            "2026-03-31": {"Total Revenue": 170_000_000_000, "Net Income": 16_000_000_000},
            "2025-03-31": {"Total Revenue": 150_000_000_000, "Net Income": 14_000_000_000},
            "2024-03-31": {"Total Revenue": 130_000_000_000, "Net Income": 12_000_000_000},
        },
        "balance_sheet_json": [
            {"label": "Share Capital", "Mar 2026": 1500, "Mar 2025": 1450, "Mar 2024": 1400},
        ],
        "cashflow_json": [
            {"label": "Cash from Operating Activity", "Mar 2026": 12000, "Mar 2025": 9800, "Mar 2024": 8500},
        ],
        "discrepancies_json": ["No cash flow payload fetched from yfinance or Screener.in"],
    }

    official_rows = [
        {
            "period_end": "2026-03-31",
            "announced_at": "2026-05-10T00:00:00Z",
            "revenue_from_operations": 180_000_000_000,
            "profit_before_tax": 25_000_000_000,
            "profit_after_tax": 19_000_000_000,
            "eps_basic": 112.4,
            "source_url": "https://www.bseindia.com/xbrl/result.xml",
        }
    ]

    screener_live = {
        "income_statement": [
            {"label": "Sales&nbsp;+ ", "Mar 2026": 16000, "Mar 2025": 14500, "Mar 2024": 13200},
            {"label": "Net Profit", "Mar 2026": 1700, "Mar 2025": 1500, "Mar 2024": 1280},
        ],
        "balance_sheet": [],
        "cash_flow": [],
    }

    yfinance_live = {
        "financials_json": {
            "2026-03-31": {"Total Revenue": 175_000_000_000, "Net Income": 17_500_000_000},
            "2025-03-31": {"Total Revenue": 155_000_000_000, "Net Income": 15_500_000_000},
            "2024-03-31": {"Total Revenue": 135_000_000_000, "Net Income": 13_500_000_000},
        },
        "balance_sheet_json": {"2026-03-31": {"Total Assets": 320_000_000_000}},
        "cashflow_json": {"2026-03-31": {"Operating Cash Flow": 45_000_000_000}},
    }

    normalized = _normalize_financial_payload(
        symbol="TEST",
        snapshot=snapshot,
        cache_row=cache_row,
        official_rows=official_rows,
        screener_live=screener_live,
        yfinance_live=yfinance_live,
    )

    assert [row["id"] for row in normalized["periods"]] == ["2024", "2025", "2026"]
    assert normalized["ratios"]["valuation"][0]["key"] == "pe_ratio"

    income_rows = {row["key"]: row for row in normalized["income_statement"]["rows"]}
    # Official XBRL should win over cache/screener/yfinance for FY2026 revenue.
    assert income_rows["revenue"]["values"]["2026"] == 18000.0
    # EPS stays in INR/share (not converted to crore).
    assert income_rows["eps"]["values"]["2026"] == 112.4
    # HTML entity cleanup from "Sales&nbsp;+" should still map to revenue row for prior years.
    assert income_rows["revenue"]["values"]["2024"] is not None

    quality = normalized["quality"]
    assert "No cash flow payload fetched from yfinance or Screener.in" in quality["discrepancies"]
    assert quality["confidence"] > 0.5
    assert any(source["code"] == "official_xbrl" for source in normalized["sources"])


def test_normalize_financial_payload_returns_quality_warnings_for_partial_data():
    normalized = _normalize_financial_payload(
        symbol="TEST",
        snapshot={},
        cache_row=None,
        official_rows=[],
        screener_live=None,
        yfinance_live=None,
    )

    assert normalized["periods"] == []
    assert normalized["quality"]["missing_fields"]
    assert normalized["quality"]["discrepancies"]


def test_company_financials_returns_normalized_sections(monkeypatch):
    service = ScreenerService()

    async def fake_snapshot(_identifier: str, *, period: str = "MAX"):
        return {
            "as_of": "2026-06-19T00:00:00Z",
            "resolved": {"symbol": "TEST", "cin": "L00000MH2000PLC000001"},
            "fundamentals": {
                "metrics": {"pe_ratio": 19.8, "pb_ratio": 3.1},
                "financial_trends": {
                    "annual_revenue": {"dates": ["2024-03-31", "2025-03-31", "2026-03-31"], "values": [90_000_000_000, 110_000_000_000, 130_000_000_000]},
                    "annual_net_income": {"dates": ["2024-03-31", "2025-03-31", "2026-03-31"], "values": [9_000_000_000, 10_000_000_000, 12_000_000_000]},
                },
                "sources": {"snapshot": "NSE", "yahoo_url": "https://finance.yahoo.com/quote/TEST.NS"},
            },
            "score": {"prospekt_score": 72.4, "grade": "B"},
            "summary": {"positives": ["Healthy growth"], "negatives": []},
            "freshness": {"age_hours": {"history": 4.0}},
        }

    monkeypatch.setattr(service, "company_snapshot", fake_snapshot)
    monkeypatch.setattr(
        service,
        "_load_company_financials_cache",
        lambda *, symbol, cin: {
            "income_statement_json": [{"label": "Sales", "Mar 2026": 13000, "Mar 2025": 11000, "Mar 2024": 9000}],
            "balance_sheet_json": [{"label": "Total Assets", "Mar 2026": 42000, "Mar 2025": 39000, "Mar 2024": 36000}],
            "cashflow_json": [{"label": "Cash from Operating Activity", "Mar 2026": 5600, "Mar 2025": 4900, "Mar 2024": 4300}],
            "discrepancies_json": [],
            "updated_at": "2026-06-01T00:00:00Z",
        },
    )
    monkeypatch.setattr(service, "_load_official_financial_rows", lambda *, symbol, cin: [])

    payload = asyncio.run(service.company_financials("TEST"))

    assert "ratios" in payload
    assert "income_statement" in payload
    assert "balance_sheet" in payload
    assert "cash_flow" in payload
    assert payload["periods"][-1]["id"] == "2026"



def test_company_snapshot_runs_supplemental_fetches_concurrently(monkeypatch):
    service = ScreenerService()

    async def fake_resolve_identity(_identifier: str):
        return _ResolvedIdentity(
            query="TEST",
            symbol="TEST",
            cin="L00000MH2000PLC000001",
            isin="INE000A01011",
            company_name="Test Ltd",
            sector="Industrials",
            confidence=0.9,
            source="unit_test",
        )

    async def fake_fetch_india_snapshot(symbol: str):
        return india_data_module.IndiaCompanySnapshot(
            symbol=symbol,
            isin="INE000A01011",
            cin="L00000MH2000PLC000001",
            company_name="Test Ltd",
            sector="Industrials",
            industry="Capital Goods",
            current_price=100.0,
            pe_ratio=20.0,
            pb_ratio=2.0,
            roe=14.0,
            roce=18.0,
            debt_to_equity=0.4,
            market_cap_cr=10000.0,
            promoter_holding=55.0,
            source="screener.in",
        )

    async def fake_fetch_shareholding_pattern(_symbol: str):
        return None

    async def fake_fetch_delivery_snapshot(_symbol: str):
        return {"status": "unavailable"}

    async def fake_fetch_news(query: str, limit: int = 14):
        if query.startswith("Test Ltd"):
            await asyncio.sleep(0.2)
        return []

    def fake_fetch_nse_announcements(identifier: str, max_results: int = 14):
        if identifier == "TEST":
            time.sleep(0.2)
        return []

    async def slow_chart(_symbol: str, *, timeout_s: float = 4.0):
        await asyncio.sleep(0.2)
        prices = [100.0 + idx for idx in range(260)]
        dates = [f"2025-01-{(idx % 28) + 1:02d}" for idx in range(260)]
        return SimpleNamespace(price=prices[-1], change_pct=1.2, currency="INR", source_url="https://finance.yahoo.com", financial_metrics={}, name="Test Ltd", series_dates=dates, series_closes=prices)

    async def slow_peers(**_kwargs):
        await asyncio.sleep(0.2)
        return {"status": "ok", "items": []}

    async def empty_payload(_cin: str | None):
        return {}

    monkeypatch.setattr(service, "_resolve_identity", fake_resolve_identity)
    monkeypatch.setattr(screener_service_module, "fetch_india_snapshot", fake_fetch_india_snapshot)
    monkeypatch.setattr(screener_service_module, "fetch_shareholding_pattern", fake_fetch_shareholding_pattern)
    monkeypatch.setattr(screener_service_module, "fetch_nse_delivery_snapshot", fake_fetch_delivery_snapshot)
    monkeypatch.setattr(screener_service_module, "fetch_news", fake_fetch_news)
    monkeypatch.setattr(screener_service_module, "fetch_nse_announcements", fake_fetch_nse_announcements)
    monkeypatch.setattr(service, "_fetch_yahoo_best", lambda *_args, **_kwargs: asyncio.sleep(0, result=None))
    monkeypatch.setattr(service, "_fetch_yahoo_chart_best", slow_chart)
    monkeypatch.setattr(service, "_peer_comparison", slow_peers)
    monkeypatch.setattr(service, "_governance_payload", empty_payload)
    monkeypatch.setattr(service, "_network_payload", empty_payload)
    monkeypatch.setattr(service, "_provenance_payload", empty_payload)
    monkeypatch.setattr(service, "_health_payload", empty_payload)
    monkeypatch.setattr(service, "_staleness_payload", empty_payload)
    monkeypatch.setattr(service, "_promoter_chain_payload", empty_payload)
    monkeypatch.setattr(service, "_enforcement_payload", lambda _cin: asyncio.sleep(0, result=[]))

    start = time.perf_counter()
    snapshot = asyncio.run(service.company_snapshot("TEST", _force_refresh=True))
    elapsed = time.perf_counter() - start

    assert elapsed < 0.65
    assert snapshot["technicals"]["status"] == "ok"
    assert snapshot["peers"]["status"] == "ok"


def test_moneycontrol_symbol_map_is_available():
    assert isinstance(india_data_module._MC_SYMBOL_MAP, dict)
    assert india_data_module._MC_SYMBOL_MAP.get("RELIANCE")


def test_parse_moneycontrol_json_produces_history_series():
    payload = {
        "s": "ok",
        "c": [100.0, 102.5, 101.0],
        "t": [1718006400, 1718092800, 1718179200],
    }

    snap = india_data_module._parse_moneycontrol_json(payload, "RELIANCE")

    assert snap is not None
    assert snap.current_price == 101.0
    assert len(snap.series_dates) == 3
    assert len(snap.series_closes) == 3
    assert snap.series_closes[-1] == 101.0
    assert snap.change_pct == round(((101.0 - 102.5) / 102.5) * 100.0, 2)


def test_parse_screener_html_accepts_debt_eq_label_without_yahoo():
    html = """
    <html><body>
      <h1 class="company-name">Example Ltd</h1>
      <ul id="top-ratios">
        <li><span class="name">Current Price</span><span class="number">Rs 500</span></li>
        <li><span class="name">Debt / Eq</span><span class="number">0.42</span></li>
      </ul>
    </body></html>
    """

    snap = india_data_module._parse_screener_html(html, "EXAMPLE")

    assert snap is not None
    assert snap.debt_to_equity == 0.42


def test_parse_screener_html_derives_debt_to_equity_from_balance_sheet():
    html = """
    <html><body>
      <h1 class="company-name">Example Ltd</h1>
      <section id="balance-sheet">
        <table>
          <tr><td>Share Capital +</td><td>100</td><td>120</td></tr>
          <tr><td>Reserves</td><td>3,900</td><td>4,880</td></tr>
          <tr><td>Borrowings +</td><td>2,400</td><td>2,500</td></tr>
        </table>
      </section>
      <ul id="top-ratios">
        <li><span class="name">Current Price</span><span class="number">Rs 500</span></li>
      </ul>
    </body></html>
    """

    snap = india_data_module._parse_screener_html(html, "EXAMPLE")

    assert snap is not None
    assert snap.debt_to_equity == 0.5

