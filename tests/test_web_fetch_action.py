"""Unit tests for web_fetch_skill (v0.41, #25th base Skill).

Covers the single ``fetch_url`` action exposed by the web_fetch
Skill. Implementation uses httpx; tests mock httpx.AsyncClient
to avoid real network calls.

Target: 12 tests covering inventory, input validation, happy
path, error handling, HTML stripping, and title extraction.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmwikify.apps.chat.skills import (
    SkillContext,
    SkillRegistry,
    SkillRuntime,
)
from llmwikify.apps.chat.skills.actions import (
    ALL_ACTIONS,
    register_all_actions,
    unregister_all_actions,
    web_fetch_skill,
)
from llmwikify.apps.chat.skills.actions.web_fetch_action import (
    DEFAULT_MAX_CHARS,
    DEFAULT_TIMEOUT,
    MAX_HARD_CAP,
    _extract_title,
    _strip_html,
    fetch_url,
    fetch_url_sync,
)


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext()


@pytest.fixture
def fresh_registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def populated_registry(fresh_registry: SkillRegistry) -> SkillRegistry:
    register_all_actions(fresh_registry)
    return fresh_registry


@pytest.fixture
def runtime(populated_registry: SkillRegistry) -> SkillRuntime:
    return SkillRuntime(populated_registry)


# ─── Inventory ───────────────────────────────────────────────────


class TestInventory:
    def test_skill_name_is_web_fetch(self) -> None:
        assert web_fetch_skill.name == "web_fetch"

    def test_skill_has_one_action(self) -> None:
        assert set(web_fetch_skill.actions.keys()) == {"fetch_url"}

    def test_skill_in_all_actions(self) -> None:
        assert web_fetch_skill in ALL_ACTIONS

    def test_skill_registerable(self, fresh_registry: SkillRegistry) -> None:
        n = register_all_actions(fresh_registry)
        assert n == 25
        assert fresh_registry.has("web_fetch")

    def test_fetch_url_action_schema(self) -> None:
        action = web_fetch_skill.actions["fetch_url"]
        schema = action.input_schema
        assert "url" in schema["required"]
        assert "url" in schema["properties"]
        assert "max_chars" in schema["properties"]
        assert schema["properties"]["max_chars"]["default"] == DEFAULT_MAX_CHARS
        assert schema["properties"]["max_chars"]["maximum"] == MAX_HARD_CAP


# ─── Input validation ───────────────────────────────────────────


class TestInputValidation:
    @pytest.mark.asyncio
    async def test_missing_url(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute("web_fetch", "fetch_url", {}, ctx)
        assert r.status == "error"
        assert "url" in r.error.lower()

    @pytest.mark.asyncio
    async def test_empty_url(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_fetch", "fetch_url", {"url": "   "}, ctx,
        )
        assert r.status == "error"
        assert "url" in r.error.lower()

    @pytest.mark.asyncio
    async def test_bad_max_chars(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_fetch", "fetch_url",
            {"url": "https://example.com", "max_chars": "not-int"},
            ctx,
        )
        assert r.status == "error"
        assert "max_chars" in r.error

    @pytest.mark.asyncio
    async def test_negative_max_chars(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        r = await runtime.execute(
            "web_fetch", "fetch_url",
            {"url": "https://example.com", "max_chars": -1},
            ctx,
        )
        assert r.status == "error"
        assert "max_chars" in r.error

    @pytest.mark.asyncio
    async def test_huge_max_chars_capped(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        """max_chars > MAX_HARD_CAP gets silently capped, not rejected."""
        # Mock httpx to return a short page
        with patch("httpx.AsyncClient") as mock_async_client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            resp = MagicMock()
            resp.status_code = 200
            resp.text = "<html><head><title>T</title></head><body>Hello world.</body></html>"
            client.get = AsyncMock(return_value=resp)
            mock_async_client.return_value = client

            r = await runtime.execute(
                "web_fetch", "fetch_url",
                {"url": "https://example.com", "max_chars": 100_000_000},
                ctx,
            )
        assert r.status == "ok"
        # Capped at MAX_HARD_CAP
        assert r.data["length"] <= MAX_HARD_CAP


# ─── HTML helpers ────────────────────────────────────────────────


class TestHtmlHelpers:
    def test_extract_title(self) -> None:
        assert _extract_title("<html><head><title>Hello World</title></head></html>") == "Hello World"

    def test_extract_title_empty(self) -> None:
        assert _extract_title("<html><body>no title here</body></html>") == ""

    def test_extract_title_multiline(self) -> None:
        html = "<title>Line 1\nLine 2</title>"
        assert _extract_title(html) == "Line 1\nLine 2"

    def test_strip_html_basic(self) -> None:
        assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"

    def test_strip_html_removes_script(self) -> None:
        text = _strip_html(
            "<div>visible<script>alert('x')</script></div>"
        )
        assert "visible" in text
        assert "alert" not in text
        assert "script" not in text.lower()

    def test_strip_html_removes_style(self) -> None:
        text = _strip_html(
            "<div>visible<style>.x{color:red}</style></div>"
        )
        assert "visible" in text
        assert "color" not in text

    def test_strip_html_collapses_whitespace(self) -> None:
        text = _strip_html("<p>a</p>   <p>b</p>\n\n<p>c</p>")
        assert text == "a b c"


# ─── Happy path: fetch_url returns structured payload ────────────


def _make_mock_httpx_response(
    text: str = "<html><head><title>Mock Title</title></head><body><p>Hello world.</p></body></html>",
    status_code: int = 200,
):
    """Build a mock httpx response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_fetch_url_basic(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch("httpx.AsyncClient") as mock_async_client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(return_value=_make_mock_httpx_response())
            mock_async_client.return_value = client

            r = await runtime.execute(
                "web_fetch", "fetch_url",
                {"url": "https://example.com"}, ctx,
            )
        assert r.status == "ok"
        d = r.data
        assert d["url"] == "https://example.com"
        assert d["status"] == 200
        assert d["title"] == "Mock Title"
        assert "Hello world" in d["content"]
        assert d["length"] > 0
        assert d["truncated"] is False

    @pytest.mark.asyncio
    async def test_fetch_url_long_content_truncated(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        long_body = "<p>" + ("x" * 5000) + "</p>"
        with patch("httpx.AsyncClient") as mock_async_client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(return_value=_make_mock_httpx_response(long_body))
            mock_async_client.return_value = client

            r = await runtime.execute(
                "web_fetch", "fetch_url",
                {"url": "https://example.com", "max_chars": 100}, ctx,
            )
        assert r.status == "ok"
        assert r.data["truncated"] is True
        assert len(r.data["content"]) <= 100

    @pytest.mark.asyncio
    async def test_fetch_url_404_returns_error(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch("httpx.AsyncClient") as mock_async_client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(return_value=_make_mock_httpx_response("", status_code=404))
            mock_async_client.return_value = client

            r = await runtime.execute(
                "web_fetch", "fetch_url",
                {"url": "https://example.com/missing"}, ctx,
            )
        assert r.status == "error"
        assert "404" in r.error

    @pytest.mark.asyncio
    async def test_fetch_url_network_failure(
        self, runtime: SkillRuntime, ctx: SkillContext,
    ) -> None:
        with patch("httpx.AsyncClient") as mock_async_client:
            client = AsyncMock()
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client.get = AsyncMock(side_effect=ConnectionError("dns failure"))
            mock_async_client.return_value = client

            r = await runtime.execute(
                "web_fetch", "fetch_url",
                {"url": "https://no-such-host.example"}, ctx,
            )
        assert r.status == "error"
        assert "ConnectionError" in r.error or "dns failure" in r.error


# ─── Sync wrapper (for subagent_worker tool loop) ───────────────


class TestSyncWrapper:
    def test_fetch_url_sync_basic(self) -> None:
        with patch("httpx.AsyncClient") as mock_async_client:
            client_instance = MagicMock()
            client_instance.__aenter__ = AsyncMock(return_value=client_instance)
            client_instance.__aexit__ = AsyncMock(return_value=None)
            client_instance.get = AsyncMock(return_value=_make_mock_httpx_response())
            mock_async_client.return_value = client_instance

            r = fetch_url_sync("https://example.com", max_chars=500)
        assert r["status"] == 200
        assert r["title"] == "Mock Title"
        assert "Hello world" in r["content"]

    def test_fetch_url_sync_empty_url(self) -> None:
        r = fetch_url_sync("")
        assert "error" in r
        assert r.get("url") == ""


# ─── Constants ───────────────────────────────────────────────────


class TestConstants:
    def test_default_max_chars(self) -> None:
        assert DEFAULT_MAX_CHARS == 2000

    def test_max_hard_cap(self) -> None:
        assert MAX_HARD_CAP == 50_000

    def test_default_timeout(self) -> None:
        assert DEFAULT_TIMEOUT == 10.0