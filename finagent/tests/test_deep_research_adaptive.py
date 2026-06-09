from __future__ import annotations

import asyncio
import types
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient


def _local_token(secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": "adaptive-deep-test",
            "email": "adaptive-deep-test@example.com",
            "name": "Adaptive Deep Test",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=1),
            "iss": "prospektlab",
            "aud": "prospektlab-api",
        },
        secret,
        algorithm="HS256",
    )


def test_comparison_queries_schedule_peer_pass():
    import finagent.gateway.run as gateway

    pass_ids = gateway._select_deep_evidence_pass_ids(
        "Compare TCS vs Infosys on margins, valuation and moat",
        "Compare TCS vs Infosys on margins, valuation and moat",
        is_comparison_query=True,
        portfolio_scope=False,
    )

    assert pass_ids[0] == "financials"
    assert "peer_comparison" in pass_ids


def test_non_comparison_queries_skip_peer_pass():
    import finagent.gateway.run as gateway

    pass_ids = gateway._select_deep_evidence_pass_ids(
        "Explain TCS valuation and governance risks",
        "Explain TCS valuation and governance risks",
        is_comparison_query=False,
        portfolio_scope=False,
    )

    assert "peer_comparison" not in pass_ids


def test_freshness_queries_include_news_pass():
    import finagent.gateway.run as gateway

    pass_ids = gateway._select_deep_evidence_pass_ids(
        "Give the latest news and sentiment on TCS",
        "Give the latest news and sentiment on TCS",
        is_comparison_query=False,
        portfolio_scope=False,
    )

    assert "news_narrative" in pass_ids


def test_strong_ikg_can_stop_evidence_early():
    import finagent.gateway.run as gateway

    assert gateway._should_stop_deep_evidence(
        {
            "ikg_sufficient": True,
            "can_answer_objective": True,
            "objective_needs_fresh_web": False,
            "conflict_count": 0,
            "doc_count": 1,
            "primary_citations": 0,
            "news_item_count": 0,
        },
        objective="Build a comprehensive deep research report on TCS",
        raw_query="Build a comprehensive deep research report on TCS",
        required_pass_ids=["financials", "valuation", "risk"],
        completed_pass_ids=["financials"],
        is_comparison_query=False,
    ) is True


@pytest.mark.anyio
async def test_deep_research_only_recalls_memory_on_first_and_final_pass(monkeypatch):
    import finagent.gateway.run as gateway

    gateway._TASKS.clear()
    calls: list[object] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        calls.append(loop_config)
        cp = types.SimpleNamespace(
            runtime_meta={
                "ikg_sufficient": False,
                "can_answer_objective": False,
                "objective_needs_fresh_web": False,
                "conflict_count": 1,
                "doc_count": 1,
                "primary_citations": 0,
                "news_item_count": 0,
            }
        )
        return None, cp

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/research/deep",
            json={
                "target": "TCS",
                "objective": "Build a comprehensive deep research report on TCS",
                "max_wall_seconds": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text

        for _ in range(40):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

    assert len(calls) >= 2
    assert calls[0].enable_memory is True
    for cfg in calls[1:-1]:
        assert cfg.enable_memory is False

    final_cfg = calls[-1]
    assert final_cfg.enable_memory is True
    assert final_cfg.response_depth == "deep"
    assert final_cfg.reflection_max_rounds == 1
    assert final_cfg.synth_model == (gateway.os.getenv("FINAGENT_SYNTH_MODEL") or "gpt-4o")

    gateway._TASKS.clear()
