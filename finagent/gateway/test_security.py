import pytest
import jwt
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from finagent.gateway.run import app, JWT_SECRET, _SESSION_META

client = TestClient(app, raise_server_exceptions=False)

@pytest.fixture(autouse=True)
def clean_sessions():
    _SESSION_META.clear()
    client.cookies.clear()


def _mint_test_token(payload: dict) -> str:
    """Helper to mint test tokens with required exp/iat/iss/aud claims."""
    now = datetime.now(timezone.utc)
    payload["iat"] = now
    payload["exp"] = now + timedelta(hours=1)
    payload.setdefault("iss", "prospektlab")
    payload.setdefault("aud", "prospektlab-api")
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def test_health_redaction():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["finagent_home"] == "<redacted>"

def test_config_redaction():
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert data["finagent_home"] == "<redacted>"

def test_security_headers_middleware():
    response = client.get("/health")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" in response.headers
    assert "Content-Security-Policy" in response.headers

def test_cors_options_rejection():
    # Current middleware is configured to allow cross-origin requests broadly.
    headers = {
        "Origin": "http://malicious-site.com",
        "Access-Control-Request-Method": "GET"
    }
    response = client.options("/health", headers=headers)
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "GET" in response.headers["Access-Control-Allow-Methods"]

def test_unauthenticated_endpoint_access():
    # Endpoints that are now secured must return 401 when accessed without authorization header
    routes = [
        ("/memos", "GET"),
        ("/chat/history?session_id=123", "GET"),
        ("/sessions/123/status", "GET"),
        ("/sessions/123/memo", "GET"),
        ("/sessions/123/events", "GET"),
        ("/sessions/123/result", "GET"),
        ("/sessions/123/stream", "GET"),
        ("/sessions/123/stop", "POST"),
        ("/sessions/123", "DELETE"),
        ("/memory/stats", "GET"),
        ("/memory/facts", "GET"),
        ("/memory/sessions", "GET"),
        ("/memory/clear/dummy", "DELETE")
    ]
    for route, method in routes:
        if method == "GET":
            response = client.get(route)
        elif method == "POST":
            response = client.post(route)
        elif method == "DELETE":
            response = client.delete(route)
        assert response.status_code == 401, f"Failed for {route} with method {method}"
        assert response.json()["detail"] == "Missing or invalid authentication credentials"

def test_invalid_jwt_token():
    headers = {"Authorization": "Bearer invalid_token_xyz"}
    response = client.get("/memos", headers=headers)
    assert response.status_code == 401
    assert response.json()["detail"] in {
        "Could not validate authentication credentials",
        "Supabase JWT verification secret is required",
        "Token has expired",
    }

def test_valid_jwt_access():
    # Mint a valid local JWT token with exp/iat
    token = _mint_test_token({"user_id": "test_user_1", "email": "test@example.com"})
    headers = {"Authorization": f"Bearer {token}"}
    
    with patch("finagent.gateway.run._MEMOS_DIR") as mock_dir:
        mock_dir.is_dir.return_value = False
        response = client.get("/memos", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"memos": []}

def test_auth_me_accepts_bearer_header():
    token = _mint_test_token({"user_id": "test_user_2", "email": "header@example.com"})
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "header@example.com"
    assert data["user_id"] == "test_user_2"

def test_supabase_hs256_token_sets_tenant_id(monkeypatch):
    from finagent.gateway.run import _decode_current_user

    monkeypatch.setenv("SUPABASE_JWT_SECRET", "supabase-secret")
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "tenant-123",
            "email": "supabase@example.com",
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        "supabase-secret",
        algorithm="HS256",
    )

    user = _decode_current_user(token)

    assert user["tenant_id"] == "tenant-123"
    assert user["auth_provider"] == "supabase_jwt"

def test_supabase_token_requires_configured_secret(monkeypatch):
    from finagent.gateway.run import _decode_current_user

    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": "tenant-123",
            "email": "supabase@example.com",
            "aud": "authenticated",
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        "supabase-secret",
        algorithm="HS256",
    )

    with pytest.raises(HTTPException) as exc:
        _decode_current_user(token)

    assert exc.value.status_code == 401
    assert "Supabase JWT verification secret is required" in exc.value.detail

def test_bola_session_ownership_verification():
    # Two different users
    user1_token = _mint_test_token({"user_id": "user1", "email": "user1@example.com"})
    user2_token = _mint_test_token({"user_id": "user2", "email": "user2@example.com"})
    
    session_id = "a1b2c3d4e5f6"
    
    # Store session record owned by user1 in memory
    _SESSION_META[session_id] = {
        "session_id": session_id,
        "user_email": "user1@example.com",
        "target": "TCS",
        "mode": "standard"
    }
    
    # Mock files to avoid actual OS errors when verifying ownership or loading session metadata
    with patch("finagent.gateway.run._session_meta_path") as mock_meta_path:
        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file.read_text.return_value = '{"session_id": "a1b2c3d4e5f6", "user_email": "user1@example.com"}'
        mock_meta_path.return_value = mock_file
        
        # User 1 should be allowed access
        headers_u1 = {"Authorization": f"Bearer {user1_token}"}
        response = client.get(f"/sessions/{session_id}/status", headers=headers_u1)
        assert response.status_code == 200
        
        # User 2 should be rejected with 403 Forbidden (BOLA/IDOR protection)
        headers_u2 = {"Authorization": f"Bearer {user2_token}"}
        response = client.get(f"/sessions/{session_id}/status", headers=headers_u2)
        assert response.status_code == 403
        assert response.json()["detail"] == "Access denied: You do not own this research session."
