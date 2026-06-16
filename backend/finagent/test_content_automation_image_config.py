from __future__ import annotations

from finagent.content_automation import (
    _normalize_foundry_resource_endpoint,
    _normalize_image_base_url,
    _resolve_image_client_config,
)


def test_normalize_image_base_url_appends_openai_suffix() -> None:
    raw = "https://api.openai.example/v1/"
    assert _normalize_image_base_url(raw) == "https://api.openai.example/v1"


def test_normalize_foundry_resource_endpoint_strips_project_path() -> None:
    raw = "https://prospektlabv3-resource.services.ai.azure.com/api/projects/prospektlabv3/"
    assert _normalize_foundry_resource_endpoint(raw) == "https://prospektlabv3-resource.services.ai.azure.com"


def test_resolve_image_client_config_prefers_foundry_when_configured(monkeypatch) -> None:
    """Default-path contract: when Azure Foundry credentials AND a project
    endpoint are configured, prefer Foundry for chatgpt-image-2 — this matches
    the deployed-customer setup where the Azure path is the canonical route."""
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_IMAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECTS_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://prospektlabv3-resource.services.ai.azure.com/api/projects/prospektlabv3",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT", "gpt-image-1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "gpt-image-1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "azure-foundry"
    assert config.model == "chatgpt-image-2"


def test_resolve_image_client_config_falls_back_to_openai_when_foundry_absent(monkeypatch) -> None:
    """When no Azure Foundry credentials are configured, fall back to OpenAI."""
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECTS_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_IMAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECTS_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "gpt-image-1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "openai"
    assert config.model == "chatgpt-image-2"
    assert config.base_url is None


def test_resolve_image_client_config_uses_explicit_openai_base_url(monkeypatch) -> None:
    monkeypatch.delenv("AZURE_AI_FOUNDRY_IMAGE_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL", "https://prospektlabv3-resource.openai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT", "gpt-image-1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "azure-foundry"
    assert config.model == "chatgpt-image-2"
    assert config.base_url == "https://prospektlabv3-resource.openai.azure.com/openai/v1"
    assert config.request_url == (
        "https://prospektlabv3-resource.openai.azure.com/openai/deployments/chatgpt-image-2/images/generations"
        "?api-version=2025-04-01-preview"
    )


def test_resolve_image_client_config_prefers_explicit_image_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_PROVIDER", raising=False)
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_MODEL", raising=False)
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_IMAGE_ENDPOINT",
        "https://prospektlabv3-resource.services.ai.azure.com/openai/v1/images/generations",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_OPENAI_BASE_URL", "https://prospektlabv3-resource.services.ai.azure.com/openai/v1")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT", "gpt-image-1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "azure-foundry"
    assert config.model == "chatgpt-image-2"
    assert config.image_endpoint == "https://prospektlabv3-resource.services.ai.azure.com/openai/v1/images/generations"
    assert config.base_url == "https://prospektlabv3-resource.services.ai.azure.com/openai/v1"


def test_resolve_image_client_config_can_force_openai(monkeypatch) -> None:
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://prospektlabv3-resource.services.ai.azure.com/api/projects/prospektlabv3",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "gpt-image-1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "openai"
    assert config.model == "chatgpt-image-2"


def test_resolve_image_client_config_can_keep_legacy_model_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "gpt-image-1")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_ALLOW_GPT_IMAGE_1", "1")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "openai"
    assert config.model == "gpt-image-1"


def test_resolve_image_client_config_can_force_foundry(monkeypatch) -> None:
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_PROVIDER", "foundry")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_FORCE_FOUNDRY_CHATGPT_IMAGE_2", "1")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://prospektlabv3-resource.services.ai.azure.com/api/projects/prospektlabv3",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT", "chatgpt-image-2")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "chatgpt-image-2")

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "azure-foundry"
    assert config.model == "chatgpt-image-2"


def test_resolve_image_client_config_respects_foundry_provider_for_chatgpt_image_2(monkeypatch) -> None:
    """When FINAGENT_CONTENT_IMAGE_PROVIDER=foundry is set, route through Azure
    Foundry — matches the explicit-config contract for the deployed customer."""
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_PROVIDER", "foundry")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_API_KEY", "test-foundry-key")
    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT",
        "https://prospektlabv3-resource.services.ai.azure.com/api/projects/prospektlabv3",
    )
    monkeypatch.setenv("AZURE_AI_FOUNDRY_IMAGE_DEPLOYMENT", "chatgpt-image-2")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("FINAGENT_CONTENT_IMAGE_MODEL", "chatgpt-image-2")
    monkeypatch.delenv("FINAGENT_CONTENT_IMAGE_FORCE_FOUNDRY_CHATGPT_IMAGE_2", raising=False)

    config = _resolve_image_client_config()

    assert config is not None
    assert config.provider == "azure-foundry"
    assert config.model == "chatgpt-image-2"
