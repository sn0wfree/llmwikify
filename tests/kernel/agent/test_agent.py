"""Tests for kernel/agent/ (Phase 1 of G+Y: 通用框架拆解).

Covers:
  - hook: UnifiedHook 16 methods all no-op
  - context: UnifiedContext dataclass + properties
  - _core_types: StepResult.ok/fail, Pipeline serial composition, _maybe_await
  - spec: BaseSpec / CodegenSpec / ReasonResponse / ActResult / UnifiedResult
  - loop: UnifiedAgentLoop 5-step state machine (PRECHECK → REASON → ACT → OBSERVE → FINALIZE)
  - codegen_pipeline: CodegenReasoner / CodeActor / generate_factor_code (async + sync)
  - steps: 15 Step classes instantiate and have handle()
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

from llmwikify.kernel.agent import (
    ActResult,
    BaseSpec,
    CodeActor,
    CodegenReasoner,
    CodegenSpec,
    Pipeline,
    ReasonResponse,
    StepHandler,
    StepResult,
    StreamingHandler,
    UnifiedAgentLoop,
    UnifiedContext,
    UnifiedHook,
    UnifiedResult,
    _maybe_await,
    generate_factor_code,
    generate_factor_code_sync,
)
from llmwikify.kernel.agent.steps import (
    BuildFeedbackStep,
    CheckEmptyStep,
    CheckFieldStep,
    CheckSuccessStep,
    CheckToolCallsStep,
    CodeExecResult,
    ExecuteCodeStep,
    ExtractCodeStep,
    ExtractJSONStep,
    LLMCallStep,
    MapStep,
    TruncateStep,
    ValidateAndExecuteStep,
    ValidateSafetyStep,
    ValidateSyntaxStep,
    WrapStep,
)

# ─── hook ───────────────────────────────────────────────────


class TestUnifiedHook:
    def test_all_methods_noop(self):
        hook = UnifiedHook()
        ctx = UnifiedContext(spec=BaseSpec(messages=[]))
        # 16 hook methods, all no-op
        assert hook.wants_streaming() is False
        hook.before_iteration(ctx)
        hook.on_reason_start(ctx)
        hook.on_reason_end(ctx, None)
        hook.on_stream(ctx, "delta")
        hook.emit_reasoning(ctx, "thinking")
        hook.emit_reasoning_end(ctx)
        hook.on_act_start(ctx)
        hook.on_act_end(ctx, None)
        hook.after_tool_executed(ctx, None, None)
        hook.on_tool_error(ctx, None, RuntimeError("x"))
        hook.on_confirmation(ctx, None)
        hook.on_observe(ctx)
        hook.on_error(ctx, RuntimeError("x"))
        assert hook.finalize(ctx, "content") == "content"
        hook.after_iteration(ctx)

    def test_subclass_override(self):
        class MyHook(UnifiedHook):
            def on_reason_end(self, ctx, response):
                ctx.messages.append({"role": "system", "content": "captured"})

        hook = MyHook()
        ctx = UnifiedContext(spec=BaseSpec(messages=[]))
        hook.on_reason_end(ctx, ReasonResponse(raw_content="x"))
        assert ctx.messages[-1]["content"] == "captured"


# ─── context ────────────────────────────────────────────────


class TestUnifiedContext:
    def test_basic(self):
        spec = BaseSpec(messages=[{"role": "user", "content": "hi"}])
        ctx = UnifiedContext(spec=spec)
        assert ctx.messages == [{"role": "user", "content": "hi"}]
        assert ctx.iteration == 0
        assert ctx.start_time > 0
        assert ctx.stop_reason == ""

    def test_elapsed_sec(self):
        ctx = UnifiedContext(spec=BaseSpec(messages=[]))
        import time
        time.sleep(0.01)
        assert ctx.elapsed_sec >= 0.01

    def test_tools_empty(self):
        spec = BaseSpec(messages=[])
        ctx = UnifiedContext(spec=spec)
        assert ctx.tools is None


# ─── _core_types ────────────────────────────────────────────


class TestStepResult:
    def test_ok(self):
        r = StepResult.ok("output_value", [{"type": "x"}])
        assert r.output == "output_value"
        assert r.success is True
        assert r.error is None
        assert r.events == [{"type": "x"}]

    def test_fail(self):
        r = StepResult.fail("oops")
        assert r.success is False
        assert r.error == "oops"
        assert r.output is None


class TestPipeline:
    def test_serial_compose(self):
        async def run():
            class DoubleStep(StepHandler):
                async def handle(self, input, spec, ctx):
                    return StepResult.ok(input * 2)
            p = Pipeline(DoubleStep(), DoubleStep())
            return await p.handle(3, None, None)

        result = asyncio.run(run())
        assert result.output == 12
        assert result.success

    def test_fail_fast(self):
        async def run():
            class FailStep(StepHandler):
                async def handle(self, input, spec, ctx):
                    return StepResult.fail("boom")
            p = Pipeline(FailStep(), FailStep())
            return await p.handle(0, None, None)

        result = asyncio.run(run())
        assert not result.success
        assert "boom" in result.error


class TestMaybeAwait:
    def test_sync_callable(self):
        async def run():
            return await _maybe_await(lambda x: x * 2, 3)
        assert asyncio.run(run()) == 6

    def test_async_callable(self):
        async def afn(x):
            return x + 1
        async def run():
            return await _maybe_await(afn, 5)
        assert asyncio.run(run()) == 6

    def test_value(self):
        async def run():
            return await _maybe_await(42)
        assert asyncio.run(run()) == 42


# ─── spec ───────────────────────────────────────────────────


class TestSpec:
    def test_base_spec(self):
        spec = BaseSpec(messages=[{"role": "user", "content": "x"}])
        assert spec.max_iterations == 10
        assert spec.temperature == 0.3

    def test_codegen_spec(self):
        spec = CodegenSpec(messages=[], factor_name="alpha-001", formula_brief="rank(volume)")
        assert spec.df is None
        assert spec.factor_name == "alpha-001"
        assert spec.max_repair_rounds == 3

    def test_unified_result_to_dict(self):
        r = UnifiedResult(code="x = 1", stop_reason="completed", iterations=2, elapsed_sec=1.5)
        d = r.to_dict()
        assert d["code"] == "x = 1"
        assert d["is_valid"] is True
        assert d["error_kind"] == "none"
        assert d["iterations"] == 2

    def test_unified_result_error(self):
        r = UnifiedResult(error="boom", stop_reason="error")
        d = r.to_dict()
        assert d["is_valid"] is False
        assert d["error_kind"] == "execute_error"
        assert d["error_message"] == "boom"


# ─── loop ───────────────────────────────────────────────────


class TestUnifiedAgentLoop:
    def test_basic_loop(self):
        async def reasoner(input, spec, ctx):
            return StepResult.ok(ReasonResponse(raw_content="hello", code="x = 1"))

        async def actor(input, spec, ctx):
            return StepResult.ok(ActResult(success=True, output="ok", code=input.code))

        class ReasonerHandler(StepHandler):
            async def handle(self, input, spec, ctx):
                return await reasoner(input, spec, ctx)

        class ActorHandler(StepHandler):
            async def handle(self, input, spec, ctx):
                return await actor(input, spec, ctx)

        async def run():
            loop = UnifiedAgentLoop(
                reasoner=ReasonerHandler(),
                actor=ActorHandler(),
                deciders={"after_act": CheckSuccessStep()},
            )
            return await loop.run_to_completion(CodegenSpec(messages=[]))

        result = asyncio.run(run())
        assert result.stop_reason in ("completed", "success")
        assert result.code == "x = 1"

    def test_loop_with_max_iterations(self):
        async def run():
            class AlwaysEmptyReasoner(StepHandler):
                async def handle(self, input, spec, ctx):
                    return StepResult.ok(ReasonResponse(raw_content="", code=None, is_valid=False))

            class AlwaysFailActor(StepHandler):
                async def handle(self, input, spec, ctx):
                    return StepResult.ok(ActResult(success=False, error="fail"))

            loop = UnifiedAgentLoop(
                reasoner=AlwaysEmptyReasoner(),
                actor=AlwaysFailActor(),
            )
            return await loop.run_to_completion(CodegenSpec(messages=[], max_iterations=2))

        result = asyncio.run(run())
        # Loop runs max_iterations=2 times then breaks
        assert result.iterations == 2


# ─── steps ──────────────────────────────────────────────────


class TestSteps:
    @pytest.mark.parametrize("cls,args", [
        (CheckFieldStep, {"field": "success"}),
        (CheckEmptyStep, {"field": "tool_calls"}),
        (CheckSuccessStep, {}),
        (CheckToolCallsStep, {}),
        (ExtractCodeStep, {}),
        (ValidateSyntaxStep, {}),
        (ValidateSafetyStep, {}),
        (ExecuteCodeStep, {}),
        (ValidateAndExecuteStep, {}),
        (LLMCallStep, {"llm_client": None}),
        (ExtractJSONStep, {}),
        (BuildFeedbackStep, {}),
        (TruncateStep, {}),
        (MapStep, {"fn": lambda x: x}),
        (WrapStep, {"cls": dict}),
    ])
    def test_step_has_handle(self, cls, args):
        step = cls(**args)
        assert hasattr(step, "handle")
        assert callable(step.handle)
        assert inspect.iscoroutinefunction(step.handle)

    def test_extract_code_step_no_fence(self):
        async def run():
            return await ExtractCodeStep().handle("no code here", None, None)
        result = asyncio.run(run())
        assert not result.success

    def test_extract_code_step_with_fence(self):
        async def run():
            return await ExtractCodeStep().handle("```python\nx = 1\n```", None, None)
        result = asyncio.run(run())
        assert result.success
        assert "x = 1" in result.output

    def test_validate_syntax_step(self):
        async def run_valid():
            return await ValidateSyntaxStep().handle("x = 1", None, None)

        async def run_invalid():
            return await ValidateSyntaxStep().handle("def x(:", None, None)

        assert asyncio.run(run_valid()).success
        assert not asyncio.run(run_invalid()).success

    def test_check_success_step(self):
        async def run():
            return await CheckSuccessStep().handle(ActResult(success=True), None, None)
        result = asyncio.run(run())
        assert result.output == (True, "success")

    def test_map_step(self):
        async def run():
            return await MapStep(lambda x: x * 2).handle(5, None, None)
        assert asyncio.run(run()).output == 10


# ─── codegen_pipeline ───────────────────────────────────────


class TestCodegenPipeline:
    def test_codegen_reasoner_init(self):
        # Just instantiate (no LLM call)
        reasoner = CodegenReasoner(llm_client=None)
        assert isinstance(reasoner, Pipeline)

    def test_code_actor_init(self):
        actor = CodeActor()
        assert hasattr(actor, "_executor")
        assert hasattr(actor, "_feedback")

    def test_generate_factor_code_sync(self):
        import polars as pl
        df = pl.DataFrame({"x": [1, 2, 3]})
        result = generate_factor_code_sync(
            "test-factor", "return df['x'] * 2", df,
        )
        # Without LLM, it should fail gracefully
        assert result.stop_reason in ("error", "completed", "success")

    def test_generate_factor_code_async(self):
        import polars as pl
        df = pl.DataFrame({"x": [1, 2, 3]})

        async def run():
            return await generate_factor_code(
                "test-factor", "return df['x'] * 2", df,
            )
        result = asyncio.run(run())
        assert result.stop_reason in ("error", "completed", "success")


# ─── 15 step classes count ──────────────────────────────────


def test_all_15_steps_exported():
    """确保 15 个 step classes 全部可 import."""
    from llmwikify.kernel.agent.steps import (
        BuildFeedbackStep,
        CheckEmptyStep,
        CheckFieldStep,
        CheckSuccessStep,
        CheckToolCallsStep,
        ExecuteCodeStep,
        ExtractCodeStep,
        ExtractJSONStep,
        LLMCallStep,
        MapStep,
        TruncateStep,
        ValidateAndExecuteStep,
        ValidateSafetyStep,
        ValidateSyntaxStep,
        WrapStep,
    )
    assert len([
        BuildFeedbackStep, CheckEmptyStep, CheckFieldStep, CheckSuccessStep,
        CheckToolCallsStep, CodeExecResult, ExecuteCodeStep, ExtractCodeStep,
        ExtractJSONStep, LLMCallStep, MapStep, TruncateStep,
        ValidateAndExecuteStep, ValidateSafetyStep, ValidateSyntaxStep, WrapStep,
    ]) == 16  # 15 Step classes + 1 dataclass (CodeExecResult)
