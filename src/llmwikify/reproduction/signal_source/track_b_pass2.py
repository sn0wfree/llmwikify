"""TrackBPass2SignalSource — broker research reports (招商/浙商 style).

Reads:
  track_b_pass2.json schema:
    {
      "paper_id": "20180302-招商证券-A股涅槃论（捌）",
      "pass2_details": [
        {"name": "板块轮动周期表",
         "description": "基于信贷周期...",
         "l1": {"definition": "...", "formula": "Phase_State = ..."},
         "success": true, "error": null, ...},
        ...
      ]
    }

Yields Signal with:
  - id:   f"signal-{idx:03d}"          (e.g. "signal-001")
          Index-based because Chinese names produce empty slugs (CJK stripped
          by `generate_slug`). Consistent with TrackBSignalSource's index pattern.
  - name: pass2_detail["name"]        (Chinese or English)
  - formula_brief: pass2_detail["l1"]["formula"]
  - metadata: {paper_id, index, description, source: "track_b_pass2"}

Used for 招商证券 / 浙商证券 papers where:
  - Names are in Chinese
  - Formulas are enriched with L1 definitions
  - ~5-15 signals per paper (vs 101 in 101 alphas)
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .base import Signal


class TrackBPass2SignalSource:
    """Reads pass2_details from track_b_pass2.json (broker report style).

    Attributes:
        track_b_pass2_path: Path to track_b_pass2.json.
        paper_id: Paper identifier (auto-loaded from JSON if None).
    """

    def __init__(self, track_b_pass2_path: Path, paper_id: str | None = None) -> None:
        self._path: Path = track_b_pass2_path
        self._paper_id: str | None = paper_id

    @property
    def paper_id(self) -> str:
        if self._paper_id is not None:
            return self._paper_id
        try:
            data: dict = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"track_b_pass2.json not found: {self._path}"
            ) from exc
        return data.get("paper_id", self._path.parent.name)

    def iter_signals(self) -> Iterable[Signal]:
        """Yield one Signal per pass2_details entry (skipping failed)."""
        data: dict = json.loads(self._path.read_text(encoding="utf-8"))
        paper_id: str = self._paper_id or data.get("paper_id", self._path.parent.name)
        for idx, detail in enumerate(data.get("pass2_details", []), start=1):
            if not detail.get("success", True):
                continue
            l1: dict = detail.get("l1") or {}
            yield Signal(
                id=f"signal-{idx:03d}",
                name=detail.get("name", f"signal-{idx:03d}"),
                formula_brief=l1.get("formula", ""),
                metadata={
                    "index": idx,
                    "source": "track_b_pass2",
                    "paper_id": paper_id,
                    "description": detail.get("description", ""),
                    "definition": l1.get("definition", ""),
                    "l1": l1,
                    "l2": detail.get("l2"),
                    "l3": detail.get("l3"),
                    "l4": detail.get("l4"),
                },
            )

    def __repr__(self) -> str:
        return f"TrackBPass2SignalSource(track_b_pass2={self._path.name})"
