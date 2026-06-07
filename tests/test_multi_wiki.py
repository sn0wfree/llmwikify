"""Tests for multi-wiki management system (Phase 1)."""

import pytest
from pathlib import Path
from datetime import datetime

from llmwikify.core.wiki_instance import WikiInstance, WikiType, WikiStatus
from llmwikify.core.wiki_discovery import WikiDiscovery
from llmwikify.core.remote_wiki import RemoteWiki
from llmwikify.core.wiki_registry import WikiRegistry


class TestWikiInstance:
    """Tests for WikiInstance dataclass."""

    def test_create_local_instance(self, tmp_path):
        """Create a local wiki instance."""
        instance = WikiInstance(
            wiki_id="test-wiki",
            name="Test Wiki",
            wiki_type=WikiType.LOCAL,
            root=tmp_path,
        )

        assert instance.wiki_id == "test-wiki"
        assert instance.name == "Test Wiki"
        assert instance.wiki_type == WikiType.LOCAL
        assert instance.root == tmp_path
        assert instance.status == WikiStatus.READY

    def test_create_remote_instance(self):
        """Create a remote wiki instance."""
        instance = WikiInstance(
            wiki_id="remote-wiki",
            name="Remote Wiki",
            wiki_type=WikiType.REMOTE,
            root=None,
            url="http://localhost:8765",
        )

        assert instance.wiki_id == "remote-wiki"
        assert instance.wiki_type == WikiType.REMOTE
        assert instance.root is None
        assert instance.url == "http://localhost:8765"

    def test_to_dict(self, tmp_path):
        """Convert instance to dictionary."""
        instance = WikiInstance(
            wiki_id="test-wiki",
            name="Test Wiki",
            wiki_type=WikiType.LOCAL,
            root=tmp_path,
            page_count=42,
        )

        d = instance.to_dict()
        assert d["wiki_id"] == "test-wiki"
        assert d["name"] == "Test Wiki"
        assert d["type"] == "local"
        assert d["root"] == str(tmp_path)
        assert d["page_count"] == 42

    def test_from_dict(self, tmp_path):
        """Create instance from dictionary."""
        d = {
            "wiki_id": "test-wiki",
            "name": "Test Wiki",
            "type": "local",
            "root": str(tmp_path),
            "status": "ready",
        }

        instance = WikiInstance.from_dict(d)
        assert instance.wiki_id == "test-wiki"
        assert instance.root == tmp_path

    def test_from_dict_remote(self):
        """Create remote instance from dictionary."""
        d = {
            "wiki_id": "remote-wiki",
            "name": "Remote Wiki",
            "type": "remote",
            "url": "http://localhost:8765",
        }

        instance = WikiInstance.from_dict(d)
        assert instance.wiki_type == WikiType.REMOTE
        assert instance.url == "http://localhost:8765"


class TestWikiDiscovery:
    """Tests for WikiDiscovery scanner."""

    def test_scan_single_wiki(self, tmp_path):
        """Discover a single wiki in directory."""
        wiki_dir = tmp_path / "my-wiki"
        wiki_dir.mkdir()
        db_file = wiki_dir / ".llmwikify.db"
        db_file.write_text("")

        scanner = WikiDiscovery()
        results = scanner.scan([str(tmp_path)], depth=1)

        assert len(results) == 1
        assert results[0]["wiki_id"] == "my-wiki"
        assert results[0]["root"] == wiki_dir

    def test_scan_nested_wikis(self, tmp_path):
        """Discover wikis at different depths, but not nested within a wiki."""
        wiki_a = tmp_path / "wiki-a"
        wiki_a.mkdir()
        (wiki_a / ".llmwikify.db").write_text("")

        wiki_b = tmp_path / "subdir" / "wiki-b"
        wiki_b.mkdir(parents=True)
        (wiki_b / ".llmwikify.db").write_text("")

        scanner = WikiDiscovery()
        results = scanner.scan([str(tmp_path)], depth=2)

        wiki_ids = [r["wiki_id"] for r in results]
        assert "wiki-a" in wiki_ids
        assert "wiki-b" in wiki_ids

    def test_scan_nested_within_wiki_skipped(self, tmp_path):
        """When a wiki is found, its subdirectories are not scanned."""
        outer_wiki = tmp_path / "outer-wiki"
        outer_wiki.mkdir()
        (outer_wiki / ".llmwikify.db").write_text("")

        inner_wiki = outer_wiki / "inner-wiki"
        inner_wiki.mkdir()
        (inner_wiki / ".llmwikify.db").write_text("")

        scanner = WikiDiscovery()
        results = scanner.scan([str(tmp_path)], depth=5)

        wiki_ids = [r["wiki_id"] for r in results]
        assert "outer-wiki" in wiki_ids
        assert "inner-wiki" not in wiki_ids

    def test_exclude_patterns(self, tmp_path):
        """Respect exclude patterns."""
        node_modules = tmp_path / "node_modules" / "my-wiki"
        node_modules.mkdir(parents=True)
        (node_modules / ".llmwikify.db").write_text("")

        normal = tmp_path / "my-wiki"
        normal.mkdir()
        (normal / ".llmwikify.db").write_text("")

        scanner = WikiDiscovery()
        results = scanner.scan([str(tmp_path)], depth=3)

        wiki_ids = [r["wiki_id"] for r in results]
        assert "my-wiki" in wiki_ids
        assert "node_modules" not in [str(r["root"]) for r in results]

    def test_nonexistent_path(self):
        """Handle non-existent scan path gracefully."""
        scanner = WikiDiscovery()
        results = scanner.scan(["/nonexistent/path"], depth=1)
        assert results == []


class TestRemoteWiki:
    """Tests for RemoteWiki HTTP client."""

    def test_init(self):
        """Initialize RemoteWiki client."""
        client = RemoteWiki(
            url="http://localhost:8765",
            api_key="test-key",
            timeout=30,
        )

        assert client.url == "http://localhost:8765"
        assert client.api_key == "test-key"
        assert client.timeout == 30

    def test_get_headers(self):
        """Get request headers with auth."""
        client = RemoteWiki(url="http://localhost:8765", api_key="test-key")
        headers = client._get_headers()

        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-key"

    def test_get_headers_no_auth(self):
        """Get request headers without auth."""
        client = RemoteWiki(url="http://localhost:8765")
        headers = client._get_headers()

        assert "Authorization" not in headers

    def test_close(self):
        """Close HTTP session."""
        from unittest.mock import MagicMock

        client = RemoteWiki(url="http://localhost:8765")
        client._session = MagicMock()
        client.close()
        assert client._session is None


class TestWikiRegistry:
    """Tests for WikiRegistry."""

    def test_init(self):
        """Initialize WikiRegistry."""
        config = {"wikis": {"default": "test-wiki"}}
        registry = WikiRegistry(config)
        # Note: _default_wiki_id is set during initialize(), not __init__
        assert registry._config["wikis"]["default"] == "test-wiki"

    def test_register_local_wiki(self, tmp_path):
        """Register a local wiki."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        instance = registry.register_wiki(
            wiki_id="test-wiki",
            name="Test Wiki",
            root=tmp_path,
        )

        assert instance.wiki_id == "test-wiki"
        assert "test-wiki" in registry._instances

    def test_register_remote_wiki(self):
        """Register a remote wiki."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        instance = registry.register_remote(
            wiki_id="remote-wiki",
            name="Remote Wiki",
            url="http://localhost:8765",
        )

        assert instance.wiki_id == "remote-wiki"
        assert instance.wiki_type == WikiType.REMOTE
        assert "remote-wiki" in registry._remote_clients

    def test_unregister_wiki(self, tmp_path):
        """Remove wiki from registry."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        registry.register_wiki(
            wiki_id="test-wiki",
            name="Test Wiki",
            root=tmp_path,
        )

        registry.unregister_wiki("test-wiki")
        assert "test-wiki" not in registry._instances

    def test_unregister_nonexistent_wiki(self):
        """Raise error when unregistering non-existent wiki."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        with pytest.raises(KeyError):
            registry.unregister_wiki("nonexistent")

    def test_list_wikis(self, tmp_path):
        """List all registered wikis."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        registry.register_wiki("wiki-a", "Wiki A", tmp_path / "a")
        registry.register_wiki("wiki-b", "Wiki B", tmp_path / "b")

        wikis = registry.list_wikis()
        assert len(wikis) == 2

    def test_set_default_wiki(self, tmp_path):
        """Set default wiki."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        registry.register_wiki("wiki-a", "Wiki A", tmp_path / "a")
        registry.register_wiki("wiki-b", "Wiki B", tmp_path / "b")

        registry.set_default_wiki("wiki-b")
        assert registry.get_default_wiki_id() == "wiki-b"
        assert registry._instances["wiki-b"].is_default is True
        assert registry._instances["wiki-a"].is_default is False

    def test_set_default_nonexistent_wiki(self, tmp_path):
        """Raise error when setting non-existent wiki as default."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        with pytest.raises(KeyError):
            registry.set_default_wiki("nonexistent")

    def test_get_wiki_instance(self, tmp_path):
        """Get WikiInstance by ID."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        registry.register_wiki("test-wiki", "Test Wiki", tmp_path)
        instance = registry.get_wiki_instance("test-wiki")

        assert instance.wiki_id == "test-wiki"

    def test_get_wiki_instance_nonexistent(self):
        """Raise error for non-existent wiki."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        with pytest.raises(KeyError):
            registry.get_wiki_instance("nonexistent")

    def test_scan_directories(self, tmp_path):
        """Scan directories for wikis."""
        # Create wiki directories
        wiki_a = tmp_path / "wiki-a"
        wiki_a.mkdir()
        (wiki_a / ".llmwikify.db").write_text("")

        wiki_b = tmp_path / "wiki-b"
        wiki_b.mkdir()
        (wiki_b / ".llmwikify.db").write_text("")

        config = {"wikis": {}}
        registry = WikiRegistry(config)

        new_wikis = registry.scan_directories([str(tmp_path)], depth=1)

        assert len(new_wikis) == 2
        wiki_ids = [w.wiki_id for w in new_wikis]
        assert "wiki-a" in wiki_ids
        assert "wiki-b" in wiki_ids

    def test_scan_skips_registered(self, tmp_path):
        """Skip already registered wikis during scan."""
        # Create wiki directory
        wiki_dir = tmp_path / "my-wiki"
        wiki_dir.mkdir()
        (wiki_dir / ".llmwikify.db").write_text("")

        config = {"wikis": {}}
        registry = WikiRegistry(config)

        # Pre-register the wiki
        registry.register_wiki("my-wiki", "My Wiki", wiki_dir)

        # Scan should not add duplicates
        new_wikis = registry.scan_directories([str(tmp_path)], depth=1)
        assert len(new_wikis) == 0

    def test_close(self, tmp_path):
        """Close registry and clean up resources."""
        config = {"wikis": {}}
        registry = WikiRegistry(config)

        registry.register_wiki("test-wiki", "Test Wiki", tmp_path)
        registry.close()

        assert len(registry._instances) == 0
        assert len(registry._wiki_objects) == 0


class TestConfigWikis:
    """Tests for wikis configuration."""

    def test_get_wikis_config_default(self):
        """Get default wikis configuration."""
        from llmwikify.foundation.config import get_wikis_config

        config = get_wikis_config()
        assert config["default"] is None
        assert config["local"] == []
        assert config["remote"] == []
        assert config["discovery"]["enabled"] is False

    def test_get_wikis_config_custom(self):
        """Get custom wikis configuration."""
        from llmwikify.foundation.config import get_wikis_config

        custom_config = {
            "wikis": {
                "default": "my-wiki",
                "local": [{"id": "my-wiki", "path": "."}],
            }
        }

        config = get_wikis_config(custom_config)
        assert config["default"] == "my-wiki"
        assert len(config["local"]) == 1
