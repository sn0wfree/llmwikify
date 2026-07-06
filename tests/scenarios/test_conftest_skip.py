"""Tests for the scenarios conftest auto-skip helpers.

Covers ``tests/scenarios/conftest.py``:

  * ``_server_base_url()`` — reads ``SERVER_URL`` env, default localhost:8765
  * ``_is_server_available()`` — GET /api/health with 2s timeout
  * ``pytest_collection_modifyitems()`` — skips ``@pytest.mark.llm`` and
    ``@pytest.mark.requires_server`` markers when their prerequisites
    are unavailable

These helpers gate 5 ``tests/scenarios/test_04_chat_react.py`` tests
that need a running llmwikify server. Without them, CI jobs that
don't start the server see 5 ConnectionRefusedError failures instead
of clean skips.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import httpx
import pytest


def _reload_conftest():
    """Load conftest.py from this test file's directory.

    ``tests/__init__.py`` doesn't exist, so ``tests.scenarios.conftest``
    isn't importable as a dotted path. Load the module by file location
    instead so we can monkeypatch its helpers directly.
    """
    cf_path = Path(__file__).resolve().parent / "conftest.py"
    spec = importlib.util.spec_from_file_location("_scenarios_conftest", cf_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestServerBaseUrl:
    """``_server_base_url()`` priority: SERVER_URL env > default."""

    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("SERVER_URL", raising=False)
        cf = _reload_conftest()
        assert cf._server_base_url() == "http://localhost:8765"

    def test_respects_server_url_env(self, monkeypatch):
        monkeypatch.setenv("SERVER_URL", "http://example.test:9999")
        cf = _reload_conftest()
        assert cf._server_base_url() == "http://example.test:9999"


class TestIsServerAvailable:
    """``_is_server_available()`` health-probe with 2s timeout."""

    def test_returns_true_on_200(self, monkeypatch):
        """A 200 from ``/api/health`` means the server is up."""
        monkeypatch.setenv("SERVER_URL", "http://probe.test:1234")

        class FakeResponse:
            status_code = 200

        def fake_get(url, timeout):
            assert url == "http://probe.test:1234/api/health"
            assert timeout == 2.0
            return FakeResponse()

        monkeypatch.setattr(httpx, "get", fake_get)
        cf = _reload_conftest()
        assert cf._is_server_available() is True

    def test_returns_false_on_non_200(self, monkeypatch):
        """A non-200 status means the server is reachable but unhealthy."""
        monkeypatch.setenv("SERVER_URL", "http://probe.test:1234")

        class FakeResponse:
            status_code = 503

        monkeypatch.setattr(httpx, "get", lambda url, timeout: FakeResponse())
        cf = _reload_conftest()
        assert cf._is_server_available() is False

    def test_returns_false_on_connection_refused(self, monkeypatch):
        """ConnectError → False. This is the CI-no-server path."""
        monkeypatch.setenv("SERVER_URL", "http://nope.test:1234")

        def fake_get(url, timeout):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "get", fake_get)
        cf = _reload_conftest()
        assert cf._is_server_available() is False

    def test_returns_false_on_timeout(self, monkeypatch):
        """Timeout → False (treat as unavailable)."""
        monkeypatch.setenv("SERVER_URL", "http://slow.test:1234")

        def fake_get(url, timeout):
            raise httpx.TimeoutException("read timed out")

        monkeypatch.setattr(httpx, "get", fake_get)
        cf = _reload_conftest()
        assert cf._is_server_available() is False


class TestCollectionModifyItems:
    """``pytest_collection_modifyitems()`` skip markers by prerequisite."""

    def test_adds_llm_skip_when_no_llm(self, monkeypatch):
        """Without LLM_API_KEY, llm-marked items get a skip marker."""
        cf = _reload_conftest()
        monkeypatch.setattr(cf, "_is_llm_available", lambda: False)
        monkeypatch.setattr(cf, "_is_server_available", lambda: True)

        item = _FakeItem(markers={"llm"})
        cf.pytest_collection_modifyitems(None, [item])

        skip_reasons = [m.kwargs.get("reason", "") for m in item.added_markers]
        assert any("LLM_API_KEY" in r for r in skip_reasons)

    def test_adds_server_skip_when_no_server(self, monkeypatch):
        """Without server, requires_server-marked items get a skip marker."""
        cf = _reload_conftest()
        monkeypatch.setattr(cf, "_is_llm_available", lambda: True)
        monkeypatch.setattr(cf, "_is_server_available", lambda: False)

        item = _FakeItem(markers={"requires_server"})
        cf.pytest_collection_modifyitems(None, [item])

        skip_reasons = [m.kwargs.get("reason", "") for m in item.added_markers]
        assert any("server not available" in r for r in skip_reasons)

    def test_no_skip_when_both_available(self, monkeypatch):
        """When both prerequisites are met, no skip markers are added."""
        cf = _reload_conftest()
        monkeypatch.setattr(cf, "_is_llm_available", lambda: True)
        monkeypatch.setattr(cf, "_is_server_available", lambda: True)

        item = _FakeItem(markers={"llm", "requires_server"})
        cf.pytest_collection_modifyitems(None, [item])
        assert item.added_markers == []


class _FakeItem:
    """Minimal pytest.Item stand-in for testing collection-modify hooks."""

    def __init__(self, markers):
        self.keywords = set(markers)
        self.added_markers = []

    def add_marker(self, marker):
        self.added_markers.append(marker)
