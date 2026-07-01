"""AcademicPdfSignalSource — academic papers (1601_00991v3 style).

Reads:
  track_b_pass2.json (same schema as TrackBPass2SignalSource), but:
  - signal_id uses paper_id prefix: `{paper_id}_alpha-{idx:03d}`
    (e.g. "1601_00991v3_alpha-046") to namespace by paper, since multiple
    academic papers may use overlapping "Alpha#N" naming.
  - signal_id also preserves original "Alpha#N" in name field for traceability.

Yields Signal with:
  - id:   f"{paper_id}_alpha-{idx:03d}"
  - name: pass2_detail["name"]        (typically "Alpha#N")
  - formula_brief: pass2_detail["l1"]["formula"]
  - metadata: {paper_id, index, "alpha_index": N, source: "academic_pdf_pass2"}

Why a separate implementation from TrackBPass2SignalSource?
  - Naming convention differs (paper_id-prefixed to support multi-paper pipelines)
  - Tracks `alpha_index` separately from `index` (Alpha#46 → idx 46)
  - Suitable for academic papers that often have ambiguous English name slugs
    ("Alpha#1" is meaningless without paper context)
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from .base import Signal


class AcademicPdfSignalSource:
    """Reads pass2_details with paper_id-prefixed IDs (academic PDF style).

    Attributes:
        track_b_pass2_path: Path to track_b_pass2.json.
        paper_id: Paper identifier (required for ID prefixing; auto-loaded if None).
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
        """Yield one Signal per pass2_details entry with paper_id prefix."""
        data: dict = json.loads(self._path.read_text(encoding="utf-8"))
        paper_id: str = self._paper_id or data.get("paper_id", self._path.parent.name)
        for idx, detail in enumerate(data.get("pass2_details", []), start=1):
            if not detail.get("success", True):
                continue
            l1: dict = detail.get("l1") or {}
            # Extract alpha_index from "Alpha#46" → 46 (preserves naming convention)
            alpha_index: int | None = self._parse_alpha_index(detail.get("name", ""))
            yield Signal(
                id=f"{paper_id}_alpha-{idx:03d}",
                name=detail.get("name", f"Alpha#{idx}"),
                formula_brief=l1.get("formula", ""),
                metadata={
                    "index": idx,
                    "alpha_index": alpha_index,
                    "source": "academic_pdf_pass2",
                    "paper_id": paper_id,
                    "description": detail.get("description", ""),
                    "definition": l1.get("definition", ""),
                    "l1": l1,
                    "l2": detail.get("l2"),
                    "l3": detail.get("l3"),
                    "l4": detail.get("l4"),
                },
            )

    @staticmethod
    def _parse_alpha_index(name: str) -> int | None:
        """Parse "Alpha#46" → 46. Returns None if not matching the pattern."""
        import re
        match = re.match(r"^Alpha#(\d+)$", name)
        return int(match.group(1)) if match else None

    def __repr__(self) -> str:
        return f"AcademicPdfSignalSource(track_b_pass2={self._path.name}, paper_id={self._paper_id!r})"
