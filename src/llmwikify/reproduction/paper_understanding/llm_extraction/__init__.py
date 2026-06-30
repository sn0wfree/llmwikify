"""Adaptive paper extraction pipeline (Track A + Track B).

Replaces the legacy single-prompt extraction in ``extract_paper.py``.
Stage 0-4 pipeline: Ingest → Plan → Extract → Validate → Save.
"""

from ...common.llm_factory import build_default_client, load_llm_config
from .defer import DeferredItem, DeferredQueue
from .log_decorator import with_logging
from .orchestrator import run_one_paper
from .plan_saver import save_plan
from .planner import PlanResult, plan_paper
from .preview import generate_preview, write_preview
from .retry import DeferError, RetryConfig, with_retry
from .runlog import (
    STAGES,
    Checkpoint,
    RunEvent,
    RunLogger,
    load_checkpoint,
    make_run_logger,
    save_checkpoint,
)
from .section_detector import (
    Section,
    SectionDetectionResult,
    detect_sections,
)
from .stage0_ingest import Stage0Result, run_stage0_ingest
from .track_a import TrackAResult, run_track_a
from .track_b import (
    SignalDetail,
    SignalStub,
    TrackBResult,
    run_track_b,
)
from .validator import ValidationIssue, ValidationReport, validate_paper_outputs

__all__ = [
    "run_stage0_ingest",
    "Stage0Result",
    "detect_sections",
    "Section",
    "SectionDetectionResult",
    "plan_paper",
    "PlanResult",
    "save_plan",
    "run_track_a",
    "TrackAResult",
    "run_track_b",
    "TrackBResult",
    "SignalStub",
    "SignalDetail",
    "validate_paper_outputs",
    "ValidationReport",
    "ValidationIssue",
    "generate_preview",
    "write_preview",
    "Checkpoint",
    "RunEvent",
    "RunLogger",
    "STAGES",
    "load_checkpoint",
    "save_checkpoint",
    "make_run_logger",
    "with_logging",
    "with_retry",
    "RetryConfig",
    "DeferError",
    "DeferredItem",
    "DeferredQueue",
    "run_one_paper",
    "build_default_client",
    "load_llm_config",
]
