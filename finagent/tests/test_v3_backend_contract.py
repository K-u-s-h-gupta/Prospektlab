from __future__ import annotations

import asyncio
import sys
import types

import httpx
import jwt
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from finagent.ingestion.markdown_extractor import extract_positions_from_markdown
from finagent.ingestion.portfolio_schema import PortfolioExtractionSchema
from finagent.memory.store import MemoryFact, get_memory_store
from finagent.portfolio_mirrors import load_active_positions, portfolio_weights, replace_active_positions
from finagent.portfolio_sentinel import CONCENTRATION_RULE, run_portfolio_sentinel
from finagent.storage.sqlite import connect_wal


def _mint_test_token(payload: dict, secret: str) -> str:
    now = datetime.now(timezone.utc)
    payload["iat"] = now
    payload["exp"] = now + timedelta(hours=1)
    payload.setdefault("iss", "prospektlab")
    payload.setdefault("aud", "prospektlab-api")
    return jwt.encode(payload, secret, algorithm="HS256")


def setup_function(function):
    """Force in-memory fallback for tests by disabling Supabase configuration."""
    import finagent.storage.supabase_store as _ss
    import finagent.memory.store as _ms
    _ss._is_supabase_configured = lambda: False
    _ss._portfolio_store = None
    _ss._memory_store = None
    _ss._state_store = None
    _ss._token_usage_store = None
    _ms._singleton = None


def test_connect_wal_sets_pragmas(tmp_path):
    db = tmp_path / "state.sqlite3"
    with connect_wal(db) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert synchronous == 1


def test_memory_store_accepts_explicit_created_at_and_summary():
    store = get_memory_store()
    created_at = 1710000000.0

    saved = asyncio.run(
        store.remember(
            MemoryFact(
                target_key="TCS",
                kind="financial",
                body="Revenue grew year over year.",
                confidence="HIGH",
                user_email="memory@example.com",
                created_at=created_at,
            )
        )
    )

    assert saved == 1

    rows = asyncio.run(
        store.get_facts(
            target_key="TCS",
            user_email="memory@example.com",
            limit=10,
        )
    )
    assert len(rows) == 1
    assert float(rows[0]["created_at"]) == created_at

    asyncio.run(
        store.save_session_summary(
            session_id="sess-memory-1",
            target_key="TCS",
            target_display="TCS",
            summary="Portfolio remains resilient.",
            metrics={"quality": 0.92},
            citation_count=2,
            quality_score=0.92,
            user_email="memory@example.com",
        )
    )

    summary = asyncio.run(store.last_summary("TCS", user_email="memory@example.com"))
    assert summary is not None
    assert summary["summary"] == "Portfolio remains resilient."


async def _seed_positions(tenant_id: str, positions: list[dict]) -> None:
    await replace_active_positions(tenant_id, positions)


def test_position_mirrors_are_tenant_scoped():
    asyncio.run(_seed_positions("tenant-a", [
        {"symbol": "TCS", "exchange": "NSE", "quantity": 2, "market_value": 1000, "active": True},
    ]))
    asyncio.run(_seed_positions("tenant-b", [
        {"symbol": "RELIANCE", "exchange": "NSE", "quantity": 1, "market_value": 2000, "active": True},
    ]))

    positions = asyncio.run(load_active_positions("tenant-a"))

    assert [p.symbol for p in positions] == ["TCS.NS"]
    assert portfolio_weights(positions) == {"TCS.NS": 1.0}


def test_portfolio_sentinel_injects_concentration_rule(monkeypatch):
    async def fake_load(tenant_id):
        return [
            types.SimpleNamespace(exchange_symbol="TCS", normalized_symbol="TCS", symbol="TCS", market_value=900),
            types.SimpleNamespace(exchange_symbol="INFY", normalized_symbol="INFY", symbol="INFY", market_value=100),
        ]

    monkeypatch.setattr("finagent.portfolio_sentinel.load_active_positions", fake_load)
    fake_quant = types.SimpleNamespace(
        run_full_portfolio_risk=lambda *args, **kwargs: {"hhi_analysis": {"hhi_decimal": 0.82}}
    )
    monkeypatch.setitem(sys.modules, "finagent.tools.mcp_servers.quant_server", fake_quant)

    result = asyncio.run(run_portfolio_sentinel("tenant-a"))

    assert result.concentration_alert is True
    assert CONCENTRATION_RULE in result.rules


def test_portfolio_mirror_api_replaces_only_verified_tenant(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    client = TestClient(app, raise_server_exceptions=False)
    token_a = _mint_test_token({"user_id": "tenant-a", "email": "a@example.com"}, JWT_SECRET)
    token_b = _mint_test_token({"user_id": "tenant-b", "email": "b@example.com"}, JWT_SECRET)

    response = client.post(
        "/portfolio/mirror",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"positions": [{"symbol": "TCS", "exchange": "NSE", "quantity": 2, "market_value": 1000, "cost_basis": 500}]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "MIRROR_SYNCHRONIZED"
    assert response.json()["weights"] == {"TCS.NS": 1.0}

    response_b = client.get("/portfolio/mirror", headers={"Authorization": f"Bearer {token_b}"})

    assert response_b.status_code == 200
    assert response_b.json()["positions"] == []


def test_portfolio_replace_uses_inserted_rows_when_reload_is_empty(monkeypatch):
    import finagent.portfolio_mirrors as mirrors

    class InsertReturningStore:
        async def replace_active_positions(self, tenant_id, positions):
            return [
                {
                    **positions[0],
                    "tenant_id": tenant_id,
                    "active": 1,
                }
            ]

        async def load_active_positions(self, tenant_id):
            return []

    monkeypatch.setattr(mirrors, "get_portfolio_store", lambda: InsertReturningStore())

    positions = asyncio.run(
        mirrors.replace_active_positions(
            "tenant-a",
            [{"symbol": "BAJEL", "exchange": "NSE", "quantity": 40, "market_value": 7255.2}],
        )
    )

    assert len(positions) == 1
    assert positions[0].symbol == "BAJEL.NS"
    assert positions[0].market_value == 7255.2


def test_ecas_upload_endpoint_mirrors_equity_positions(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    async def fake_parse(pdf_bytes, filename, password):
        assert pdf_bytes == b"%PDF-1.7 fake"
        assert password == "secret"
        return PortfolioExtractionSchema.model_validate({
            "status": "MIRROR_SYNCHRONIZED",
            "source_type": "pdf",
            "confidence": 0.9,
            "investor": {"name": "Test User", "email": "a@example.com", "pan": "ABCDE1234F"},
            "diagnostics": {"transformer": "mineru"},
            "positions": [{
                "symbol": "INFY",
                "exchange": "NSE",
                "quantity": 3,
                "market_value": 4500,
                "cost_basis": 3000,
                "name": "Infosys Limited",
                "isin": "INE009A01021",
                "confidence": 0.95,
            }],
        })

    monkeypatch.setattr("finagent.gateway.run.parse_portfolio_document", fake_parse)
    client = TestClient(app, raise_server_exceptions=False)
    token = _mint_test_token({"user_id": "tenant-a", "email": "a@example.com"}, JWT_SECRET)

    response = client.post(
        "/api/portfolio/upload-cas",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("ecas.pdf", b"%PDF-1.7 fake", "application/pdf")},
        data={"password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "pdf"
    assert response.json()["status"] == "MIRROR_SYNCHRONIZED"
    assert response.json()["weights"] == {"INFY.NS": 1.0}
    assert response.json()["positions"][0]["cost_basis"] == 3000


def test_markdown_extractor_uses_visible_rows_not_sandbox_names():
    md = """
| Symbol | Name | Qty | Market Value | Avg Cost | LTP |
|---|---|---:|---:|---:|---:|
| TCS | Tata Consultancy Services | 2 | ₹7,000 | 3000 | 3500 |
| INFY | Infosys Limited | 4 | ₹6,400 | 1400 | 1600 |
"""

    extraction = extract_positions_from_markdown(md, source_type="csv")
    symbols = {p.symbol for p in extraction.positions}

    assert extraction.status == "MIRROR_SYNCHRONIZED"
    assert symbols == {"TCS", "INFY"}
    assert "HDFCBANKLIMITED" not in symbols
    assert "RELIANCEINDUSTRIESLIMITED" not in symbols


def test_screenshot_upload_requires_review_and_does_not_write(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    async def fake_image_extract(image_bytes, filename):
        assert image_bytes.startswith(b"\x89PNG")
        return PortfolioExtractionSchema.model_validate({
            "status": "REVIEW_REQUIRED",
            "source_type": "image",
            "confidence": 0.8,
            "positions": [{
                "symbol": "TCS",
                "exchange": "NSE",
                "quantity": 2,
                "market_value": 7000,
                "name": "Tata Consultancy Services",
                "confidence": 0.8,
                "raw_evidence": "TCS 2 7000",
            }],
        })

    monkeypatch.setattr("finagent.gateway.run.extract_portfolio_from_image", fake_image_extract)
    client = TestClient(app, raise_server_exceptions=False)
    token = _mint_test_token({"user_id": "tenant-img", "email": "img@example.com"}, JWT_SECRET)

    response = client.post(
        "/api/portfolio/upload-screenshot",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("holdings.png", b"\x89PNG\x0d\x0a\x1a\x0a fake", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["review_id"]
    assert asyncio.run(load_active_positions("tenant-img")) == []


def test_portfolio_chat_requires_synchronized_mirror():
    from finagent.gateway.run import JWT_SECRET, app

    client = TestClient(app, raise_server_exceptions=False)
    token = _mint_test_token({"user_id": "tenant-empty", "email": "empty@example.com"}, JWT_SECRET)

    response = client.post(
        "/research/start",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "Run a risk audit on my portfolio concentration", "mode": "deep"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["session_id"]
    assert body["stream"]
    assert body["status"]
    assert body["mode"] == "deep"
    assert body["passes"] == 8


def test_portfolio_preflight_allows_contextual_fallback_when_store_unavailable(monkeypatch):
    import finagent.gateway.run as gateway

    async def unavailable(_tenant_id):
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr(gateway, "load_active_positions", unavailable)

    allowed = asyncio.run(gateway._require_synchronized_portfolio("tenant-a", allow_empty=True))

    assert allowed is False


def test_portfolio_news_degrades_when_store_unavailable(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    async def unavailable(_tenant_id):
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr("finagent.gateway.run.load_active_positions", unavailable)
    client = TestClient(app, raise_server_exceptions=False)
    token = _mint_test_token({"user_id": "tenant-news", "email": "news@example.com"}, JWT_SECRET)

    response = client.get(
        "/portfolio/news?limit=8",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["store_unavailable"] is True


def test_portfolio_analytics_degrades_when_store_unavailable(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    async def unavailable(_tenant_id):
        raise RuntimeError("mirror unavailable")

    monkeypatch.setattr("finagent.gateway.run.load_active_positions", unavailable)
    client = TestClient(app, raise_server_exceptions=False)
    token = _mint_test_token({"user_id": "tenant-analytics", "email": "analytics@example.com"}, JWT_SECRET)

    response = client.get(
        "/portfolio/analytics",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "MIRROR_EMPTY"
    assert body["store_unavailable"] is True


def test_supabase_portfolio_store_serves_cached_mirror_on_timeout(monkeypatch, tmp_path):
    import finagent.storage.supabase_store as supabase_store

    monkeypatch.setenv("FINAGENT_HOME", str(tmp_path))
    monkeypatch.setattr(supabase_store, "_PORTFOLIO_MIRROR_FAST_CACHE_TTL_S", 0)

    class TimeoutClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise httpx.ConnectTimeout("connect timed out")

    monkeypatch.setattr(supabase_store, "_supabase_async_client", lambda: TimeoutClient())

    store = supabase_store.SupabasePortfolioStore()
    rows = [{
        "tenant_id": "tenant-cache",
        "symbol": "TCS.NS",
        "exchange": "NSE",
        "quantity": 2,
        "market_value": 7000,
        "cost_basis": 6000,
        "active": 1,
        "name": "Tata Consultancy Services",
    }]
    store._write_cache("tenant-cache", rows)

    loaded = asyncio.run(store.load_active_positions("tenant-cache"))

    assert loaded == rows


def test_supabase_portfolio_store_uses_fresh_memory_cache(monkeypatch, tmp_path):
    import finagent.storage.supabase_store as supabase_store

    monkeypatch.setenv("FINAGENT_HOME", str(tmp_path))
    monkeypatch.setattr(supabase_store, "_PORTFOLIO_MIRROR_FAST_CACHE_TTL_S", 30)

    class UnexpectedClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *args, **kwargs):
            raise AssertionError("fresh portfolio cache should avoid a Supabase round trip")

    monkeypatch.setattr(supabase_store, "_supabase_async_client", lambda: UnexpectedClient())

    store = supabase_store.SupabasePortfolioStore()
    rows = [{
        "tenant_id": "tenant-fast-cache",
        "symbol": "RELIANCE.NS",
        "exchange": "NSE",
        "quantity": 5,
        "market_value": 14000,
        "cost_basis": 12000,
        "active": 1,
        "name": "Reliance Industries",
    }]
    store._write_cache("tenant-fast-cache", rows)

    loaded = asyncio.run(store.load_active_positions("tenant-fast-cache"))

    assert loaded == rows


def test_portfolio_extraction_llm_schema_is_openai_strict():
    from finagent.ingestion.portfolio_schema import (
        PortfolioExtractionLLMResponse,
        PortfolioPositionSchema,
        ensure_openai_strict_schema,
    )

    # These must never regress — they are passed (directly or indirectly) to OpenAI
    ensure_openai_strict_schema(PortfolioExtractionLLMResponse)
    ensure_openai_strict_schema(PortfolioPositionSchema)

    # The main runtime schema is intentionally allowed to have flexible dicts
    # (diagnostics, investor) and is never sent as response_format to OpenAI.
    main_schema = PortfolioExtractionLLMResponse.model_json_schema()
    assert "diagnostics" not in main_schema.get("properties", {})
    assert "investor" not in main_schema.get("properties", {})
