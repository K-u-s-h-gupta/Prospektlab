from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient


def _local_token(secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": "chat-mode-smoke",
            "email": "chat-mode-smoke@example.com",
            "name": "Chat Mode Smoke",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + timedelta(hours=1),
            "iss": "prospektlab",
            "aud": "prospektlab-api",
        },
        secret,
        algorithm="HS256",
    )


@pytest.mark.anyio
async def test_chat_research_accepts_authenticated_standard_and_deep_modes(monkeypatch):
    import finagent.gateway.run as gateway

    monkeypatch.setenv("FINAGENT_USE_SWARM_STANDARD", "0")
    monkeypatch.setenv("FINAGENT_USE_SWARM_DEEP", "0")
    gateway._TASKS.clear()
    calls: list[str] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        calls.append(str(loop_config.response_depth))
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="smoke-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        for mode in ("standard", "deep"):
            response = await client.post(
                "/chat/research",
                json={
                    "message": "Who owns Adani Enterprises through which entities?",
                    "mode": mode,
                    "max_wall_seconds": 30,
                },
                headers=headers,
            )
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["session_id"]
            assert data["stream"].startswith("/sessions/")
            for _ in range(20):
                if not gateway._TASKS:
                    break
                await asyncio.sleep(0.1)

    assert "standard" in calls
    assert "deep" in calls
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_session_result_uses_answer_payload_when_memo_is_absent(monkeypatch):
    import finagent.gateway.run as gateway

    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_standard_mode_enables_deep_lite_for_multi_factor_queries(monkeypatch):
    import finagent.gateway.run as gateway

    monkeypatch.setenv("FINAGENT_USE_SWARM_STANDARD", "0")
    gateway._TASKS.clear()
    cfgs: list[object] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        cfgs.append(loop_config)
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="smoke-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "Give a comprehensive analysis of Reliance governance, ownership structure, valuation, and regulatory risks",
                "mode": "standard",
                "max_wall_seconds": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

    assert cfgs
    cfg = cfgs[-1]
    assert cfg.response_depth == "standard"
    assert cfg.enable_reflection is True
    assert cfg.enable_blindspot is True
    assert cfg.enable_deep_dive is True
    assert cfg.fast_mode is False
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_standard_mode_keeps_fast_profile_for_simple_snapshot(monkeypatch):
    import finagent.gateway.run as gateway

    monkeypatch.setenv("FINAGENT_USE_SWARM_STANDARD", "0")
    gateway._TASKS.clear()
    cfgs: list[object] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        cfgs.append(loop_config)
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="smoke-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "What is TCS current PE ratio?",
                "mode": "standard",
                "max_wall_seconds": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

    assert cfgs
    cfg = cfgs[-1]
    assert cfg.response_depth == "standard"
    assert cfg.enable_reflection is False
    assert cfg.enable_blindspot is False
    assert cfg.enable_deep_dive is False
    assert cfg.fast_mode is True
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_chat_research_guest_sets_cookie_and_can_fetch_result(monkeypatch):
    import finagent.gateway.run as gateway
    import finagent.storage.supabase_store as ss

    monkeypatch.setenv("FINAGENT_USE_SWARM_STANDARD", "0")
    monkeypatch.setenv("FINAGENT_USE_SWARM_DEEP", "0")
    gateway._TASKS.clear()
    gateway._GUEST_FALLBACK_STATE_STORE = None
    monkeypatch.setattr(ss, "_is_supabase_configured", lambda: False)
    ss._state_store = None

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="guest-smoke-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "What is TCS current PE ratio?",
                "mode": "standard",
                "max_wall_seconds": 30,
            },
        )
        assert response.status_code == 200, response.text
        assert "pl_guest=" in (response.headers.get("set-cookie") or "")
        session_id = response.json()["session_id"]

        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

        result = await client.get(f"/sessions/{session_id}/result")
        assert result.status_code == 200, result.text
        assert result.json()["memo"] == "guest-smoke-ok"

    gateway._TASKS.clear()
    gateway._GUEST_FALLBACK_STATE_STORE = None


@pytest.mark.anyio
async def test_chat_research_guest_remains_available_when_rate_limit_stores_fail(monkeypatch):
    import finagent.gateway.run as gateway
    import finagent.storage.supabase_store as ss

    monkeypatch.setenv("FINAGENT_USE_SWARM_STANDARD", "0")
    monkeypatch.setenv("FINAGENT_USE_SWARM_DEEP", "0")
    gateway._TASKS.clear()

    class BrokenStore:
        async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
            raise RuntimeError("primary rate-limit store unavailable")

    class BrokenFallback:
        async def check_rate_limit(self, key: str, limit: int, window_seconds: int) -> bool:
            raise RuntimeError("fallback rate-limit store unavailable")

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="guest-availability-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(ss, "get_state_store", lambda: BrokenStore())
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)
    gateway._GUEST_FALLBACK_STATE_STORE = BrokenFallback()

    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "Summarize risk for TCS.",
                "mode": "standard",
                "max_wall_seconds": 30,
            },
        )
        assert response.status_code == 200, response.text

    gateway._TASKS.clear()
    gateway._GUEST_FALLBACK_STATE_STORE = None

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_run_research_session(target, objective, *, loop_config, **kwargs):
        gateway.BUS.emit(
            loop_config.session_id,
            "final",
            answer="smoke-ok",
            mode=loop_config.response_depth,
            target=target,
        )
        gateway.BUS.close(loop_config.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_research_session", fake_run_research_session)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={"message": "Who owns Adani Enterprises?", "mode": "standard", "max_wall_seconds": 30},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        session_id = response.json()["session_id"]
        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

        result = await client.get(f"/sessions/{session_id}/result", headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["memo"] == "smoke-ok"

    gateway._TASKS.clear()
