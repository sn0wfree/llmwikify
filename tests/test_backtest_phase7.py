"""Phase 7 TDD 前置测试: 验证 backtest/ 目标模块在搬迁前可用.

6 个测试, 定义 backtest/ 子包的公共 API 契约.
"""
from __future__ import annotations

import inspect


def test_factor_backtest_universe_callable():
    from llmwikify.reproduction.backtest_pkg.factor_backtest import (
        run_factor_backtest_universe,
    )
    assert callable(run_factor_backtest_universe)


def test_metrics_evaluation_callable():
    from llmwikify.reproduction.backtest_pkg.metrics import evaluation
    assert callable(evaluation)


def test_strategies_import():
    from llmwikify.reproduction.backtest_pkg import strategies
    assert hasattr(strategies, "SIGNAL_NODE_REGISTRY")


def test_l5_validation_import():
    from llmwikify.reproduction.backtest_pkg.l5_validation import run_l5_validation
    assert callable(run_l5_validation)


def test_backtest_import():
    from llmwikify.reproduction.backtest_pkg.run_backtest import run_backtest
    assert callable(run_backtest)


def test_factor_value_store_import():
    from llmwikify.reproduction.backtest_pkg.factor_value_store import (
        store_factor_values,
    )
    assert callable(store_factor_values)
