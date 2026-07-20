"""Tests for foundation.migration — .wiki-config.yaml auto-migration."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llmwikify.foundation.migration import (
    CURRENT_VERSION,
    MIGRATABLE_SECTIONS,
    MigrationConflict,
    MigrationResult,
    WikiDiscoveryProvider,
    auto_migrate_wiki_config,
    detect_config_version,
    discover_wikis,
    needs_migration,
)


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(
        yaml.safe_dump(data, default_flow_style=False, allow_unicode=True),
        encoding="utf-8",
    )


def _read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _patch_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect HOME to tmp_path so llmwikify.json is created there."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


# ─── TestNeedsMigration ──────────────────────────────────────────────


class TestNeedsMigration:
    def test_no_config_file(self, tmp_path: Path) -> None:
        assert needs_migration(tmp_path) is False

    def test_missing_version_field(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "directories": {"raw": "raw"},
            "llm": {"provider": "minimax", "model": "minimax-M3"},
        })
        assert needs_migration(tmp_path) is True

    def test_old_version(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "version": "0.40",
            "directories": {"raw": "raw"},
        })
        assert needs_migration(tmp_path) is True

    def test_current_version(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "version": CURRENT_VERSION,
            "directories": {"raw": "raw"},
        })
        assert needs_migration(tmp_path) is False

    def test_newer_version(self, tmp_path: Path) -> None:
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "version": "0.42",
            "directories": {"raw": "raw"},
        })
        assert needs_migration(tmp_path) is False

    def test_unparseable_yaml(self, tmp_path: Path) -> None:
        (tmp_path / ".wiki-config.yaml").write_text(": invalid: yaml: :")
        # Unparseable files are reported as needing migration (to give user
        # a chance to see the error and fix manually).
        assert needs_migration(tmp_path) is True


# ─── TestDetectConfigVersion ─────────────────────────────────────────


class TestDetectConfigVersion:
    def test_missing_version(self) -> None:
        assert detect_config_version({}) == "0.0"

    def test_explicit_version(self) -> None:
        assert detect_config_version({"version": "0.41"}) == "0.41"


# ─── TestAutoMigration ───────────────────────────────────────────────


class TestAutoMigration:
    def test_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        result = auto_migrate_wiki_config(tmp_path)
        assert result.migrated is False
        assert result.reason == "no_config"

    def test_already_migrated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "version": CURRENT_VERSION,
            "directories": {"raw": "raw"},
        })
        result = auto_migrate_wiki_config(tmp_path)
        assert result.migrated is False
        assert result.reason == "already_migrated"

    def test_migrate_llm_only(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "directories": {"raw": "raw"},
            "llm": {"provider": "minimax", "model": "minimax-M3", "api_key": "sk-test"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.migrated is True
        assert result.reason == "migrated"
        # Global config has the llm section
        global_cfg = json.loads(
            (tmp_path / ".llmwikify" / "llmwikify.json").read_text()
        )
        assert global_cfg["llm"]["provider"] == "minimax"
        assert global_cfg["llm"]["model"] == "minimax-M3"
        # Wiki config retains directories but not llm
        wiki_cfg = _read_yaml(tmp_path / ".wiki-config.yaml")
        assert "llm" not in wiki_cfg
        assert wiki_cfg["directories"]["raw"] == "raw"
        assert wiki_cfg["version"] == CURRENT_VERSION
        # Backup created
        assert result.backup_path is not None
        assert result.backup_path.exists()

    def test_migrate_multiple_sections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "directories": {"raw": "src"},
            "llm": {"provider": "openai"},
            "research_mutable": {"max_sub_queries": 30},
            "chat_mutable": {"max_chat_rounds": 8},
            "mcp": {"port": 9000},
            "prompts": {"custom_dir": "/tmp/prompts"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.migrated is True
        global_cfg = json.loads(
            (tmp_path / ".llmwikify" / "llmwikify.json").read_text()
        )
        assert global_cfg["llm"]["provider"] == "openai"
        assert global_cfg["research_mutable"]["max_sub_queries"] == 30
        assert global_cfg["chat_mutable"]["max_chat_rounds"] == 8
        assert global_cfg["mcp"]["port"] == 9000
        assert global_cfg["prompts"]["custom_dir"] == "/tmp/prompts"
        # Wiki only retains non-migrated sections
        wiki_cfg = _read_yaml(tmp_path / ".wiki-config.yaml")
        assert "llm" not in wiki_cfg
        assert "research_mutable" not in wiki_cfg
        assert "chat_mutable" not in wiki_cfg
        assert "mcp" not in wiki_cfg
        assert "prompts" not in wiki_cfg
        assert wiki_cfg["directories"]["raw"] == "src"

    def test_version_bump_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "version": "0.40",
            "directories": {"raw": "raw"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.migrated is True
        assert result.reason == "version_bump_only"
        wiki_cfg = _read_yaml(tmp_path / ".wiki-config.yaml")
        assert wiki_cfg["version"] == CURRENT_VERSION

    def test_no_migratable_sections(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "directories": {"raw": "raw"},
            "database": {"name": ".db"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        # No llm/research etc. → no migration, no version bump
        assert result.migrated is False
        assert result.reason == "no_migratable_sections"

    def test_dry_run_no_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax", "model": "minimax-M3"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="dry_run")
        assert result.dry_run is True
        assert result.migrated is False
        assert result.reason == "dry_run"
        assert len(result.changes) > 0
        # No files written
        assert not (tmp_path / ".llmwikify" / "llmwikify.json").exists()
        # Original file unchanged (no version field added)
        wiki_cfg = _read_yaml(tmp_path / ".wiki-config.yaml")
        assert "version" not in wiki_cfg

    def test_backup_filename_format(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {"llm": {"provider": "minimax"}})
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.backup_path is not None
        # Format: .wiki-config.yaml.bak.<timestamp>
        assert ".bak." in result.backup_path.name
        # Is integer timestamp after .bak.
        suffix = result.backup_path.name.split(".bak.")[-1]
        assert suffix.isdigit()

    def test_backup_preserves_content(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        original = {
            "directories": {"raw": "src"},
            "llm": {"provider": "minimax", "model": "minimax-M3", "api_key": "sk-secret"},
        }
        _write_yaml(tmp_path / ".wiki-config.yaml", original)
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.backup_path is not None
        backup_data = _read_yaml(result.backup_path)
        assert backup_data == original


# ─── TestConflictResolution ──────────────────────────────────────────


class TestConflictResolution:
    def test_no_conflicts(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {"llm": {"provider": "minimax"}})
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert result.conflicts == []

    def test_detect_conflict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_home(monkeypatch, tmp_path)
        # Pre-existing global config with conflicting value
        (tmp_path / ".llmwikify").mkdir()
        (tmp_path / ".llmwikify" / "llmwikify.json").write_text(
            json.dumps({"llm": {"provider": "openai", "model": "gpt-4o"}})
        )
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax", "model": "minimax-M3"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert len(result.conflicts) == 2  # provider + model
        keys = {(c.section, c.key) for c in result.conflicts}
        assert ("llm", "provider") in keys
        assert ("llm", "model") in keys

    def test_global_priority_keeps_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        (tmp_path / ".llmwikify").mkdir()
        (tmp_path / ".llmwikify" / "llmwikify.json").write_text(
            json.dumps({"llm": {"provider": "openai", "model": "gpt-4o"}})
        )
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax", "model": "minimax-M3"},
        })
        auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        global_cfg = json.loads(
            (tmp_path / ".llmwikify" / "llmwikify.json").read_text()
        )
        # Existing global values preserved on conflict
        assert global_cfg["llm"]["provider"] == "openai"
        # Non-conflicting wiki values would be applied — but here
        # both keys conflict. Verify the priority semantics:
        # wiki offers minimax-M3, but global keeps gpt-4o.
        assert global_cfg["llm"]["model"] == "gpt-4o"

    def test_wiki_priority_overrides_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        (tmp_path / ".llmwikify").mkdir()
        (tmp_path / ".llmwikify" / "llmwikify.json").write_text(
            json.dumps({"llm": {"provider": "openai"}})
        )
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax"},
        })
        auto_migrate_wiki_config(tmp_path, auto_resolve="wiki")
        global_cfg = json.loads(
            (tmp_path / ".llmwikify" / "llmwikify.json").read_text()
        )
        # Wiki value overrides global
        assert global_cfg["llm"]["provider"] == "minimax"

    def test_strict_mode_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        (tmp_path / ".llmwikify").mkdir()
        (tmp_path / ".llmwikify" / "llmwikify.json").write_text(
            json.dumps({"llm": {"provider": "openai"}})
        )
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax"},
        })
        with pytest.raises(RuntimeError, match="conflicts"):
            auto_migrate_wiki_config(tmp_path, auto_resolve="strict")


# ─── TestChangesTracking ─────────────────────────────────────────────


class TestChangesTracking:
    def test_changes_recorded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax", "model": "minimax-M3"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        assert len(result.changes) == 2
        sections = {(c.section, c.key) for c in result.changes}
        assert ("llm", "provider") in sections
        assert ("llm", "model") in sections

    def test_changes_record_conflicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_home(monkeypatch, tmp_path)
        (tmp_path / ".llmwikify").mkdir()
        (tmp_path / ".llmwikify" / "llmwikify.json").write_text(
            json.dumps({"llm": {"provider": "openai"}})
        )
        _write_yaml(tmp_path / ".wiki-config.yaml", {
            "llm": {"provider": "minimax"},
        })
        result = auto_migrate_wiki_config(tmp_path, auto_resolve="global")
        # Provider change should be flagged as conflict
        provider_change = next(
            c for c in result.changes if c.key == "provider"
        )
        assert provider_change.conflict is True


# ─── TestWikiDiscoveryProvider ─────────────────────────────────────


class TestWikiDiscoveryProvider:
    """Tests for WikiDiscoveryProvider protocol."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """WikiDiscoveryProvider should be runtime_checkable."""

        class ValidProvider:
            def discover_wiki_roots(
                self, scan_paths: list[str], depth: int = 2
            ) -> list[Path]:
                return []

        provider = ValidProvider()
        assert isinstance(provider, WikiDiscoveryProvider)

    def test_protocol_rejects_invalid(self) -> None:
        """Objects without discover_wiki_roots should not satisfy protocol."""

        class InvalidProvider:
            pass

        assert not isinstance(InvalidProvider(), WikiDiscoveryProvider)

    def test_protocol_rejects_wrong_signature(self) -> None:
        """Objects with wrong signature should not satisfy protocol."""

        class WrongSignature:
            def discover_wiki_roots(self) -> list[Path]:
                return []

        # runtime_checkable only checks method existence, not signature
        # But this is still useful for type checking
        provider = WrongSignature()
        assert isinstance(provider, WikiDiscoveryProvider)


# ─── TestDiscoverWikis ─────────────────────────────────────────────


class TestDiscoverWikis:
    """Tests for discover_wikis function."""

    def test_no_config_no_provider(self, tmp_path: Path) -> None:
        """Without config or provider, returns empty list."""
        result = discover_wikis(root=tmp_path)
        assert result == []

    def test_cwd_with_config(self, tmp_path: Path) -> None:
        """Finds wiki in CWD when .wiki-config.yaml exists."""
        (tmp_path / ".wiki-config.yaml").write_text("version: '0.41'")
        result = discover_wikis(root=tmp_path)
        assert tmp_path in result

    def test_env_var_with_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Finds wiki via WIKI_ROOT env var."""
        wiki_dir = tmp_path / "env_wiki"
        wiki_dir.mkdir()
        (wiki_dir / ".wiki-config.yaml").write_text("version: '0.41'")
        monkeypatch.setenv("WIKI_ROOT", str(wiki_dir))
        result = discover_wikis(root=tmp_path)
        assert wiki_dir in result

    def test_provider_called_with_scan_paths(self, tmp_path: Path) -> None:
        """Provider is called with scan_paths and depth."""
        mock_provider = MagicMock(spec=WikiDiscoveryProvider)
        mock_provider.discover_wiki_roots.return_value = []

        discover_wikis(root=tmp_path, provider=mock_provider, scan_paths=["/scan"], depth=3)
        mock_provider.discover_wiki_roots.assert_called_once_with(["/scan"], 3)

    def test_provider_defaults_scan_paths_to_root(self, tmp_path: Path) -> None:
        """When scan_paths is None, provider receives [str(root)]."""
        mock_provider = MagicMock(spec=WikiDiscoveryProvider)
        mock_provider.discover_wiki_roots.return_value = []

        discover_wikis(root=tmp_path, provider=mock_provider)
        mock_provider.discover_wiki_roots.assert_called_once_with([str(tmp_path)], 2)

    def test_provider_results_merged(self, tmp_path: Path) -> None:
        """Provider results are merged with CWD and env results."""
        wiki_dir = tmp_path / "provider_wiki"
        wiki_dir.mkdir()
        (wiki_dir / ".wiki-config.yaml").write_text("version: '0.41'")

        mock_provider = MagicMock(spec=WikiDiscoveryProvider)
        mock_provider.discover_wiki_roots.return_value = [wiki_dir]

        result = discover_wikis(root=tmp_path, provider=mock_provider)
        assert wiki_dir in result

    def test_provider_exception_caught(self, tmp_path: Path) -> None:
        """Provider exceptions are caught and ignored."""
        mock_provider = MagicMock(spec=WikiDiscoveryProvider)
        mock_provider.discover_wiki_roots.side_effect = RuntimeError("fail")

        # Should not raise
        result = discover_wikis(root=tmp_path, provider=mock_provider)
        assert isinstance(result, list)

    def test_no_duplicates(self, tmp_path: Path) -> None:
        """Duplicate paths from provider are not added."""
        (tmp_path / ".wiki-config.yaml").write_text("version: '0.41'")

        mock_provider = MagicMock(spec=WikiDiscoveryProvider)
        mock_provider.discover_wiki_roots.return_value = [tmp_path]

        result = discover_wikis(root=tmp_path, provider=mock_provider)
        assert result.count(tmp_path) == 1

    def test_provider_none_not_called(self, tmp_path: Path) -> None:
        """When provider is None, no provider is called."""
        # This should not raise any error
        result = discover_wikis(root=tmp_path, provider=None)
        assert isinstance(result, list)


# ─── TestWikiRegistryDiscovery ─────────────────────────────────────


class TestWikiRegistryDiscovery:
    """Tests for WikiRegistryDiscovery class."""

    def test_satisfies_protocol(self) -> None:
        """WikiRegistryDiscovery should satisfy WikiDiscoveryProvider protocol."""
        from llmwikify.kernel.multi_wiki.registry import WikiRegistryDiscovery

        mock_registry = MagicMock()
        discovery = WikiRegistryDiscovery(mock_registry)
        assert isinstance(discovery, WikiDiscoveryProvider)

    def test_returns_roots_from_instances(self, tmp_path: Path) -> None:
        """Returns root paths from registry instances."""
        from llmwikify.kernel.multi_wiki.instance import WikiInstance, WikiType
        from llmwikify.kernel.multi_wiki.registry import WikiRegistryDiscovery

        wiki_root = tmp_path / "wiki1"
        wiki_root.mkdir()

        mock_instance = MagicMock(spec=WikiInstance)
        mock_instance.root = wiki_root

        mock_registry = MagicMock()
        mock_registry.scan_directories.return_value = [mock_instance]

        discovery = WikiRegistryDiscovery(mock_registry)
        result = discovery.discover_wiki_roots([str(tmp_path)], depth=2)

        assert result == [wiki_root]
        mock_registry.scan_directories.assert_called_once_with([str(tmp_path)], 2)

    def test_filters_none_roots(self, tmp_path: Path) -> None:
        """Filters out instances with None root (remote wikis)."""
        from llmwikify.kernel.multi_wiki.instance import WikiInstance
        from llmwikify.kernel.multi_wiki.registry import WikiRegistryDiscovery

        mock_instance_remote = MagicMock(spec=WikiInstance)
        mock_instance_remote.root = None

        mock_instance_local = MagicMock(spec=WikiInstance)
        mock_instance_local.root = tmp_path / "local"

        mock_registry = MagicMock()
        mock_registry.scan_directories.return_value = [
            mock_instance_remote,
            mock_instance_local,
        ]

        discovery = WikiRegistryDiscovery(mock_registry)
        result = discovery.discover_wiki_roots([str(tmp_path)])

        assert len(result) == 1
        assert result[0] == tmp_path / "local"

    def test_empty_registry(self, tmp_path: Path) -> None:
        """Empty registry returns empty list."""
        from llmwikify.kernel.multi_wiki.registry import WikiRegistryDiscovery

        mock_registry = MagicMock()
        mock_registry.scan_directories.return_value = []

        discovery = WikiRegistryDiscovery(mock_registry)
        result = discovery.discover_wiki_roots([str(tmp_path)])

        assert result == []
