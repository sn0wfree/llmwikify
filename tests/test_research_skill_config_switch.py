"""Unit tests for research_skill._act_gather config switch (v0.41).

The 7-step research pipeline used to default ``enable_web_search``
to ``False``, so the gather_skill web fallback never fired. v0.41
makes it config-driven with a default of ``True``.

Target: 8 tests covering:
  - Default True when no config provided
  - ``research.enable_web_search=True`` passes through
  - ``research.enable_web_search=False`` blocks fallback
  - Truthy/falsy coercion
  - Other research.* keys ignored
  - sub_queries and sources pass-through
  - Empty sub_queries short-circuit
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llmwikify.apps.chat.skills import SkillContext
from llmwikify.apps.chat.skills.research_skill import _act_gather


# ─── Helpers ─────────────────────────────────────────────────────


def _make_ctx(config: dict | None = None) -> SkillContext:
    return SkillContext(config=config or {})


def _make_state(sub_queries: list[dict]) -> dict:
    return {"sub_queries": sub_queries}


def _patch_gather_handler(return_data: dict | None = None):
    """Patch gather_skill.actions["gather_for_research"].handler.

    Returns a context manager. ``return_data`` defaults to a
    success with empty sources.

    Patches the ``gather_skill`` attribute on the actual
    ``gather_skill`` module in ``sys.modules`` (NOT on the
    ``pipelines`` package, which has its own shadowing attribute).
    """
    import sys
    import importlib
    # Ensure the gather_skill module is fully loaded.
    importlib.import_module(
        "llmwikify.apps.chat.skills.pipelines.gather_skill",
    )
    gs_mod = sys.modules[
        "llmwikify.apps.chat.skills.pipelines.gather_skill"
    ]

    if return_data is None:
        return_data = {
            "sources": [],
            "_new_sources": 0,
            "_failed_queries": [],
        }

    fake_handler = AsyncMock(
        return_value=MagicMock(status="ok", data=return_data),
    )
    fake_actions = {"gather_for_research": MagicMock(handler=fake_handler)}

    return patch.object(
        gs_mod, "gather_skill",
        MagicMock(actions=fake_actions),
    ), fake_handler


# ─── Default behavior ───────────────────────────────────────────


class TestDefaultBehavior:
    @pytest.mark.asyncio
    async def test_no_config_defaults_to_true(self) -> None:
        """When config is missing, ``enable_web_search`` defaults to True."""
        ctx = _make_ctx()  # empty config
        state = _make_state([{"q": "x", "status": "pending"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        call_args = fake_handler.call_args
        passed_args = call_args.args[0]
        assert passed_args["enable_web_search"] is True, (
            "Default should be True; got "
            f"{passed_args.get('enable_web_search')!r}"
        )


# ─── Config-driven behavior ──────────────────────────────────────


class TestConfigSwitch:
    @pytest.mark.asyncio
    async def test_config_true_passes_through(self) -> None:
        ctx = _make_ctx({"research": {"enable_web_search": True}})
        state = _make_state([{"q": "x", "status": "pending"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        assert fake_handler.call_args.args[0]["enable_web_search"] is True

    @pytest.mark.asyncio
    async def test_config_false_blocks_fallback(self) -> None:
        ctx = _make_ctx({"research": {"enable_web_search": False}})
        state = _make_state([{"q": "x", "status": "pending"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        assert fake_handler.call_args.args[0]["enable_web_search"] is False

    @pytest.mark.asyncio
    async def test_non_boolean_truthy_coerced_to_true(self) -> None:
        ctx = _make_ctx({"research": {"enable_web_search": "yes"}})
        state = _make_state([{"q": "x", "status": "pending"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        assert fake_handler.call_args.args[0]["enable_web_search"] is True

    @pytest.mark.asyncio
    async def test_other_research_keys_ignored(self) -> None:
        """Other research.* keys shouldn't affect the switch."""
        ctx = _make_ctx({
            "research": {"max_concurrent": 4, "enable_web_search": False},
        })
        state = _make_state([{"q": "x", "status": "pending"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        assert fake_handler.call_args.args[0]["enable_web_search"] is False


# ─── Pass-through of sub_queries and sources ─────────────────────


class TestPassThrough:
    @pytest.mark.asyncio
    async def test_sub_queries_passed(self) -> None:
        ctx = _make_ctx({"research": {"enable_web_search": True}})
        state = _make_state([
            {"q": "alpha", "status": "pending"},
            {"q": "beta", "status": "pending"},
        ])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            await _act_gather(state, ctx)

        passed = fake_handler.call_args.args[0]
        assert len(passed["sub_queries"]) == 2
        assert passed["sub_queries"][0]["q"] == "alpha"
        assert passed["sub_queries"][1]["q"] == "beta"

    @pytest.mark.asyncio
    async def test_existing_sources_passed(self) -> None:
        ctx = _make_ctx()
        state = {
            "sub_queries": [{"q": "x", "status": "pending"}],
            "sources": [{"url": "https://a", "source_type": "wiki"}],
        }

        ctx_patch, fake_handler = _patch_gather_handler({
            "sources": [{"url": "https://a"}],
            "_new_sources": 0,
            "_failed_queries": [],
        })
        with ctx_patch:
            await _act_gather(state, ctx)

        passed = fake_handler.call_args.args[0]
        assert passed["sources"] == [
            {"url": "https://a", "source_type": "wiki"},
        ]

    @pytest.mark.asyncio
    async def test_no_sub_queries_short_circuits(self) -> None:
        """When all sub_queries are already gathered, gather handler not called."""
        ctx = _make_ctx()
        state = _make_state([{"q": "x", "status": "gathered"}])

        ctx_patch, fake_handler = _patch_gather_handler()
        with ctx_patch:
            result = await _act_gather(state, ctx)
            fake_handler.assert_not_called()

        assert result.status == "ok"
        assert result.data["_new_sources"] == 0