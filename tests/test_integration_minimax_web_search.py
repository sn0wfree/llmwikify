"""Live integration test for MiniMax web search API.

This test makes **real HTTP calls** to
``POST https://api.minimaxi.com/v1/coding_plan/search`` and verifies the
response shape that ``apps/research/web_search.py::MiniMaxSearchProvider``
expects.

Skip policy:
- Skipped unless ``MINIMAX_SEARCH_KEY`` is set — the search endpoint
  takes a coding-plan key (``sk-cp-...``), not the chat key, so
  ``LLM_API_KEY`` must not be accepted here
- Tagged ``integration_live``; the default pytest run excludes that marker

Run explicitly with::

      MINIMAX_SEARCH_KEY="sk-cp-..." pytest -m integration_live -v

This is the minimum-viable live test we wanted per the 2026-07-03 audit.
A passing run here proves the upstream contract that the code depends on.
"""

from __future__ import annotations

import os

import httpx
import pytest

API_URL = "https://api.minimaxi.com/v1/coding_plan/search"


def _has_key() -> bool:
    """Return True iff a MiniMax *search* key is available."""
    return bool(os.environ.get("MINIMAX_SEARCH_KEY"))


pytestmark = [
    pytest.mark.integration_live,
    pytest.mark.skipif(
        not _has_key(),
        reason="MINIMAX_SEARCH_KEY env var required for live test",
    ),
]


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
    return os.environ["MINIMAX_SEARCH_KEY"]


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
