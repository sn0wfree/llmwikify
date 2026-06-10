"""Schemas for reproduction module.

Merged schema: our 12 fields + QuantNodes summary/config/security_status/nodes.
Plus Factor/Strategy/FactorBacktest schemas for v0.4.0 three-page architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BacktestResult:
    """Result of a backtest run.

    Unified schema combining:
      - llmwikify fields (status/error/statistics/trades/signal_type/params + final_cash/total_return/sharpe/max_dd/win_rate)
      - QuantNodes fields (summary/config/security_status/nodes)
    """

    # llmwikify fields
    status: str = "success"  # "success" | "error"
    error: str | None = None
    statistics: dict[str, float] = field(default_factory=dict)
    trades: list[dict[str, Any]] = field(default_factory=list)
    final_cash: float = 0.0
    total_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    signal_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    # QuantNodes fields (optional, only populated when going through QuantNodes path)
    summary: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    security_status: str = "unknown"
    nodes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "error": self.error,
            "statistics": self.statistics,
            "trades": self.trades,
            "final_cash": self.final_cash,
            "total_return": self.total_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "signal_type": self.signal_type,
            "params": self.params,
            "summary": self.summary,
            "config": self.config,
            "security_status": self.security_status,
            "nodes": self.nodes,
        }


@dataclass
class WikiFactor:
    """Factor definition extracted from paper or user-defined."""

    name: str = ""
    factor_class: str = ""        # momentum | value | volatility | quality | size | growth | composite
    factor_params: dict[str, Any] = field(default_factory=dict)
    factor_source: str = ""       # paper reference or "user-defined"
    status: str = "draft"         # draft | validated | deprecated
    wiki_page: str = ""           # wiki/factor/{slug}.md path

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "factor_class": self.factor_class,
            "factor_params": self.factor_params,
            "factor_source": self.factor_source,
            "status": self.status,
            "wiki_page": self.wiki_page,
        }


@dataclass
class WikiStrategy:
    """Strategy definition extracted from paper or user-defined."""

    name: str = ""
    strategy_class: str = ""      # trend_following | factor_ranking | stat_arb | mean_reversion | composite
    signal_type: str = ""         # ma_cross | rsi | momentum | volatility | factor_rank | signal_composite
    signal_params: dict[str, Any] = field(default_factory=dict)
    factor_refs: list[str] = field(default_factory=list)  # references to Factor wiki pages
    rebalance_freq: str = "daily" # daily | weekly | monthly | quarterly
    status: str = "draft"         # draft | backtested | validated | deprecated
    wiki_page: str = ""           # wiki/strategy/{slug}.md path

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "strategy_class": self.strategy_class,
            "signal_type": self.signal_type,
            "signal_params": self.signal_params,
            "factor_refs": self.factor_refs,
            "rebalance_freq": self.rebalance_freq,
            "status": self.status,
            "wiki_page": self.wiki_page,
        }


@dataclass
class FactorBacktestResult:
    """Result of a single-factor backtest."""

    ic_mean: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0
    t_stat: float = 0.0
    win_rate: float = 0.0         # IC > 0 ratio
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    turnover: float = 0.0
    quantile_returns: dict[str, float] = field(default_factory=dict)  # {group: annual_return}
    ic_series: list[dict[str, Any]] = field(default_factory=list)     # [{date, ic}]
    quantile_curves: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # {group: [{date, value}]}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "icir": self.icir,
            "t_stat": self.t_stat,
            "win_rate": self.win_rate,
            "annual_return": self.annual_return,
            "max_drawdown": self.max_drawdown,
            "turnover": self.turnover,
            "quantile_returns": self.quantile_returns,
            "ic_series": self.ic_series,
            "quantile_curves": self.quantile_curves,
        }