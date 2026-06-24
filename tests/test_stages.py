"""Tests for Phase 14D: pipeline stages."""
from __future__ import annotations

from llmwikify.reproduction.pipeline.stages.base import Stage, StageContext
from llmwikify.reproduction.pipeline.stages.backtest import BacktestStage
from llmwikify.reproduction.pipeline.stages.codegen import CodegenStage
from llmwikify.reproduction.pipeline.stages.paper_understanding import PaperUnderstandingStage
from llmwikify.reproduction.pipeline.stages.persist_factor import PersistFactorStage


class TestStageContext:
    def test_default_fields(self):
        ctx = StageContext()
        assert ctx.workspace_path is None
        assert ctx.alpha_indices == []
        assert ctx.metadata == {}

    def test_mutable(self):
        ctx = StageContext()
        ctx.metadata["key"] = "value"
        assert ctx.metadata["key"] == "value"


class TestPaperUnderstandingStage:
    def test_name(self):
        assert PaperUnderstandingStage.name == "paper_understanding"

    def test_execute_returns_ctx(self):
        stage = PaperUnderstandingStage()
        ctx = StageContext()
        result = stage.execute(ctx)
        assert result is ctx

    def test_required_prompts(self):
        stage = PaperUnderstandingStage()
        assert stage.required_prompts == ["track_a", "track_b"]


class TestCodegenStage:
    def test_name(self):
        assert CodegenStage.name == "codegen"

    def test_execute_returns_ctx(self):
        stage = CodegenStage()
        ctx = StageContext()
        result = stage.execute(ctx)
        assert result is ctx

    def test_required_prompts(self):
        stage = CodegenStage()
        assert stage.required_prompts == ["code_gen"]


class TestBacktestStage:
    def test_name(self):
        assert BacktestStage.name == "backtest"

    def test_execute_returns_ctx(self):
        stage = BacktestStage()
        ctx = StageContext()
        result = stage.execute(ctx)
        assert result is ctx


class TestPersistFactorStage:
    def test_name(self):
        assert PersistFactorStage.name == "persist_factor"

    def test_execute_returns_ctx(self):
        stage = PersistFactorStage()
        ctx = StageContext()
        result = stage.execute(ctx)
        assert result is ctx


class TestAllStagesAreSubclass:
    def test_all_stages(self):
        stages = [PaperUnderstandingStage, CodegenStage, BacktestStage, PersistFactorStage]
        for cls in stages:
            assert issubclass(cls, Stage)
