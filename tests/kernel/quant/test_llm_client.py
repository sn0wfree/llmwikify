"""Tests for kernel/quant/llm_client (C2: extracted from reproduction/common/llm_factory).

Covers:
  - load_llm_config: file not found, parse error, valid file
  - _resolve_provider_info: known providers, unknown fallback, warning
  - build_llm_client: config required, provider required, api_key required,
    successful construction, model override
  - cycle break: kernel/llm_client has no apps/ or reproduction/ dependency
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def valid_config_file(tmp_path: Path) -> Path:
    """Write a valid ~/.llmwikify/llmwikify.json with [llm] section."""
    cfg = tmp_path / "llmwikify.json"
    cfg.write_text(json.dumps({
        "llm": {
            "enabled": True,
            "provider": "minimax",
            "base_url": "https://api.minimaxi.com/v1",
            "api_key": "test-key-123",
            "model": "minimax-M2.7",
            "timeout": 600,
        },
    }))
    return cfg


@pytest.fixture
def disabled_config_file(tmp_path: Path) -> Path:
    """Config with llm.enabled = False."""
    cfg = tmp_path / "llmwikify.json"
    cfg.write_text(json.dumps({"llm": {"enabled": False}}))
    return cfg


@pytest.fixture
def missing_provider_config(tmp_path: Path) -> Path:
    """Config without provider (C2 invariant: must fail loudly)."""
    cfg = tmp_path / "llmwikify.json"
    cfg.write_text(json.dumps({
        "llm": {
            "enabled": True,
            "api_key": "test-key",
            "model": "minimax-M2.7",
        },
    }))
    return cfg


# ─── load_llm_config ─────────────────────────────────────────────────


class TestLoadLLMConfig:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        from llmwikify.kernel.quant.llm_client import load_llm_config

        result = load_llm_config(config_path=tmp_path / "nope.json")
        assert result == {}

    def test_valid_file_returns_llm_section(self, valid_config_file: Path) -> None:
        from llmwikify.kernel.quant.llm_client import load_llm_config

        result = load_llm_config(config_path=valid_config_file)
        assert result["enabled"] is True
        assert result["provider"] == "minimax"
        assert result["api_key"] == "test-key-123"

    def test_malformed_json_returns_empty(self, tmp_path: Path) -> None:
        from llmwikify.kernel.quant.llm_client import load_llm_config

        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json")
        result = load_llm_config(config_path=bad)
        assert result == {}

    def test_no_llm_section_returns_empty(self, tmp_path: Path) -> None:
        from llmwikify.kernel.quant.llm_client import load_llm_config

        cfg = tmp_path / "no_llm.json"
        cfg.write_text(json.dumps({"wiki": {"dir": "/x"}}))
        result = load_llm_config(config_path=cfg)
        assert result == {}


# ─── _resolve_provider_info ──────────────────────────────────────────


class TestResolveProviderInfo:
    def test_known_provider_minimax(self) -> None:
        from llmwikify.kernel.quant.llm_client import _resolve_provider_info

        url, auth = _resolve_provider_info("minimax")
        assert url == "https://api.minimaxi.com/v1"
        assert auth == "bearer"

    def test_known_provider_xiaomi(self) -> None:
        from llmwikify.kernel.quant.llm_client import _resolve_provider_info

        url, auth = _resolve_provider_info("xiaomi")
        assert url == "https://api.xiaomi.com/v1"
        assert auth == "bearer"

    def test_known_provider_anthropic_uses_x_api_key(self) -> None:
        from llmwikify.kernel.quant.llm_client import _resolve_provider_info

        url, auth = _resolve_provider_info("anthropic")
        assert auth == "x-api-key"

    def test_unknown_provider_falls_back_with_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from llmwikify.kernel.quant.llm_client import _resolve_provider_info

        caplog.set_level("WARNING", logger="llmwikify.kernel.quant.llm_client")
        url, auth = _resolve_provider_info("totally-unknown-provider")
        # Falls back to OpenAI defaults
        assert url == "https://api.openai.com/v1"
        assert auth == "bearer"
        # Logs a warning
        assert any(
            "totally-unknown-provider" in r.message for r in caplog.records
        )


# ─── build_llm_client ───────────────────────────────────────────────


class TestBuildLLMClient:
    def test_constructs_with_valid_config(
        self, valid_config_file: Path,
    ) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client

        client = build_llm_client(config_path=valid_config_file)
        assert client.provider == "minimax"
        assert client.model == "minimax-M2.7"
        assert client.api_key == "test-key-123"
        assert client.auth_header == "bearer"
        # StreamableLLMClient normalizes base_url (strips trailing /v1)
        assert client.base_url == "https://api.minimaxi.com"

    def test_disabled_config_raises(
        self, disabled_config_file: Path,
    ) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client

        with pytest.raises(RuntimeError, match="LLM is disabled"):
            build_llm_client(config_path=disabled_config_file)

    def test_missing_provider_raises_loudly(
        self, missing_provider_config: Path,
    ) -> None:
        """C2 invariant: provider is required (was hardcoded to 'minimax')."""
        from llmwikify.kernel.quant.llm_client import build_llm_client

        with pytest.raises(RuntimeError, match="Missing 'provider'"):
            build_llm_client(config_path=missing_provider_config)

    def test_missing_api_key_raises(self, tmp_path: Path) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client

        cfg = tmp_path / "no_key.json"
        cfg.write_text(json.dumps({
            "llm": {
                "enabled": True,
                "provider": "minimax",
                "model": "minimax-M2.7",
            },
        }))
        with pytest.raises(RuntimeError, match="Missing api_key"):
            build_llm_client(config_path=cfg)

    def test_model_override_takes_precedence(
        self, valid_config_file: Path,
    ) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client

        client = build_llm_client(
            config_path=valid_config_file, model="custom-model",
        )
        assert client.model == "custom-model"

    def test_config_dict_passed_directly(
        self, valid_config_file: Path,
    ) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client, load_llm_config

        cfg = load_llm_config(config_path=valid_config_file)
        client = build_llm_client(config=cfg)
        assert client.provider == "minimax"

    def test_xiaomi_provider_uses_correct_url(self, tmp_path: Path) -> None:
        from llmwikify.kernel.quant.llm_client import build_llm_client

        cfg = tmp_path / "xiaomi.json"
        cfg.write_text(json.dumps({
            "llm": {
                "enabled": True,
                "provider": "xiaomi",
                "api_key": "xiaomi-key",
                "model": "mimo-v2",
            },
        }))
        client = build_llm_client(config_path=cfg)
        assert client.provider == "xiaomi"
        # StreamableLLMClient normalizes base_url (strips trailing /v1)
        assert client.base_url == "https://api.xiaomi.com"
        assert client.model == "mimo-v2"


# ─── Cycle break invariant ──────────────────────────────────────────


class TestCycleBreak:
    """C2: kernel/quant/llm_client must NOT depend on apps/ or reproduction/."""

    def test_no_apps_dependency(self) -> None:
        """Grep the source: no `from llmwikify.apps` import."""
        import llmwikify.kernel.quant.llm_client as mod

        source = mod.__file__
        assert source is not None
        content = Path(source).read_text(encoding="utf-8")
        assert "from llmwikify.apps" not in content
        assert "import llmwikify.apps" not in content

    def test_no_reproduction_dependency(self) -> None:
        """Grep the source: no `from llmwikify.reproduction` import."""
        import llmwikify.kernel.quant.llm_client as mod

        source = mod.__file__
        assert source is not None
        content = Path(source).read_text(encoding="utf-8")
        assert "from llmwikify.reproduction" not in content
        assert "import llmwikify.reproduction" not in content

    def test_importable_from_both_apps_and_reproduction_paths(self) -> None:
        """Sanity: kernel/llm_client importable without cycle."""
        from llmwikify.kernel.quant.llm_client import build_llm_client, load_llm_config
        assert callable(build_llm_client)
        assert callable(load_llm_config)
