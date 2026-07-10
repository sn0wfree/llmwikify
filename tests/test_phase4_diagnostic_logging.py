"""Phase 4 diagnostic logging tests.

Covers:
  - FallbackSearchProvider logs the resolved chain at construction
  - gather_skill web_search fallback logs at INFO/WARNING (not DEBUG)
  - gatherer.py logs WebSearch invocation/result/timeout at INFO/WARNING
  - routes.start_autoresearch persists a config_info event to the session

All tests are pure unit tests with mocked deps; no I/O, no LLM, no DB
beyond in-memory event capture.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── FallbackSearchProvider chain summary ────────────────────────


class TestFallbackSearchProviderLogsChain:
    """Phase 4: FallbackSearchProvider must log the provider chain
    once at construction so operators can verify ordering.
    """

    def test_logs_chain_summary_at_info(self, caplog) -> None:
        from llmwikify.apps.research.web_search import (
            DuckDuckGoProvider,
            FallbackSearchProvider,
            SearXNGProvider,
        )
        chain = [SearXNGProvider("http://x"), DuckDuckGoProvider()]
        with caplog.at_level(logging.INFO, logger="llmwikify.apps.research.web_search"):
            FallbackSearchProvider(chain)
        messages = [r.message for r in caplog.records]
        chain_log = [m for m in messages if "fallback chain" in m]
        assert chain_log, (
            "FallbackSearchProvider.__init__ should log the resolved chain"
        )
        # Verify both providers are named
        msg = chain_log[0]
        assert "SearXNGProvider" in msg
        assert "DuckDuckGoProvider" in msg
        # Order is preserved (SearXNG first, DuckDuckGo second)
        assert msg.index("SearXNGProvider") < msg.index("DuckDuckGoProvider")


# ─── gather_skill web_search fallback level ──────────────────────


class TestGatherSkillFallbackLoggingLevel:
    """Phase 4: gather_skill's web_search fallback path must log
    success at INFO and failure at WARNING (was DEBUG, easy to miss).
    """

    @pytest.mark.asyncio
    async def test_successful_web_search_logs_at_info(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When the web_search fallback returns results, both the
        invocation and the result-count log lines must appear at INFO.
        """
        from llmwikify.apps.chat.skills import SkillContext
        from llmwikify.apps.chat.skills.pipelines.gather_skill import _gather
        from llmwikify.apps.research.web_search import SearchResult

        # Wiki returns 0 results to force web fallback path.
        wiki = MagicMock()
        wiki.search = MagicMock(return_value=[])

        ctx = SkillContext(config={"web_search_results_per_query": 3}).with_overrides(wiki=wiki)

        # Patch WebSearch.search to return 2 results synchronously
        mock_search_instance = MagicMock()
        mock_search_instance.search = AsyncMock(
            return_value=[
                SearchResult(title="t1", url="https://a", snippet="s1"),
                SearchResult(title="t2", url="https://b", snippet="s2"),
            ]
        )

        with patch(
            "llmwikify.apps.research.web_search.WebSearch",
            return_value=mock_search_instance,
        ):
            with caplog.at_level(
                logging.DEBUG,
                logger="llmwikify.apps.chat.skills.pipelines.gather_skill",
            ):
                r = await _gather(
                    {"sub_queries": [{"q": "alpha"}], "enable_web_search": True},
                    ctx,
                )

        assert r.status == "ok"
        info_msgs = [
            r for r in caplog.records
            if r.levelno == logging.INFO
            and "gather_skill web_search fallback" in r.message
        ]
        assert len(info_msgs) >= 2, (
            f"expected invocation + result-count INFO logs, got: "
            f"{[r.message for r in caplog.records]}"
        )
        # Result-count log mentions 2 results
        assert any("2 results" in r.message for r in info_msgs)

    @pytest.mark.asyncio
    async def test_failed_web_search_logs_at_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When WebSearch raises an exception, the failure must be
        logged at WARNING (not DEBUG), so operators see it.
        """
        from llmwikify.apps.chat.skills import SkillContext
        from llmwikify.apps.chat.skills.pipelines.gather_skill import _gather

        wiki = MagicMock()
        wiki.search = MagicMock(return_value=[])

        ctx = SkillContext(config={"web_search_results_per_query": 3}).with_overrides(wiki=wiki)

        mock_search_instance = MagicMock()
        mock_search_instance.search = AsyncMock(
            side_effect=RuntimeError("search provider unavailable"),
        )

        with patch(
            "llmwikify.apps.research.web_search.WebSearch",
            return_value=mock_search_instance,
        ):
            with caplog.at_level(
                logging.DEBUG,
                logger="llmwikify.apps.chat.skills.pipelines.gather_skill",
            ):
                r = await _gather(
                    {"sub_queries": [{"q": "alpha"}], "enable_web_search": True},
                    ctx,
                )

        assert r.status == "ok"
        warn_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "web_search fallback failed" in r.message
        ]
        assert warn_msgs, (
            "WebSearch failure in gather_skill fallback must log at WARNING"
        )
        assert any("search provider unavailable" in r.message for r in warn_msgs)


# ─── gatherer.py WebSearch invocation logging ────────────────────


class TestGathererWebSearchLogging:
    """Phase 4: gatherer._gather_one must log WebSearch invocations
    at INFO and timeouts at WARNING. Previously had no logging at
    all, which made "why is gather hanging?" impossible to debug.
    """

    @pytest.mark.asyncio
    async def test_logs_invocation_and_result_count(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When the gatherer invokes WebSearch for a 'web' sub-query,
        it should log both the invocation and the result count.
        """
        from llmwikify.apps.chat.gatherer import SourceGatherer
        from llmwikify.apps.research.web_search import SearchResult

        # Build a minimal SourceGatherer with mocked deps
        wiki = MagicMock()
        db = MagicMock()
        sm = MagicMock()
        sm.session_id = "test-session"
        sm.complete_sub_query = MagicMock()

        # parallel_wiki_search=False keeps the test focused on the
        # simple web path (no parallel wiki search to mock).
        config = {
            "web_search_results_per_query": 5,
            "parallel_wiki_search": False,
        }
        gatherer = SourceGatherer(wiki, db, sm, config)

        # Build a sub-query that forces web search path
        sub_query = {
            "id": 42,
            "query": "machine learning",
            "source_type": "web",
            "url": "",
        }

        # Mock WebSearch to return 3 results
        mock_search = MagicMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(title="t1", url="https://a", snippet="s1"),
                SearchResult(title="t2", url="https://b", snippet="s2"),
                SearchResult(title="t3", url="https://c", snippet="s3"),
            ]
        )

        # Mock _fetch_url to return placeholder content
        async def fake_fetch_url(source_type, url):
            return f"<html>content for {url}</html>"

        with patch(
            "llmwikify.apps.research.web_search.WebSearch",
            return_value=mock_search,
        ):
            with patch.object(gatherer, "_fetch_url", fake_fetch_url):
                with caplog.at_level(
                    logging.DEBUG, logger="llmwikify.apps.chat.gatherer",
                ):
                    await gatherer._gather_one(sub_query, seen_urls=set())

        # Verify INFO logs for invocation + result count
        info_msgs = [
            r for r in caplog.records
            if r.levelno == logging.INFO and "Gather sub_query" in r.message
        ]
        assert len(info_msgs) >= 2, (
            f"expected invocation + result-count INFO logs, got: "
            f"{[r.message for r in caplog.records]}"
        )
        assert any("invoking WebSearch" in r.message for r in info_msgs)
        assert any("returned 3 results" in r.message for r in info_msgs)

    @pytest.mark.asyncio
    async def test_logs_timeout_at_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When WebSearch hangs long enough for asyncio.wait_for to
        time it out, the gatherer must log at WARNING before raising
        ValueError('Search timed out').
        """
        from llmwikify.apps.chat.gatherer import SourceGatherer

        wiki = MagicMock()
        db = MagicMock()
        sm = MagicMock()
        sm.session_id = "test-session"

        config = {
            "web_search_results_per_query": 5,
            "parallel_wiki_search": False,
        }
        gatherer = SourceGatherer(wiki, db, sm, config)

        sub_query = {
            "id": 99,
            "query": "slow query",
            "source_type": "web",
            "url": "",
        }

        # Mock WebSearch to raise asyncio.TimeoutError when called.
        # The gatherer's wait_for wraps this, so TimeoutError
        # propagates and triggers the except branch.
        mock_search = MagicMock()

        async def timeout_search(*args, **kwargs):
            raise asyncio.TimeoutError()

        mock_search.search = timeout_search

        with patch(
            "llmwikify.apps.research.web_search.WebSearch",
            return_value=mock_search,
        ):
            with caplog.at_level(
                logging.DEBUG, logger="llmwikify.apps.chat.gatherer",
            ):
                # _gather_one catches the ValueError internally and
                # returns []; we just check the WARNING log fired.
                await gatherer._gather_one(sub_query, seen_urls=set())

        warn_msgs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and "timed out" in r.message
        ]
        assert warn_msgs, (
            f"Gatherer must log WebSearch timeout at WARNING; "
            f"got: {[r.message for r in caplog.records]}"
        )


# ─── routes.start_autoresearch config_info event ────────────────


class TestStartAutoresearchPersistsConfigInfo:
    """Phase 4: start_autoresearch must persist a config_info event
    with the search provider configuration, so the UI / operators
    can see which providers the engine will try.
    """

    def _setup_deps(self, config: dict | None = None):
        """Wire up the autoresearch module globals with mocks."""
        from llmwikify.apps.research import routes as routes_mod

        # Mock DB that captures append_events calls
        db = MagicMock()
        db.append_events = MagicMock(return_value=1)

        # Mock session_manager
        sm = MagicMock()
        sm.create_session = MagicMock(return_value="sess-abc123")

        # Mock engine
        engine = MagicMock()
        engine.session_manager = sm
        engine.db = db
        engine.config = config or {
            "search_provider": "auto",
            "minimax_api_key": None,
            "max_react_rounds": 10,
            "max_replan_attempts": 2,
            "web_search_results_per_query": 5,
        }

        # Wire up the routes module globals
        routes_mod._AUTORESEARCH_DB = db
        routes_mod._WIKI_REGISTRY = MagicMock()
        routes_mod._LLM_CLIENT = MagicMock()
        routes_mod._AUTORESEARCH_CONFIG = engine.config
        routes_mod._ENGINE_CACHE = {}
        # Bypass wiki lookup with a cached engine
        routes_mod._ENGINE_CACHE["default"] = engine

        # Stub the task manager so tm.start() doesn't fire a real task
        mock_tm = MagicMock()
        mock_tm.start = MagicMock()
        with patch(
            "llmwikify.apps.research.routes.get_task_manager",
            return_value=mock_tm,
        ):
            yield engine, db, routes_mod

        # Reset globals to avoid leaking into other tests
        routes_mod._AUTORESEARCH_DB = None
        routes_mod._WIKI_REGISTRY = None
        routes_mod._LLM_CLIENT = None
        routes_mod._AUTORESEARCH_CONFIG = None
        routes_mod._ENGINE_CACHE = {}

    @pytest.mark.asyncio
    async def test_persists_config_info_event_with_provider(
        self,
    ) -> None:
        """start_autoresearch must call db.append_events with a
        config_info payload that includes the search provider name.
        """
        from fastapi import Request

        from llmwikify.apps.research import routes as routes_mod

        config = {
            "search_provider": "minimax",
            "minimax_api_key": "sk-cp-test",
            "max_react_rounds": 12,
            "max_replan_attempts": 3,
            "web_search_results_per_query": 7,
        }

        for _engine, db, _routes_mod in self._setup_deps(config=config):
            # Build a minimal request-like object
            request = MagicMock(spec=Request)
            request.json = AsyncMock(
                return_value={"query": "alpha-beta-gamma", "wiki_id": None}
            )

            response = await routes_mod.start_autoresearch(request)
            assert response["session_id"] == "sess-abc123"
            assert response["status"] == "running"

            # append_events must have been called with [config_info, ...]
            assert db.append_events.called, (
                "start_autoresearch should persist a config_info event"
            )
            call_args = db.append_events.call_args
            events = call_args[0][1]
            assert len(events) == 1
            ev = events[0]
            assert ev["type"] == "config_info"
            assert ev["phase"] == "start"
            assert ev["search_provider"] == "minimax"
            assert ev["minimax_configured"] is True
            assert ev["max_react_rounds"] == 12
            assert ev["max_replan_attempts"] == 3
            assert ev["web_search_results_per_query"] == 7

    @pytest.mark.asyncio
    async def test_minimax_configured_false_when_no_key(
        self,
    ) -> None:
        """When no minimax_api_key is configured, minimax_configured
        must be False in the persisted event.
        """
        from fastapi import Request

        from llmwikify.apps.research import routes as routes_mod

        config = {
            "search_provider": "duckduckgo",
            "minimax_api_key": None,
            "max_react_rounds": 10,
            "max_replan_attempts": 2,
            "web_search_results_per_query": 5,
        }

        for _engine, db, _routes_mod in self._setup_deps(config=config):
            request = MagicMock(spec=Request)
            request.json = AsyncMock(
                return_value={"query": "test query", "wiki_id": None}
            )

            await routes_mod.start_autoresearch(request)

            events = db.append_events.call_args[0][1]
            ev = events[0]
            assert ev["search_provider"] == "duckduckgo"
            assert ev["minimax_configured"] is False

    @pytest.mark.asyncio
    async def test_logs_startup_summary(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """start_autoresearch must emit an INFO log summarizing
        the search provider configuration at startup.
        """
        from fastapi import Request

        from llmwikify.apps.research import routes as routes_mod

        config = {
            "search_provider": "minimax",
            "minimax_api_key": "sk-cp-test",
            "max_react_rounds": 10,
            "max_replan_attempts": 2,
        }

        for _engine, _db, _routes_mod in self._setup_deps(config=config):
            request = MagicMock(spec=Request)
            request.json = AsyncMock(
                return_value={"query": "test", "wiki_id": None}
            )

            with caplog.at_level(
                logging.INFO, logger="llmwikify.apps.research.routes",
            ):
                await routes_mod.start_autoresearch(request)

            msgs = [
                r for r in caplog.records
                if "autoresearch start" in r.message
                and "session=sess-abc123" in r.message
            ]
            assert msgs, (
                f"expected startup summary log, got: "
                f"{[r.message for r in caplog.records]}"
            )
            msg = msgs[0].message
            assert "provider=minimax" in msg
            assert "minimax_key=True" in msg

    @pytest.mark.asyncio
    async def test_handles_append_events_failure_gracefully(
        self,
    ) -> None:
        """If db.append_events raises, start_autoresearch must not
        fail the request (log warning + continue).
        """
        from fastapi import Request

        from llmwikify.apps.research import routes as routes_mod

        for _engine, db, _routes_mod in self._setup_deps():
            db.append_events = MagicMock(
                side_effect=RuntimeError("DB locked"),
            )
            request = MagicMock(spec=Request)
            request.json = AsyncMock(
                return_value={"query": "test", "wiki_id": None}
            )

            response = await routes_mod.start_autoresearch(request)
            # Session is still created; only the diagnostic event failed
            assert response["session_id"] == "sess-abc123"
            assert response["status"] == "running"
