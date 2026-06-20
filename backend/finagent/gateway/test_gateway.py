import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import HTTPException
from finagent.gateway.email_delivery import EmailDeliveryOutcome
from finagent.gateway.run import app, auth_rate_limiter, research_rate_limiter, default_rate_limiter, _mint_token

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


@patch("finagent.gateway.run.supabase.store_outreach_unsubscribe", new_callable=AsyncMock)
def test_outreach_unsubscribe_endpoint(mock_store_unsubscribe):
    mock_store_unsubscribe.return_value = {
        "email": "optout@example.com",
        "reason": "unsubscribe",
    }

    response = client.post(
        "/api/outreach/unsubscribe",
        json={"email": "optout@example.com", "reason": "unsubscribe", "source": "public_page"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["email"] == "optout@example.com"
    assert data["reason"] == "unsubscribe"
    mock_store_unsubscribe.assert_awaited_once()


@patch("finagent.gateway.run.supabase.store_outreach_event", new_callable=AsyncMock)
def test_outreach_event_ingest_endpoint(mock_store_event):
    token = _mint_token("user-1", "owner@example.com", "Owner User")
    mock_store_event.return_value = {
        "owner_email": "owner@example.com",
        "event_type": "opened",
    }

    response = client.post(
        "/api/outreach/events/ingest",
        json={
            "owner_email": "owner@example.com",
            "event_type": "opened",
            "provider": "azure_communication_services",
            "message_id": 42,
            "provider_message_id": "abc123",
            "source": "provider_webhook",
            "note": "test",
            "event_payload": {"delivered_at": "2026-06-10T00:00:00Z"},
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["event"]["event_type"] == "opened"
    mock_store_event.assert_awaited_once()


@patch("finagent.gateway.run.supabase.list_outreach_events", new_callable=AsyncMock)
def test_list_outreach_events_endpoint(mock_list_events):
    token = _mint_token("user-1", "owner@example.com", "Owner User")
    mock_list_events.return_value = [
        {
            "owner_email": "owner@example.com",
            "message_id": 42,
            "event_type": "opened",
            "provider": "azure_communication_services",
            "event_payload": {},
            "occurred_at": 1,
            "created_at": 1,
        },
        {
            "owner_email": "someoneelse@example.com",
            "message_id": 99,
            "event_type": "clicked",
            "provider": "azure_communication_services",
            "event_payload": {},
            "occurred_at": 2,
            "created_at": 2,
        },
    ]

    response = client.get(
        "/api/outreach/events",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["event_type"] == "opened"
    mock_list_events.assert_awaited_once()


@patch("finagent.gateway.run._load_outreach_template_text")
def test_get_outreach_template_endpoint(mock_load_template):
    token = _mint_token("user-1", "owner@example.com", "Owner User")
    mock_load_template.return_value = {
        "path": "C:/tmp/outreach.md",
        "subject": "Would love your feedback on ProspektLab",
        "body": "Hi there",
        "template_text": "Subject: Would love your feedback on ProspektLab\n\nHi there",
        "line_count": 2,
        "updated_at": "2026-06-10T00:00:00+00:00",
    }

    response = client.get(
        "/api/ops/outreach/template",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["subject"] == "Would love your feedback on ProspektLab"
    mock_load_template.assert_called_once()


@patch("finagent.gateway.run._save_outreach_template_text")
def test_update_outreach_template_endpoint(mock_save_template):
    token = _mint_token("user-1", "owner@example.com", "Owner User")
    mock_save_template.return_value = {
        "path": "C:/tmp/outreach.md",
        "subject": "New Subject",
        "body": "Hi there",
        "template_text": "Subject: New Subject\n\nHi there",
        "line_count": 2,
        "updated_at": "2026-06-10T00:00:00+00:00",
    }

    response = client.put(
        "/api/ops/outreach/template",
        json={"template_text": "Subject: New Subject\n\nHi there"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["template"]["subject"] == "New Subject"
    mock_save_template.assert_called_once()


def test_outreach_unsubscribe_endpoint_rejects_invalid_email():
    response = client.post(
        "/api/outreach/unsubscribe",
        json={"email": "not-an-email", "reason": "unsubscribe", "source": "public_page"},
    )

    assert response.status_code == 422


@patch("finagent.gateway.run.generate_article_automation", new_callable=AsyncMock)
def test_generate_content_article_endpoint(mock_generate):
    token = _mint_token("user-1", "content@example.com", "Content User")
    mock_generate.return_value.model_dump.return_value = {
        "slug": "automated-insight",
        "title": "Automated Insight",
        "description": "Automated article description for SEO publishing.",
        "route_base": "insights",
        "public_url": "https://prospektlab.com/insights/automated-insight/",
        "html_path": "C:/tmp/article/index.html",
        "json_path": "C:/tmp/article/article.json",
        "image_path": "C:/tmp/article/cover.svg",
        "mirrored_public_path": "C:/tmp/public/insights/automated-insight",
        "mirrored_sitemap": "C:/tmp/public/sitemap.xml",
        "generated_at": "2026-06-06T00:00:00+00:00",
        "sources_used": [],
    }

    response = client.post(
        "/api/content/articles/generate",
        json={"topic": "Automated Insight Topic"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["slug"] == "automated-insight"
    assert data["route_base"] == "insights"
    mock_generate.assert_awaited_once()


@patch("finagent.gateway.run.generate_article_batch", new_callable=AsyncMock)
def test_generate_content_article_batch_endpoint(mock_generate_batch):
    token = _mint_token("user-1", "content@example.com", "Content User")
    mock_generate_batch.return_value.model_dump.return_value = {
        "route_base": "insights",
        "generated_at": "2026-06-06T00:00:00+00:00",
        "total_requested": 2,
        "total_completed": 2,
        "total_failed": 0,
        "items": [],
        "failures": [],
    }

    response = client.post(
        "/api/content/articles/generate-batch",
        json={"topics": [{"topic": "First automated topic"}, {"topic": "Second automated topic"}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_requested"] == 2
    assert data["total_completed"] == 2
    mock_generate_batch.assert_awaited_once()


@patch("finagent.gateway.run.ingest_market_event_triggers", new_callable=AsyncMock)
def test_ingest_content_events_endpoint(mock_ingest):
    token = _mint_token("user-1", "content@example.com", "Content User")
    mock_ingest.return_value.model_dump.return_value = {
        "route_base": "insights",
        "generated_at": "2026-06-06T00:00:00+00:00",
        "discovered_events": 3,
        "generated_articles": 2,
        "auto_published": 1,
        "drafts": 1,
        "skipped_seen": 1,
        "failures": [],
        "items": [],
    }

    response = client.post(
        "/api/content/events/ingest",
        json={"watches": [{"source": "sebi", "company_name": "SEBI"}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["discovered_events"] == 3
    assert data["generated_articles"] == 2
    mock_ingest.assert_awaited_once()


@patch("finagent.gateway.run.list_generated_articles")
def test_list_content_articles_endpoint(mock_list_articles):
    token = _mint_token("user-1", "content@example.com", "Content User")
    mock_list_articles.return_value = [
        {
            "slug": "automated-insight",
            "title": "Automated Insight",
            "route_base": "insights",
            "public_url": "https://prospektlab.com/insights/automated-insight/",
            "generated_at": "2026-06-06T00:00:00+00:00",
        }
    ]

    response = client.get(
        "/api/content/articles?route_base=insights&limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["items"][0]["slug"] == "automated-insight"


@patch("finagent.gateway.run.load_generated_article_html")
@patch("finagent.gateway.run.is_generated_article_published")
def test_public_generated_insight_route(mock_is_published, mock_load_html):
    mock_is_published.return_value = True
    mock_load_html.return_value = "<html><body><h1>Automated Insight</h1></body></html>"
    response = client.get("/insights/automated-insight")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Automated Insight" in response.text


@patch("finagent.gateway.run.is_generated_article_published")
def test_public_generated_insight_route_hides_draft(mock_is_published):
    mock_is_published.return_value = False
    response = client.get("/insights/draft-insight")
    assert response.status_code == 404

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


@patch("finagent.gateway.run._send_sms_code")
@patch("finagent.gateway.supabase_client.store_verification_code", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.get_user_by_email", new_callable=AsyncMock)
def test_auth_send_verification_sms_success(mock_get_user, mock_store_code, mock_send_sms):
    mock_get_user.return_value = None
    mock_store_code.return_value = True
    mock_send_sms.return_value = EmailDeliveryOutcome(delivered=True, provider="sms", detail="message-123")

    response = client.post("/auth/send-verification", json={
        "email": "user@example.com",
        "mobile": "9876543210",
        "channel": "sms",
    })

    assert response.status_code == 200
    assert response.json()["message"] == "Verification code sent by SMS successfully."
    mock_store_code.assert_awaited_once()
    args = mock_store_code.await_args.args
    assert args[0] == "+919876543210"
    assert mock_store_code.await_args.kwargs["type_"] == "signup"
    mock_send_sms.assert_called_once()
    assert mock_send_sms.call_args.args[0] == "+919876543210"


@patch("finagent.gateway.supabase_client.get_user_by_email", new_callable=AsyncMock)
def test_auth_send_verification_sms_requires_mobile(mock_get_user):
    mock_get_user.return_value = None

    response = client.post("/auth/send-verification", json={
        "email": "user@example.com",
        "channel": "sms",
    })

    assert response.status_code == 400
    assert response.json()["detail"] == "Mobile number is required for SMS verification."


@patch("finagent.gateway.run._send_sms_code")
@patch("finagent.gateway.supabase_client.store_verification_code", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.get_user_by_email", new_callable=AsyncMock)
def test_auth_forgot_password_sms_success(mock_get_user, mock_store_code, mock_send_sms):
    mock_get_user.return_value = {
        "id": "user-1",
        "email": "user@example.com",
        "mobile": "+919876543210",
    }
    mock_store_code.return_value = True
    mock_send_sms.return_value = EmailDeliveryOutcome(delivered=True, provider="sms", detail="message-456")

    response = client.post("/auth/forgot-password", json={
        "email": "user@example.com",
        "channel": "sms",
    })

    assert response.status_code == 200
    assert response.json()["message"] == "Reset code sent by SMS."
    args = mock_store_code.await_args.args
    assert args[0] == "+919876543210"
    assert mock_store_code.await_args.kwargs["type_"] == "reset"
    mock_send_sms.assert_called_once()
    assert mock_send_sms.call_args.args[0] == "+919876543210"
    assert mock_send_sms.call_args.kwargs["is_reset"] is True


@patch("finagent.gateway.supabase_client.update_admin_user_password", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.verify_and_consume_code", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.get_user_by_email", new_callable=AsyncMock)
def test_auth_reset_password_accepts_sms_code(mock_get_user, mock_verify_code, mock_update_password):
    mock_get_user.return_value = {
        "id": "user-1",
        "email": "user@example.com",
        "mobile": "+919876543210",
    }
    mock_verify_code.side_effect = [False, True]
    mock_update_password.return_value = {}

    response = client.post("/auth/reset-password", json={
        "email": "user@example.com",
        "code": "123456",
        "new_password": "ValidPass1!",
    })

    assert response.status_code == 200
    assert response.json()["message"] == "Password reset successfully."
    assert mock_verify_code.await_count == 2
    first_call = mock_verify_code.await_args_list[0].args
    second_call = mock_verify_code.await_args_list[1].args
    assert first_call[0] == "user@example.com"
    assert second_call[0] == "+919876543210"
    mock_update_password.assert_awaited_once_with("user-1", "ValidPass1!")


@patch("finagent.gateway.supabase_client.upsert_profile", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.create_admin_user", new_callable=AsyncMock)
@patch("finagent.gateway.supabase_client.verify_and_consume_code", new_callable=AsyncMock)
def test_auth_signup_accepts_sms_verification(mock_verify_code, mock_create_user, mock_upsert_profile):
    mock_verify_code.side_effect = [False, True]
    mock_create_user.return_value = {"id": "user-1"}
    mock_upsert_profile.return_value = {
        "id": "user-1",
        "email": "user@example.com",
        "full_name": "Test User",
        "mobile": "+919876543210",
    }

    response = client.post("/auth/signup", json={
        "name": "Test User",
        "email": "user@example.com",
        "password": "ValidPass1!",
        "mobile": "9876543210",
        "verification_code": "123456",
    })

    assert response.status_code == 200
    body = response.json()
    assert "token" in body
    assert body["user"]["email"] == "user@example.com"
    assert mock_verify_code.await_count == 2
    assert mock_verify_code.await_args_list[0].args[0] == "user@example.com"
    assert mock_verify_code.await_args_list[1].args[0] == "+919876543210"
    mock_create_user.assert_awaited_once_with(
        "user@example.com",
        "ValidPass1!",
        "Test User",
        mobile="+919876543210",
        auth_provider="email",
        referral_source="organic",
        email_confirm=True,
    )

