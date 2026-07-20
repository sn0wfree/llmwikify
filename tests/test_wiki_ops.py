"""Tests for wiki._wiki_ops — wiki operations helpers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from llmwikify.interfaces.server.http.wiki._wiki_ops import (
    enrich_status,
    load_wiki_config,
    wiki_or_404,
    write_page,
)


class TestWikiOr404:
    """Tests for wiki_or_404() context manager."""

    def test_returns_wiki(self) -> None:
        """Returns wiki when found."""
        mock_wiki = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_wiki.return_value = mock_wiki

        with wiki_or_404(mock_registry, "test_id") as wiki:
            assert wiki is mock_wiki

    def test_raises_404_on_key_error(self) -> None:
        """Raises HTTPException(404) when wiki not found."""
        mock_registry = MagicMock()
        mock_registry.get_wiki.side_effect = KeyError("not found")

        with pytest.raises(HTTPException) as exc_info:
            with wiki_or_404(mock_registry, "missing_id"):
                pass

        assert exc_info.value.status_code == 404
        assert "missing_id" in exc_info.value.detail

    def test_does_not_raise_on_success(self) -> None:
        """Does not raise when wiki is found."""
        mock_wiki = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_wiki.return_value = mock_wiki

        # Should not raise
        with wiki_or_404(mock_registry, "test_id"):
            pass

    def test_yields_correct_wiki(self) -> None:
        """Yields the correct wiki instance."""
        mock_wiki = MagicMock()
        mock_wiki.status.return_value = {"pages": 10}
        mock_registry = MagicMock()
        mock_registry.get_wiki.return_value = mock_wiki

        with wiki_or_404(mock_registry, "test_id") as wiki:
            status = wiki.status()
            assert status == {"pages": 10}


class TestEnrichStatus:
    """Tests for enrich_status() function."""

    def test_adds_all_types(self) -> None:
        """Adds all_types from pages_by_type."""
        status = {"pages_by_type": {"note": 5, "concept": 3}}
        result = enrich_status(status)
        assert set(result["all_types"]) == {"note", "concept"}

    def test_no_pages_by_type(self) -> None:
        """Returns unchanged when no pages_by_type."""
        status = {"pages": 10}
        result = enrich_status(status)
        assert result == {"pages": 10}


class TestWritePage:
    """Tests for write_page() function."""

    def test_empty_page_name_raises(self) -> None:
        """Raises 400 when page_name is empty."""
        mock_wiki = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            write_page(mock_wiki, "", "content")
        assert exc_info.value.status_code == 400

    def test_success(self) -> None:
        """Returns success dict."""
        mock_wiki = MagicMock()
        mock_wiki.write_page.return_value = "Page written"
        result = write_page(mock_wiki, "test_page", "content")
        assert result == {"message": "Page written", "page_name": "test_page"}

    def test_value_error_raises_400(self) -> None:
        """Raises 400 on ValueError."""
        mock_wiki = MagicMock()
        mock_wiki.write_page.side_effect = ValueError("invalid name")
        with pytest.raises(HTTPException) as exc_info:
            write_page(mock_wiki, "bad/name", "content")
        assert exc_info.value.status_code == 400


class TestLoadWikiConfig:
    """Tests for load_wiki_config() function."""

    def test_returns_default_when_no_config(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns default config when file doesn't exist."""
        from llmwikify.foundation.config import Config

        # Reset Config singleton
        Config._instance = None
        monkeypatch.setattr(Path, "home", lambda: tmp_path)

        result = load_wiki_config()
        assert "allowed_remote_hosts" in result
        assert result["allowed_remote_hosts"] == ["*"]
