import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from finagent.gateway.run import app, auth_rate_limiter, research_rate_limiter, default_rate_limiter

client = TestClient(app, raise_server_exceptions=False)

@pytest.fixture(autouse=True)
def reset_rate_limiters():
    # Reset rate limit histories before each test
    auth_rate_limiter.history = {}
    research_rate_limiter.history = {}
    default_rate_limiter.history = {}
    client.cookies.clear()
    # Also clear in-memory rate limits used by the new backend
    try:
        import finagent.storage.supabase_store as _ss
        _ss._is_supabase_configured = lambda: False
        _ss._portfolio_store = None
        _ss._memory_store = None
        _ss._state_store = None
        _ss._token_usage_store = None
    except Exception:
        pass

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_capabilities_endpoint():
    response = client.get("/capabilities")
    assert response.status_code == 200
    assert "capabilities" in response.json()
    assert response.json()["agent"] == "FinAgent"

def test_config_endpoint():
    response = client.get("/config")
    assert response.status_code == 200
    assert "finagent_home" in response.json()


def test_app_requires_auth_redirect():
    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/login"

def test_pydantic_validation_handler():
    # Send signup request with invalid email to trigger Pydantic validation error
    payload = {
        "name": "Test User",
        "email": "invalid-email-format",
        "password": "short", # also triggers min_length validation since password must be at least 8 chars
        "mobile": "12345",
        "verification_code": "123456"
    }
    response = client.post("/auth/signup", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["detail"] == "Input validation failed"
    assert "errors" in data
    assert len(data["errors"]) > 0

@patch("finagent.gateway.supabase_client.authenticate_user", new_callable=AsyncMock)
def test_auth_login_success(mock_auth):
    mock_auth.return_value = {
        "access_token": "mock-jwt-token",
        "user": {
            "id": "john-doe-id",
            "user_metadata": {
                "full_name": "John Doe",
                "name": "John Doe"
            }
        }
    }
    
    payload = {
        "email": "john.doe@example.com",
        "password": "validpassword123"
    }
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "token" in data
    # The token should be a JWT token, decode it to verify
    import jwt
    from finagent.gateway.run import JWT_SECRET
    decoded = jwt.decode(data["token"], JWT_SECRET, algorithms=["HS256"], audience="prospektlab-api")
    assert decoded["email"] == "john.doe@example.com"
    assert decoded["user_id"] == "john-doe-id"
    assert data["user"]["name"] == "John Doe"
    assert data["user"]["email"] == "john.doe@example.com"
    assert "prospektlab_auth=" in response.headers.get("set-cookie", "")


@patch("finagent.gateway.supabase_client.authenticate_user", new_callable=AsyncMock)
def test_app_ignores_token_query_without_cookie(mock_auth):
    mock_auth.return_value = {
        "access_token": "mock-jwt-token",
        "user": {
            "id": "john-doe-id",
            "user_metadata": {
                "full_name": "John Doe",
                "name": "John Doe"
            }
        }
    }
    login_response = client.post("/auth/login", json={
        "email": "john.doe@example.com",
        "password": "validpassword123"
    })
    token = login_response.json()["token"]
    client.cookies.clear()
    bootstrap_response = client.get(f"/app?token={token}", follow_redirects=False)
    assert bootstrap_response.status_code == 302
    assert bootstrap_response.headers["location"] == "/login"
    assert "prospektlab_auth=" not in bootstrap_response.headers.get("set-cookie", "")

@patch("finagent.gateway.supabase_client.authenticate_user", new_callable=AsyncMock)
def test_auth_login_invalid_credentials(mock_auth):
    # Simulate Supabase returning a 401 for wrong credentials
    mock_auth.side_effect = HTTPException(status_code=401, detail="Invalid email or password.")
    
    payload = {
        "email": "john.doe@example.com",
        "password": "wrongpassword123"
    }
    response = client.post("/auth/login", json=payload)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."

def test_rate_limiting_trigger():
    # auth_rate_limiter is configured to allow 10 requests per minute
    # Let's perform 11 requests to trigger rate limit on /auth/login
    payload = {
        "email": "rate.limit@example.com",
        "password": "somepassword123"
    }
    
    # We patch authenticate_user to just return a dummy dictionary so we don't hit Supabase
    with patch("finagent.gateway.supabase_client.authenticate_user", new_callable=AsyncMock) as mock_auth:
        mock_auth.return_value = {
            "access_token": "token",
            "user": {"user_metadata": {"name": "User"}}
        }
        
        for i in range(10):
            response = client.post("/auth/login", json=payload)
            assert response.status_code == 200
            
        # The 11th request should be rate-limited (HTTP 429)
        response = client.post("/auth/login", json=payload)
        assert response.status_code == 429
        assert response.json()["detail"] == "Too many requests. Please try again later."

@patch("finagent.gateway.supabase_client.get_user_by_email", new_callable=AsyncMock)
def test_global_exception_handler(mock_get_user):
    # Mocking get_user_by_email to throw an unexpected Exception (not an HTTPException)
    # This should be caught by our global exception handler middleware and return 500
    mock_get_user.side_effect = ValueError("Unexpected database crash!")
    
    payload = {
        "email": "john.doe@example.com"
    }
    response = client.post("/auth/send-verification", json=payload)
    assert response.status_code == 500
    data = response.json()
    assert data["detail"] == "An internal server error occurred."
    assert data["error_type"] == "ValueError"

@patch("httpx.get")
def test_get_user_id_from_auth_via_api(mock_get):
    from finagent.gateway.supabase_client import get_user_id_from_auth
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "users": [
            {"email": "test@example.com", "id": "uuid-1234"}
        ]
    }
    mock_get.return_value = mock_resp
    
    user_id = get_user_id_from_auth("test@example.com")
    assert user_id == "uuid-1234"
    mock_get.assert_called_once()

