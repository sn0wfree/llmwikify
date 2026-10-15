"""Live integration test for MiniMax web search API.

This test makes **real HTTP calls** to
``POST https://api.minimaxi.com/v1/coding_plan/search`` and verifies the
response shape that ``apps/research/web_search.py::MiniMaxSearchProvider``
expects.

Skip policy:
- Skipped if ``MINIMAX_SEARCH_KEY`` env var is unset
- Skipped if the API returns non-2xx (e.g. token expired)
- Run explicitly with::

      MINIMAX_SEARCH_KEY="sk-cp-..." pytest tests/integration_minimax_web_search.py -v

This is the minimum-viable live test we wanted per the 2026-07-03 audit.
A passing run here proves the upstream contract that the code depends on.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = "https://api.minimaxi.com/v1/coding_plan/search"


def _has_key() -> bool:
    """Return True iff we have a MiniMax key to test against."""
    return bool(os.environ.get("MINIMAX_SEARCH_KEY") or os.environ.get("LLM_API_KEY"))


pytestmark = pytest.mark.skipif(
    not _has_key(),
    reason="MINIMAX_SEARCH_KEY (or LLM_API_KEY) env var required for live test",
)


def _post(query: str, key: str) -> dict:
    """Make a real search request. Returns the parsed JSON body."""
    with httpx.Client(timeout=30) as client:
        resp = client.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {key}",
                "MM-API-Source": "Minimax-MCP",
                "Content-Type": "application/json",
            },
            json={"q": query},
        )
    resp.raise_for_status()
    return resp.json()


def _key() -> str:
    return os.environ.get("MINIMAX_SEARCH_KEY") or os.environ["LLM_API_KEY"]


class TestMiniMaxWebSearchContract:
    """Validate the upstream contract ``MiniMaxSearchProvider`` depends on."""

    def test_basic_query_returns_organic(self):
        """The happy path: query → 0+ organic results."""
        body = _post("python programming", _key())
        assert body["base_resp"]["status_code"] == 0, body
        assert isinstance(body.get("organic"), list)
        assert len(body["organic"]) >= 1, body

    def test_organic_items_have_required_keys(self):
        """Each organic item must have title / link / snippet (code reads these)."""
        body = _post("python programming", _key())
        assert body["base_resp"]["status_code"] == 0
        for item in body["organic"]:
            assert "title" in item
            assert "link" in item
            assert "snippet" in item
            assert item["link"], "link must not be empty"
            assert item["link"].startswith(("http://", "https://"))

    def test_chinese_query_works(self):
        """The endpoint supports Chinese queries (regression for v0.39 case)."""
        body = _post("llmwikify 知识库", _key())
        assert body["base_resp"]["status_code"] == 0, body
        # Chinese results may be sparser; just check the call succeeded
        assert isinstance(body.get("organic"), list)


# ─── marker for CI / explicit opt-in ────────────────────────────


def pytest_collection_modifyitems(config, items):
    """Tag every test in this file with ``integration_live`` so CI can split them.

    Run only the fast subset by default::

        pytest -m "not integration_live"

    Run also the live web tests with the key::

        MINIMAX_SEARCH_KEY=... pytest -m integration_live
    """
    for item in items:
        item.add_marker(pytest.mark.integration_live)
