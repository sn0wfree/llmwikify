"""Tests for L5 scoring with reverse factors (abs() on sharpe, calmar, sortino)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))


def test_score_return_uses_abs_sharpe():
    """Verify _score_return uses |sharpe| so reverse factors get credit."""
    from llmwikify.reproduction.backtest_pkg.l5_validation import _score_return

    # Reverse factor: sharpe = -1.5 (strong but negative)
    # Before fix: 0 points. After fix: 8 points.
    return_analysis = {"sharpe": -1.5, "calmar": -0.5, "sortino": -2.0}
    score = _score_return(return_analysis)
    # With abs: 8 (sharpe) + 4 (calmar) + 6 (sortino) = 18
    assert score == 18, f"Expected 18 for reverse factor with strong abs metrics, got {score}"


def test_score_return_positive_factor():
    """Verify _score_return also works for positive factors."""
    from llmwikify.reproduction.backtest_pkg.l5_validation import _score_return

    return_analysis = {"sharpe": 1.5, "calmar": 0.5, "sortino": 2.0}
    score = _score_return(return_analysis)
    assert score == 18, f"Expected 18 for normal factor, got {score}"


def test_score_group_uses_abs_sharpe():
    """Verify _score_group uses |ls_sharpe|."""
    from llmwikify.reproduction.backtest_pkg.l5_validation import _score_group

    # Reverse factor
    group_analysis = {
        "ls_sharpe": -2.0,  # very strong but negative
        "ls_ann_return": -0.6,
        "ls_max_drawdown": 0.15,  # positive
        "group_returns": {"G1": 0.05, "G2": 0.03, "G3": 0.01, "G4": -0.02, "G5": -0.05},
        "group_monotonicity": "G1>G2>G3>G4>G5",
    }
    score = _score_group(group_analysis)
    # With abs: 10 (sharpe) + 5 (monotonic) + 3 (|mdd| < 0.2) = 18
    assert score == 18, f"Expected 18 for reverse factor with strong abs sharpe, got {score}"


def test_score_group_uses_abs_mdd():
    """Verify _score_group uses |mdd|."""
    from llmwikify.reproduction.backtest_pkg.l5_validation import _score_group

    # Even with positive ls_mdd, abs is used
    group_analysis = {
        "ls_sharpe": 1.0,  # > 0.5 threshold
        "ls_ann_return": 0.1,
        "ls_max_drawdown": 0.05,  # small positive MDD
        "group_returns": {"G1": 0.05, "G2": 0.03, "G3": 0.01, "G4": -0.02, "G5": -0.05},
        "group_monotonicity": "G1>G2>G3>G4>G5",
    }
    score = _score_group(group_analysis)
    # 7 (sharpe > 0.5) + 5 (monotonic) + 5 (|mdd| < 0.1) = 17
    assert score == 17, f"Expected 17, got {score}"


def test_reverse_factor_gets_higher_score():
    """Reverse factors with strong abs metrics should score same as positive factors."""
    from llmwikify.reproduction.backtest_pkg.l5_validation import _score_return, _score_group

    # Same absolute metrics, different signs
    return_pos = {"sharpe": 1.5, "calmar": 0.5, "sortino": 2.0}
    return_neg = {"sharpe": -1.5, "calmar": -0.5, "sortino": -2.0}
    assert _score_return(return_pos) == _score_return(return_neg)

    group_pos = {
        "ls_sharpe": 1.5,
        "ls_ann_return": 0.5,
        "ls_max_drawdown": 0.1,
        "group_returns": {"G1": 0.05, "G2": 0.03, "G3": 0.01, "G4": -0.02, "G5": -0.05},
        "group_monotonicity": "G1>G2>G3>G4>G5",
    }
    group_neg = {**group_pos, "ls_sharpe": -1.5, "ls_ann_return": -0.5}
    assert _score_group(group_pos) == _score_group(group_neg)
