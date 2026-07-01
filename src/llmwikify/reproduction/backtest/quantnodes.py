"""QuantNodesBacktest — QuantNodes PipelineRunner adapter.

Replaces v2's `_run_pipeline_backtest` method. Wraps:
  1. `build_qn_config(factor_name, h5_path, code, config=run_config)`
  2. `PipelineRunner.from_dict(qn_config).run()` → ctx
  3. `extract_full_backtest_from_ctx(ctx)` → metrics dict

Configuration:
  - `config` (optional): RunConfig or similar — used by `build_qn_config` to
    fill in date ranges, groups, hedge, adj_mode, etc. If None, defaults
    are used (single-stock 5-group IC analyzer).
  - `factor_name_resolver` (optional): callable(signal) → str. Default uses
    `signal.id` (always filesystem-safe via SignalSource conventions).

Why a separate `factor_name_resolver`?
  - `signal.name` may be Chinese (招商/浙商 broker reports)
  - `signal.id` is always filesystem-safe (enforced by SignalSource)
  - `build_qn_config` sanitizes via `re.sub(r"[^A-Za-z0-9_]", "_", ...)`, so
    either works, but using `signal.id` is more consistent.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..signal_source.base import Signal

logger = logging.getLogger(__name__)


class QuantNodesBacktest:
    """QuantNodes PipelineRunner adapter for backtest execution.

    Args:
        config: Optional RunConfig-like object. If None, defaults are used.
        factor_name_resolver: callable(Signal) → str. Default uses `signal.id`.

    Example:
        engine = QuantNodesBacktest(config=run_config)
        metrics = engine.run(
            code="def compute_factor(df): return df['close'].rank()",
            h5_path=Path("/data/alpha_001.h5"),
            signal=signal,
        )
        # metrics = {"ic_mean": 0.01, "icir": 0.1, "win_rate": 0.51, ...}
    """

    def __init__(
        self,
        config: Any = None,
        factor_name_resolver: Callable[[Signal], str] | None = None,
    ) -> None:
        self._config = config
        self._resolve = factor_name_resolver or self._default_resolver

    @staticmethod
    def _default_resolver(signal: Signal) -> str:
        """Default: use signal.id (always filesystem-safe)."""
        return signal.id

    def run(
        self,
        code: str,
        h5_path: Path,
        signal: Signal,
    ) -> dict[str, Any]:
        """Run QuantNodes 12-node pipeline and extract metrics.

        Args:
            code: Generated Python function source.
            h5_path: Path to factor H5 file.
            signal: Source Signal (used for factor_name).

        Returns:
            Metrics dict from `extract_full_backtest_from_ctx`. On failure,
            returns `{"error": "..."}` (does NOT raise — caller decides).

        Raises:
            FileNotFoundError: If QuantNodes dependencies are missing.
        """
        from QuantNodes.research.factor_test.pipeline_runner import PipelineRunner

        from llmwikify.reproduction.pipeline.backtest_config import build_qn_config
        from llmwikify.reproduction.pipeline.backtest_extract import (
            extract_full_backtest_from_ctx,
        )

        factor_name: str = self._resolve(signal)
        logger.info("[backtest] factor=%s h5=%s", factor_name, h5_path.name)
        try:
            qn_config = build_qn_config(
                factor_name=factor_name,
                h5_path=h5_path,
                expression=code,
                config=self._config,
            )
            runner = PipelineRunner.from_dict(qn_config)
            ctx = runner.run()
            return extract_full_backtest_from_ctx(ctx)
        except Exception as exc:
            logger.warning(
                "[backtest] %s failed: %s: %s",
                factor_name, type(exc).__name__, str(exc)[:100],
            )
            return {
                "error": f"{type(exc).__name__}: {exc}",
                "ic_mean": None,
                "icir": None,
                "win_rate": None,
            }
