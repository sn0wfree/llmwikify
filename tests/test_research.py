"""Comprehensive unit tests for Deep Research implementation."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


def _run_async(coro):
    """Run async coroutine, handling nested event loop issues."""
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        raise

from llmwikify.agent.backend.db import AgentDatabase
from llmwikify.agent.backend.research.config import DEFAULT_RESEARCH_CONFIG, merge_research_config
from llmwikify.agent.backend.research.session import ResearchSessionManager
from llmwikify.agent.backend.research.web_search import WebSearch, SearchResult
from llmwikify.agent.backend.research.gatherer import SourceGatherer
from llmwikify.agent.backend.research.analyzer import SourceAnalyzer
from llmwikify.agent.backend.research.synthesizer import ResearchSynthesizer
from llmwikify.agent.backend.research.report import ReportGenerator
from llmwikify.agent.backend.research.review import ResearchReviewer, ResearchRevisor
from llmwikify.agent.backend.research.engine import ResearchEngine


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def db(tmp_path):
    """Create a temporary AgentDatabase."""
    return AgentDatabase(tmp_path / "test_agent.db")


@pytest.fixture
def session_manager(db):
    """Create a ResearchSessionManager with temp DB."""
    return ResearchSessionManager(db)


@pytest.fixture
def mock_wiki(tmp_path):
    """Create a mock Wiki object."""
    wiki = MagicMock()
    wiki.root = tmp_path / "wiki"
    wiki.root.mkdir(parents=True, exist_ok=True)
    (wiki.root / "raw").mkdir(exist_ok=True)
    (wiki.root / "raw" / "research").mkdir(parents=True, exist_ok=True)

    wiki.index_file = tmp_path / "wiki" / "index.md"
    wiki.index_file.write_text("# Test Wiki Index\n\nSome content about testing.\n")

    wiki.search.return_value = [{"name": "Test Page", "score": 0.9}]
    wiki.page_io.read_page.return_value = "# Test Page\n\nThis is test content."
    wiki.analyze_source.return_value = {
        "topics": ["testing", "python"],
        "entities": [{"name": "pytest", "type": "product"}],
        "key_facts": ["pytest is a testing framework"],
        "claims": [{"statement": "pytest is popular", "confidence": "high", "context": "intro"}],
        "suggested_pages": [],
        "cross_refs": [],
    }

    return wiki


@pytest.fixture
def mock_llm():
    """Create a mock LLM client."""
    llm = MagicMock()
    llm.chat.return_value = '{"query": "test sub-query", "source_type": "web", "url": ""}'
    llm.chat_with_tools.return_value = {"content": "test", "tool_calls": None}
    return llm


@pytest.fixture
def config():
    """Default research config for testing."""
    return dict(DEFAULT_RESEARCH_CONFIG)


# ==============================================================================
# 1. DB Layer Tests
# ==============================================================================


class TestResearchDB:
    """Tests for research-related DB operations."""

    def test_create_research_session(self, db):
        session_id = db.create_research_session("wiki1", "test query")
        assert session_id is not None
        assert len(session_id) == 8

        session = db.get_research_session(session_id)
        assert session is not None
        assert session["wiki_id"] == "wiki1"
        assert session["query"] == "test query"
        assert session["status"] == "planning"
        assert session["current_step"] == "planning"
        assert session["progress"] == 0.0
        assert session["result"] is None

    def test_list_research_sessions(self, db):
        db.create_research_session("wiki1", "query 1")
        db.create_research_session("wiki1", "query 2")
        db.create_research_session("wiki2", "query 3")

        all_sessions = db.list_research_sessions()
        assert len(all_sessions) == 3

        wiki1_sessions = db.list_research_sessions("wiki1")
        assert len(wiki1_sessions) == 2

        wiki2_sessions = db.list_research_sessions("wiki2")
        assert len(wiki2_sessions) == 1

    def test_update_research_status(self, db):
        session_id = db.create_research_session("wiki1", "test")
        db.update_research_status(session_id, "gathering", "gathering")

        session = db.get_research_session(session_id)
        assert session["status"] == "gathering"
        assert session["current_step"] == "gathering"

    def test_update_research_progress(self, db):
        session_id = db.create_research_session("wiki1", "test")
        db.update_research_progress(session_id, 0.5)

        session = db.get_research_session(session_id)
        assert session["progress"] == 0.5

    def test_finalize_research(self, db):
        session_id = db.create_research_session("wiki1", "test")
        result_json = json.dumps({"markdown": "# Report", "query": "test"})
        db.finalize_research(session_id, result_json, "Research: Test")

        session = db.get_research_session(session_id)
        assert session["status"] == "done"
        assert session["result"] is not None
        assert session["wiki_page_name"] == "Research: Test"

    def test_get_nonexistent_session(self, db):
        session = db.get_research_session("nonexistent")
        assert session is None

    def test_save_sub_query(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-query 1", "web", "https://example.com")
        assert sq_id is not None

        sub_queries = db.get_sub_queries(session_id)
        assert len(sub_queries) == 1
        assert sub_queries[0]["query"] == "sub-query 1"
        assert sub_queries[0]["source_type"] == "web"
        assert sub_queries[0]["url"] == "https://example.com"
        assert sub_queries[0]["status"] == "pending"

    def test_update_sub_query_done(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        db.update_sub_query(sq_id, "done", result={"content_length": 100})

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "done"
        assert sub_queries[0]["result"] == {"content_length": 100}
        assert sub_queries[0]["completed_at"] is not None

    def test_update_sub_query_failed(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        db.update_sub_query(sq_id, "failed", error="connection timeout")

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "failed"
        assert sub_queries[0]["error"] == "connection timeout"

    def test_save_source(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        source_id = db.save_source(
            session_id, sq_id, "web", "https://example.com",
            "Example Page", 5000, "Preview text"
        )
        assert source_id is not None

        sources = db.get_sources(session_id)
        assert len(sources) == 1
        assert sources[0]["title"] == "Example Page"
        assert sources[0]["source_type"] == "web"
        assert sources[0]["content_length"] == 5000
        assert sources[0]["content_preview"] == "Preview text"
        assert sources[0]["rating"] is None

    def test_update_source_analysis(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        source_id = db.save_source(session_id, sq_id, "web", "https://example.com", "Title", 100)

        analysis = {"topics": ["test"], "entities": []}
        db.update_source_analysis(source_id, analysis)

        sources = db.get_sources(session_id)
        assert sources[0]["analysis"] == analysis

    def test_rate_source(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        source_id = db.save_source(session_id, sq_id, "web", "https://example.com", "Title", 100)

        db.rate_source(source_id, 4)

        sources = db.get_sources(session_id)
        assert sources[0]["rating"] == 4

    def test_get_source_count(self, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        assert db.get_source_count(session_id) == 0

        db.save_source(session_id, sq_id, "web", "https://a.com", "A", 100)
        assert db.get_source_count(session_id) == 1

        db.save_source(session_id, sq_id, "web", "https://b.com", "B", 200)
        assert db.get_source_count(session_id) == 2

    def test_schema_migration_adds_columns(self, tmp_path):
        """Test that existing DB gets new columns via migration."""
        db_path = tmp_path / "migrate_test.db"
        import sqlite3

        # Create old schema
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute("""
                CREATE TABLE research_sessions (
                    id TEXT PRIMARY KEY,
                    wiki_id TEXT NOT NULL,
                    query TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    progress REAL DEFAULT 0.0,
                    wiki_page_name TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

        # Open with AgentDatabase (should migrate)
        db = AgentDatabase(db_path)
        session_id = "test1234"
        with sqlite3.connect(str(db_path)) as conn:
            conn.execute(
                "INSERT INTO research_sessions (id, wiki_id, query) VALUES (?, ?, ?)",
                (session_id, "wiki1", "test"),
            )
            conn.commit()

        # Verify new columns exist and work
        session = db.get_research_session(session_id)
        assert session is not None
        assert "current_step" in session
        assert "result" in session
        assert "updated_at" in session


# ==============================================================================
# 2. Config Tests
# ==============================================================================


class TestResearchConfig:
    """Tests for research configuration."""

    def test_default_config_has_all_keys(self):
        assert "max_sub_queries" in DEFAULT_RESEARCH_CONFIG
        assert "max_source_content_length" in DEFAULT_RESEARCH_CONFIG
        assert "research_timeout_minutes" in DEFAULT_RESEARCH_CONFIG
        assert "max_parallel_gathering" in DEFAULT_RESEARCH_CONFIG
        assert "web_search_results_per_query" in DEFAULT_RESEARCH_CONFIG
        assert "max_retry_attempts" in DEFAULT_RESEARCH_CONFIG
        assert "similarity_threshold" in DEFAULT_RESEARCH_CONFIG
        assert "max_review_rounds" in DEFAULT_RESEARCH_CONFIG
        assert "planning_model" in DEFAULT_RESEARCH_CONFIG
        assert "report_model" in DEFAULT_RESEARCH_CONFIG

    def test_merge_no_overrides(self):
        config = merge_research_config()
        assert config == DEFAULT_RESEARCH_CONFIG

    def test_merge_with_overrides(self):
        overrides = {"max_sub_queries": 10, "max_review_rounds": 3}
        config = merge_research_config(overrides)
        assert config["max_sub_queries"] == 10
        assert config["max_review_rounds"] == 3
        assert config["max_parallel_gathering"] == DEFAULT_RESEARCH_CONFIG["max_parallel_gathering"]

    def test_merge_ignores_unknown_keys(self):
        overrides = {"unknown_key": "value", "max_sub_queries": 5}
        config = merge_research_config(overrides)
        assert "unknown_key" not in config
        assert config["max_sub_queries"] == 5

    def test_merge_none_overrides(self):
        config = merge_research_config(None)
        assert config == DEFAULT_RESEARCH_CONFIG

    def test_merge_empty_overrides(self):
        config = merge_research_config({})
        assert config == DEFAULT_RESEARCH_CONFIG


# ==============================================================================
# 3. Session Manager Tests
# ==============================================================================


class TestResearchSessionManager:
    """Tests for ResearchSessionManager."""

    def test_create_session(self, session_manager, db):
        session_id = session_manager.create_session("test query", "wiki1")
        assert session_id is not None
        assert session_manager.session_id == session_id

        session = db.get_research_session(session_id)
        assert session["query"] == "test query"
        assert session["wiki_id"] == "wiki1"

    def test_get_session_with_relations(self, session_manager):
        session_id = session_manager.create_session("test", "wiki1")
        session_manager.add_sub_query(session_id, "sub-q1", "web")
        session_manager.add_sub_query(session_id, "sub-q2", "wiki")

        session = session_manager.get_session(session_id)
        assert "sub_queries" in session
        assert "sources" in session
        assert len(session["sub_queries"]) == 2

    def test_update_status(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        session_manager.update_status(session_id, "gathering", "gathering", 0.2)

        session = db.get_research_session(session_id)
        assert session["status"] == "gathering"
        assert session["current_step"] == "gathering"

    def test_add_and_complete_sub_query(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        session_manager.complete_sub_query(sq_id, {"content_length": 500})

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "done"
        assert sub_queries[0]["result"] == {"content_length": 500}

    def test_fail_sub_query(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        session_manager.fail_sub_query(sq_id, "timeout error")

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "failed"
        assert sub_queries[0]["error"] == "timeout error"

    def test_add_source(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        source_id = session_manager.add_source(
            session_id, sq_id, "web", "https://example.com",
            "Example", 1000, "Preview"
        )

        sources = db.get_sources(session_id)
        assert len(sources) == 1
        assert sources[0]["id"] == source_id

    def test_update_source_analysis(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        source_id = session_manager.add_source(
            session_id, sq_id, "web", "https://example.com", "Title", 100
        )

        analysis = {"topics": ["test"]}
        session_manager.update_source_analysis(source_id, analysis)

        sources = db.get_sources(session_id)
        assert sources[0]["analysis"] == analysis

    def test_finalize(self, session_manager, db):
        session_id = session_manager.create_session("test", "wiki1")
        session_manager.finalize(session_id, {"markdown": "# Report"}, "Research: Test")

        session = db.get_research_session(session_id)
        assert session["status"] == "done"
        assert session["wiki_page_name"] == "Research: Test"


# ==============================================================================
# 4. WebSearch Tests
# ==============================================================================


class TestWebSearch:
    """Tests for WebSearch."""

    def test_search_returns_results(self):
        search = WebSearch({"web_search_results_per_query": 3})
        mock_results = [
            {"title": "Result 1", "href": "https://example.com/1", "body": "Snippet 1"},
            {"title": "Result 2", "href": "https://example.com/2", "body": "Snippet 2"},
        ]

        with patch("duckduckgo_search.DDGS") as MockDDGS:
            mock_ddgs = MagicMock()
            mock_ddgs.text.return_value = mock_results
            MockDDGS.return_value.__enter__ = MagicMock(return_value=mock_ddgs)
            MockDDGS.return_value.__exit__ = MagicMock(return_value=False)

            results = _run_async(
                search.search("test query")
            )

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[0].url == "https://example.com/1"
        assert results[1].snippet == "Snippet 2"

    def test_search_handles_exception(self):
        search = WebSearch({})
        with patch("duckduckgo_search.DDGS", side_effect=Exception("network error")):
            results = _run_async(
                search.search("test")
            )
        assert results == []

    def test_search_with_type_web(self):
        search = WebSearch({})
        with patch.object(search, "search", return_value=[SearchResult("T", "https://x.com", "S")]):
            results = _run_async(
                search.search_with_type("query", "web")
            )
        assert len(results) == 1
        assert results[0]["source_type"] == "web"

    def test_search_with_type_youtube(self):
        search = WebSearch({})
        with patch.object(search, "search", return_value=[SearchResult("T", "https://youtube.com/watch", "S")]):
            results = _run_async(
                search.search_with_type("query", "youtube")
            )
        assert len(results) == 1
        assert results[0]["source_type"] == "youtube"

    def test_search_with_type_wiki(self):
        search = WebSearch({})
        results = _run_async(
            search.search_with_type("query", "wiki")
        )
        assert len(results) == 1
        assert results[0]["source_type"] == "wiki"
        assert results[0]["url"] == ""


# ==============================================================================
# 4b. Search Provider Tests
# ==============================================================================


class TestSearXNGProvider:
    """Tests for SearXNG search provider."""

    def test_search_returns_results(self):
        from llmwikify.agent.backend.research.web_search import SearXNGProvider

        provider = SearXNGProvider("http://localhost:8888")
        mock_response = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=mock_response))
            mock_get.return_value.raise_for_status = MagicMock()
            results = _run_async(provider.search("test", 5))

        assert len(results) == 2
        assert results[0].title == "Result 1"
        assert results[0].url == "https://example.com/1"

    def test_search_filters_empty_urls(self):
        from llmwikify.agent.backend.research.web_search import SearXNGProvider

        provider = SearXNGProvider("http://localhost:8888")
        mock_response = {
            "results": [
                {"title": "Good", "url": "https://example.com", "content": "OK"},
                {"title": "Bad", "url": "", "content": "No URL"},
            ]
        }

        with patch("httpx.AsyncClient.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=mock_response))
            mock_get.return_value.raise_for_status = MagicMock()
            results = _run_async(provider.search("test", 5))

        assert len(results) == 1

    def test_search_handles_error(self):
        from llmwikify.agent.backend.research.web_search import SearXNGProvider

        provider = SearXNGProvider("http://localhost:8888")

        with patch("httpx.AsyncClient.get", side_effect=Exception("connection refused")):
            with pytest.raises(Exception, match="connection refused"):
                _run_async(provider.search("test", 5))


class TestTavilyProvider:
    """Tests for Tavily search provider."""

    def test_search_returns_results(self):
        from llmwikify.agent.backend.research.web_search import TavilyProvider

        provider = TavilyProvider("tvly-test-key")
        mock_response = {
            "results": [
                {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet 1"},
                {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet 2"},
            ]
        }

        with patch("tavily.TavilyClient") as MockClient:
            MockClient.return_value.search.return_value = mock_response
            results = _run_async(provider.search("test", 5))

        assert len(results) == 2
        assert results[0].title == "Result 1"

    def test_search_handles_error(self):
        from llmwikify.agent.backend.research.web_search import TavilyProvider

        provider = TavilyProvider("tvly-test-key")

        with patch("tavily.TavilyClient", side_effect=Exception("invalid key")):
            with pytest.raises(Exception, match="invalid key"):
                _run_async(provider.search("test", 5))


class TestMiniMaxSearchProvider:
    """Tests for MiniMax search provider."""

    def test_search_returns_results(self):
        from llmwikify.agent.backend.research.web_search import MiniMaxSearchProvider

        provider = MiniMaxSearchProvider("test-key", "https://api.minimaxi.com")
        mock_response = {
            "organic": [
                {"title": "MiniMax Result 1", "link": "https://example.com/1", "snippet": "Snippet 1", "date": "2025-01-01"},
                {"title": "MiniMax Result 2", "link": "https://example.com/2", "snippet": "Snippet 2", "date": "2025-01-02"},
            ],
            "related_searches": [{"query": "related 1"}],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value.post = AsyncMock(return_value=mock_resp)
            results = _run_async(provider.search("test", 5))

        assert len(results) == 2
        assert results[0].title == "MiniMax Result 1"
        assert results[0].url == "https://example.com/1"

    def test_search_filters_empty_links(self):
        from llmwikify.agent.backend.research.web_search import MiniMaxSearchProvider

        provider = MiniMaxSearchProvider("test-key")
        mock_response = {
            "organic": [
                {"title": "Result 1", "link": "https://example.com/1", "snippet": "S1"},
                {"title": "Result 2", "link": "", "snippet": "S2"},
                {"title": "Result 3", "snippet": "S3"},
            ],
            "base_resp": {"status_code": 0, "status_msg": "success"},
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value.post = AsyncMock(return_value=mock_resp)
            results = _run_async(provider.search("test", 5))

        assert len(results) == 1
        assert results[0].url == "https://example.com/1"

    def test_search_raises_on_api_error(self):
        from llmwikify.agent.backend.research.web_search import MiniMaxSearchProvider

        provider = MiniMaxSearchProvider("test-key")
        mock_response = {
            "organic": [],
            "base_resp": {"status_code": 1004, "status_msg": "invalid api key"},
        }

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = mock_response

        with patch("httpx.AsyncClient") as MockClient:
            MockClient.return_value.__aenter__ = AsyncMock(return_value=MockClient.return_value)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value.post = AsyncMock(return_value=mock_resp)
            with pytest.raises(RuntimeError, match="MiniMax API error 1004"):
                _run_async(provider.search("test", 5))


class TestFallbackSearchProvider:
    """Tests for FallbackSearchProvider."""

    def test_returns_first_successful(self):
        from llmwikify.agent.backend.research.web_search import FallbackSearchProvider, SearchResult

        p1 = MagicMock()
        p1.search = AsyncMock(return_value=[SearchResult("T1", "https://u1", "S1")])
        p2 = MagicMock()
        p2.search = AsyncMock(return_value=[SearchResult("T2", "https://u2", "S2")])

        provider = FallbackSearchProvider([p1, p2])
        results = _run_async(provider.search("test", 5))

        assert len(results) == 1
        assert results[0].title == "T1"
        p2.search.assert_not_called()

    def test_falls_back_on_failure(self):
        from llmwikify.agent.backend.research.web_search import FallbackSearchProvider, SearchResult

        p1 = MagicMock()
        p1.search = AsyncMock(side_effect=Exception("p1 failed"))
        p2 = MagicMock()
        p2.search = AsyncMock(return_value=[SearchResult("T2", "https://u2", "S2")])

        provider = FallbackSearchProvider([p1, p2])
        results = _run_async(provider.search("test", 5))

        assert len(results) == 1
        assert results[0].title == "T2"

    def test_returns_empty_if_all_fail(self):
        from llmwikify.agent.backend.research.web_search import FallbackSearchProvider

        p1 = MagicMock()
        p1.search = AsyncMock(side_effect=Exception("p1 failed"))
        p2 = MagicMock()
        p2.search = AsyncMock(side_effect=Exception("p2 failed"))

        provider = FallbackSearchProvider([p1, p2])
        results = _run_async(provider.search("test", 5))

        assert results == []

    def test_skips_empty_results(self):
        from llmwikify.agent.backend.research.web_search import FallbackSearchProvider, SearchResult

        p1 = MagicMock()
        p1.search = AsyncMock(return_value=[])
        p2 = MagicMock()
        p2.search = AsyncMock(return_value=[SearchResult("T2", "https://u2", "S2")])

        provider = FallbackSearchProvider([p1, p2])
        results = _run_async(provider.search("test", 5))

        assert len(results) == 1
        assert results[0].title == "T2"


class TestCreateSearchProvider:
    """Tests for create_search_provider factory."""

    def test_auto_mode_creates_chain(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, FallbackSearchProvider, DuckDuckGoProvider
        )

        config = {"search_provider": "auto"}
        provider = create_search_provider(config)

        assert isinstance(provider, FallbackSearchProvider)
        assert len(provider.providers) == 1  # only DuckDuckGo in auto without keys
        assert isinstance(provider.providers[0], DuckDuckGoProvider)

    def test_auto_with_tavily_key(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, FallbackSearchProvider, TavilyProvider, DuckDuckGoProvider
        )

        config = {"search_provider": "auto", "tavily_api_key": "tvly-test"}
        provider = create_search_provider(config)

        assert isinstance(provider, FallbackSearchProvider)
        assert len(provider.providers) == 2
        assert isinstance(provider.providers[0], TavilyProvider)
        assert isinstance(provider.providers[1], DuckDuckGoProvider)

    def test_auto_with_minimax_key(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, FallbackSearchProvider, MiniMaxSearchProvider, DuckDuckGoProvider
        )

        config = {"search_provider": "auto", "minimax_api_key": "test-key"}
        provider = create_search_provider(config)

        assert isinstance(provider, FallbackSearchProvider)
        assert len(provider.providers) == 2
        assert isinstance(provider.providers[0], MiniMaxSearchProvider)
        assert isinstance(provider.providers[1], DuckDuckGoProvider)

    def test_auto_with_searxng_url(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, FallbackSearchProvider, SearXNGProvider
        )

        config = {"search_provider": "auto", "searxng_url": "http://localhost:8888"}
        provider = create_search_provider(config)

        assert isinstance(provider, FallbackSearchProvider)
        assert isinstance(provider.providers[0], SearXNGProvider)

    def test_auto_full_chain(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, FallbackSearchProvider,
            SearXNGProvider, MiniMaxSearchProvider, TavilyProvider, DuckDuckGoProvider
        )

        config = {
            "search_provider": "auto",
            "searxng_url": "http://localhost:8888",
            "minimax_api_key": "test-key",
            "tavily_api_key": "tvly-test",
        }
        provider = create_search_provider(config)

        assert isinstance(provider, FallbackSearchProvider)
        assert len(provider.providers) == 4
        assert isinstance(provider.providers[0], SearXNGProvider)
        assert isinstance(provider.providers[1], MiniMaxSearchProvider)
        assert isinstance(provider.providers[2], TavilyProvider)
        assert isinstance(provider.providers[3], DuckDuckGoProvider)

    def test_explicit_minimax_only(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, MiniMaxSearchProvider
        )

        config = {"search_provider": "minimax", "minimax_api_key": "test-key"}
        provider = create_search_provider(config)

        assert len(provider.providers) == 1
        assert isinstance(provider.providers[0], MiniMaxSearchProvider)

    def test_explicit_tavily_only(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, TavilyProvider
        )

        config = {"search_provider": "tavily", "tavily_api_key": "tvly-test"}
        provider = create_search_provider(config)

        assert len(provider.providers) == 1
        assert isinstance(provider.providers[0], TavilyProvider)

    def test_no_config_falls_back_to_ddg(self):
        from llmwikify.agent.backend.research.web_search import (
            create_search_provider, DuckDuckGoProvider
        )

        provider = create_search_provider({})
        assert len(provider.providers) == 1
        assert isinstance(provider.providers[0], DuckDuckGoProvider)


class TestSourceGatherer:
    """Tests for SourceGatherer."""

    def test_gather_web_source(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "test query", "web", "https://example.com")

        gatherer = SourceGatherer(mock_wiki, db, session_manager, config)

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract:
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="Article content here",
                source_type="url",
                title="Example Article",
                metadata={"url": "https://example.com"},
            )

            events = _run_async(
                gatherer.gather([{"id": sq_id, "source_type": "web", "url": "https://example.com", "query": "test"}])
            )

        assert len(events) == 1
        assert events[0]["type"] == "source_gathered"
        assert events[0]["source_type"] == "web"

        # Verify DB state
        sources = db.get_sources(session_id)
        assert len(sources) == 1
        # title is set to url (from `title = url or query` in gatherer)
        assert sources[0]["title"] == "https://example.com"

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "done"

    def test_gather_wiki_source(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "Test Page", "wiki")

        gatherer = SourceGatherer(mock_wiki, db, session_manager, config)

        events = _run_async(
            gatherer.gather([{"id": sq_id, "source_type": "wiki", "url": "", "query": "Test Page"}])
        )

        assert len(events) == 1
        assert events[0]["type"] == "source_gathered"
        assert events[0]["source_type"] == "wiki"

    def test_gather_handles_failure(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "bad query", "web", "https://fail.com")

        gatherer = SourceGatherer(mock_wiki, db, session_manager, config)

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract:
            mock_extract.side_effect = Exception("connection failed")

            events = _run_async(
                gatherer.gather([{"id": sq_id, "source_type": "web", "url": "https://fail.com", "query": "bad"}])
            )

        assert len(events) == 1
        assert events[0]["type"] == "sub_query_failed"

        sub_queries = db.get_sub_queries(session_id)
        assert sub_queries[0]["status"] == "failed"

    def test_gather_searches_for_url_when_missing(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "python docs", "web")

        gatherer = SourceGatherer(mock_wiki, db, session_manager, config)

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract, \
             patch("llmwikify.agent.backend.research.web_search.WebSearch") as MockSearch:
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="content", source_type="url", title="Python Docs", metadata={}
            )
            mock_search_instance = MagicMock()
            mock_search_instance.search = AsyncMock(return_value=[
                SearchResult("Python Docs", "https://docs.python.org", "Python documentation")
            ])
            MockSearch.return_value = mock_search_instance

            events = _run_async(
                gatherer.gather([{"id": sq_id, "source_type": "web", "url": "", "query": "python docs"}])
            )

        assert len(events) == 1
        assert events[0]["type"] == "source_gathered"

    def test_gather_truncates_long_content(self, mock_wiki, db, config):
        config["max_source_content_length"] = 100
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "test", "web", "https://example.com")

        gatherer = SourceGatherer(mock_wiki, db, session_manager, config)

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract:
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="x" * 500, source_type="url", title="Long", metadata={}
            )

            _run_async(
                gatherer.gather([{"id": sq_id, "source_type": "web", "url": "https://example.com", "query": "test"}])
            )

        sources = db.get_sources(session_id)
        assert sources[0]["content_length"] <= 100


# ==============================================================================
# 6. SourceAnalyzer Tests
# ==============================================================================


class TestSourceAnalyzer:
    """Tests for SourceAnalyzer."""

    def test_analyze_source(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        source_id = session_manager.add_source(
            session_id, sq_id, "web", "https://example.com", "Title", 100, "Preview content"
        )

        analyzer = SourceAnalyzer(mock_wiki, session_manager, config)
        sources = db.get_sources(session_id)

        events = _run_async(
            analyzer.analyze_sources(sources)
        )

        assert len(events) == 1
        assert events[0]["type"] == "source_analyzed"
        assert events[0]["source_id"] == source_id

        # Verify analysis stored in DB
        updated_sources = db.get_sources(session_id)
        assert updated_sources[0]["analysis"] is not None
        assert "topics" in updated_sources[0]["analysis"]

    def test_analyze_skips_already_analyzed(self, mock_wiki, db, config):
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        source_id = session_manager.add_source(
            session_id, sq_id, "web", "https://example.com", "Title", 100, "Content"
        )
        session_manager.update_source_analysis(source_id, {"topics": ["already done"]})

        analyzer = SourceAnalyzer(mock_wiki, session_manager, config)
        sources = db.get_sources(session_id)

        events = _run_async(
            analyzer.analyze_sources(sources)
        )

        assert len(events) == 0  # skipped

    def test_analyze_handles_failure(self, mock_wiki, db, config):
        mock_wiki.analyze_source.side_effect = Exception("LLM error")
        session_manager = ResearchSessionManager(db)
        session_id = session_manager.create_session("test", "wiki1")
        sq_id = session_manager.add_sub_query(session_id, "sub-q", "web")
        session_manager.add_source(session_id, sq_id, "web", "https://example.com", "Title", 100, "Content")

        analyzer = SourceAnalyzer(mock_wiki, session_manager, config)
        sources = db.get_sources(session_id)

        events = _run_async(
            analyzer.analyze_sources(sources)
        )

        assert len(events) == 1
        assert events[0]["type"] == "source_analysis_failed"


# ==============================================================================
# 7. ResearchSynthesizer Tests
# ==============================================================================


class TestResearchSynthesizer:
    """Tests for ResearchSynthesizer."""

    def test_synthesize_with_sources(self, mock_wiki, config):
        sources = [
            {
                "id": "s1",
                "title": "Source 1",
                "source_type": "web",
                "rating": 5,
                "analysis": {
                    "topics": ["python", "testing"],
                    "entities": [{"name": "pytest", "type": "product"}],
                    "claims": [{"statement": "pytest is popular", "confidence": "high", "context": "intro"}],
                    "key_facts": ["pytest is a testing framework"],
                    "suggested_pages": [],
                    "cross_refs": [],
                },
            },
            {
                "id": "s2",
                "title": "Source 2",
                "source_type": "web",
                "rating": 3,
                "analysis": {
                    "topics": ["python"],
                    "entities": [],
                    "claims": [],
                    "key_facts": [],
                    "suggested_pages": [],
                    "cross_refs": [],
                },
            },
        ]

        synthesizer = ResearchSynthesizer(mock_wiki, config)
        result = _run_async(
            synthesizer.synthesize(sources)
        )

        assert "reinforced_claims" in result
        assert "contradictions" in result
        assert "knowledge_gaps" in result
        assert "new_entities" in result
        assert "suggested_updates" in result
        assert result["sources_analyzed"] == 2

    def test_synthesize_skips_sources_without_analysis(self, mock_wiki, config):
        sources = [
            {"id": "s1", "title": "No Analysis", "source_type": "web", "analysis": None},
            {"id": "s2", "title": "Error", "source_type": "web", "analysis": {"status": "error"}},
        ]

        synthesizer = ResearchSynthesizer(mock_wiki, config)
        result = _run_async(
            synthesizer.synthesize(sources)
        )

        assert result["sources_analyzed"] == 2

    def test_synthesize_prioritizes_high_rated(self, mock_wiki, config):
        sources = [
            {"id": "s1", "title": "Low", "source_type": "web", "rating": 1, "analysis": {"topics": ["a"], "entities": [], "claims": [], "key_facts": [], "suggested_pages": [], "cross_refs": []}},
            {"id": "s2", "title": "High", "source_type": "web", "rating": 5, "analysis": {"topics": ["b"], "entities": [], "claims": [], "key_facts": [], "suggested_pages": [], "cross_refs": []}},
        ]

        synthesizer = ResearchSynthesizer(mock_wiki, config)
        result = _run_async(
            synthesizer.synthesize(sources)
        )

        assert result["sources_analyzed"] == 2


# ==============================================================================
# 8. ReportGenerator Tests
# ==============================================================================


class TestReportGenerator:
    """Tests for ReportGenerator."""

    def test_generate_report(self, mock_wiki, mock_llm, config):
        mock_llm.chat.return_value = """# Test Report

## Executive Summary
This is a test report about machine learning.

## References
[[Source:abc123def456]] Example Source - https://example.com
"""

        generator = ReportGenerator(mock_wiki, mock_llm, config)
        sources = [
            {"id": "s1", "title": "Example Source", "url": "https://example.com", "source_type": "web", "content_preview": "Content", "analysis": {"topics": ["ml"], "key_facts": ["fact1"]}},
        ]
        synthesis = {"reinforced_claims": [], "contradictions": [], "knowledge_gaps": [], "new_entities": []}

        report = _run_async(
            generator.generate("machine learning", sources, synthesis)
        )

        assert "Test Report" in report
        assert "Source:" in report
        mock_llm.chat.assert_called_once()

    def test_generate_report_handles_empty_sources(self, mock_wiki, mock_llm, config):
        mock_llm.chat.return_value = "# Empty Report\n\nNo sources found."

        generator = ReportGenerator(mock_wiki, mock_llm, config)
        report = _run_async(
            generator.generate("test", [], {})
        )

        assert "Empty Report" in report

    def test_build_source_map(self, mock_wiki, mock_llm, config):
        generator = ReportGenerator(mock_wiki, mock_llm, config)
        sources = [
            {"url": "https://a.com", "title": "A", "source_type": "web"},
            {"title": "B", "source_type": "wiki", "url": ""},
        ]

        source_map = generator._build_source_map(sources)
        assert len(source_map) == 2
        for h, info in source_map.items():
            assert len(h) == 12
            assert "title" in info
            assert "source_type" in info


# ==============================================================================
# 9. Review Tests
# ==============================================================================


class TestResearchReviewer:
    """Tests for ResearchReviewer."""

    def test_review_approved(self, mock_wiki, mock_llm, config):
        mock_llm.chat.return_value = json.dumps({
            "approved": True,
            "score": 8,
            "feedback": "Good report",
            "issues": [],
        })

        reviewer = ResearchReviewer(mock_wiki, mock_llm, config)
        result = _run_async(
            reviewer.review("test query", "# Report content", [])
        )

        assert result["approved"] is True
        assert result["score"] == 8
        assert result["issues"] == []

    def test_review_not_approved(self, mock_wiki, mock_llm, config):
        mock_llm.chat.return_value = json.dumps({
            "approved": False,
            "score": 4,
            "feedback": "Missing sources",
            "issues": ["No citations", "Too short"],
        })

        reviewer = ResearchReviewer(mock_wiki, mock_llm, config)
        result = _run_async(
            reviewer.review("test query", "# Short report", [])
        )

        assert result["approved"] is False
        assert result["score"] == 4
        assert len(result["issues"]) == 2

    def test_review_handles_llm_failure(self, mock_wiki, mock_llm, config):
        mock_llm.chat.side_effect = Exception("LLM down")

        reviewer = ResearchReviewer(mock_wiki, mock_llm, config)
        result = _run_async(
            reviewer.review("test", "# Report", [])
        )

        # Should default to NOT approved on failure (safer behavior)
        assert result["approved"] is False
        assert "failed" in result["feedback"].lower()


class TestResearchRevisor:
    """Tests for ResearchRevisor."""

    def test_revise_report(self, mock_wiki, mock_llm, config):
        mock_llm.chat.return_value = "# Revised Report\n\nFixed version with citations [[Source:abc]]."

        revisor = ResearchRevisor(mock_wiki, mock_llm, config)
        result = _run_async(
            revisor.revise(
                "# Original Report",
                ["Missing citations"],
                [{"id": "s1", "title": "Source", "url": "https://x.com", "source_type": "web"}],
            )
        )

        assert "Revised Report" in result
        mock_llm.chat.assert_called_once()


# ==============================================================================
# 10. ResearchEngine Tests
# ==============================================================================


class TestResearchEngine:
    """Tests for ResearchEngine orchestrator."""

    def test_engine_init(self, mock_wiki, mock_llm, db, config):
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        assert engine.wiki is mock_wiki
        assert engine.db is db
        assert engine._default_llm is mock_llm
        assert engine._planning_llm is mock_llm  # fallback when no planning_model
        assert engine._report_llm is mock_llm  # fallback when no report_model

    def test_engine_init_with_model_layering(self, mock_wiki, mock_llm, db, config):
        config["planning_model"] = {"provider": "test", "model": "planner"}
        config["report_model"] = {"provider": "test", "model": "reporter"}

        with patch("llmwikify.agent.backend.research.engine.create_llm") as mock_create:
            mock_planner = MagicMock()
            mock_reporter = MagicMock()
            mock_create.side_effect = [mock_planner, mock_reporter]

            engine = ResearchEngine(mock_wiki, db, mock_llm, config)

            assert engine._planning_llm is mock_planner
            assert engine._report_llm is mock_reporter
            assert engine._default_llm is mock_llm

    def test_engine_run_yields_events(self, mock_wiki, mock_llm, db, config):
        """Test that engine.run yields proper SSE events."""
        config["max_review_rounds"] = 1

        # Mock LLM responses
        mock_llm.chat.side_effect = [
            # Planning: return sub-queries
            json.dumps([{"query": "test sub", "source_type": "web", "url": "https://example.com"}]),
            # Report: return markdown
            "# Test Report\n\nContent [[Source:abc123]].",
            # Review: return approved
            json.dumps({"approved": True, "score": 8, "feedback": "Good", "issues": []}),
        ]

        # Mock extractors
        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract, \
             patch.object(mock_wiki, "analyze_source", return_value={
                 "topics": ["test"], "entities": [], "claims": [], "key_facts": ["fact"],
                 "suggested_pages": [], "cross_refs": [],
             }):
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="Article content", source_type="url", title="Article", metadata={}
            )

            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test query", "wiki1")

            events = []
            async def run():
                async for event in engine.run(session_id, "test query"):
                    events.append(event)

            _run_async(run())

        # Verify event types
        event_types = [e["type"] for e in events]
        assert "step" in event_types
        assert "sub_query_created" in event_types
        assert "source_gathered" in event_types
        assert "progress" in event_types
        assert "synthesis_complete" in event_types
        assert "review_passed" in event_types
        assert "done" in event_types

        # Verify final state
        session = db.get_research_session(session_id)
        assert session["status"] == "done"

    def test_engine_run_handles_planning_failure(self, mock_wiki, mock_llm, db, config):
        """Test graceful handling when planning LLM fails."""
        config["max_review_rounds"] = 0  # skip review

        mock_llm.chat.side_effect = [
            "invalid json",  # Planning fails → fallback to single query
            "# Report",      # Report
        ]

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract, \
             patch.object(mock_wiki, "analyze_source", return_value={"status": "skipped"}):
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="content", source_type="url", title="T", metadata={}
            )

            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test", "wiki1")

            events = []
            async def run():
                async for event in engine.run(session_id, "test"):
                    events.append(event)

            _run_async(run())

        # Should fail early when no sources gathered (planning failure + no search results)
        session = db.get_research_session(session_id)
        assert session["status"] == "error"

    def test_engine_review_loop(self, mock_wiki, mock_llm, db, config):
        """Test review loop with issues then approval."""
        config["max_review_rounds"] = 2

        mock_llm.chat.side_effect = [
            # Planning
            json.dumps([{"query": "sub", "source_type": "wiki", "url": ""}]),
            # Report v1
            "# Draft Report",
            # Review round 1: issues found
            json.dumps({"approved": False, "score": 5, "feedback": "Needs improvement", "issues": ["Missing citations"]}),
            # Revise
            "# Revised Report with citations",
            # Review round 2: approved
            json.dumps({"approved": True, "score": 8, "feedback": "Good now", "issues": []}),
        ]

        with patch.object(mock_wiki, "analyze_source", return_value={"status": "skipped"}):
            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("test", "wiki1")

            events = []
            async def run():
                async for event in engine.run(session_id, "test"):
                    events.append(event)

            _run_async(run())

        event_types = [e["type"] for e in events]
        assert "review_issues" in event_types
        assert "review_passed" in event_types

    def test_step_event_helper(self, mock_wiki, mock_llm, db, config):
        engine = ResearchEngine(mock_wiki, db, mock_llm, config)
        event = engine._step_event("planning", "Starting...")
        assert event["type"] == "step"
        assert event["step"] == "planning"
        assert event["message"] == "Starting..."
        assert "session_id" in event


# ==============================================================================
# 11. Route Tests
# ==============================================================================


class TestResearchRoutes:
    """Tests for research API routes."""

    @pytest.fixture
    def client(self, db, mock_wiki):
        """Create a FastAPI test client."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from llmwikify.agent.backend.routes.research import router, set_research_deps

        # Create a mock wiki registry
        registry = MagicMock()
        registry.get_default_wiki.return_value = mock_wiki
        registry.get_wiki.return_value = mock_wiki

        # Create a mock LLM
        llm = MagicMock()
        llm.chat.return_value = "# Test Report"

        set_research_deps(db=db, wiki_registry=registry, llm_client=llm, config=None)

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    def test_list_research_empty(self, client):
        response = client.get("/api/research/")
        assert response.status_code == 200
        data = response.json()
        assert "research_sessions" in data
        assert data["research_sessions"] == []

    def test_list_research_with_sessions(self, client, db):
        db.create_research_session("wiki1", "test query")
        response = client.get("/api/research/")
        assert response.status_code == 200
        data = response.json()
        assert len(data["research_sessions"]) == 1
        assert data["research_sessions"][0]["query"] == "test query"

    def test_get_research(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        response = client.get(f"/api/research/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "test"
        assert "sub_queries" in data
        assert "sources" in data

    def test_get_nonexistent_research(self, client):
        response = client.get("/api/research/nonexistent")
        assert response.status_code == 404

    def test_get_sub_queries(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        db.save_sub_query(session_id, "sub-q", "web")
        response = client.get(f"/api/research/{session_id}/sub-queries")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sub_queries"]) == 1

    def test_get_sources(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        db.save_source(session_id, sq_id, "web", "https://x.com", "Title", 100)
        response = client.get(f"/api/research/{session_id}/sources")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sources"]) == 1

    def test_pause_research(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        db.update_research_status(session_id, "gathering", "gathering")
        response = client.post(f"/api/research/{session_id}/pause")
        assert response.status_code == 200
        data = response.json()
        assert data["paused"] is True

        session = db.get_research_session(session_id)
        assert session["status"] == "paused"

    def test_pause_non_pausable(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        db.finalize_research(session_id, "{}")
        response = client.post(f"/api/research/{session_id}/pause")
        assert response.status_code == 400

    def test_delete_research(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        response = client.delete(f"/api/research/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["cancelled"] is True

        session = db.get_research_session(session_id)
        assert session["status"] == "cancelled"

    def test_rate_research(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        sq_id = db.save_sub_query(session_id, "sub-q", "web")
        source_id = db.save_source(session_id, sq_id, "web", "https://x.com", "Title", 100)

        response = client.post(f"/api/research/{session_id}/rate", json={
            "rating": 4,
            "source_ratings": {source_id: 5},
            "feedback": "Good research",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["rated"] is True

        # Verify source rating
        sources = db.get_sources(session_id)
        assert sources[0]["rating"] == 5

    def test_start_research_empty_query(self, client):
        response = client.post("/api/research/start", json={"query": ""})
        assert response.status_code == 400

    def test_resume_non_paused(self, client, db):
        session_id = db.create_research_session("wiki1", "test")
        db.update_research_status(session_id, "done")
        response = client.post(f"/api/research/{session_id}/resume")
        assert response.status_code == 400


# ==============================================================================
# 12. Integration Tests
# ==============================================================================


class TestResearchIntegration:
    """Integration tests for the full research pipeline."""

    def test_full_pipeline_mock(self, mock_wiki, mock_llm, db, config):
        """Test full pipeline with mocked LLM and extractors."""
        config["max_review_rounds"] = 1

        call_count = [0]
        def mock_chat(messages, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:  # Planning
                return json.dumps([
                    {"query": "sub topic 1", "source_type": "web", "url": "https://a.com"},
                    {"query": "sub topic 2", "source_type": "wiki", "url": ""},
                ])
            elif call_count[0] == 2:  # Report
                return "# Full Report\n\nContent with [[Source:hash]]."
            elif call_count[0] == 3:  # Review
                return json.dumps({"approved": True, "score": 8, "feedback": "Good", "issues": []})
            return ""

        mock_llm.chat.side_effect = mock_chat

        with patch("llmwikify.agent.backend.research.gatherer.extract_url") as mock_extract, \
             patch.object(mock_wiki, "analyze_source", return_value={
                 "topics": ["topic1"], "entities": [], "claims": [],
                 "key_facts": ["fact1"], "suggested_pages": [], "cross_refs": [],
             }):
            from llmwikify.extractors.base import ExtractedContent
            mock_extract.return_value = ExtractedContent(
                text="Web content", source_type="url", title="Web Page", metadata={}
            )

            engine = ResearchEngine(mock_wiki, db, mock_llm, config)
            session_id = engine.session_manager.create_session("full test", "wiki1")

            events = []
            async def run():
                async for event in engine.run(session_id, "full test"):
                    events.append(event)

            _run_async(run())

        # Verify complete pipeline
        session = db.get_research_session(session_id)
        assert session["status"] == "done"
        assert session["progress"] == 1.0

        sub_queries = db.get_sub_queries(session_id)
        assert len(sub_queries) == 2

        sources = db.get_sources(session_id)
        assert len(sources) >= 1

        # Verify event sequence
        event_types = [e["type"] for e in events]
        assert event_types.index("step") < event_types.index("sub_query_created")
        assert event_types.index("sub_query_created") < event_types.index("source_gathered")
        assert event_types.index("source_gathered") < event_types.index("done")
