from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from finagent.runtime_provider import is_provider_unavailable_error

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from publish_pipeline import chat_with_fallback  # noqa: E402


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, *, content: str = "", exc: Exception | None = None) -> None:
        self.content = content
        self.exc = exc
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return _FakeResponse(self.content)


class _FakeClient:
    def __init__(self, *, content: str = "", exc: Exception | None = None) -> None:
        completions = _FakeCompletions(content=content, exc=exc)
        self.chat = type("Chat", (), {"completions": completions})()


def test_provider_unavailable_detector_matches_azure_deployment_404() -> None:
    exc = Exception("404 Not Found: The API deployment for this resource does not exist.")

    assert is_provider_unavailable_error(exc)


def test_chat_with_fallback_uses_secondary_provider_when_primary_deployment_is_missing() -> None:
    primary = _FakeClient(exc=Exception("404 Not Found: The API deployment for this resource does not exist."))
    fallback = _FakeClient(content='{"status":"ok"}')

    result = asyncio.run(
        chat_with_fallback(
            primary,  # type: ignore[arg-type]
            "missing-azure-deployment",
            fallback,  # type: ignore[arg-type]
            "gpt-4o-mini",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.1,
            max_tokens=50,
            timeout=5,
            response_format={"type": "json_object"},
        )
    )

    assert result == '{"status":"ok"}'
    assert primary.chat.completions.calls[0]["model"] == "missing-azure-deployment"
    assert fallback.chat.completions.calls[0]["model"] == "gpt-4o-mini"
