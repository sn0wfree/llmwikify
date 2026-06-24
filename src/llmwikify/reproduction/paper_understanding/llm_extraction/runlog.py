"""RunLogger + Checkpoint for paper-level structured logging & resume.

- RunLogger: appends JSONL events to ``run_log.jsonl`` per paper
- Checkpoint: tracks completion per stage for resume on crash

Files written to ``quant/papers/{paper_id}/``:
- ``run_log.jsonl`` — one JSON event per line
- ``checkpoint.json`` — single dict with stage_done flags
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ── Event ──────────────────────────────────────────────────


@dataclass
class RunEvent:
    """A single event in a paper's run log."""
    timestamp: float
    paper_id: str
    stage: str      # "stage0" | "stage1_call1" | "planner" | "track_a" | "track_b_pass1" | "track_b_pass2"
    event: str      # "start" | "llm_call" | "success" | "fail" | "retry" | "skip"
    latency_ms: int = 0
    detail: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ── RunLogger ──────────────────────────────────────────────


class RunLogger:
    """Append-only JSONL logger for one paper's run.

    Writes to ``{work_dir}/run_log.jsonl``. Safe to call from multiple
    stages of the same paper.
    """

    def __init__(self, work_dir: Path, paper_id: str):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.work_dir / "run_log.jsonl"
        self.paper_id = paper_id

    def log(
        self,
        stage: str,
        event: str,
        latency_ms: int = 0,
        detail: dict | None = None,
        error: str | None = None,
    ) -> None:
        ev = RunEvent(
            timestamp=time.time(),
            paper_id=self.paper_id,
            stage=stage,
            event=event,
            latency_ms=latency_ms,
            detail=detail or {},
            error=error,
        )
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ev.to_dict(), ensure_ascii=False) + "\n")

    def start_stage(self, stage: str) -> None:
        self.log(stage, "start")

    def llm_call(self, stage: str, latency_ms: int, **detail) -> None:
        self.log(stage, "llm_call", latency_ms=latency_ms, detail=detail)

    def success(self, stage: str, latency_ms: int, **detail) -> None:
        self.log(stage, "success", latency_ms=latency_ms, detail=detail)

    def fail(self, stage: str, error: str, latency_ms: int = 0) -> None:
        self.log(stage, "fail", latency_ms=latency_ms, error=error)

    def skip(self, stage: str, reason: str) -> None:
        self.log(stage, "skip", detail={"reason": reason})

    def read_all(self) -> list[dict]:
        """Read all events back (for debugging)."""
        if not self.log_path.exists():
            return []
        return [
            json.loads(line)
            for line in self.log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


# ── Checkpoint ─────────────────────────────────────────────


# Stages in execution order
STAGES = [
    "stage0",
    "stage1_call1",
    "stage1_call2",
    "track_a",
    "track_b_pass1",
    "track_b_pass2",
]


@dataclass
class Checkpoint:
    """Per-paper completion flags for resume."""
    paper_id: str
    status: str = "pending"  # pending | running | done | failed
    last_updated: float = 0.0
    error: str | None = None
    stages: dict = field(default_factory=dict)

    def __post_init__(self):
        # Initialize stage flags
        if not self.stages:
            self.stages = dict.fromkeys(STAGES, False)

    def mark(self, stage: str) -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage: {stage}")
        self.stages[stage] = True
        self.last_updated = time.time()

    def is_done(self, stage: str) -> bool:
        return self.stages.get(stage, False)

    def is_complete(self) -> bool:
        """All stages done (or skipped)."""
        return all(self.stages.values())

    def pending_stages(self) -> list[str]:
        return [s for s in STAGES if not self.stages.get(s, False)]

    def to_dict(self) -> dict:
        return asdict(self)


# ── I/O ────────────────────────────────────────────────────


def load_checkpoint(work_dir: Path) -> Checkpoint:
    """Load checkpoint from disk, or create fresh one."""
    work_dir = Path(work_dir)
    cp_path = work_dir / "checkpoint.json"
    paper_id = work_dir.name
    if cp_path.exists():
        try:
            data = json.loads(cp_path.read_text(encoding="utf-8"))
            cp = Checkpoint(
                paper_id=data.get("paper_id", paper_id),
                status=data.get("status", "pending"),
                last_updated=data.get("last_updated", 0.0),
                error=data.get("error"),
                stages=data.get("stages", {}),
            )
            # Ensure all known stages are present
            for s in STAGES:
                cp.stages.setdefault(s, False)
            return cp
        except json.JSONDecodeError as exc:
            logger.warning("[checkpoint] corrupted at %s: %s", cp_path, exc)
    return Checkpoint(paper_id=paper_id)


def save_checkpoint(cp: Checkpoint, work_dir: Path) -> None:
    """Save checkpoint to disk."""
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    cp_path = work_dir / "checkpoint.json"
    cp.last_updated = time.time()
    cp_path.write_text(
        json.dumps(cp.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.debug("[checkpoint] saved: %s", cp_path)


def make_run_logger(work_dir: Path) -> RunLogger:
    """Convenience constructor."""
    work_dir = Path(work_dir)
    return RunLogger(work_dir=work_dir, paper_id=work_dir.name)
