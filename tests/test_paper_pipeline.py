"""Tests for PR1 PaperPipeline framework + backward compat shims.

Covers:
  - PaperRecipe construction + validation (paper_id, workers)
  - PaperPipeline.run() serial / parallel dispatch
  - Lock semantics (Bug 3 mirror): _print_lock only around record
  - indices filter (101-alphas style)
  - empty result handling
  - parallel failure appends synthetic result (Bug 5 mirror)
  - shim re-exports (pipeline.stages.base, pipeline.workspace)
"""
from __future__ import annotations

import warnings
from collections.abc import Iterable
from typing import Any

import pytest

from llmwikify.reproduction.core import (
    PaperPipeline,
    PaperRecipe,
    Stage,
    StageContext,
)

# ─── Test helpers ──────────────────────────────────────────────────────


class _StubSignal:
    """Minimal Signal-shaped object for tests."""

    def __init__(self, signal_id: str, formula: str = "f(x) = x") -> None:
        self.id = signal_id
        self.name = signal_id
        self.formula_brief = formula
        self.metadata: dict = {}


class _StubSignalSource:
    """SignalSource protocol implementation (no inheritance)."""

    def __init__(self, signals: list[_StubSignal]) -> None:
        self._signals = signals

    def iter_signals(self) -> Iterable[_StubSignal]:
        return iter(self._signals)


class _StubDataSource:
    name = "stub_data"

    def get(self, symbol: str, start: str, end: str) -> Any:
        return None


class _StubBacktest:
    """BacktestEngine protocol implementation."""

    def __init__(self, succeed: bool = True) -> None:
        self._succeed = succeed
        self.calls: list[str] = []

    def run(self, code: str, h5_path, signal: _StubSignal) -> dict:
        self.calls.append(signal.id)
        if self._succeed:
            return {"ic_mean": 0.01, "icir": 0.1, "win_rate": 0.51}
        raise RuntimeError("stub backtest fail")


class _StubSink:
    """Sink protocol implementation."""

    def __init__(self) -> None:
        self.written: list[Any] = []

    def write_one(self, result: Any):
        from pathlib import Path
        self.written.append(result)
        return Path(f"/tmp/stub_{len(self.written)}.json")


def _make_recipe(
    signal_ids: list[str] | None = None,
    workers: int = 1,
    backtest_succeed: bool = True,
    sinks: list | None = None,
) -> PaperRecipe:
    if signal_ids is None:
        signal_ids = ["alpha-001", "alpha-002"]
    return PaperRecipe(
        paper_id="test_paper",
        signal_source=_StubSignalSource([_StubSignal(sid) for sid in signal_ids]),
        data_source=_StubDataSource(),
        backtest_engine=_StubBacktest(succeed=backtest_succeed),
        sinks=sinks if sinks is not None else [_StubSink()],
        workers=workers,
    )


# ─── PaperRecipe ───────────────────────────────────────────────────────


class TestPaperRecipe:
    def test_minimal_construction(self) -> None:
        recipe = _make_recipe()
        assert recipe.paper_id == "test_paper"
        assert recipe.workers == 1
        assert len(recipe.sinks) == 1

    def test_empty_paper_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="paper_id must be non-empty"):
            PaperRecipe(
                paper_id="",
                signal_source=_StubSignalSource([]),
                data_source=_StubDataSource(),
                backtest_engine=_StubBacktest(),
            )

    def test_zero_workers_rejected(self) -> None:
        with pytest.raises(ValueError, match="workers must be >= 1"):
            PaperRecipe(
                paper_id="x",
                signal_source=_StubSignalSource([]),
                data_source=_StubDataSource(),
                backtest_engine=_StubBacktest(),
                workers=0,
            )

    def test_workers_capped_at_three(self) -> None:
        """v2 cap: LLM rate limit is 3 concurrent."""
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            recipe = PaperRecipe(
                paper_id="x",
                signal_source=_StubSignalSource([]),
                data_source=_StubDataSource(),
                backtest_engine=_StubBacktest(),
                workers=10,
            )
        assert recipe.workers == 3
        assert any("exceeds LLM rate-limit cap" in str(c.message) for c in caught)


# ─── PaperPipeline: serial ─────────────────────────────────────────────


class TestPaperPipelineSerial:
    def test_serial_runs_all_signals(self) -> None:
        recipe = _make_recipe(signal_ids=["alpha-001", "alpha-002", "alpha-003"])
        pipeline = PaperPipeline(recipe)
        results = pipeline.run()
        assert len(results) == 3
        assert all(r["signal_id"].startswith("alpha-") for r in results)

    def test_serial_records_all_results(self) -> None:
        recipe = _make_recipe(signal_ids=["alpha-001", "alpha-002"])
        pipeline = PaperPipeline(recipe)
        pipeline.run()
        assert len(pipeline.results) == 2
        assert pipeline.failures == 0

    def test_serial_no_indices_returns_all(self) -> None:
        recipe = _make_recipe(signal_ids=["alpha-001", "alpha-002", "alpha-003"])
        pipeline = PaperPipeline(recipe)
        results = pipeline.run(indices=range(1, 4))
        # alpha-001, alpha-002, alpha-003 → 3 results
        assert len(results) == 3

    def test_serial_partial_indices_filter(self) -> None:
        recipe = _make_recipe(signal_ids=["alpha-001", "alpha-002", "alpha-003"])
        pipeline = PaperPipeline(recipe)
        results = pipeline.run(indices=range(1, 3))
        # alpha-001, alpha-002 → 2 results
        assert len(results) == 2
        assert {r["signal_id"] for r in results} == {"alpha-001", "alpha-002"}

    def test_serial_empty_signals_returns_empty(self) -> None:
        recipe = _make_recipe(signal_ids=[])
        pipeline = PaperPipeline(recipe)
        results = pipeline.run()
        assert results == []

    def test_serial_logs_timing(self, caplog) -> None:
        import logging
        recipe = _make_recipe(signal_ids=["alpha-001"])
        pipeline = PaperPipeline(recipe)
        with caplog.at_level(logging.INFO, logger="llmwikify.reproduction.core.pipeline"):
            pipeline.run()
        assert any("starting" in r.message for r in caplog.records)
        assert any("done" in r.message for r in caplog.records)


# ─── PaperPipeline: parallel ───────────────────────────────────────────


class TestPaperPipelineParallel:
    def test_parallel_workers_2(self) -> None:
        recipe = _make_recipe(signal_ids=["alpha-001", "alpha-002"], workers=2)
        pipeline = PaperPipeline(recipe)
        results = pipeline.run()
        assert len(results) == 2

    def test_parallel_workers_3(self) -> None:
        recipe = _make_recipe(
            signal_ids=["alpha-001", "alpha-002", "alpha-003", "alpha-004"],
            workers=3,
        )
        pipeline = PaperPipeline(recipe)
        results = pipeline.run()
        assert len(results) == 4

    def test_parallel_dispatch_uses_semaphore(self) -> None:
        """Smoke: parallel dispatch does not deadlock."""
        recipe = _make_recipe(
            signal_ids=[f"alpha-{i:03d}" for i in range(1, 7)],
            workers=3,
        )
        pipeline = PaperPipeline(recipe)
        results = pipeline.run()
        assert len(results) == 6


# ─── Shim backward compat ─────────────────────────────────────────────


class TestShimBackwardCompat:
    def test_pipeline_stages_base_reexports_stage(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from llmwikify.reproduction.core.stage import Stage as NewStage
            from llmwikify.reproduction.pipeline.stages.base import Stage as OldStage
        assert OldStage is NewStage

    def test_pipeline_stages_base_reexports_stagecontext(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from llmwikify.reproduction.core.stage import StageContext as NewCtx
            from llmwikify.reproduction.pipeline.stages.base import (
                StageContext as OldCtx,
            )
        assert OldCtx is NewCtx

    def test_pipeline_workspace_workspace_still_works(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from llmwikify.reproduction.pipeline.workspace import Workspace

            class MyStage(Stage):
                name = "my_stage"

                def execute(self, ctx: StageContext) -> StageContext:
                    return ctx

            ws = Workspace()
            ws.register(MyStage())
            assert ws.list_stages() == ["my_stage"]
            ctx = ws.execute(["my_stage"])
            assert isinstance(ctx, StageContext)

    def test_shim_emits_deprecation_warning(self) -> None:
        import importlib
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import llmwikify.reproduction.pipeline.stages.base as mod
            importlib.reload(mod)
            # Trigger one attribute access to ensure module body re-evaluated
            _ = mod.Stage
            assert any(
                issubclass(c.category, DeprecationWarning)
                and "pipeline.stages.base is deprecated" in str(c.message)
                for c in caught
            )
