"""SingleJsonSink — write output_dir/single_factor_<id>.json per signal.

Replaces v2's `FactorStage._persist_result(idx, result)`:
    out_file = output_dir / f"single_factor_{idx:03d}.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str))

Generalized to use `signal.id` instead of `alpha-{idx:03d}` so any paper
(招商/1601) can write per-signal JSON with the appropriate id.

Output naming:
  - 101 alphas: `single_factor_alpha-001.json`
  - 招商: `single_factor_signal-001.json`
  - 1601: `single_factor_1601_00991v3_alpha-001.json`
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..backtest.base import FactorResult

logger = logging.getLogger(__name__)


class SingleJsonSink:
    """Writes output_dir/single_factor_<signal.id>.json per signal.

    Args:
        output_dir: Directory to write per-signal JSON files into.
        indent: JSON indentation (default 2 for readability).
    """

    def __init__(self, output_dir: Path, indent: int = 2) -> None:
        self._dir = Path(output_dir)
        self._indent = indent

    @property
    def output_dir(self) -> Path:
        return self._dir

    def _filename(self, signal_id: str) -> str:
        """single_factor_<signal_id>.json — sanitized for filesystem."""
        safe_id = signal_id.replace("/", "_").replace("\\", "_")
        return f"single_factor_{safe_id}.json"

    def write_one(self, result: FactorResult) -> Path:
        """Write one FactorResult to a single_factor_<id>.json file.

        Mirrors v2's `_persist_result` — uses `to_dict()` for JSON-friendly
        dict and `default=str` for non-serializable types (Path, polars
        Series dtype names).
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        out_file = self._dir / self._filename(result.signal.id)
        out_file.write_text(
            json.dumps(
                result.to_dict(),
                indent=self._indent,
                ensure_ascii=False,
                default=str,
            ),
            encoding="utf-8",
        )
        logger.debug("[sink] wrote %s (%d bytes)", out_file.name, out_file.stat().st_size)
        return out_file

    def write_batch(self, results: list[FactorResult]) -> list[Path]:
        """No batch aggregation — single writes are sufficient."""
        return []

    def flush(self) -> None:
        """No-op: each write_one flushes immediately."""
        return None
