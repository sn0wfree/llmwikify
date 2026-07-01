"""Tests for contracts: pydantic BaseModel schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from llmwikify.reproduction.paper_understanding import contracts as ct


class TestEnums:
    """Test Enum 类型 (3 测试)."""

    def test_page_status_enum_values(self) -> None:
        """PageStatus 含 status 字段值."""
        assert ct.PageStatus.DRAFT.value == "draft"
        assert ct.PageStatus.VALIDATED.value == "validated"
        assert ct.PageStatus.BACKTESTED.value == "backtested"
        assert ct.PageStatus.DEPRECATED.value == "deprecated"

    def test_run_status_enum_values(self) -> None:
        """RunStatus 含 success/error."""
        assert ct.RunStatus.SUCCESS.value == "success"
        assert ct.RunStatus.ERROR.value == "error"

    def test_session_stage_enum_values(self) -> None:
        """SessionStage 含 7 个 stage."""
        stages = [s.value for s in ct.SessionStage]
        assert "pending" in stages
        assert "extracting" in stages
        assert "backtesting" in stages
        assert "analyzing" in stages
        assert "done" in stages
        assert "error" in stages


class TestModels:
    """Test pydantic 模型 (5 测试)."""

    def test_factor_page_basic(self) -> None:
        """FactorPage 基本构造."""
        page = ct.FactorPage(
            title="Momentum",
            factor_class=ct.FactorClass.MOMENTUM,
            signal_type=ct.SignalType.MOMENTUM,
        )
        assert page.title == "Momentum"
        assert page.factor_class == ct.FactorClass.MOMENTUM

    def test_backtest_result_page(self) -> None:
        """BacktestResultPage 构造."""
        page = ct.BacktestResultPage(
            title="BT Result 1",
            run_id="20240101-20241231",
        )
        assert page.title == "BT Result 1"
        assert page.run_id == "20240101-20241231"
        assert page.equity_curve == []
        assert page.monthly_returns == {}


    def test_backtest_result_page_time_series(self) -> None:
        """BacktestResultPage accepts equity_curve + monthly_returns (P2 schema, P3 inputs)."""
        page = ct.BacktestResultPage(
            title="BT",
            run_id="r1",
            final_cash=1_100_000.0,
            equity_curve=[
                {"date": "2024-01-01", "value": 1_000_000.0},
                {"date": "2024-12-31", "value": 1_100_000.0},
            ],
            monthly_returns={"2024-01": 1.2, "2024-02": -0.5},
        )
        assert len(page.equity_curve) == 2
        assert page.equity_curve[0]["date"] == "2024-01-01"
        assert page.monthly_returns["2024-01"] == 1.2

    def test_backtest_result_page_render_includes_time_series(self) -> None:
        """render_page must emit equity_curve + monthly_returns lines (P2 Schema 优先)."""
        page = ct.BacktestResultPage(
            title="BT",
            run_id="r1",
            equity_curve=[{"date": "2024-01-01", "value": 1.0}],
            monthly_returns={"2024-01": 1.5},
        )
        md = ct.render_page(page, body="body")
        assert "equity_curve:" in md
        assert "monthly_returns:" in md

    def test_reproduction_page(self) -> None:
        """ReproductionPage 构造."""
        page = ct.ReproductionPage(
            title="Repro 1",
            paper_ref="papers/p1",
        )
        assert page.title == "Repro 1"
        assert page.paper_ref == "papers/p1"

    def test_strategy_page(self) -> None:
        """StrategyPage 构造."""
        page = ct.StrategyPage(
            title="My Strategy",
            strategy_class=ct.StrategyClass.FACTOR_RANKING,
        )
        assert page.title == "My Strategy"
        assert page.strategy_class == ct.StrategyClass.FACTOR_RANKING

    def test_source_page(self) -> None:
        """SourcePage 构造."""
        page = ct.SourcePage(
            title="Source 1",
            paper_id="p1",
            source_type="web",
            source_ref="http://example.com",
        )
        assert page.title == "Source 1"
        assert page.source_ref == "http://example.com"


class TestModelValidation:
    """Test pydantic ValidationError (3 测试)."""

    def test_required_field_missing_raises(self) -> None:
        """缺必填字段 (title) 抛 ValidationError."""
        with pytest.raises(ValidationError):
            ct.FactorPage()  # title 必填

    def test_factor_page_serialization(self) -> None:
        """FactorPage.model_dump() 正确序列化."""
        page = ct.FactorPage(
            title="M",
            factor_class=ct.FactorClass.MOMENTUM,
        )
        d = page.model_dump()
        assert d["title"] == "M"
        assert d["factor_class"] == "momentum"

    def test_nested_enum_in_model(self) -> None:
        """ReproductionPage 接受 SessionStage 枚举."""
        page = ct.ReproductionPage(
            title="R",
            paper_ref="papers/p1",
            stage=ct.SessionStage.EXTRACTING,
        )
        assert page.stage == ct.SessionStage.EXTRACTING


class TestModelConsistency:
    """Test 模型间一致性 (2 测试)."""

    def test_factor_class_enum_complete(self) -> None:
        """FactorClass 8 个值 (含 UNKNOWN)."""
        assert len(ct.FactorClass) == 8

    def test_signal_type_enum_complete(self) -> None:
        """SignalType 7 个值 (含 UNKNOWN)."""
        assert len(ct.SignalType) == 7
