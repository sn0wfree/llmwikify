"""Tests for Xiaomi MiMo LLM provider."""

import pytest

from llmwikify._legacy.adapters import StreamableLLMClient
from llmwikify.apps.agent.providers import list_providers, get_provider
from llmwikify.apps.agent.providers.xiaomi import XiaomiProvider


class TestXiaomiProvider:
    """Tests for XiaomiProvider implementation."""

    def test_provider_name(self):
        p = XiaomiProvider()
        assert p.provider_name() == "xiaomi"

    def test_default_base_url(self):
        p = XiaomiProvider()
        assert p.default_base_url() == "https://token-plan-cn.xiaomimimo.com/v1"

    def test_default_model(self):
        p = XiaomiProvider()
        assert p.default_model() == "mimo-v2.5-pro"

    def test_supported_models(self):
        p = XiaomiProvider()
        models = p.supported_models()
        assert "mimo-v2.5-pro" in models
        assert "mimo-v2.5" in models
        assert "mimo-v2-flash" in models
        assert "mimo-v2-pro" in models
        assert "mimo-v2-omni" in models
        assert len(models) == 5

    def test_registered_in_registry(self):
        providers = list_providers()
        assert "xiaomi" in providers

    def test_get_provider(self):
        p = get_provider("xiaomi")
        assert isinstance(p, XiaomiProvider)

    def test_from_config(self):
        p = XiaomiProvider()
        config = {
            "api_key": "tp-test-key-123",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "model": "mimo-v2.5-pro",
        }
        client = p.from_config(config)
        assert isinstance(client, StreamableLLMClient)
        assert client.provider == "xiaomi"
        assert client.api_key == "tp-test-key-123"
        assert client.model == "mimo-v2.5-pro"
        assert client.reasoning_split is True
        assert client.auth_header == "api-key"

    def test_from_config_defaults(self):
        p = XiaomiProvider()
        config = {"api_key": "tp-test"}
        client = p.from_config(config)
        assert client.model == "mimo-v2.5-pro"
        assert "xiaomimimo.com" in client.base_url
        assert client.auth_header == "api-key"

    def test_from_config_missing_key(self):
        p = XiaomiProvider()
        with pytest.raises(ValueError, match="API key not configured"):
            p.from_config({})

    def test_from_config_env_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "tp-env-key")
        p = XiaomiProvider()
        client = p.from_config({})
        assert client.api_key == "tp-env-key"
        monkeypatch.delenv("LLM_API_KEY")

    def test_validate_config_valid(self):
        p = XiaomiProvider()
        errors = p.validate_config({"api_key": "tp-test", "model": "mimo-v2.5-pro"})
        assert errors == []

    def test_validate_config_missing_key(self):
        p = XiaomiProvider()
        errors = p.validate_config({})
        assert len(errors) == 1
        assert "API key" in errors[0]

    def test_validate_config_invalid_model(self):
        p = XiaomiProvider()
        errors = p.validate_config({"api_key": "tp-test", "model": "gpt-4o"})
        assert len(errors) == 1
        assert "not supported" in errors[0]


class TestStreamableLLMClientAuthHeader:
    """Tests for auth_header support in StreamableLLMClient."""

    def test_default_bearer_auth(self):
        client = StreamableLLMClient(
            provider="openai",
            api_key="sk-test",
            model="gpt-4o",
        )
        assert client.auth_header == "bearer"
        headers = client._build_headers()
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer sk-test"
        assert "api-key" not in headers

    def test_api_key_auth(self):
        client = StreamableLLMClient(
            provider="xiaomi",
            api_key="tp-test-key",
            model="mimo-v2.5-pro",
            auth_header="api-key",
        )
        assert client.auth_header == "api-key"
        headers = client._build_headers()
        assert "api-key" in headers
        assert headers["api-key"] == "tp-test-key"
        assert "Authorization" not in headers

    def test_xiaomi_default_url(self):
        client = StreamableLLMClient(provider="xiaomi", api_key="tp-test")
        assert "xiaomimimo.com" in client.base_url

    def test_base_url_strips_v1(self):
        client = StreamableLLMClient(
            provider="xiaomi",
            base_url="https://token-plan-cn.xiaomimimo.com/v1",
            api_key="tp-test",
        )
        assert client.base_url == "https://token-plan-cn.xiaomimimo.com"
        assert "/v1" not in client.base_url
