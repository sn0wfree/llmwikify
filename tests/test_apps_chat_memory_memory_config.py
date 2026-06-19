"""Tests for memory_config helpers (Phase 6 Step 4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llmwikify.apps.chat.memory.memory_config import (
    DEFAULT_CONFIG_FILENAME,
    MemoryConfig,
    load_memory_config,
    write_default_memory_config,
)


class TestMemoryConfigDefaults:
    def test_defaults(self) -> None:
        cfg = MemoryConfig()
        assert cfg.consolidation["trigger_token_threshold"] == 4000
        assert cfg.consolidation["keep_recent_messages"] == 8
        assert cfg.consolidation["min_consolidation_interval_sec"] == 60.0
        assert cfg.dream["enabled"] is True
        assert cfg.dream["cron_expression"] == "0 3 * * *"
        assert cfg.dream["max_batch_size"] == 20

    def test_load_missing_returns_defaults(self, tmp_path: Path) -> None:
        cfg = load_memory_config(tmp_path)
        assert cfg.consolidation["trigger_token_threshold"] == 4000

    def test_load_corrupted_returns_defaults(self, tmp_path: Path) -> None:
        # Write garbage
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text("not-valid-json")
        cfg = load_memory_config(tmp_path)
        # Still gets defaults
        assert cfg.consolidation["trigger_token_threshold"] == 4000


class TestMemoryConfigLoad:
    def test_load_full_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / DEFAULT_CONFIG_FILENAME
        config_path.write_text(json.dumps({
            "consolidation": {
                "trigger_token_threshold": 8000,
                "keep_recent_messages": 4,
            },
            "dream": {
                "enabled": False,
                "cron_expression": "0 * * * *",
            },
        }))
        cfg = load_memory_config(tmp_path)
        assert cfg.consolidation["trigger_token_threshold"] == 8000
        assert cfg.consolidation["keep_recent_messages"] == 4
        # Defaults preserved for unset keys
        assert cfg.consolidation["summary_max_tokens"] == 1024
        assert cfg.dream["enabled"] is False
        assert cfg.dream["cron_expression"] == "0 * * * *"

    def test_load_partial_config(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
            "consolidation": {"trigger_token_threshold": 9999},
        }))
        cfg = load_memory_config(tmp_path)
        assert cfg.consolidation["trigger_token_threshold"] == 9999
        # dream section untouched (uses defaults)
        assert cfg.dream["enabled"] is True

    def test_load_empty_dict(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text("{}")
        cfg = load_memory_config(tmp_path)
        assert cfg.consolidation["trigger_token_threshold"] == 4000

    def test_load_invalid_types_ignored(self, tmp_path: Path) -> None:
        (tmp_path / DEFAULT_CONFIG_FILENAME).write_text(json.dumps({
            "consolidation": "not-a-dict",
            "dream": 42,
        }))
        cfg = load_memory_config(tmp_path)
        # Both sections retain defaults
        assert cfg.consolidation["trigger_token_threshold"] == 4000
        assert cfg.dream["enabled"] is True


class TestMemoryConfigWrite:
    def test_write_default_creates_file(self, tmp_path: Path) -> None:
        path = write_default_memory_config(tmp_path)
        assert path.exists()
        # Should be parseable JSON
        data = json.loads(path.read_text())
        assert "consolidation" in data
        assert "dream" in data

    def test_write_default_does_not_overwrite(self, tmp_path: Path) -> None:
        config_path = tmp_path / DEFAULT_CONFIG_FILENAME
        config_path.write_text('{"custom": true}')
        write_default_memory_config(tmp_path)
        # Existing file is preserved
        assert json.loads(config_path.read_text()) == {"custom": True}

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        write_default_memory_config(nested)
        assert (nested / DEFAULT_CONFIG_FILENAME).exists()
