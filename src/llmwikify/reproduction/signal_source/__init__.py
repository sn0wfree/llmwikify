"""Signal extraction abstraction — paper-format agnostic.

Public API:
  - Signal: one formula/factor extracted from a paper (id, name, formula_brief, metadata)
  - SignalSource: protocol that enumerates Signals from a paper directory

Concrete implementations (see separate modules):
  - TrackBSignalSource: 101-style papers (track_b_checkpoint.json with pass1_signals)
  - TrackBPass2SignalSource: broker reports (track_b_pass2.json, Chinese names)
  - AcademicPdfSignalSource: academic papers (track_b_pass2.json, English names + paper_id prefix)

Each implementation reads a different file format but yields a uniform `Signal`
stream. The rest of the pipeline (`PaperPipeline`, `BacktestEngine`, `Sink`) is
format-agnostic.

Usage:
    from llmwikify.reproduction.signal_source import TrackBSignalSource
    src = TrackBSignalSource(Path("quant/papers/101_alphas_minimal/track_b_checkpoint.json"))
    for signal in src.iter_signals():
        print(signal.id, signal.name)
"""
from __future__ import annotations

from .academic_pdf import AcademicPdfSignalSource
from .base import Signal, SignalSource
from .track_b import TrackBSignalSource
from .track_b_pass2 import TrackBPass2SignalSource

__all__ = [
    "Signal",
    "SignalSource",
    "TrackBSignalSource",
    "TrackBPass2SignalSource",
    "AcademicPdfSignalSource",
]
