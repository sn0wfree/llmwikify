"""Tests for foundation.config — Config singleton class."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from llmwikify.foundation.config import (
    Config,
    DEFAULT_CONFIG,
    get_db_path,
    get_default_config,
    get_directory,
    get_mcp_config,
    get_search_config,
    get_wikis_config,
    load_config,
)


@pytest.fixture(autouse=True)
def _reset_config_singleton():
    """Reset Config singleton between tests."""
    Config._instance = None
    yield
    Config._instance = None


class TestConfigSingleton:
    """Tests for Config singleton behavior."""

    def test_singleton_same_instance(self) -> None:
        """Multiple Config() calls return the same instance."""
        c1 = Config()
        c2 = Config()
        assert c1 is c2

    def test_singleton_reset(self) -> None:
        """After resetting _instance, new Config() creates fresh instance."""
        c1 = Config()
        Config._instance = None
        c2 = Config()
        assert c1 is not c2

    def test_home_property(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """home property returns ~/.llmwikify path."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        # Must reset singleton AFTER setting env var
        Config._instance = None
        c = Config()
        assert c.home == tmp_path / ".llmwikify"

    def test_path_property(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """path property returns ~/.llmwikify/llmwikify.json."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        # Must reset singleton AFTER setting env var
        Config._instance = None
        c = Config()
        assert c.path == tmp_path / ".llmwikify" / "llmwikify.json"

    def test_env_var_override(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """LLMWIKIFY_HOME env var overrides default home."""
        custom_home = tmp_path / "custom"
        monkeypatch.setenv("LLMWIKIFY_HOME", str(custom_home))
        Config._instance = None
        c = Config()
        assert c.home == custom_home / ".llmwikify"


class TestConfigGet:
    """Tests for Config.get() method."""

    def test_get_full_config_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() with no file returns empty dict."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        result = c.get()
        assert result == {}

    def test_get_section_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get(section) with missing section returns empty dict."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        result = c.get("llm")
        assert result == {}

    def test_get_section_with_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get(section, default) returns default when section missing."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        result = c.get("llm", {"provider": "minimax"})
        assert result == {"provider": "minimax"}

    def test_get_from_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() reads from llmwikify.json."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        config_dir = tmp_path / ".llmwikify"
        config_dir.mkdir()
        config_file = config_dir / "llmwikify.json"
        config_file.write_text(json.dumps({"llm": {"provider": "openai"}}))

        Config._instance = None
        c = Config()
        result = c.get("llm")
        assert result == {"provider": "openai"}

    def test_get_caches_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get() caches the result after first read."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        config_dir = tmp_path / ".llmwikify"
        config_dir.mkdir()
        config_file = config_dir / "llmwikify.json"
        config_file.write_text(json.dumps({"llm": {"provider": "openai"}}))

        Config._instance = None
        c = Config()
        result1 = c.get("llm")

        # Modify file
        config_file.write_text(json.dumps({"llm": {"provider": "minimax"}}))

        # Should still return cached result
        result2 = c.get("llm")
        assert result1 == result2 == {"provider": "openai"}


class TestConfigGetWikiConfig:
    """Tests for Config.get_wiki_config() method."""

    def test_no_config_file(self, tmp_path: Path) -> None:
        """Returns empty dict when .wiki-config.yaml doesn't exist."""
        c = Config()
        result = c.get_wiki_config(tmp_path)
        assert result == {}

    def test_with_config_file(self, tmp_path: Path) -> None:
        """Reads .wiki-config.yaml."""
        config_file = tmp_path / ".wiki-config.yaml"
        config_file.write_text("version: '0.41'\ndirectories:\n  raw: raw\n")

        c = Config()
        result = c.get_wiki_config(tmp_path)
        assert result["version"] == "0.41"
        assert result["directories"]["raw"] == "raw"

    def test_caches_result(self, tmp_path: Path) -> None:
        """Caches wiki config after first read."""
        config_file = tmp_path / ".wiki-config.yaml"
        config_file.write_text("version: '0.41'\n")

        c = Config()
        result1 = c.get_wiki_config(tmp_path)

        # Modify file
        config_file.write_text("version: '0.42'\n")

        # Should still return cached result
        result2 = c.get_wiki_config(tmp_path)
        assert result1 == result2


class TestConfigGetDefault:
    """Tests for Config.get_default() method."""

    def test_get_default_llm(self) -> None:
        """get_default('llm') returns default llm section."""
        c = Config()
        result = c.get_default("llm")
        assert "provider" in result or result == {}

    def test_get_default_missing_section(self) -> None:
        """get_default() with missing section returns empty dict."""
        c = Config()
        result = c.get_default("nonexistent")
        assert result == {}


class TestConfigSave:
    """Tests for Config.save() method."""

    def test_save_creates_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save() creates the config file."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()
        c.save({"provider": "openai"}, section="llm")

        config_file = tmp_path / ".llmwikify" / "llmwikify.json"
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert data["llm"] == {"provider": "openai"}

    def test_save_merges_with_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save(section) merges with existing config."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        config_dir = tmp_path / ".llmwikify"
        config_dir.mkdir()
        config_file = config_dir / "llmwikify.json"
        config_file.write_text(json.dumps({"research": {"max_sources": 10}}))

        Config._instance = None
        c = Config()
        c.save({"provider": "openai"}, section="llm")

        data = json.loads(config_file.read_text())
        assert data["llm"] == {"provider": "openai"}
        assert data["research"] == {"max_sources": 10}

    def test_save_invalidates_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """save() invalidates the cache."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()

        # Prime cache
        c.get()
        assert c._cache is not None

        # Save should invalidate
        c.save({"provider": "openai"}, section="llm")
        assert c._cache is None


class TestConfigReload:
    """Tests for Config.reload() method."""

    def test_reload_clears_cache(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """reload() clears all caches."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()

        # Prime caches
        c.get()
        c.get_wiki_config(tmp_path)
        assert c._cache is not None
        assert len(c._wiki_cache) > 0

        # Reload should clear
        c.reload()
        assert c._cache is None
        assert len(c._wiki_cache) == 0


class TestConfigEnsureDir:
    """Tests for Config.ensure_dir() method."""

    def test_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_dir() creates the home directory."""
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        Config._instance = None
        c = Config()

        assert not c.home.exists()
        c.ensure_dir()
        assert c.home.exists()


class TestBackwardCompatFunctions:
    """Tests for backward-compatible functions."""

    def test_get_default_config(self) -> None:
        """get_default_config() returns deep copy of DEFAULT_CONFIG."""
        result = get_default_config()
        assert result == DEFAULT_CONFIG
        # Verify it's a deep copy
        result["llm"]["provider"] = "modified"
        assert DEFAULT_CONFIG["llm"]["provider"] != "modified"

    def test_load_config_no_file(self, tmp_path: Path) -> None:
        """load_config() with no file returns defaults."""
        result = load_config(tmp_path)
        assert result == DEFAULT_CONFIG

    def test_load_config_with_file(self, tmp_path: Path) -> None:
        """load_config() merges with user config."""
        config_file = tmp_path / ".wiki-config.yaml"
        config_file.write_text("llm:\n  provider: openai\n")

        result = load_config(tmp_path)
        assert result["llm"]["provider"] == "openai"
        # Other defaults should be preserved
        assert result["directories"]["raw"] == "raw"

    def test_get_db_path(self, tmp_path: Path) -> None:
        """get_db_path() returns wiki_root / db_name."""
        result = get_db_path(tmp_path)
        assert result == tmp_path / ".llmwikify.db"

    def test_get_directory(self, tmp_path: Path) -> None:
        """get_directory() returns wiki_root / dir_name."""
        result = get_directory(tmp_path, "raw")
        assert result == tmp_path / "raw"

    def test_get_mcp_config(self) -> None:
        """get_mcp_config() returns MCP config."""
        result = get_mcp_config()
        assert "host" in result
        assert "port" in result
        assert "transport" in result

    def test_get_search_config(self) -> None:
        """get_search_config() returns search config."""
        result = get_search_config()
        assert "backend" in result

    def test_get_wikis_config(self) -> None:
        """get_wikis_config() returns wikis config."""
        result = get_wikis_config()
        assert "default" in result
        assert "local" in result
        assert "remote" in result
