"""Persistent run-state store for dynamic workflows.

Stores one JSON file per run under
``~/.llmwikify/workflows/runs/{run_id}.json``. The schema is small
and human-readable so an operator can inspect or repair a run by
hand if needed.

This is **not** a transactional store. Writes are best-effort and
idempotent (overwriting the same JSON path). If you need stronger
guarantees, swap in a SQLite-backed implementation later — the
public API stays the same.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class RunState:
    """The complete persisted state of one workflow run."""

    run_id: str
    workflow_name: str
    source_path: str | None
    started_at: float
    status: str                          # "running" | "complete" | "failed" | "halted" | "partial"
    inputs_data: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    phases: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_tokens_used: int = 0
    total_agents_spawned: int = 0
    last_updated: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_json(cls, text: str) -> "RunState":
        d = json.loads(text)
        return cls(
            run_id=d["run_id"],
            workflow_name=d["workflow_name"],
            source_path=d.get("source_path"),
            started_at=float(d.get("started_at", 0.0)),
            status=d.get("status", "running"),
            inputs_data=d.get("inputs_data", {}),
            session_id=d.get("session_id", ""),
            phases=d.get("phases", {}),
            total_tokens_used=int(d.get("total_tokens_used", 0)),
            total_agents_spawned=int(d.get("total_agents_spawned", 0)),
            last_updated=float(d.get("last_updated", 0.0)),
        )


class RunStore:
    """File-backed store of ``RunState``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @classmethod
    def default(cls) -> "RunStore":
        return cls(Path(os.path.expanduser("~/.llmwikify/workflows/runs")))

    def save(self, state: RunState) -> Path:
        """Atomic write: write to temp file, then rename."""
        state.last_updated = time.time()
        target = self.root / f"{state.run_id}.json"
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=f".{state.run_id}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                f.write(state.to_json())
            os.replace(tmp_path, target)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return target

    def load(self, run_id: str) -> RunState | None:
        path = self.root / f"{run_id}.json"
        if not path.exists():
            return None
        try:
            return RunState.from_json(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("failed to load run state from %s: %s", path, e)
            return None

    def list_runs(
        self,
        *,
        workflow_name: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[RunState]:
        """List runs newest-first, optionally filtered."""
        out: list[RunState] = []
        for p in sorted(self.root.glob("wf_*.json"), reverse=True):
            state = self.load(p.stem)
            if state is None:
                continue
            if workflow_name and state.workflow_name != workflow_name:
                continue
            if status and state.status != status:
                continue
            out.append(state)
            if len(out) >= limit:
                break
        return out

    def delete(self, run_id: str) -> bool:
        path = self.root / f"{run_id}.json"
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False


__all__ = ["RunState", "RunStore"]
