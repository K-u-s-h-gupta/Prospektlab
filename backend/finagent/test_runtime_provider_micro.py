"""Tests for the micro model-routing tier."""

from __future__ import annotations

import importlib

import finagent.runtime_provider as rp


def _clear(monkeypatch):
    for k in (
        "AZURE_AI_FOUNDRY_API_KEY", "AZURE_AI_PROJECTS_API_KEY", "AZURE_OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "XAI_API_KEY",
        "FINAGENT_OPENAI_MODEL", "FINAGENT_SYNTH_MODEL",
        "FINAGENT_OPENAI_MODEL_SIMPLE", "FINAGENT_OPENAI_MODEL_MINI",
        "FINAGENT_OPENAI_MODEL_MICRO", "FINAGENT_OPENAI_MODEL_NANO",
    ):
        monkeypatch.delenv(k, raising=False)


def test_micro_uses_micro_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FINAGENT_OPENAI_MODEL_MICRO", "gpt-5.4-nano")
    monkeypatch.setenv("FINAGENT_OPENAI_MODEL", "gpt-5.4")
    cfg = rp.resolve_openai_config("micro")
    assert cfg is not None
    assert cfg.model == "gpt-5.4-nano"


def test_micro_falls_back_to_mini(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FINAGENT_OPENAI_MODEL_MINI", "gpt-5.4-mini")
    cfg = rp.resolve_openai_config("micro")
    assert cfg.model == "gpt-5.4-mini"


def test_complex_unaffected_by_micro_env(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FINAGENT_OPENAI_MODEL_MICRO", "gpt-5.4-nano")
    monkeypatch.setenv("FINAGENT_OPENAI_MODEL", "gpt-5.4")
    cfg = rp.resolve_openai_config("complex")
    assert cfg.model == "gpt-5.4"  # analysis tier never downgraded to micro


def test_micro_xai_fallback(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    monkeypatch.setenv("FINAGENT_XAI_MODEL_SIMPLE", "grok-3-mini")
    cfg = rp.resolve_openai_config("micro")
    assert cfg is not None
    assert cfg.model == "grok-3-mini"


def test_openai_base_url_is_used_with_api_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "compatible-test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.services.ai.azure.com/openai/v1/responses")
    cfg = rp.resolve_openai_config("moderate")
    assert cfg is not None
    assert cfg.api_key == "compatible-test-key"
    assert cfg.base_url == "https://example.services.ai.azure.com/openai/v1"
