from __future__ import annotations

import asyncio
import sys
import types

import jwt
from fastapi.testclient import TestClient

from finagent.portfolio_mirrors import init_position_mirrors, load_active_positions, portfolio_weights
from finagent.portfolio_sentinel import CONCENTRATION_RULE, run_portfolio_sentinel
from finagent.storage.sqlite import connect_wal


def test_connect_wal_sets_pragmas(tmp_path):
    db = tmp_path / "state.sqlite3"
    with connect_wal(db) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

    assert journal_mode.lower() == "wal"
    assert synchronous == 1


def test_position_mirrors_are_tenant_scoped(tmp_path):
    db = tmp_path / "memory.sqlite3"
    init_position_mirrors(db)
    with connect_wal(db) as conn:
        conn.execute(
            "INSERT INTO position_mirrors(tenant_id, symbol, exchange, quantity, market_value, active) VALUES (?, ?, ?, ?, ?, ?)",
            ("tenant-a", "TCS", "NSE", 2, 1000, 1),
        )
        conn.execute(
            "INSERT INTO position_mirrors(tenant_id, symbol, exchange, quantity, market_value, active) VALUES (?, ?, ?, ?, ?, ?)",
            ("tenant-b", "RELIANCE", "NSE", 1, 2000, 1),
        )

    positions = load_active_positions("tenant-a", db_path=db)

    assert [p.symbol for p in positions] == ["TCS"]
    assert portfolio_weights(positions) == {"TCS.NS": 1.0}


def test_portfolio_sentinel_injects_concentration_rule(monkeypatch, tmp_path):
    db = tmp_path / "memory.sqlite3"
    init_position_mirrors(db)
    with connect_wal(db) as conn:
        conn.execute(
            "INSERT INTO position_mirrors(tenant_id, symbol, exchange, quantity, market_value, active) VALUES (?, ?, ?, ?, ?, ?)",
            ("tenant-a", "TCS", "NSE", 1, 900, 1),
        )
        conn.execute(
            "INSERT INTO position_mirrors(tenant_id, symbol, exchange, quantity, market_value, active) VALUES (?, ?, ?, ?, ?, ?)",
            ("tenant-a", "INFY", "NSE", 1, 100, 1),
        )

    monkeypatch.setattr("finagent.portfolio_sentinel.load_active_positions", lambda tenant_id: load_active_positions(tenant_id, db_path=db))
    fake_quant = types.SimpleNamespace(
        run_full_portfolio_risk=lambda *args, **kwargs: {"hhi_analysis": {"hhi_decimal": 0.82}}
    )
    monkeypatch.setitem(sys.modules, "finagent.tools.mcp_servers.quant_server", fake_quant)

    result = asyncio.run(run_portfolio_sentinel("tenant-a"))

    assert result.concentration_alert is True
    assert CONCENTRATION_RULE in result.rules


def test_portfolio_mirror_api_replaces_only_verified_tenant(monkeypatch, tmp_path):
    from finagent.gateway.run import JWT_SECRET, app

    db = tmp_path / "memory.sqlite3"
    monkeypatch.setattr("finagent.portfolio_mirrors._DEFAULT_DB", db)
    client = TestClient(app, raise_server_exceptions=False)
    token_a = jwt.encode({"user_id": "tenant-a", "email": "a@example.com"}, JWT_SECRET, algorithm="HS256")
    token_b = jwt.encode({"user_id": "tenant-b", "email": "b@example.com"}, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/portfolio/mirror",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"positions": [{"symbol": "TCS", "exchange": "NSE", "quantity": 2, "market_value": 1000}]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "MIRROR_SYNCHRONIZED"
    assert response.json()["weights"] == {"TCS.NS": 1.0}

    response_b = client.get("/portfolio/mirror", headers={"Authorization": f"Bearer {token_b}"})

    assert response_b.status_code == 200
    assert response_b.json()["positions"] == []


def test_ecas_upload_endpoint_mirrors_equity_positions(monkeypatch, tmp_path):
    from finagent.gateway.run import JWT_SECRET, app

    db = tmp_path / "memory.sqlite3"
    monkeypatch.setattr("finagent.portfolio_mirrors._DEFAULT_DB", db)

    async def fake_parse(pdf_bytes, filename, password):
        assert pdf_bytes == b"%PDF-1.7 fake"
        assert password == "secret"
        return {
            "demat_accounts": [
                {
                    "holdings": {
                        "equities": [
                            {
                                "symbol": "INFY",
                                "exchange": "NSE",
                                "quantity": 3,
                                "market_value": 4500,
                                "cost_basis": 3000,
                            }
                        ]
                    }
                }
            ]
        }

    monkeypatch.setattr("finagent.gateway.run.parse_ecas_pdf", fake_parse)
    client = TestClient(app, raise_server_exceptions=False)
    token = jwt.encode({"user_id": "tenant-a", "email": "a@example.com"}, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/api/portfolio/upload-cas",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("ecas.pdf", b"%PDF-1.7 fake", "application/pdf")},
        data={"password": "secret"},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "ecas_pdf"
    assert response.json()["status"] == "MIRROR_SYNCHRONIZED"
    assert response.json()["weights"] == {"INFY.NS": 1.0}
    assert response.json()["positions"][0]["cost_basis"] == 3000


def test_portfolio_chat_requires_synchronized_mirror(monkeypatch):
    from finagent.gateway.run import JWT_SECRET, app

    client = TestClient(app, raise_server_exceptions=False)
    token = jwt.encode({"user_id": "tenant-empty", "email": "empty@example.com"}, JWT_SECRET, algorithm="HS256")

    response = client.post(
        "/research/start",
        headers={"Authorization": f"Bearer {token}"},
        json={"target": "Run a risk audit on my portfolio concentration", "mode": "deep"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["status"] == "MIRROR_REQUIRED"
