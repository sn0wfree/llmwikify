"""Tests for pipeline/ framework skeleton (Phase 14A)."""
from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.reproduction.pipeline.config import WorkspaceConfig
from llmwikify.reproduction.pipeline.runner import PipelineResult, PipelineRunner
from llmwikify.reproduction.pipeline.stages.base import Stage, StageContext
from llmwikify.reproduction.pipeline.workspace import Workspace


class TestWorkspaceConfig:
    """WorkspaceConfig dataclass (1 test)."""

    def test_defaults(self) -> None:
        cfg = WorkspaceConfig()
        assert cfg.workspace_path == Path(".")
        assert cfg.alpha_indices == []
        assert cfg.max_workers == 1
        assert cfg.timeout_s == 300.0


class TestPipelineRunner:
    """PipelineRunner stub (1 test)."""

    def test_run_returns_empty_result(self) -> None:
        runner = PipelineRunner(WorkspaceConfig(workspace_path=Path("/tmp/test")))
        result = runner.run()
        assert isinstance(result, PipelineResult)
        assert result.stages_completed == []
        assert result.stages_failed == []
        assert result.errors == []


class TestStage:
    """Stage ABC (1 test)."""

    def test_cannot_instantiate_abc(self) -> None:
        with pytest.raises(TypeError):
            Stage()  # type: ignore[abstract]

    def test_concrete_stage(self) -> None:
        class DummyStage(Stage):
            name = "dummy"

            def execute(self, ctx: StageContext) -> StageContext:
                ctx.metadata["ran"] = True
                return ctx

        stage = DummyStage()
        ctx = StageContext()
        result = stage.execute(ctx)
        assert result.metadata["ran"] is True


class TestWorkspace:
    """Workspace stage registry (1 test)."""

    def test_get_stage_returns_none_when_missing(self) -> None:
        ws = Workspace()
        assert ws.get_stage("nonexistent") is None

    def test_register_and_get(self) -> None:
        class DummyStage(Stage):
            name = "x"

            def execute(self, ctx: StageContext) -> StageContext:
                return ctx

        ws = Workspace()
        ws.register(DummyStage())
        assert ws.get_stage("x") is not None
        assert ws.list_stages() == ["x"]

    def test_execute_runs_registered_stages(self) -> None:
        class AppendStage(Stage):
            name = "append"

            def execute(self, ctx: StageContext) -> StageContext:
                ctx.metadata.setdefault("log", []).append(self.name)
                return ctx

        ws = Workspace()
        ws.register(AppendStage())
        ctx = ws.execute()
        assert ctx.metadata["log"] == ["append"]

    def test_execute_skips_unregistered_names(self) -> None:
        ws = Workspace()
        ctx = ws.execute(stage_names=["nope"])
        assert isinstance(ctx, StageContext)
