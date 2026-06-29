"""SkipLoader — load cached results from output_dir on resume.

PR9b: extracted from v2's FactorStage. Two responsibilities:
  1. **scan** — which idx have a cached `single_factor_NNN.json`?
  2. **load** — re-hydrate cached JSON → FactorResult via ResultFactory

Why a class (vs module-level functions)?
  - The two operations share the same `output_dir` + `alpha_start/alpha_end`
    state (the discovery parameters), so bundling them into a class makes
    the dependency explicit.
  - Composes with ResultFactory (PR9a) — `load(skip, factory)` takes the
    factory as a parameter, keeping SkipLoader pure (no module-level coupling).

Why keep JSON loading inside SkipLoader (vs in ResultFactory)?
  - The "skip existing" logic is specific to v2's batch run flow, NOT
    to the FactorResult lifecycle. ResultFactory.from_cached_dict stays a
    pure dict→FactorResult converter; SkipLoader handles the file I/O
    and error tolerance (Bug 6: corrupt JSON should not crash the batch).
  - This keeps each helper's responsibility focused.

Bug 6 invariant: corrupt JSON files are skipped with a warning, not raised.
  - A single corrupt file must not abort the entire batch run.
  - The warning is logged via the standard `logging` module.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .result_factory import ResultFactory

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SkipLoader:
    """Load cached FactorResults from output_dir on resume.

    Two-step workflow:
      1. `scan()` returns the set of idx that have a cached file.
      2. `load(skip, factory)` reads each cached file and returns FactorResult list.

    Args:
        output_dir: Directory containing `single_factor_NNN.json` files.
        alpha_start: First alpha index (inclusive).
        alpha_end: Last alpha index (inclusive).
        skip_existing: If False, `scan()` returns empty set (skip logic disabled).
    """

    output_dir: Path
    alpha_start: int
    alpha_end: int
    skip_existing: bool = True

    def scan(self) -> set[int]:
        """Return set of alpha indices to skip (have cached results).

        Returns:
            Set of idx in [alpha_start, alpha_end] whose
            `single_factor_{idx:03d}.json` exists in output_dir.
            Empty set if `skip_existing` is False or output_dir missing.
        """
        if not self.skip_existing:
            return set()
        if not self.output_dir.exists():
            return set()
        try:
            with __import__("os").scandir(self.output_dir) as it:
                existing = {e.name for e in it if e.is_file()}
        except OSError as exc:
            logger.warning("[skip_loader] scandir %s failed: %s", self.output_dir, exc)
            return set()
        skip: set[int] = set()
        for idx in range(self.alpha_start, self.alpha_end + 1):
            if f"single_factor_{idx:03d}.json" in existing:
                skip.add(idx)
        return skip

    def load(
        self,
        skip: Iterable[int],
        factory: ResultFactory,
    ) -> list:
        """Load cached JSON for each skip idx → list of FactorResult.

        Corrupt JSON files are skipped with a warning (Bug 6 invariant).
        Uses `factory.from_cached_dict` (PR9a) to convert.

        Args:
            skip: Iterable of indices to load.
            factory: ResultFactory for dict→FactorResult conversion.

        Returns:
            List of FactorResult (in sorted order of idx). Skipped
            entries (corrupt JSON) are NOT in the list.
        """
        results: list = []
        for idx in sorted(skip):
            p = self.output_dir / f"single_factor_{idx:03d}.json"
            try:
                loaded: dict = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning(
                    "[skip_loader] skip-corrupt: alpha-%03d: %s", idx, exc,
                )
                continue
            results.append(factory.from_cached_dict(loaded, idx))
        return results
