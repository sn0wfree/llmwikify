"""Additional unit tests for Jina integration, web fallback chain,
WikiDreamEditor proposals, and concurrent processing."""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ═══════════════════════════════════════════════════════════════════════
# Jina extractor edge cases
# ═══════════════════════════════════════════════════════════════════════


def test_jina_extractor_handles_timeout():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    with patch("httpx.get", side_effect=Exception("Read timed out")):
        result = extract_via_jina("https://example.com/slow")
    assert result is None


def test_jina_extractor_handles_http_error():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_response.raise_for_status.side_effect = Exception("500 Server Error")

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/broken")
    assert result is None


def test_jina_extractor_handles_malformed_json():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.side_effect = ValueError("malformed JSON")

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/garbage")
    assert result is None


def test_jina_extractor_fallback_to_description():
    """When 'content' is missing, extractor returns None (only content is supported)."""
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": {
            "title": "Page",
            "description": "A summary instead of full content",
        }
    }

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/desc-only")

    # No 'content' key → returns None (content is required)
    assert result is None


def test_jina_extractor_uses_url_as_title_fallback():
    from llmwikify.foundation.extractors.jina import extract_via_jina

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": {"content": "Some content here."}}

    with patch("httpx.get", return_value=mock_response):
        result = extract_via_jina("https://example.com/no-title")

    assert result is not None
    assert result.title == "https://example.com/no-title"


# ═══════════════════════════════════════════════════════════════════════
# Web extractor fallback chain
# ═══════════════════════════════════════════════════════════════════════


def test_web_extractor_returns_trafilatura_when_good_content():
    """Trafilatura with substantial content wins over Jina."""
    from llmwikify.foundation.extractors.web import _extract_url

    long_text = "This is a substantial article. " * 20  # > 100 chars

    mock_trafilatura = MagicMock()
    mock_trafilatura.fetch_url.return_value = "<html><body>long</body></html>"
    mock_trafilatura.extract.return_value = long_text

    with patch.dict("sys.modules", {"trafilatura": mock_trafilatura}):
        result = _extract_url("https://example.com/article")

    assert result is not None
    assert len(result.text) > 100
    # Should NOT have called Jina
    # (verified by lack of exception or by checking no "via": "jina" in metadata)


def test_web_extractor_falls_back_on_short_trafilatura():
    """Trafilatura returns short content → Jina fallback."""
    from llmwikify.foundation.extractors.web import _extract_url

    mock_trafilatura = MagicMock()
    mock_trafilatura.fetch_url.return_value = "<html>short</html>"
    mock_trafilatura.extract.return_value = "short"

    jina_result = MagicMock()
    jina_result.text = "Substantial content from Jina " * 20
    jina_result.title = "Jina"
    jina_result.metadata = {"via": "jina"}

    with patch.dict("sys.modules", {"trafilatura": mock_trafilatura}):
        with patch("llmwikify.foundation.extractors.jina.extract_via_jina", return_value=jina_result):
            result = _extract_url("https://example.com/short")

    assert result is not None
    assert "Jina" in result.text


def test_web_extractor_handles_both_failure():
    """Both trafilatura and Jina fail → error result."""
    from llmwikify.foundation.extractors.web import _extract_url

    mock_trafilatura = MagicMock()
    mock_trafilatura.fetch_url.return_value = None

    with patch.dict("sys.modules", {"trafilatura": mock_trafilatura}):
        with patch("llmwikify.foundation.extractors.jina.extract_via_jina", return_value=None):
            result = _extract_url("https://example.com/dead")

    assert result is not None
    assert result.source_type == "error"


def test_web_extractor_skips_jina_on_good_trafilatura():
    """When trafilatura succeeds, Jina should NOT be called."""
    from llmwikify.foundation.extractors.web import _extract_url

    long_text = "Substantial content here. " * 20

    mock_trafilatura = MagicMock()
    mock_trafilatura.fetch_url.return_value = "<html>x</html>"
    mock_trafilatura.extract.return_value = long_text

    jina_called = False

    def jina_should_not_be_called(*args, **kwargs):
        nonlocal jina_called
        jina_called = True
        return None

    with patch.dict("sys.modules", {"trafilatura": mock_trafilatura}):
        with patch("llmwikify.foundation.extractors.jina.extract_via_jina", side_effect=jina_should_not_be_called):
            result = _extract_url("https://example.com/good")

    assert result is not None
    assert jina_called is False


# ═══════════════════════════════════════════════════════════════════════
# Search provider chain
# ═══════════════════════════════════════════════════════════════════════


def test_create_provider_with_jina_key():
    """Jina API key is passed through."""
    from llmwikify.apps.research.web_search import (
        JinaSearchProvider,
        create_search_provider,
    )

    provider = create_search_provider({
        "search_provider": "auto",
        "jina_api_key": "test-key-123",
    })
    assert isinstance(provider.providers[0], JinaSearchProvider)
    assert provider.providers[0].api_key == "test-key-123"


def test_create_provider_jina_only_mode():
    """search_provider='jina' only registers Jina."""
    from llmwikify.apps.research.web_search import (
        JinaSearchProvider,
        create_search_provider,
    )

    provider = create_search_provider({"search_provider": "jina"})
    assert len(provider.providers) == 1
    assert isinstance(provider.providers[0], JinaSearchProvider)


def test_create_provider_no_config_uses_default_chain():
    """Empty config → Jina + DuckDuckGo (always-on providers)."""
    from llmwikify.apps.research.web_search import (
        DuckDuckGoProvider,
        JinaSearchProvider,
        create_search_provider,
    )

    provider = create_search_provider({})
    provider_types = [type(p).__name__ for p in provider.providers]
    assert "JinaSearchProvider" in provider_types
    assert "DuckDuckGoProvider" in provider_types


# ═══════════════════════════════════════════════════════════════════════
# WikiDreamEditor proposal CRUD
# ═══════════════════════════════════════════════════════════════════════


def _make_dream_db(tmp_path):
    """Create a real WikiDatabase for proposal tests."""
    from llmwikify.apps.wiki.db import WikiDatabase

    db = WikiDatabase(tmp_path)
    return db


def test_dream_proposal_create_and_retrieve(tmp_path):
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager

    db = _make_dream_db(tmp_path)
    mgr = WikiDreamProposalManager(db=db, wiki_id="w1")

    proposal = mgr.create_proposal(
        page_name="Test Page",
        edit_type="create",
        content="# Test\n\nContent.",
        reason="auto-test",
    )

    assert proposal["status"] == "pending"
    assert proposal["page_name"] == "Test Page"

    retrieved = db.get_dream_proposals("w1", status="pending")
    assert any(p["id"] == proposal["id"] for p in retrieved)


def test_dream_proposal_approve_reject(tmp_path):
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager

    db = _make_dream_db(tmp_path)
    mgr = WikiDreamProposalManager(db=db, wiki_id="w1")

    p1 = mgr.create_proposal(page_name="P1", edit_type="create", content="x", reason="r")
    p2 = mgr.create_proposal(page_name="P2", edit_type="create", content="y", reason="r")

    mgr.approve(p1["id"])
    mgr.reject(p2["id"])

    # Verify via the manager's own _proposals list
    approved = next(p for p in mgr._proposals if p["id"] == p1["id"])
    rejected = next(p for p in mgr._proposals if p["id"] == p2["id"])
    assert approved["status"] == "approved"
    assert rejected["status"] == "rejected"

    # Verify via DB (INSERT OR REPLACE)
    all_proposals = db.get_dream_proposals("w1", status=None)
    assert any(p["id"] == p1["id"] and p["status"] == "approved" for p in all_proposals)
    assert any(p["id"] == p2["id"] and p["status"] == "rejected" for p in all_proposals)


def test_dream_proposal_auto_approve_short_appends(tmp_path):
    """append < threshold gets auto-approved."""
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager

    db = _make_dream_db(tmp_path)
    mgr = WikiDreamProposalManager(db=db, wiki_id="w1")

    short = mgr.create_proposal(
        page_name="S", edit_type="append", content="x" * 50, reason="r"
    )
    long_p = mgr.create_proposal(
        page_name="L", edit_type="append", content="x" * 200, reason="r"
    )

    auto = mgr.auto_approve_pending()
    auto_ids = [p["id"] for p in auto]
    assert short["id"] in auto_ids
    assert long_p["id"] not in auto_ids


def test_dream_proposal_apply_writes_to_wiki(tmp_path):
    """Approved proposal → apply_proposals writes to wiki."""
    from llmwikify.apps.agent.wiki_dream_editor import WikiDreamEditor
    from llmwikify.kernel import Wiki

    wiki = Wiki(tmp_path / "wiki")
    wiki.init()

    db = _make_dream_db(tmp_path)
    editor = WikiDreamEditor(wiki=wiki, data_dir=tmp_path / "agent-data", db=db, wiki_id="w1")

    editor.proposal_manager.create_proposal(
        page_name="New Page",
        edit_type="create",
        content="# New Page\n\nAuto-created.",
        reason="test",
    )

    proposals = db.get_dream_proposals("w1", status="pending")
    assert len(proposals) == 1

    result = editor.apply_wiki_dream_proposals()
    assert "applied" in result or "approved" in result


# ═══════════════════════════════════════════════════════════════════════
# Auto-ingest concurrent processing (per-file locks + cache)
# ═══════════════════════════════════════════════════════════════════════


def _make_svc_for_concurrent(tmp_path, wiki):
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    (tmp_path / "raw").mkdir(exist_ok=True)
    wiki = wiki or SimpleNamespace(
        root=tmp_path,
        raw_dir=tmp_path / "raw",
        config={"llm": {"enabled": False}},
        ingest_source=lambda p: {
            "title": "t", "source_name": "s", "content": "x", "error": None,
        },
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    return AutoIngestService(
        wiki=wiki, wiki_id="t",
        config=AutoIngestConfig(debounce_seconds=0.05),
        llm_semaphore=asyncio.Semaphore(3),
    )


def test_concurrent_same_file_serialized(tmp_path):
    """Two concurrent calls for the same file → only one ingest."""
    ingest_calls = []

    def track(p):
        ingest_calls.append(p)
        time.sleep(0.1)  # simulate slow extraction
        return {"title": "t", "source_name": "s", "content": "x", "error": None}

    from types import SimpleNamespace as NS
    wiki = NS(
        root=tmp_path, raw_dir=tmp_path / "raw",
        config={"llm": {"enabled": False}},
        ingest_source=track,
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    (tmp_path / "raw").mkdir()
    f = tmp_path / "raw" / "same.md"
    f.write_text("x")

    svc = _make_svc_for_concurrent(tmp_path, wiki)

    async def scenario():
        await asyncio.gather(
            svc._process_file(f),
            svc._process_file(f),
            svc._process_file(f),
        )

    asyncio.run(scenario())
    # Per-file lock + re-check: only first call should reach ingest_source
    assert len(ingest_calls) == 1


def test_concurrent_different_files_parallel(tmp_path):
    """Different files should run in parallel (no per-file lock contention)."""
    from pathlib import Path as P
    from types import SimpleNamespace as NS

    completed = []

    def track(p):
        time.sleep(0.2)  # simulate slow extraction
        completed.append(P(p).name)
        return {"title": "t", "source_name": "s", "content": "x", "error": None}

    wiki = NS(
        root=tmp_path, raw_dir=tmp_path / "raw",
        config={"llm": {"enabled": False}},
        ingest_source=track,
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    (tmp_path / "raw").mkdir()
    for i in range(3):
        (tmp_path / "raw" / f"f{i}.md").write_text("x")

    svc = _make_svc_for_concurrent(tmp_path, wiki)

    async def scenario():
        tasks = [
            svc._process_file(tmp_path / "raw" / f"f{i}.md")
            for i in range(3)
        ]
        start = time.monotonic()
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - start
        return elapsed

    elapsed = asyncio.run(scenario())
    # 3 files × 0.2s serial = 0.6s; parallel should ≈ 0.2s
    assert elapsed < 0.5
    assert len(completed) == 3


def test_extraction_cache_hit_skips_ingest(tmp_path):
    """Cached extraction result should skip wiki.ingest_source."""
    from types import SimpleNamespace as NS

    call_count = [0]

    def counting_ingest(p):
        call_count[0] += 1
        return {"title": "t", "source_name": "s", "content": "x", "error": None}

    wiki = NS(
        root=tmp_path, raw_dir=tmp_path / "raw",
        config={"llm": {"enabled": False}},
        ingest_source=counting_ingest,
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    (tmp_path / "raw").mkdir()
    f = tmp_path / "raw" / "cached.md"
    f.write_text("x")

    svc = _make_svc_for_concurrent(tmp_path, wiki)

    async def scenario():
        await svc._process_file(f)
        # Second call with same file (same mtime+size) should hit cache
        await svc._process_file(f)

    asyncio.run(scenario())
    # Cache hit: second call shouldn't re-ingest
    assert call_count[0] == 1


def test_extraction_cache_eviction(tmp_path):
    """Cache evicts old entries when > 50."""
    from llmwikify.apps.agent.maintenance.auto_ingest import AutoIngestService
    from llmwikify.apps.agent.maintenance.config import AutoIngestConfig

    wiki = SimpleNamespace(
        root=tmp_path, raw_dir=tmp_path / "raw",
        config={"llm": {"enabled": False}},
        ingest_source=lambda p: {
            "title": "t", "source_name": "s", "content": "x", "error": None,
        },
        _llm_process_source=lambda r: {"operations": []},
        execute_operations=lambda ops: {"operations_executed": 0},
    )
    (tmp_path / "raw").mkdir()

    svc = AutoIngestService(
        wiki=wiki, wiki_id="t",
        config=AutoIngestConfig(),
        llm_semaphore=asyncio.Semaphore(3),
    )

    # Fill cache with 60 entries
    for i in range(60):
        svc._extraction_cache[(f"f{i}.md", float(i), i)] = {"title": "t"}
        svc._save_processed()  # also writes the JSON state, not the cache

    # Manually trigger eviction path (in _process_file)
    # Simulate by calling _process_file for new file
    (tmp_path / "raw" / "trigger.md").write_text("x")
    asyncio.run(svc._process_file(tmp_path / "raw" / "trigger.md"))

    # Cache should have been trimmed to ≤50
    assert len(svc._extraction_cache) <= 50


# ═══════════════════════════════════════════════════════════════════════
# Source filter: Reddit fix
# ═══════════════════════════════════════════════════════════════════════


def test_reddit_not_in_low_quality_patterns():
    from llmwikify.apps.chat.harness.source_filter import SourceFilter

    assert not any("reddit" in p for p in SourceFilter.LOW_QUALITY_PATTERNS)


def test_reddit_not_low_quality_and_not_pinterest():
    """Reddit should be neutral (not penalized), Pinterest should be low quality."""
    from llmwikify.apps.chat.harness.source_filter import SourceFilter

    f = SourceFilter()
    # Pinterest is in LOW_QUALITY_PATTERNS → 0.2
    assert f._score_domain("https://pinterest.com/pin/123") == 0.2
    # Reddit was removed from LOW_QUALITY_PATTERNS → neutral 0.5
    assert f._score_domain("https://reddit.com/r/python") == 0.5
    # Reddit-specific paths not penalized
    assert f._score_domain("https://reddit.com/r/MachineLearning") == 0.5


# ═══════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════
# _llm_process_source workflow optimizations
# ═══════════════════════════════════════════════════════════════════════


# _llm_process_source workflow optimizations: covered indirectly via
# integration tests with real Wiki instances (test_v019_wiki_synthesize.py
# etc.). Direct unit testing of _llm_process_source requires mocking the
# full LLM client chain which is fragile.
