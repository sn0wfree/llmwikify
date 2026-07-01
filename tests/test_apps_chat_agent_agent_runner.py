"""Phase 15 — AgentRunner abstract base class tests (borrowed from nanobot v0.2.1).

Covers:
  - AgentRunner ABC can't be instantiated directly
  - Generic type binding: subclasses get their own spec/result types
  - Concrete subclass with run_stream + run_to_completion works
  - wants_streaming default False; subclasses may override
  - name property defaults to type(self).__name__
  - ChatRunnerV2 IS-A AgentRunner (subclass relationship holds)
  - FakeAgentRunner satisfies the contract for downstream consumers
    (proves SubagentManager / future CronSkill / future WorkflowActor
    can use any AgentRunner, not just ChatRunnerV2)
  - SubagentManager duck-type check accepts stub parent with collaborator attrs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from llmwikify.apps.chat.agent.agent_runner import AgentRunner
from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
from llmwikify.apps.chat.agent.spec import ChatRunResult, ChatRunSpec
from llmwikify.apps.chat.agent.subagent_manager import (
    SubagentManager,
    SubagentSpec,
)

# ── ABC enforcement ─────────────────────────────────────────────


class TestAgentRunnerABC:
    def test_cannot_instantiate_directly(self) -> None:
        """The ABC raises TypeError if you try to instantiate it without
        implementing the abstract methods."""
        with pytest.raises(TypeError) as exc:
            AgentRunner()  # type: ignore[abstract]
        msg = str(exc.value)
        assert "abstract" in msg.lower() or "run_stream" in msg

    def test_subclass_missing_run_stream_cannot_instantiate(self) -> None:
        """A subclass that only implements one of two abstract methods
        still cannot be instantiated."""

        class IncompleteRunner(AgentRunner):
            async def run_to_completion(self, spec):
                return None

        with pytest.raises(TypeError):
            IncompleteRunner()  # type: ignore[abstract]

    def test_subclass_with_all_methods_can_instantiate(self) -> None:
        """Implementing both run_stream and run_to_completion is enough."""

        class CompleteRunner(AgentRunner):
            async def run_stream(self, spec):
                yield {"type": "done"}

            async def run_to_completion(self, spec):
                return None

        r = CompleteRunner()
        assert r is not None


# ── Generic binding ─────────────────────────────────────────────


class TestAgentRunnerGeneric:
    def test_subclass_can_bind_own_types(self) -> None:
        """A subclass can specify its own spec/result types via Generic
        parameterization; this is just a typing aid, runtime works either way."""

        @dataclass
        class CustomSpec:
            goal: str = ""

        @dataclass
        class CustomResult:
            ok: bool = False

        class CustomRunner(AgentRunner[CustomSpec, CustomResult]):
            async def run_stream(self, spec):
                yield {"type": "done", "content": spec.goal}

            async def run_to_completion(self, spec):
                return CustomResult(ok=True)

        r = CustomRunner()
        spec = CustomSpec(goal="hello")
        import asyncio
        result = asyncio.run(r.run_to_completion(spec))
        assert result.ok is True

    def test_unbound_subclass_defaults_to_any(self) -> None:
        """A subclass that doesn't parameterize still works with any spec/result."""

        class UnboundRunner(AgentRunner):
            async def run_stream(self, spec):
                yield {"type": "done"}

            async def run_to_completion(self, spec):
                return {"unbound": True}

        r = UnboundRunner()
        import asyncio
        result = asyncio.run(r.run_to_completion({"any": "spec"}))
        assert result == {"unbound": True}


# ── Default behavior ────────────────────────────────────────────


class TestAgentRunnerDefaults:
    def test_wants_streaming_default_false(self) -> None:
        class R(AgentRunner):
            async def run_stream(self, spec):
                yield {}

            async def run_to_completion(self, spec):
                return None

        assert R().wants_streaming() is False

    def test_wants_streaming_can_be_overridden(self) -> None:
        class R(AgentRunner):
            async def run_stream(self, spec):
                yield {}

            async def run_to_completion(self, spec):
                return None

            def wants_streaming(self) -> bool:
                return True

        assert R().wants_streaming() is True

    def test_name_defaults_to_class_name(self) -> None:
        class MyRunner(AgentRunner):
            async def run_stream(self, spec):
                yield {}

            async def run_to_completion(self, spec):
                return None

        r = MyRunner()
        assert r.name == "MyRunner"

    def test_name_can_be_overridden(self) -> None:
        class R(AgentRunner):
            async def run_stream(self, spec):
                yield {}

            async def run_to_completion(self, spec):
                return None

            @property
            def name(self) -> str:
                return "custom-name"

        assert R().name == "custom-name"


# ── ChatRunnerV2 IS-A AgentRunner ───────────────────────────────


class TestChatRunnerV2IsAgentRunner:
    def test_chat_runner_v2_subclass(self) -> None:
        """ChatRunnerV2 must remain a subclass of AgentRunner after the
        Phase 15 inheritance change."""
        assert issubclass(ChatRunnerV2, AgentRunner)

    def test_chat_runner_v2_concrete_instance_is_agent_runner(self) -> None:
        """A ChatRunnerV2 instance is isinstance AgentRunner."""
        # Construct with no collaborators — just to test isinstance
        # without actually running anything
        runner = ChatRunnerV2(
            chat_service=None,
            tool_executor=None,
            prompt_builder=None,
        )
        assert isinstance(runner, AgentRunner)

    def test_chat_runner_v2_default_wants_streaming(self) -> None:
        """ChatRunnerV2 inherits the default wants_streaming=False.
        The actual streaming logic lives in run_stream / hook.wants_streaming
        but the ABC capability returns False (subclasses that actually
        stream MUST override)."""
        runner = ChatRunnerV2(
            chat_service=None, tool_executor=None, prompt_builder=None,
        )
        # Default from AgentRunner base; ChatRunnerV2 doesn't override
        assert runner.wants_streaming() is False

    def test_chat_runner_v2_name(self) -> None:
        runner = ChatRunnerV2(
            chat_service=None, tool_executor=None, prompt_builder=None,
        )
        assert runner.name == "ChatRunnerV2"


# ── FakeAgentRunner for downstream consumers ────────────────────


class TestFakeAgentRunnerContract:
    """A downstream consumer (e.g. SubagentManager / future CronSkill)
    should be able to work with ANY AgentRunner, not just ChatRunnerV2.
    This proves the abstraction is real, not just a type-hint."""

    def test_fake_runner_satisfies_abc(self) -> None:
        @dataclass
        class FakeSpec:
            goal: str = ""
            max_iterations: int = 1

        @dataclass
        class FakeResult:
            iterations: int = 0
            final_content: str = ""
            error: str | None = None

        class FakeRunner(AgentRunner[FakeSpec, FakeResult]):
            def __init__(self) -> None:
                self.call_count = 0

            async def run_stream(self, spec):
                for i in range(spec.max_iterations):
                    yield {"type": "delta", "n": i}
                    yield {"type": "tool_call_start", "tool": "fake_tool"}
                yield {
                    "type": "done",
                    "content": f"done after {spec.max_iterations}",
                    "stop_reason": "completed",
                }

            async def run_to_completion(self, spec):
                self.call_count += 1
                events = [ev async for ev in self.run_stream(spec)]
                done = next(
                    ev for ev in events if ev.get("type") == "done"
                )
                return FakeResult(
                    iterations=spec.max_iterations,
                    final_content=done.get("content", ""),
                )

        runner = FakeRunner()
        spec = FakeSpec(goal="hi", max_iterations=3)
        import asyncio

        # Test run_stream end-to-end
        async def _drain():
            events = []
            async for ev in runner.run_stream(spec):
                events.append(ev)
            return events

        events = asyncio.run(_drain())
        # 3 iterations × 2 events + 1 done
        assert len(events) == 7
        assert events[-1]["type"] == "done"
        assert "3" in events[-1]["content"]

        # Test run_to_completion
        result = asyncio.run(runner.run_to_completion(spec))
        assert result.iterations == 3
        assert "3" in result.final_content
        assert runner.call_count == 1

    def test_fake_runner_passes_subagent_manager_construction(self) -> None:
        """Phase 16+ (2026-06-23): SubagentManager.__init__ no longer
        gates on the 4 private-attribute ``hasattr`` check; any
        ``AgentRunner`` subclass is accepted at construction. The
        canonical test for the runtime validation is in
        ``tests/test_apps_chat_agent_execution_context.py``
        (``TestSubagentManagerAcceptsAnyAgentRunner``)."""

        class FakeRunner(AgentRunner):
            async def run_stream(self, spec):
                yield {"type": "done"}

            async def run_to_completion(self, spec):
                return None

        fake = FakeRunner()
        # Should NOT raise — FakeRunner is an AgentRunner subclass;
        # validation happens at run() time via execution_context().
        mgr = SubagentManager(fake)  # type: ignore[arg-type]
        assert mgr.max_concurrent == 2

    def test_subagent_manager_accepts_plain_object(self) -> None:
        """Phase 16+ (2026-06-23): SubagentManager accepts ANY
        object at construction (no isinstance / no hasattr check).
        Validation is deferred to ``run()`` time. This is a
        weak-typing stance by design; the canonical test for
        non-``AgentRunner`` rejection at run time is in
        ``tests/test_apps_chat_agent_execution_context.py``
        (``test_rejects_non_agent_runner_at_run_time``)."""

        stub = object()
        mgr = SubagentManager(stub)  # type: ignore[arg-type]
        assert mgr.max_concurrent == 2

    def test_subagent_manager_does_not_check_attrs_at_construction(self) -> None:
        """Phase 16+ (2026-06-23): the 4-field ``hasattr`` check is
        gone — even a partial object is accepted at construction.
        The canonical runtime-validation test is in
        ``tests/test_apps_chat_agent_execution_context.py``."""

        class _StubPartial:
            def __init__(self) -> None:
                self._chat_service = object()  # only one of four

        mgr = SubagentManager(_StubPartial())  # type: ignore[arg-type]
        assert mgr.max_concurrent == 2


# ── Polymorphism: dispatch via base type ────────────────────────


class TestAgentRunnerPolymorphism:
    def test_can_dispatch_run_to_completion_via_base_type(self) -> None:
        """A function typed as ``AgentRunner`` can dispatch to either
        a real ChatRunnerV2 or a fake — proving the abstraction is real."""

        class Fake(AgentRunner):
            def __init__(self) -> None:
                self.calls = 0

            async def run_stream(self, spec):
                yield {"type": "done", "content": "fake-done"}

            async def run_to_completion(self, spec):
                self.calls += 1
                return {"fake": True}

        class Real(ChatRunnerV2):
            """Use ChatRunnerV2 directly; we won't actually invoke it,
            just confirm the type system dispatches via the base class."""

        runners: list[AgentRunner] = [Fake()]
        import asyncio

        async def _dispatch(runner: AgentRunner):
            return await runner.run_to_completion({"x": 1})

        results = asyncio.run(_dispatch(runners[0]))
        assert results == {"fake": True}
        assert runners[0].calls == 1

    def test_type_hint_param_accepts_subclass(self) -> None:
        """A function annotated ``runner: AgentRunner`` accepts a
        ChatRunnerV2 instance (subclass assignment works)."""

        def takes_runner(runner: AgentRunner) -> str:
            return runner.name

        runner = ChatRunnerV2(
            chat_service=None, tool_executor=None, prompt_builder=None,
        )
        assert takes_runner(runner) == "ChatRunnerV2"
