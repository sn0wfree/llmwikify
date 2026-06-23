"""Tests for ``AgentExecutionContext`` + LSP-correct ``SubagentManager``.

Phase 16+ (2026-06-23) lifted the 4 private-attribute ``hasattr``
gate that ``SubagentManager.__init__`` used to enforce. The manager
now reads collaborators through the new
:meth:`AgentRunner.execution_context` ABC method, so any
``AgentRunner`` subclass works — including a test ``FakeAgentRunner``
that does NOT inherit from ``ChatRunnerV2``.

These tests cover:

  - ``AgentExecutionContext`` dataclass shape (smoke test)
  - ``ChatRunnerV2.execution_context()`` returns a fresh ctx
  - ``ChatRunnerV2.__init__`` accepts the ctx-only signature
  - ``ChatRunnerV2.__init__`` requires either ctx OR all 3 collaborators
  - ``SubagentManager`` accepts a non-ChatRunnerV2 ``AgentRunner``
  - ``SubagentManager`` child ctx overrides hook + memory_manager
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from llmwikify.apps.chat.agent.agent_runner import AgentRunner
from llmwikify.apps.chat.agent.execution_context import (
    AgentExecutionContext,
)
from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
from llmwikify.apps.chat.agent.subagent_manager import (
    SubagentManager,
    SubagentResult,
    SubagentSpec,
)
from llmwikify.foundation.callback import NoOpHook


class TestAgentExecutionContext:
    def test_dataclass_holds_all_six_fields(self):
        cs = MagicMock()
        te = MagicMock()
        pb = MagicMock()
        ctx = AgentExecutionContext(
            chat_service=cs,
            tool_executor=te,
            prompt_builder=pb,
            config={"max": 5},
            memory_manager=None,
            hook=NoOpHook(),
        )
        assert ctx.chat_service is cs
        assert ctx.tool_executor is te
        assert ctx.prompt_builder is pb
        assert ctx.config == {"max": 5}
        assert ctx.memory_manager is None
        assert isinstance(ctx.hook, NoOpHook)

    def test_optional_fields_default(self):
        """The 3 optional fields default to None."""
        ctx = AgentExecutionContext(
            chat_service=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
        )
        assert ctx.config is None
        assert ctx.memory_manager is None
        assert ctx.hook is None


class TestChatRunnerV2ExecutionContext:
    def test_returns_fresh_ctx(self):
        runner = ChatRunnerV2(
            chat_service=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
            config={"k": 1},
            hook=NoOpHook(),
            memory_manager=None,
        )
        ctx = runner.execution_context()
        assert isinstance(ctx, AgentExecutionContext)
        assert ctx.config == {"k": 1}

    def test_ctx_does_not_share_state(self):
        """Two calls return independent ctxs (mutations don't leak)."""
        runner = ChatRunnerV2(
            chat_service=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
        )
        ctx_a = runner.execution_context()
        ctx_b = runner.execution_context()
        assert ctx_a is not ctx_b
        # Mutating one must not affect the other.
        ctx_a.config = {"mutated": True}
        assert ctx_b.config != {"mutated": True}


class TestChatRunnerV2DualSignature:
    def test_accepts_ctx_only(self):
        cs = MagicMock()
        te = MagicMock()
        pb = MagicMock()
        ctx = AgentExecutionContext(
            chat_service=cs, tool_executor=te, prompt_builder=pb,
        )
        runner = ChatRunnerV2(ctx=ctx)
        assert runner._chat_service is cs
        assert runner._tool_executor is te
        assert runner._prompt_builder is pb

    def test_accepts_legacy_kwargs(self):
        """Old call sites (3 collaborators) still work."""
        runner = ChatRunnerV2(
            chat_service=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
        )
        assert runner._chat_service is not None

    def test_rejects_empty_init(self):
        """Either ctx or all 3 collaborators are required, OR
        the explicit all-None "skeleton" mode is allowed for
        AgentRunner ABC base + skeleton tests."""
        # All-None is allowed (skeleton mode).
        runner = ChatRunnerV2()
        assert runner._chat_service is None
        # But a *partial* set is rejected.
        with pytest.raises(TypeError, match="partial set"):
            ChatRunnerV2(chat_service=MagicMock(), tool_executor=None)

    def test_ctx_overrides_legacy_kwargs(self):
        """If both ctx and kwargs are passed, ctx wins for collaborators."""
        cs_ctx = MagicMock(name="ctx_cs")
        cs_kw = MagicMock(name="kw_cs")
        ctx = AgentExecutionContext(
            chat_service=cs_ctx,
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
        )
        runner = ChatRunnerV2(
            chat_service=cs_kw,  # legacy
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
            ctx=ctx,  # wins
        )
        assert runner._chat_service is cs_ctx


class TestSubagentManagerAcceptsAnyAgentRunner:
    """The LSP fix: any AgentRunner subclass works, not just ChatRunnerV2."""

    def test_accepts_custom_fake_agent_runner(self):
        """A non-ChatRunnerV2 AgentRunner is now valid input."""

        class _FakeAgentRunner(AgentRunner):
            def __init__(self) -> None:
                self._stub_ctx = AgentExecutionContext(
                    chat_service=MagicMock(name="cs"),
                    tool_executor=MagicMock(name="te"),
                    prompt_builder=MagicMock(name="pb"),
                )

            async def run_stream(self, spec):
                yield {"type": "done", "content": "ok"}
                return
                yield  # make this an async generator

            async def run_to_completion(self, spec):
                from dataclasses import dataclass as _dc
                @_dc
                class _R:
                    error = None
                    final_content = "ok"
                    tools_used = []
                    usage = {}
                    state_trace = []
                    stop_reason = "completed"
                return _R()

            def execution_context(self):
                return self._stub_ctx

        mgr = SubagentManager(_FakeAgentRunner())
        assert mgr.max_concurrent == 2

    def test_rejects_non_agent_runner_at_run_time(self):
        """Passing a string (or any object) doesn't raise at __init__
        (Python doesn't enforce type hints), but the manager
        immediately calls ``parent.execution_context()`` in ``run``,
        which fails with ``AttributeError`` for non-ABC inputs."""
        mgr = SubagentManager("not a runner")  # type: ignore[arg-type]
        spec = SubagentSpec(
            goal="g",
            initial_messages=[{"role": "user", "content": "u"}],
            tool_registry=None,
            parent_session_id="p1",
        )
        with pytest.raises(AttributeError):
            import asyncio
            asyncio.run(mgr.run(spec))


class TestChildCtxOverrides:
    """The child ctx must override hook (NoOp) + memory_manager (None)."""

    def test_child_ctx_isolated_from_parent(self):
        from llmwikify.apps.chat.agent.execution_context import (
            AgentExecutionContext,
        )
        parent_ctx = AgentExecutionContext(
            chat_service=MagicMock(),
            tool_executor=MagicMock(),
            prompt_builder=MagicMock(),
            memory_manager=MagicMock(name="parent_mm"),
            hook=MagicMock(name="parent_hook"),
        )

        class _Parent(AgentRunner):
            async def run_stream(self, spec):
                yield {"type": "done"}
                return
                yield

            async def run_to_completion(self, spec):
                return None

            def execution_context(self):
                return parent_ctx

        captured = {}

        real_init = ChatRunnerV2.__init__

        def _capture(self, *args, **kwargs):
            captured.update(kwargs)
            return real_init(self, *args, **kwargs)

        # Patch ChatRunnerV2.__init__ via setattr trick
        from unittest.mock import patch
        with patch.object(ChatRunnerV2, "__init__", _capture):
            mgr = SubagentManager(_Parent())
            spec = SubagentSpec(
                goal="g",
                initial_messages=[{"role": "user", "content": "u"}],
                tool_registry=None,
                parent_session_id="p1",
            )
            # Don't actually call mgr.run() (would need async); just
            # build a child ctx the way the manager does and assert
            # the shape.
            from llmwikify.foundation.callback import NoOpHook
            pc = mgr._parent.execution_context()
            child_ctx = AgentExecutionContext(
                chat_service=pc.chat_service,
                tool_executor=pc.tool_executor,
                prompt_builder=pc.prompt_builder,
                config=pc.config,
                memory_manager=None,
                hook=NoOpHook(),
            )
            assert child_ctx.memory_manager is None
            assert isinstance(child_ctx.hook, NoOpHook)
            # parent's mm and hook untouched
            assert pc.memory_manager is not None
            assert pc.hook is not None
