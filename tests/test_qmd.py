"""Unit tests for QMD hybrid search integration."""

import json
import sys
from pathlib import Path

import pytest

from llmwikify.core import Wiki


class TestQmdConfig:
    """Tests for QMD configuration handling."""

    @pytest.fixture
    def wiki(self, tmp_path):
        w = Wiki(tmp_path)
        w.init()
        yield w
        w.close()

    def test_search_config_default(self, wiki):
        """Default search backend should be 'fts5'."""
        from llmwikify.config import get_search_config
        config = get_search_config(wiki.config)
        assert "backend" in config
        assert "qmd" in config

    def test_qmd_config_defaults(self, wiki):
        """QMD default configuration should be set."""
        from llmwikify.config import get_search_config
        config = get_search_config(wiki.config)
        qmd_config = config["qmd"]
        assert "host" in qmd_config
        assert "port" in qmd_config
        assert qmd_config["host"] == "127.0.0.1"
        assert qmd_config["port"] == 8181


class TestWikiIndexQmdSupport:
    """Tests for QMD backend support in WikiIndex."""

    @pytest.fixture
    def wiki(self, tmp_path):
        w = Wiki(tmp_path)
        w.init()
        yield w
        w.close()

    def test_search_accepts_backend_param(self, wiki):
        """Search method should accept backend parameter."""
        wiki.write_page("TestPage", "# Test\nSome content here")
        # Should not error with backend="fts5"
        results = wiki.index.search("content", limit=10, backend="fts5")
        assert isinstance(results, list)

    def test_search_qmd_backend_falls_back_gracefully(self, wiki):
        """QMD backend should fall back to FTS5 when QMD not available."""
        wiki.write_page("TestPage", "# Test\nSome content here")
        # Calling with qmd backend should not raise, just use fts5
        results = wiki.index.search("content", limit=10, backend="qmd")
        # Should still get results from FTS5 fallback
        assert isinstance(results, list)

    def test_search_results_include_mode(self, wiki):
        """Search results should include mode indicator."""
        wiki.write_page("TestPage", "# Test\nSome content here")
        results = wiki.index.search("content", limit=10, backend="fts5")
        assert len(results) > 0
        assert "mode" in results[0]
        assert results[0]["mode"] == "fts5"

    def test_get_qmd_recommendation_few_pages(self, wiki):
        """Should not recommend QMD for small wikis (< 1000 pages)."""
        wiki.write_page("TestPage", "# Test\nSome content here")
        recommendation = wiki.index.get_qmd_recommendation()
        assert "recommended" in recommendation
        # Small wiki should not recommend QMD
        assert recommendation["recommended"] is False

    def test_qmd_status_method(self, wiki):
        """Wiki qmd_status() should return proper structure."""
        status = wiki.qmd_status()
        assert isinstance(status, dict)
        assert "available" in status
        assert "recommended" in status
        assert "page_count" in status
        assert "backend" in status
        assert status["backend"] == "fts5"  # default


class TestQmdClient:
    """Tests for QmdClient class (QMD not available in test env)."""

    def test_client_can_be_imported(self):
        """QmdClient should be importable."""
        from llmwikify.core.qmd_client import QmdClient
        assert QmdClient is not None

    def test_client_init_with_defaults(self):
        """QmdClient should initialize with default host/port."""
        from llmwikify.core.qmd_client import QmdClient
        client = QmdClient()
        assert client.host == "127.0.0.1"
        assert client.port == 8181

    def test_client_init_with_custom_host_port(self):
        """QmdClient should accept custom host/port."""
        from llmwikify.core.qmd_client import QmdClient
        client = QmdClient(host="localhost", port=8080)
        assert client.host == "localhost"
        assert client.port == 8080

    def test_is_available_returns_false_when_not_running(self):
        """QmdClient.is_available() should return False when QMD not running."""
        from llmwikify.core.qmd_client import QmdClient
        client = QmdClient(port=9999)  # Use unlikely port
        result = client.is_available()
        # Should not raise, and return False since QMD not running
        assert result is False

    def test_health_returns_dict(self):
        """QmdClient.health() should return dict even when not available."""
        from llmwikify.core.qmd_client import QmdClient
        client = QmdClient(port=9999)
        result = client.health()
        assert isinstance(result, dict)

    def test_get_install_guide(self):
        """QmdClient should provide installation instructions."""
        from llmwikify.core.qmd_client import QmdClient
        guide = QmdClient.get_install_guide(QmdClient())
        assert isinstance(guide, str)
        assert "QMD" in guide
        assert "npm install" in guide
        assert "mcp" in guide


class TestQmdIndex:
    """Tests for QmdIndex wrapper class."""

    @pytest.fixture
    def wiki_root(self, tmp_path):
        return tmp_path

    def test_qmd_index_init(self, wiki_root):
        """QmdIndex should initialize correctly."""
        from llmwikify.core.qmd_index import QmdIndex
        qmd = QmdIndex(wiki_root)
        assert qmd.host == "127.0.0.1"
        assert qmd.port == 8181

    def test_qmd_index_with_custom_config(self, wiki_root):
        """QmdIndex should use custom config values."""
        from llmwikify.core.qmd_index import QmdIndex
        config = {
            "search": {
                "qmd": {
                    "host": "qmd-host",
                    "port": 8182,
                }
            }
        }
        qmd = QmdIndex(wiki_root, config=config)
        assert qmd.host == "qmd-host"
        assert qmd.port == 8182

    def test_search_returns_empty_list_when_not_available(self, wiki_root):
        """QmdIndex.search() should return empty list when QMD not available."""
        from llmwikify.core.qmd_index import QmdIndex
        qmd = QmdIndex(wiki_root)
        results = qmd.search("test")
        assert results == []

    def test_embed_returns_dict(self, wiki_root):
        """QmdIndex.embed() should return dict even when not available."""
        from llmwikify.core.qmd_index import QmdIndex
        qmd = QmdIndex(wiki_root)
        result = qmd.embed()
        assert isinstance(result, dict)
