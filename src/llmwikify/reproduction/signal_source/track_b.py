"""TrackBSignalSource — 101-style papers (track_b_checkpoint.json with pass1_signals).

Reads:
  track_b_checkpoint.json schema:
    {
      "paper_id": "101_alphas_minimal",
      "pass1_signals": [
        {"index": 1, "name": "Alpha#1", "formula_brief": "rank(...)", "description": ""},
        ...
      ]
    }

Yields Signal with:
  - id:   f"alpha-{idx:03d}"           (e.g. "alpha-001")
  - name: signal["name"]               (e.g. "Alpha#1")
  - formula_brief: signal["formula_brief"]
  - metadata: {"index": idx, "source": "track_b_pass1"}

Replaces v2's `load_formula_brief(alpha_index, track_b_path)` which read the
same file but only returned one formula at a time by index.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .base import Signal


class TrackBSignalSource:
    """Reads pass1_signals from track_b_checkpoint.json (101 alphas style).

    Attributes:
        track_b_path: Path to track_b_checkpoint.json.
        paper_id: Paper identifier (used as metadata).
    """

    def __init__(self, track_b_path: Path, paper_id: str | None = None) -> None:
        self._path: Path = track_b_path
        self._paper_id: str | None = paper_id

    @property
    def paper_id(self) -> str:
        if self._paper_id is not None:
            return self._paper_id
        try:
            data: dict = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"track_b_checkpoint.json not found: {self._path}"
            ) from exc
        return data.get("paper_id", self._path.parent.name)

    def iter_signals(self) -> Iterable[Signal]:
        """Yield one Signal per pass1_signals entry."""
        data: dict = json.loads(self._path.read_text(encoding="utf-8"))
        paper_id: str = self._paper_id or data.get("paper_id", self._path.parent.name)
        for entry in data.get("pass1_signals", []):
            idx: int = entry["index"]
            yield Signal(
                id=f"alpha-{idx:03d}",
                name=entry.get("name", f"Alpha#{idx}"),
                formula_brief=entry.get("formula_brief", ""),
                metadata={
                    "index": idx,
                    "source": "track_b_pass1",
                    "paper_id": paper_id,
                    "description": entry.get("description", ""),
                },
            )

    def __repr__(self) -> str:
        return f"TrackBSignalSource(track_b={self._path.name})"
