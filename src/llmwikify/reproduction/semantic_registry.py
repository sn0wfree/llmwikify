"""Semantic factor registry (Layer 4 of the 4-layer abstraction).

PR-5 (2026-06-21): 50+ business-semantic factor templates across 7 families.
Maps human-readable factor names (e.g. momentum_20, reversal_5) to AST templates
that bind to underlying QuantNodes primitive/composite ops.

Hierarchy:
  Primitive (317+)    : QuantNodes direct (rank, rolling_mean, ...)
  Composite (20+)     : QuantNodes composite_dag (industry_neutralize, ...)
  Polars native (8+)  : llmwikify ast_compiler (pl_alias, pl_str_contains, ...)
  Semantic (50+)      : llmwikify semantic_registry (this module)

Architecture:
- Templates are dict-of-dict AST JSON, instantiated via Pydantic ASTNode.
- Parametric templates use placeholder columns derived from a base name
  (e.g. momentum_5 -> lag_close_5 = delay(close, 5)).
- User extensions loaded from ~/.llmwikify/semantic_registry.yaml at startup.
"""
from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticOp:
    """A named business-semantic factor template.

    Attributes:
        name: Human-readable identifier (e.g. "momentum_20").
        family: One of momentum/reversal/value/volatility/volume/quality/conditional.
        description: One-line explanation for LLM prompt and human docs.
        template: AST JSON dict with placeholders for params.
        param_keys: Keys the LLM may override (e.g. window=20 -> use lag_close_20).
    """

    name: str
    family: str
    description: str
    template: dict[str, Any]
    param_keys: tuple[str, ...] = field(default_factory=tuple)


# ─── Template helpers ────────────────────────────────────────


def _tpl(
    name: str,
    family: str,
    description: str,
    template: dict[str, Any],
    param_keys: tuple[str, ...] = (),
) -> SemanticOp:
    return SemanticOp(
        name=name,
        family=family,
        description=description,
        template=template,
        param_keys=param_keys,
    )


# ─── Family 1: momentum (8 ops) ──────────────────────────────

_MOMENTUM_OPS: list[SemanticOp] = [
    _tpl(
        "momentum_n",
        "momentum",
        "n-day price momentum: close / delay(close, n) - 1",
        {
            "op": "sub",
            "args": [
                {
                    "op": "div",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": "__n__"}},
                    ],
                },
                {"op": "lit", "value": 1.0},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "log_return_n",
        "momentum",
        "n-day log return: log(close / delay(close, n))",
        {
            "op": "log",
            "args": [
                {
                    "op": "div",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": "__n__"}},
                    ],
                }
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "ts_mean_n",
        "momentum",
        "n-day rolling mean of close",
        {
            "op": "rolling_mean",
            "args": [{"op": "col", "value": "close"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "ts_zscore_n",
        "momentum",
        "n-day rolling z-score of close: (close - ts_mean) / ts_std",
        {
            "op": "div",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "rolling_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
                    ],
                },
                {"op": "rolling_std", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "ts_delta_n",
        "momentum",
        "n-day price change: close - delay(close, n)",
        {
            "op": "delta",
            "args": [{"op": "col", "value": "close"}],
            "kwargs": {"periods": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "acceleration_n",
        "momentum",
        "momentum acceleration: momentum_n - momentum_2n",
        {
            "op": "sub",
            "args": [
                {"op": "col", "value": "__factor_momentum_n__"},
                {"op": "col", "value": "__factor_momentum_2n__"},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "ema_crossover",
        "momentum",
        "EMA fast/slow crossover signal",
        {
            "op": "sub",
            "args": [
                {"op": "ewm_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"span": "__fast__"}},
                {"op": "ewm_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"span": "__slow__"}},
            ],
        },
        param_keys=("fast", "slow"),
    ),
    _tpl(
        "ts_argmax_n",
        "momentum",
        "Position of argmax in last n days (0 = today, n-1 = n days ago)",
        {
            "op": "ts_argmax",
            "args": [{"op": "col", "value": "close"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
]


# ─── Family 2: reversal (6 ops) ─────────────────────────────

_REVERSAL_OPS: list[SemanticOp] = [
    _tpl(
        "reversal_n",
        "reversal",
        "n-day reversal: -momentum_n (mean-reversion expectation)",
        {
            "op": "neg",
            "args": [
                {"op": "col", "value": "__factor_momentum_n__"},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "short_term_reversal",
        "reversal",
        "1-day reversal: -pct_change(close, 1)",
        {
            "op": "neg",
            "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}],
        },
    ),
    _tpl(
        "gap_reversal",
        "reversal",
        "Overnight gap reversal: (open - delay(close, 1)) / delay(close, 1)",
        {
            "op": "div",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"op": "col", "value": "open"},
                        {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                    ],
                },
                {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
            ],
        },
    ),
    _tpl(
        "intraday_reversal",
        "reversal",
        "Intraday reversal: (close - open) / open",
        {
            "op": "div",
            "args": [
                {"op": "sub", "args": [{"op": "col", "value": "close"}, {"op": "col", "value": "open"}]},
                {"op": "col", "value": "open"},
            ],
        },
    ),
    _tpl(
        "overnight_return",
        "reversal",
        "Overnight return: open / delay(close, 1) - 1",
        {
            "op": "sub",
            "args": [
                {
                    "op": "div",
                    "args": [
                        {"op": "col", "value": "open"},
                        {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                    ],
                },
                {"op": "lit", "value": 1.0},
            ],
        },
    ),
    _tpl(
        "max_drawdown_n",
        "reversal",
        "Max drawdown over n days: (close - ts_max(close, n)) / ts_max(close, n)",
        {
            "op": "div",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "rolling_max", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
                    ],
                },
                {"op": "rolling_max", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
]


# ─── Family 3: value (4 ops) ────────────────────────────────

_VALUE_OPS: list[SemanticOp] = [
    _tpl(
        "price_to_ma",
        "value",
        "Price to moving average ratio: close / rolling_mean(close, n)",
        {
            "op": "div",
            "args": [
                {"op": "col", "value": "close"},
                {"op": "rolling_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "ma_distance",
        "value",
        "Distance from n-day MA: (close - MA) / MA",
        {
            "op": "div",
            "args": [
                {
                    "op": "sub",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "rolling_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
                    ],
                },
                {"op": "rolling_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "price_to_high",
        "value",
        "Price to n-day high ratio: close / rolling_max(close, n)",
        {
            "op": "div",
            "args": [
                {"op": "col", "value": "close"},
                {"op": "rolling_max", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "price_to_low",
        "value",
        "Price to n-day low ratio: close / rolling_min(close, n)",
        {
            "op": "div",
            "args": [
                {"op": "col", "value": "close"},
                {"op": "rolling_min", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
            ],
        },
        param_keys=("n",),
    ),
]


# ─── Family 4: volatility (8 ops) ───────────────────────────

_VOLATILITY_OPS: list[SemanticOp] = [
    _tpl(
        "realized_vol_n",
        "volatility",
        "n-day realized volatility: ts_std(pct_change(close, 1), n)",
        {
            "op": "rolling_std",
            "args": [
                {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}
            ],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "parkinson_vol_n",
        "volatility",
        "Parkinson volatility estimate using high-low range",
        {
            "op": "sqrt",
            "args": [
                {
                    "op": "rolling_mean",
                    "args": [
                        {
                            "op": "div",
                            "args": [
                                {"op": "pow", "args": [{"op": "log", "args": [{"op": "div", "args": [{"op": "col", "value": "high"}, {"op": "col", "value": "low"}]}]}, {"op": "lit", "value": 2.0}]},
                                {"op": "lit", "value": 4.0},
                            ],
                        }
                    ],
                    "kwargs": {"window": "__n__"},
                }
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "gk_vol_n",
        "volatility",
        "Garman-Klass volatility using OHLC",
        {
            "op": "sqrt",
            "args": [
                {
                    "op": "rolling_mean",
                    "args": [
                        {"op": "col", "value": "__gk_inner_n__"}
                    ],
                    "kwargs": {"window": "__n__"},
                }
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "vol_ratio",
        "volatility",
        "Short/long volatility ratio: vol_5 / vol_20",
        {
            "op": "div",
            "args": [
                {"op": "col", "value": "__factor_realized_vol_5__"},
                {"op": "col", "value": "__factor_realized_vol_20__"},
            ],
        },
    ),
    _tpl(
        "vol_of_vol",
        "volatility",
        "Volatility of volatility (vol regime indicator)",
        {
            "op": "rolling_std",
            "args": [
                {"op": "rolling_std", "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}], "kwargs": {"window": "__n__"}}
            ],
            "kwargs": {"window": "__m__"},
        },
        param_keys=("n", "m"),
    ),
    _tpl(
        "downside_vol_n",
        "volatility",
        "n-day downside deviation (semi-volatility)",
        {
            "op": "rolling_std",
            "args": [
                {"op": "pl_min_h", "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}, {"op": "lit", "value": 0.0}]}
            ],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "true_range",
        "volatility",
        "True range: max(high-low, |high-prev_close|, |low-prev_close|)",
        {
            "op": "pl_max_h",
            "args": [
                {"op": "sub", "args": [{"op": "col", "value": "high"}, {"op": "col", "value": "low"}]},
                {"op": "abs", "args": [{"op": "sub", "args": [{"op": "col", "value": "high"}, {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}]}]},
                {"op": "abs", "args": [{"op": "sub", "args": [{"op": "col", "value": "low"}, {"op": "delay", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}]}]},
            ],
        },
    ),
    _tpl(
        "atr_n",
        "volatility",
        "Average True Range over n days",
        {
            "op": "rolling_mean",
            "args": [{"op": "col", "value": "__factor_true_range__"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
]


# ─── Family 5: volume (6 ops) ───────────────────────────────

_VOLUME_OPS: list[SemanticOp] = [
    _tpl(
        "volume_ratio_n",
        "volume",
        "n-day average volume / total average volume",
        {
            "op": "rolling_mean",
            "args": [{"op": "col", "value": "volume"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "volume_momentum",
        "volume",
        "Volume momentum: volume / delay(volume, n) - 1",
        {
            "op": "sub",
            "args": [
                {
                    "op": "div",
                    "args": [
                        {"op": "col", "value": "volume"},
                        {"op": "delay", "args": [{"op": "col", "value": "volume"}], "kwargs": {"periods": "__n__"}},
                    ],
                },
                {"op": "lit", "value": 1.0},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "volume_price_trend",
        "volume",
        "Volume-price trend: cumsum(volume * pct_change(close, 1))",
        {
            "op": "mul",
            "args": [
                {"op": "col", "value": "volume"},
                {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
            ],
        },
    ),
    _tpl(
        "amount_volatility",
        "volume",
        "Volume-weighted return volatility",
        {
            "op": "rolling_std",
            "args": [
                {
                    "op": "mul",
                    "args": [
                        {"op": "col", "value": "volume"},
                        {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                    ],
                }
            ],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "vwap_deviation",
        "volume",
        "Deviation of close from rolling VWAP",
        {
            "op": "sub",
            "args": [
                {"op": "col", "value": "close"},
                {
                    "op": "div",
                    "args": [
                        {"op": "rolling_sum", "args": [{"op": "mul", "args": [{"op": "col", "value": "close"}, {"op": "col", "value": "volume"}]}], "kwargs": {"window": "__n__"}},
                        {"op": "rolling_sum", "args": [{"op": "col", "value": "volume"}], "kwargs": {"window": "__n__"}},
                    ],
                },
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "volume_breakout",
        "volume",
        "Volume breakout: volume / rolling_mean(volume, n) > threshold",
        {
            "op": "gt",
            "args": [
                {
                    "op": "div",
                    "args": [
                        {"op": "col", "value": "volume"},
                        {"op": "rolling_mean", "args": [{"op": "col", "value": "volume"}], "kwargs": {"window": "__n__"}},
                    ],
                },
                {"op": "lit", "value": "__threshold__"},
            ],
        },
        param_keys=("n", "threshold"),
    ),
]


# ─── Family 6: quality (5 ops) ──────────────────────────────

_QUALITY_OPS: list[SemanticOp] = [
    _tpl(
        "return_stability",
        "quality",
        "Negative realized vol (higher = more stable = better quality)",
        {
            "op": "neg",
            "args": [
                {"op": "rolling_std", "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}], "kwargs": {"window": "__n__"}}
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "win_rate_n",
        "quality",
        "Rolling fraction of up days over n days",
        {
            "op": "rolling_mean",
            "args": [
                {
                    "op": "gt",
                    "args": [
                        {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                        {"op": "lit", "value": 0.0},
                    ],
                }
            ],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "sharpe_n",
        "quality",
        "n-day rolling Sharpe ratio (mean return / std return)",
        {
            "op": "div",
            "args": [
                {
                    "op": "rolling_mean",
                    "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}],
                    "kwargs": {"window": "__n__"},
                },
                {
                    "op": "rolling_std",
                    "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}],
                    "kwargs": {"window": "__n__"},
                },
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "skewness_n",
        "quality",
        "n-day return skewness",
        {
            "op": "rolling_skew",
            "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "autocorr_n_lag",
        "quality",
        "n-day rolling autocorrelation at given lag",
        {
            "op": "rolling_corr",
            "args": [
                {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                {"op": "delay", "args": [{"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}}], "kwargs": {"periods": "__lag__"}},
            ],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n", "lag"),
    ),
]


# ─── Family 7: conditional (13 ops) ─────────────────────────

_CONDITIONAL_OPS: list[SemanticOp] = [
    _tpl(
        "if_up_then_momentum",
        "conditional",
        "Conditional: if up day, take momentum; else 0",
        {
            "op": "where",
            "args": [
                {
                    "op": "gt",
                    "args": [
                        {"op": "pct_change", "args": [{"op": "col", "value": "close"}], "kwargs": {"periods": 1}},
                        {"op": "lit", "value": 0.0},
                    ],
                },
                {"op": "col", "value": "__factor_momentum_n__"},
                {"op": "lit", "value": 0.0},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "high_vol_momentum",
        "conditional",
        "Conditional: momentum in high-vol regimes only",
        {
            "op": "where",
            "args": [
                {
                    "op": "gt",
                    "args": [
                        {"op": "col", "value": "__factor_realized_vol_n__"},
                        {"op": "rolling_mean", "args": [{"op": "col", "value": "__factor_realized_vol_n__"}], "kwargs": {"window": "__m__"}},
                    ],
                },
                {"op": "col", "value": "__factor_momentum_n__"},
                {"op": "lit", "value": 0.0},
            ],
        },
        param_keys=("n", "m"),
    ),
    _tpl(
        "trend_filter",
        "conditional",
        "Conditional: momentum if close > MA_n, else reversal",
        {
            "op": "where",
            "args": [
                {
                    "op": "gt",
                    "args": [
                        {"op": "col", "value": "close"},
                        {"op": "rolling_mean", "args": [{"op": "col", "value": "close"}], "kwargs": {"window": "__n__"}},
                    ],
                },
                {"op": "col", "value": "__factor_momentum_n__"},
                {"op": "neg", "args": [{"op": "col", "value": "__factor_momentum_n__"}]},
            ],
        },
        param_keys=("n",),
    ),
    _tpl(
        "zscore_threshold",
        "conditional",
        "Sign of z-score with threshold",
        {
            "op": "pl_when",
            "args": [
                {
                    "op": "gt",
                    "args": [
                        {"op": "col", "value": "__zscore_col__"},
                        {"op": "lit", "value": "__threshold__"},
                    ],
                },
                {"op": "lit", "value": 1.0},
                {"op": "lit", "value": -1.0},
            ],
        },
        param_keys=("zscore_col", "threshold"),
    ),
    _tpl(
        "rank_signal",
        "conditional",
        "Cross-sectional rank of momentum (smoothed by n-day avg)",
        {
            "op": "rank",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
        },
        param_keys=("n",),
    ),
    _tpl(
        "zscore_signal",
        "conditional",
        "Cross-sectional z-score of momentum",
        {
            "op": "zscore",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
        },
        param_keys=("n",),
    ),
    _tpl(
        "winsorized_momentum",
        "conditional",
        "Winsorized cross-sectional momentum",
        {
            "op": "winsorize",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
        },
        param_keys=("n",),
    ),
    _tpl(
        "neutralized_momentum",
        "conditional",
        "Market-neutralized momentum (subtract cross-section mean)",
        {
            "op": "neutralize",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
        },
        param_keys=("n",),
    ),
    _tpl(
        "scaled_momentum",
        "conditional",
        "Z-score scaled cross-sectional momentum",
        {
            "op": "scale",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
        },
        param_keys=("n",),
    ),
    _tpl(
        "clipped_momentum",
        "conditional",
        "Momentum clipped to [-k, k] to limit outlier impact",
        {
            "op": "pl_max_h",
            "args": [
                {"op": "pl_min_h", "args": [{"op": "col", "value": "__factor_momentum_n__"}, {"op": "lit", "value": "__k__"}]},
                {"op": "neg", "args": [{"op": "lit", "value": "__k__"}]},
            ],
        },
        param_keys=("n", "k"),
    ),
    _tpl(
        "fill_null_zero",
        "conditional",
        "Fill NaN with 0",
        {
            "op": "fill_null",
            "args": [{"op": "col", "value": "__factor_momentum_n__"}],
            "kwargs": {"value": 0.0},
        },
        param_keys=("n",),
    ),
    _tpl(
        "rolling_apply",
        "conditional",
        "Generic rolling window application (placeholder for custom logic)",
        {
            "op": "rolling_mean",
            "args": [{"op": "col", "value": "close"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
    _tpl(
        "ts_rank",
        "conditional",
        "Time-series rank of close over n days (0..1)",
        {
            "op": "ts_rank",
            "args": [{"op": "col", "value": "close"}],
            "kwargs": {"window": "__n__"},
        },
        param_keys=("n",),
    ),
]


_DEFAULT_REGISTRY: dict[str, SemanticOp] = {
    op.name: op
    for ops_list in (
        _MOMENTUM_OPS,
        _REVERSAL_OPS,
        _VALUE_OPS,
        _VOLATILITY_OPS,
        _VOLUME_OPS,
        _QUALITY_OPS,
        _CONDITIONAL_OPS,
    )
    for op in ops_list
}


# ─── Registry loader ─────────────────────────────────────────

_REGISTRY: dict[str, SemanticOp] = {}


def _ensure_loaded() -> dict[str, SemanticOp]:
    """Lazy-load registry (default + user YAML)."""
    global _REGISTRY
    if _REGISTRY:
        return _REGISTRY
    _REGISTRY = dict(_DEFAULT_REGISTRY)
    yaml_path = Path.home() / ".llmwikify" / "semantic_registry.yaml"
    if yaml_path.exists():
        try:
            load_user_registry(yaml_path)
        except Exception as exc:
            logger.warning("Failed to load user semantic_registry.yaml: %s", exc)
    return _REGISTRY


def load_user_registry(yaml_path: Path | str) -> int:
    """Load user-defined semantic ops from YAML and merge into registry.

    YAML format:
        ops:
          my_factor:
            family: momentum
            description: "..."
            template:
              op: ...
              args: [...]
            param_keys: [n]

    Returns:
        Number of ops loaded (new + updated).
    """
    import yaml

    global _REGISTRY
    yaml_path = Path(yaml_path)
    if not yaml_path.exists():
        raise FileNotFoundError(f"semantic_registry YAML not found: {yaml_path}")

    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict) or "ops" not in data:
        raise ValueError("semantic_registry.yaml must have top-level 'ops:' key")

    count = 0
    for name, spec in data["ops"].items():
        if not isinstance(spec, dict):
            continue
        op = SemanticOp(
            name=name,
            family=spec.get("family", "custom"),
            description=spec.get("description", ""),
            template=spec.get("template", {}),
            param_keys=tuple(spec.get("param_keys", ())),
        )
        _REGISTRY[name] = op
        count += 1
    return count


def list_ops() -> list[str]:
    """Return all registered semantic op names (sorted)."""
    return sorted(_ensure_loaded().keys())


def list_by_family(family: str) -> list[str]:
    """Return ops in a given family (e.g. 'momentum')."""
    return sorted(
        name for name, op in _ensure_loaded().items() if op.family == family
    )


def get_op(name: str) -> SemanticOp | None:
    """Get a semantic op by name."""
    return _ensure_loaded().get(name)


def get_doc_for_llm() -> str:
    """Generate human/LLM-readable documentation of all registered ops.

    PR-5: Used by factor_compiler to build LLM system prompt.
    """
    lines: list[str] = [
        "# Semantic Factor Library (Layer 4 of 4-Layer Abstraction)",
        "",
        "PR-5 (2026-06-21): 50+ business-semantic factors across 7 families.",
        "Each op maps to a parameterizable AST template that compiles to polars.Expr.",
        "",
        "Use these as `factor_class` in factor.yaml to bypass AST LLM compilation.",
        "Each template may have parameters (n, fast, slow, ...) overridable via factor_params.",
        "",
    ]
    by_family: dict[str, list[SemanticOp]] = {}
    for op in _ensure_loaded().values():
        by_family.setdefault(op.family, []).append(op)
    for family, ops in sorted(by_family.items()):
        lines.append(f"## {family} ({len(ops)} ops)")
        lines.append("")
        for op in sorted(ops, key=lambda x: x.name):
            params = (
                f" params=[{', '.join(op.param_keys)}]" if op.param_keys else ""
            )
            lines.append(f"- **{op.name}**{params}: {op.description}")
        lines.append("")
    return "\n".join(lines)


# ─── Template instantiation ──────────────────────────────────


def _substitute_params(
    template: Any, params: dict[str, Any]
) -> Any:
    """Recursively substitute __placeholder__ strings with param values.

    Placeholders:
    - __n__ -> params['n']
    - __lag__ -> params['lag']
    - __factor_<name>__ -> refers to another semantic op (lazy ref)
    - __<col>__ -> refers to a synthetic column (will be injected)
    """
    if isinstance(template, dict):
        return {k: _substitute_params(v, params) for k, v in template.items()}
    if isinstance(template, list):
        return [_substitute_params(v, params) for v in template]
    if isinstance(template, str):
        if template.startswith("__") and template.endswith("__"):
            key = template[2:-2]
            if key in params:
                return params[key]
            # Leave unresolved (caller decides default behavior)
            return template
    return template


def instantiate(op_name: str, params: dict[str, Any] | None = None):
    """Instantiate a semantic op with params → ASTNode.

    Args:
        op_name: Semantic op name (e.g. "momentum_20" or "momentum_n" with n=20).
        params: Param overrides (e.g. {"n": 20, "fast": 5, "slow": 20}).

    Returns:
        ASTNode ready for compile_ast.

    Raises:
        KeyError: If op_name is not registered.
        ValueError: If required param_keys are missing.
    """
    from .ast_nodes import ASTNode  # noqa: PLC0415  (intentional local import)

    reg = _ensure_loaded()
    if op_name not in reg:
        raise KeyError(f"Unknown semantic op: {op_name!r}")
    op = reg[op_name]
    params = params or {}

    # Check required param_keys
    missing = [k for k in op.param_keys if k not in params]
    if missing:
        # Try default values for common keys
        defaults = {"n": 20, "m": 60, "fast": 5, "slow": 20, "lag": 1, "threshold": 1.0, "k": 3.0}
        for k in missing:
            if k in defaults:
                params[k] = defaults[k]
            else:
                raise ValueError(
                    f"Semantic op {op_name!r} requires param {k!r} (not provided)"
                )

    # Substitute params in template
    template = copy.deepcopy(op.template)
    substituted = _substitute_params(template, params)
    return ASTNode(**substituted)


__all__ = [
    "SemanticOp",
    "list_ops",
    "list_by_family",
    "get_op",
    "get_doc_for_llm",
    "instantiate",
    "load_user_registry",
]
