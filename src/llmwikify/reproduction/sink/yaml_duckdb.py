"""YamlDuckdbSink — write factors/<dir>/factor.{yaml,duckdb} (101 alphas style).

Replaces v2's `FactorRunner._persist_factor` + `_save_to_duckdb`.

Wraps the existing `persist/factor_library.py` and `pipeline/persist.py` API:
  - `persist_code_to_yaml(name, code, formula_brief, backtest, h5_path, code_chars,
                          config=run_config, alpha_index=...)` → (action, factor_dir)
  - `save_backtest_duckdb(name, run_id, backtest, factor_wide, factors_dir)` → path

The actual persistence logic stays in `persist/factor_library.py` — this sink
is a thin adapter that bridges FactorResult to its expected argument shape.

Output structure (101 alphas style):
    factors/<strategy_dir>/stk_alpha_NNN_HASH/
    ├── factor.yaml              # 6-layer factor definition
    ├── factor.duckdb            # backtest metrics + factor values
    └── (other artifacts)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..backtest.base import FactorResult

logger = logging.getLogger(__name__)


class YamlDuckdbSink:
    """Writes factor YAML + DuckDB per signal (canonical 6-layer storage).

    Args:
        factors_dir: Base directory (e.g. Path("quant/factors")).
        strategy_dir: Sub-directory for this batch (e.g. "101_alphas").
                      Empty string → no sub-directory.
        config: RunConfig-like object for business params (asset_type, etc.).
                Optional — defaults used if None.
        run_id_prefix: Prefix for DuckDB run_id (default "pipeline_a").
    """

    def __init__(
        self,
        factors_dir: Path,
        strategy_dir: str = "",
        config: Any = None,
        run_id_prefix: str = "pipeline_a",
    ) -> None:
        self._factors_dir = Path(factors_dir)
        self._strategy_dir = strategy_dir
        self._config = config
        self._run_id_prefix = run_id_prefix

    @property
    def factors_dir(self) -> Path:
        return self._factors_dir

    def write_one(self, result: FactorResult) -> Path:
        """Persist FactorResult to YAML + DuckDB.

        Returns:
            Path to factor_dir (created). On failure, returns Path("/dev/null").
        """
        if result.status != "success":
            # Failed signals don't get persisted to library (mirrors v2 behavior).
            logger.debug("[sink] skipping yaml/duckdb for failed signal %s", result.signal.id)
            return Path("/dev/null")

        from llmwikify.reproduction.persist.factor_library import save_backtest_duckdb
        from llmwikify.reproduction.pipeline.persist import persist_code_to_yaml

        alpha_index: int = result.signal.metadata.get("alpha_index", 0)
        if not isinstance(alpha_index, int) or alpha_index <= 0:
            alpha_index = result.signal.metadata.get("index", 0)
        if not isinstance(alpha_index, int):
            alpha_index = 0

        # 1. YAML persistence (returns (action, factor_dir))
        try:
            _, factor_dir = persist_code_to_yaml(
                factor_name=result.signal.id,
                code=result.code or "",
                formula_brief=result.signal.formula_brief,
                backtest=result.backtest,
                h5_path=str(result.h5_path) if result.h5_path else "",
                code_chars=result.code_chars,
                config=self._config,
                alpha_index=alpha_index,
                strategy_dir=self._strategy_dir,
                factors_dir=self._factors_dir,
            )
        except Exception as exc:
            logger.warning(
                "[sink] yaml persist failed for %s: %s: %s",
                result.signal.id, type(exc).__name__, str(exc)[:100],
            )
            return Path("/dev/null")

        # 2. DuckDB persistence
        try:
            rel_path: str
            if factor_dir and self._factors_dir in factor_dir.parents:
                rel_path = str(factor_dir.relative_to(self._factors_dir))
            elif factor_dir:
                rel_path = factor_dir.name
            else:
                rel_path = f"{self._strategy_dir}/{result.signal.id}" if self._strategy_dir else result.signal.id

            run_id: str = f"{self._run_id_prefix}_{alpha_index:03d}"
            save_backtest_duckdb(
                factor_name=rel_path,
                run_id=run_id,
                backtest=result.backtest,
                factor_wide=None,  # PR6 will pass factor_wide; sink currently writes metrics only
                factors_dir=self._factors_dir,
            )
        except Exception as exc:
            logger.warning(
                "[sink] duckdb persist failed for %s: %s: %s",
                result.signal.id, type(exc).__name__, str(exc)[:100],
            )
            # YAML was written, so return that path even if DuckDB failed.

        return factor_dir if factor_dir else Path("/dev/null")

    def write_batch(self, results: list[FactorResult]) -> list[Path]:
        """No batch aggregation — each signal persisted individually."""
        return []

    def flush(self) -> None:
        """No-op: each write_one persists immediately."""
        return None
