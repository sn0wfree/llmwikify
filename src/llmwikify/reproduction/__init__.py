"""Public API for paper/strategy reproduction module.

PEP 562 兼容层: 用 __getattr__ 懒加载, 避免 nanobot import 触发.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backtest_pkg.run_backtest import run_backtest
    from .schemas import BacktestResult, WikiFactor, WikiStrategy, FactorBacktestResult

__all__ = [
    "run_backtest",
    "BacktestResult",
    "WikiFactor",
    "WikiStrategy",
    "FactorBacktestResult",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "run_backtest": (".backtest_pkg.run_backtest", "run_backtest"),
    "BacktestResult": (".schemas", "BacktestResult"),
    "WikiFactor": (".schemas", "WikiFactor"),
    "WikiStrategy": (".schemas", "WikiStrategy"),
    "FactorBacktestResult": (".schemas", "FactorBacktestResult"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib
        module = importlib.import_module(module_path, package=__name__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
