"""Schemas for reproduction module.

Merged schema: our 12 fields + QuantNodes summary/config/security_status/nodes.
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