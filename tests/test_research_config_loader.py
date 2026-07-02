"""Unit tests for routes.py research config loader.

Covers:
  - _load_research_config reads research section from global config
  - _load_llm_config reads llm section from global config
  - _build_research_config_overrides applies automatic minimax key fallback
  - Explicit research.minimax_api_key wins over llm.api_key fallback
  - Unknown keys are stripped
  - Missing config file -> empty overrides (no crash)
  - Malformed JSON -> empty overrides (no crash)

Target: pure unit tests, no FastAPI server, no DB, no LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

# ─── Helpers ──────────────────────────────────────────────────────


def _write_global_config(fake_home: Path, payload: dict) -> Path:
    """Write a fake ~/.llmwikify/llmwikify.json under ``fake_home``."""
    config_dir = fake_home / ".llmwikify"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "llmwikify.json"
    config_file.write_text(json.dumps(payload))
    return config_file


def _patch_home(monkeypatch, tmp_path: Path) -> Path:
    """Redirect ``Path.home()`` to a fresh tmp dir for this test."""
    fake_home = tmp_path / "fake_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    return fake_home


# ─── _load_research_config ────────────────────────────────────────


class TestLoadResearchConfig:
    """_load_research_config reads ~/.llmwikify/llmwikify.json:research."""

    def test_returns_research_section(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {"research": {"minimax_api_key": "sk-test", "search_provider": "minimax"}},
        )
        from llmwikify.interfaces.server.http.routes import _load_research_config

        cfg = _load_research_config()
        assert cfg is not None
        assert cfg["minimax_api_key"] == "sk-test"
        assert cfg["search_provider"] == "minimax"

    def test_returns_none_when_no_config_file(self, tmp_path, monkeypatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        from llmwikify.interfaces.server.http.routes import _load_research_config

        assert _load_research_config() is None

    def test_returns_none_when_no_research_section(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(fake_home, {"llm": {"provider": "openai"}})
        from llmwikify.interfaces.server.http.routes import _load_research_config

        assert _load_research_config() is None

    def test_returns_none_on_malformed_json(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        config_dir = fake_home / ".llmwikify"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "llmwikify.json").write_text("{ invalid json")
        from llmwikify.interfaces.server.http.routes import _load_research_config

        assert _load_research_config() is None


# ─── _load_llm_config ──────────────────────────────────────────────


class TestLoadLlmConfig:
    """_load_llm_config reads ~/.llmwikify/llmwikify.json:llm."""

    def test_returns_llm_section(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {"llm": {"provider": "minimax", "api_key": "sk-cp-test", "base_url": "https://api.minimaxi.com/v1"}},
        )
        from llmwikify.interfaces.server.http.routes import _load_llm_config

        cfg = _load_llm_config()
        assert cfg is not None
        assert cfg["provider"] == "minimax"
        assert cfg["api_key"] == "sk-cp-test"

    def test_returns_none_when_no_config(self, tmp_path, monkeypatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        from llmwikify.interfaces.server.http.routes import _load_llm_config

        assert _load_llm_config() is None


# ─── _build_research_config_overrides ─────────────────────────────


class TestBuildResearchConfigOverrides:
    """Verify the public override builder behaviour."""

    def test_empty_overrides_when_no_config_file(self, tmp_path, monkeypatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        assert _build_research_config_overrides() == {}

    def test_passes_research_keys_through(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {"research": {"tavily_api_key": "tvly-xyz", "search_provider": "tavily"}},
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert out["tavily_api_key"] == "tvly-xyz"
        assert out["search_provider"] == "tavily"
        # minimax block not touched
        assert "minimax_api_key" not in out

    def test_minimax_key_falls_back_to_llm_api_key(self, tmp_path, monkeypatch) -> None:
        """When llm.provider=minimax and research.minimax_api_key is missing,
        reuse llm.api_key so the user gets search out-of-the-box.
        """
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {
                    "provider": "minimax",
                    "api_key": "sk-cp-coding-plan",
                    "base_url": "https://api.minimaxi.com/v1",
                },
                # No research section at all
            },
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert out["minimax_api_key"] == "sk-cp-coding-plan"
        assert out["minimax_api_host"] == "https://api.minimaxi.com"

    def test_explicit_research_key_wins_over_llm_fallback(
        self, tmp_path, monkeypatch
    ) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {"provider": "minimax", "api_key": "sk-cp-fallback"},
                "research": {"minimax_api_key": "sk-cp-explicit"},
            },
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert out["minimax_api_key"] == "sk-cp-explicit"

    def test_fallback_uses_search_provider_filter(
        self, tmp_path, monkeypatch
    ) -> None:
        """When user explicitly pins search_provider=tavily, do NOT inject
        minimax_api_key even if llm is minimax. Avoids surprising the user
        with a provider they didn't ask for.
        """
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {"provider": "minimax", "api_key": "sk-cp-x"},
                "research": {"search_provider": "tavily", "tavily_api_key": "tvly-q"},
            },
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert "minimax_api_key" not in out
        assert out["search_provider"] == "tavily"

    def test_fallback_skipped_for_non_minimax_llm_provider(
        self, tmp_path, monkeypatch
    ) -> None:
        """Only fall back when llm.provider == minimax (don't inject a
        stranger's minimax key into a non-minimax user's research config).
        """
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {"llm": {"provider": "openai", "api_key": "sk-openai"}},
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert "minimax_api_key" not in out

    def test_base_url_with_trailing_v1_stripped(self, tmp_path, monkeypatch) -> None:
        """base_url 'https://api.minimaxi.com/v1' becomes host
        'https://api.minimaxi.com' (search endpoint lives one level up
        from /v1/coding_plan/search).
        """
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {
                    "provider": "minimax",
                    "api_key": "sk-cp-x",
                    "base_url": "https://api.minimaxi.com/v1/",
                },
            },
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert out["minimax_api_host"] == "https://api.minimaxi.com"

    def test_explicit_host_overrides_derived(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {"provider": "minimax", "api_key": "sk-cp-x", "base_url": "https://api.minimaxi.com/v1"},
                "research": {"minimax_api_host": "https://api.custom.example.com"},
            },
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        assert out["minimax_api_host"] == "https://api.custom.example.com"

    def test_malformed_config_returns_empty(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        config_dir = fake_home / ".llmwikify"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "llmwikify.json").write_text("not json at all")
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        assert _build_research_config_overrides() == {}

    def test_unknown_keys_preserved_for_pass_through(
        self, tmp_path, monkeypatch
    ) -> None:
        """The loader doesn't validate keys; merge_six_step_config
        silently ignores unknown keys via its whitelist.
        """
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {"research": {"minimax_api_key": "sk-x", "totally_unknown_key": "ignored-by-merge"}},
        )
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        out = _build_research_config_overrides()
        # Loader keeps it (it's a known dict pass-through); merge layer
        # is responsible for filtering.
        assert out["totally_unknown_key"] == "ignored-by-merge"


# ─── Integration with merge_six_step_config ────────────────────────


class TestOverridesFlowIntoMergeSixStepConfig:
    """Verify the actual merge produces a config with the new keys."""

    def test_minimax_key_merged_into_six_step_config(self, tmp_path, monkeypatch) -> None:
        fake_home = _patch_home(monkeypatch, tmp_path)
        _write_global_config(
            fake_home,
            {
                "llm": {
                    "provider": "minimax",
                    "api_key": "sk-cp-flow",
                    "base_url": "https://api.minimaxi.com/v1",
                },
                "research": {"search_provider": "auto", "tavily_api_key": "tvly-aa"},
            },
        )
        from llmwikify.apps.chat.config import merge_six_step_config
        from llmwikify.interfaces.server.http.routes import (
            _build_research_config_overrides,
        )

        overrides = _build_research_config_overrides()
        merged = merge_six_step_config(overrides)
        # 1. explicit research section applied
        assert merged["search_provider"] == "auto"
        assert merged["tavily_api_key"] == "tvly-aa"
        # 2. llm fallback applied (search_provider==auto leaves room for fallback)
        assert merged["minimax_api_key"] == "sk-cp-flow"
        assert merged["minimax_api_host"] == "https://api.minimaxi.com"
        # 3. unknown keys dropped by merge whitelist
        assert "totally_unknown_key" not in merged

    def test_no_overrides_keeps_defaults(self) -> None:
        from llmwikify.apps.chat.config import merge_six_step_config

        merged = merge_six_step_config()
        assert merged["search_provider"] == "auto"
        assert merged["minimax_api_key"] is None
