"""Signal dataclass + SignalSource protocol.

A `Signal` is one extracted formula/factor from a paper. The fields are the
minimum required by downstream stages (codegen + backtest + sink):
  - `id`: unique, filesystem-safe (used as filename component)
  - `name`: human-readable
  - `formula_brief`: math description (input to LLM)
  - `metadata`: optional free-form extra info (paper section, confidence, etc.)

`SignalSource` is a Protocol so any class with `iter_signals()` matches.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class Signal:
    """One extracted formula/factor from a paper.

    Attributes:
        id: Unique, filesystem-safe identifier. Convention: `{paper_id}_{slug}`
            or `{paper_id}_alpha-{idx:03d}` depending on paper type.
        name: Human-readable name (e.g. "Alpha#1" or "板块轮动周期表").
        formula_brief: Math description / formula expression. Sent to LLM.
        metadata: Free-form extra info (paper section, pass1 vs pass2, etc.).
    """

    id: str
    name: str
    formula_brief: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SignalSource(Protocol):
    """Protocol that yields Signals from a paper directory."""

    def iter_signals(self) -> Iterable[Signal]: ...
