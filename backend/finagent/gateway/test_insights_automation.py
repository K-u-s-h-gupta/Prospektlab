from unittest.mock import patch

from fastapi.testclient import TestClient

from finagent.gateway.run import _mint_token, app

client = TestClient(app, raise_server_exceptions=False)


def test_content_automation_status_route():
    token = _mint_token("user-1", "content@example.com", "Content User")
    with patch("finagent.gateway.run.get_monitor_status") as mock_status:
        mock_status.return_value = {
            "status": "ok",
            "last_started_at": "2026-06-08T00:00:00+00:00",
            "last_completed_at": "2026-06-08T00:05:00+00:00",
            "last_error": "",
            "last_summary": {"generated": 2},
            "source_health": {},
            "recent_items": [],
            "cursor": 10,
            "updated_at": "2026-06-08T00:05:00+00:00",
        }

        response = client.get(
            "/api/content/automation/status",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["last_summary"]["generated"] == 2


def test_publish_route_blocks_unapproved_editorial_draft():
    token = _mint_token("user-1", "content@example.com", "Content User")
    with patch("finagent.gateway.run.load_generated_article") as mock_load:
        mock_load.return_value = {
            "slug": "draft-article",
            "editorial_review": {"ready_to_publish": False},
        }
        response = client.post(
            "/api/content/articles/draft-article/publish?route_base=insights",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 409
    assert "Editorial review" in response.json()["detail"]


def test_content_automation_status_allows_guests():
    """Content automation endpoints should not require login/signup."""
    with patch("finagent.gateway.run.get_monitor_status") as mock_status:
        mock_status.return_value = {"status": "ok"}
        response = client.get("/api/content/automation/status")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
