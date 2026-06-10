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
