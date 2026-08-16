"""Tests for Jina Search + Jina Reader extractor integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── JinaSearchProvider ────────────────────────────────────────────────


def test_jina_search_returns_results():
    from llmwikify.apps.research.web_search import JinaSearchProvider, SearchResult

    provider = JinaSearchProvider()

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"title": "Page 1", "url": "https://example.com/1", "content": "Content about AI"},
            {"title": "Page 2", "url": "https://example.com/2", "content": "Content about ML"},
        ]
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=AsyncMock(
            get=AsyncMock(return_value=mock_response)
        ))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        results = asyncio.run(provider.search("AI research", 2))

    assert len(results) == 2
    assert results[0].title == "Page 1"
    assert results[0].url == "https://example.com/1"
    assert "AI" in results[0].snippet


def test_jina_search_returns_empty_on_failure():
    from llmwikify.apps.research.web_search import JinaSearchProvider

    provider = JinaSearchProvider()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=AsyncMock(
            get=AsyncMock(side_effect=Exception("network error"))
        ))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        results = asyncio.run(provider.search("test", 5))

    assert results == []


def test_jina_search_truncates_snippet():
    from llmwikify.apps.research.web_search import JinaSearchProvider

    provider = JinaSearchProvider()
    long_content = "x" * 1000

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [{"title": "T", "url": "http://x.com", "content": long_content}]
    }

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__ = AsyncMock(return_value=AsyncMock(
            get=AsyncMock(return_value=mock_response)
        ))
        mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
        results = asyncio.run(provider.search("q", 1))

    assert len(results[0].snippet) <= 500


# ── Jina Reader extractor ────────────────────────────────────────────


def test_jina_reader_extractor():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "title": "Test Article",
            "content": "# Test\n\nThis is test content from Jina Reader.",
        }
    }

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/article")

    assert result is not None
    assert result.title == "Test Article"
    assert "Test" in result.text
    assert result.metadata["via"] == "jina"


def test_jina_reader_extractor_failure():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    with patch("httpx.get", side_effect=Exception("timeout")):
        result = extract_via_jina("https://example.com/article")

    assert result is None


def test_jina_reader_empty_content():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"title": "", "content": ""}}

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/empty")

    assert result is None


# ── Fallback chain ───────────────────────────────────────────────────


def test_web_extractor_falls_back_to_jina():
    """When trafilatura extraction returns short content, web extractor falls back to Jina."""
    from llmwikify.foundation.extractors.web import _extract_url

    # Mock trafilatura to return very short content (below threshold)
    mock_trafilatura = MagicMock()
    mock_trafilatura.fetch_url.return_value = "<html><body>short</body></html>"
    mock_trafilatura.extract.return_value = "short"

    # Mock Jina to return good content
    mock_jina_result = MagicMock()
    mock_jina_result.text = "Content from Jina Reader " * 10  # > 100 chars
    mock_jina_result.title = "Jina Title"
    mock_jina_result.metadata = {"via": "jina"}

    with patch.dict("sys.modules", {"trafilatura": mock_trafilatura}):
        with patch("llmwikify.foundation.extractors.jina.extract_via_jina", return_value=mock_jina_result):
            result = _extract_url("https://example.com/article")

    assert result is not None
    assert "Jina" in result.text


def test_create_search_provider_includes_jina():
    from llmwikify.apps.research.web_search import (
        JinaSearchProvider,
        create_search_provider,
    )

    provider = create_search_provider({"search_provider": "auto"})
    # Jina should be first in the chain
    assert isinstance(provider.providers[0], JinaSearchProvider)
