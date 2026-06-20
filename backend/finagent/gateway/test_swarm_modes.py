from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from finagent.output.contracts import AnswerArtifact, AnswerCitation, ResponseSection



def _local_token(secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "user_id": str(uuid.uuid4()),
            "email": "swarm-mode-smoke@example.com",
            "name": "Swarm Mode Smoke",
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
async def test_standard_mode_uses_swarm_v2_by_default(monkeypatch):
    import finagent.gateway.run as gateway

    gateway._TASKS.clear()
    calls: list[dict] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_standard_v2(target, objective, *, cfg):
        calls.append({"target": target, "objective": objective, "cfg": cfg})
        gateway.BUS.emit(cfg.session_id, "final", answer="swarm-v2-ok", mode="standard", target=target)
        gateway.BUS.close(cfg.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_standard_v2_research_session", fake_standard_v2)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "What is the latest on TCS Q4 results?",
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

    assert len(calls) == 1
    assert "TCS" in calls[0]["target"]
    assert calls[0]["cfg"].session_id
    assert calls[0]["cfg"].user_email == "swarm-mode-smoke@example.com"
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_deep_mode_uses_swarm_deep_by_default(monkeypatch):
    import finagent.gateway.run as gateway

    gateway._TASKS.clear()
    calls: list[dict] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_deep_swarm(target, objective, *, cfg):
        calls.append({"target": target, "objective": objective, "cfg": cfg})
        gateway.BUS.emit(cfg.session_id, "final", answer="swarm-deep-ok", mode="deep", target=target)
        gateway.BUS.close(cfg.session_id)

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_deep_swarm_research_session", fake_deep_swarm)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "Build a deep research report on TCS",
                "mode": "deep",
                "max_wall_seconds": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

    assert len(calls) == 1
    assert "TCS" in calls[0]["target"]
    assert calls[0]["cfg"].session_id
    assert calls[0]["cfg"].max_swarm_tasks == 300
    assert calls[0]["cfg"].max_swarm_concurrency == 20
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_canvas_endpoint_roundtrip(monkeypatch):
    import finagent.gateway.run as gateway

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create a canvas directly via the store
        from finagent.canvas.models import InteractiveResearchCanvas
        from finagent.canvas.store import CanvasStore

        canvas = InteractiveResearchCanvas(session_id="c" + uuid.uuid4().hex[:11], query="Analyze TCS", target="TCS.NS")
        canvas.add_section("Financials")
        CanvasStore().save(canvas)
        session_id = canvas.session_id

        # Seed ownership metadata so the authed user can access the session
        token_user = gateway._decode_current_user(headers["Authorization"].split(" ", 1)[1])
        gateway._SESSION_META[session_id] = {
            "session_id": session_id,
            "tenant_id": token_user.get("tenant_id", ""),
            "user_email": token_user.get("email", ""),
        }

        get_resp = await client.get(f"/sessions/{session_id}/canvas", headers=headers)
        assert get_resp.status_code == 200, get_resp.text
        data = get_resp.json()
        assert data["session_id"] == session_id
        assert data["target"] == "TCS.NS"

        steer_resp = await client.post(
            f"/sessions/{session_id}/canvas/steer",
            json={"command": "dig deeper into governance", "text": "Check promoter pledge", "peer": ""},
            headers=headers,
        )
        assert steer_resp.status_code == 200, steer_resp.text
        steer_data = steer_resp.json()
        assert steer_data["new_tasks"]
        assert any("governance" in t["agent_id"] for t in steer_data["new_tasks"])


@pytest.mark.anyio
async def test_pptx_export_endpoint(monkeypatch):
    import finagent.gateway.run as gateway

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Seed a session artifact so export can proceed
        session_id = "e" + uuid.uuid4().hex[:11]
        artifact = AnswerArtifact(
            mode="deep",
            depth="deep",
            title="TCS Deep Research",
            summary="Quick take.",
            sections=[ResponseSection(title="Financials", body="Revenue grew 12%.")],
            citations=[AnswerCitation(title="NSE", url="https://nseindia.com", kind="NSE")],
        )
        gateway._SESSION_ARTIFACTS[session_id] = artifact
        token_user = gateway._decode_current_user(headers["Authorization"].split(" ", 1)[1])
        gateway._SESSION_META[session_id] = {
            "session_id": session_id,
            "mode": "deep",
            "target": "TCS",
            "user_email": token_user.get("email", ""),
            "tenant_id": token_user.get("tenant_id", ""),
        }

        response = await client.post(
            "/research/export",
            json={"session_id": session_id, "format": "pptx", "style": "sell_side"},
            headers=headers,
        )
        assert response.status_code == 202, response.text
        data = response.json()
        job_id = data["job_id"]
        assert data["status"] == "queued"

        for _ in range(30):
            status_resp = await client.get(f"/research/export/{job_id}", headers=headers)
            status_data = status_resp.json()
            if status_data["status"] == "done":
                break
            await asyncio.sleep(0.2)
        assert status_data["status"] == "done"

        download_resp = await client.get(f"/research/export/{job_id}/download", headers=headers)
        assert download_resp.status_code == 200
        assert download_resp.headers["content-type"] == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        assert len(download_resp.content) > 0


@pytest.mark.anyio
async def test_deep_mode_auto_exports_when_prompt_asks_for_document(monkeypatch):
    import finagent.gateway.run as gateway

    monkeypatch.setenv("FINAGENT_USE_SWARM_DEEP", "1")
    gateway._TASKS.clear()
    doc_calls: list[dict] = []

    async def fake_weekly_usage(email: str) -> int:
        return 0

    async def fake_deep_swarm(target, objective, *, cfg):
        gateway.BUS.emit(cfg.session_id, "final", answer="swarm-deep-ok", mode="deep", target=target)
        gateway.BUS.close(cfg.session_id)

    async def fake_generate_all(self, artifact):
        doc_calls.append({"session_id": self.session_id, "artifact_title": artifact.title})
        return {
            "pdf": {"ok": True, "path": "/tmp/x.pdf", "error": None},
            "docx": {"ok": True, "path": "/tmp/x.docx", "error": None},
            "xlsx": {"ok": True, "path": "/tmp/x.xlsx", "error": None},
            "pptx": {"ok": True, "path": "/tmp/x.pptx", "error": None},
        }

    monkeypatch.setattr(gateway, "get_weekly_token_usage", fake_weekly_usage)
    monkeypatch.setattr(gateway, "run_deep_swarm_research_session", fake_deep_swarm)
    monkeypatch.setattr("finagent.swarm.document_agent.DocumentAgent.generate_all", fake_generate_all)

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/chat/research",
            json={
                "message": "Build a deep research report on TCS and download it as a PDF",
                "mode": "deep",
                "max_wall_seconds": 30,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        for _ in range(20):
            if not gateway._TASKS:
                break
            await asyncio.sleep(0.1)

    assert len(doc_calls) == 1
    assert doc_calls[0]["session_id"]
    gateway._TASKS.clear()


@pytest.mark.anyio
async def test_export_all_endpoint_generates_package(monkeypatch):
    import finagent.gateway.run as gateway

    headers = {"Authorization": f"Bearer {_local_token(gateway.JWT_SECRET)}"}
    transport = ASGITransport(app=gateway.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = "f" + uuid.uuid4().hex[:11]
        artifact = AnswerArtifact(
            mode="deep",
            depth="deep",
            title="TCS Deep Research",
            summary="Quick take.",
            sections=[ResponseSection(title="Financials", body="Revenue grew 12%.")],
            citations=[AnswerCitation(title="NSE", url="https://nseindia.com", kind="NSE")],
        )
        gateway._SESSION_ARTIFACTS[session_id] = artifact
        token_user = gateway._decode_current_user(headers["Authorization"].split(" ", 1)[1])
        gateway._SESSION_META[session_id] = {
            "session_id": session_id,
            "mode": "deep",
            "target": "TCS",
            "user_email": token_user.get("email", ""),
            "tenant_id": token_user.get("tenant_id", ""),
        }

        response = await client.post(
            "/research/export-all",
            json={"session_id": session_id, "style": "sell_side"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["session_id"] == session_id
        assert "results" in data
        assert data["results"]["pptx"]["ok"] is True
        assert data["results"]["pptx"]["path"]
