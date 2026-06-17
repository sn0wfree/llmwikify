"""Deferred queue for L1-exhausted stages (Layer 2 of 3-layer retry).

When ``with_retry`` exhausts its attempts, it raises ``DeferError``. The
caller can catch it and add the failed stage to a ``DeferredQueue``. The
queue is flushed at the end of a paper run (or any time the caller wants
to re-attempt).

Persistence:
  - Saves metadata (stage + reason + timestamp) to ``{work_dir}/deferred.json``
  - Does NOT serialize the callable / args (they live only in the current
    process). On next process start, the queue is empty but the metadata
    file is preserved for inspection.
"""
from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DeferredItem:
    """One stage to retry. ``fn`` is the function that failed."""
    stage: str
    reason: str
    added_at: float
    fn: Callable | None = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)


class DeferredQueue:
    """In-memory queue flushed at the end of a paper run.

    Usage::

        q = DeferredQueue(work_dir)
        try:
            run_stage(...)
        except DeferError as exc:
            q.add("stage_name", run_stage, (paper_id, ...), {}, reason=str(exc))
        # later:
        resolved, errors = q.flush()
        q.save_metadata()
    """

    def __init__(self, work_dir: Path):
        self.work_dir = Path(work_dir)
        self.path = self.work_dir / "deferred.json"
        self.items: list[DeferredItem] = []

    def add(
        self,
        stage: str,
        fn: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        reason: str = "",
    ) -> None:
        self.items.append(DeferredItem(
            stage=stage,
            reason=reason,
            added_at=time.time(),
            fn=fn,
            args=args,
            kwargs=kwargs or {},
        ))

    def flush(self) -> tuple[int, list[Exception]]:
        """Re-run queued items once.

        For each item, call ``fn(*args, **kwargs)``. The item is removed
        from the queue regardless of outcome (we do NOT re-queue failures
        to avoid infinite loops; caller decides whether to re-defer).

        Returns:
            (resolved_count, list_of_exceptions_for_items_that_still_fail)
        """
        resolved = 0
        errors: list[Exception] = []
        remaining: list[DeferredItem] = []
        for item in list(self.items):
            if item.fn is None:
                # Loaded from disk metadata only; cannot re-run.
                # Keep it for inspection, don't remove.
                remaining.append(item)
                continue
            try:
                item.fn(*item.args, **item.kwargs)
            except Exception as exc:
                errors.append(exc)
                logger.warning(
                    "[defer] stage=%s still failing on flush: %s", item.stage, exc,
                )
                continue
            resolved += 1
            logger.info(
                "[defer] stage=%s resolved on flush", item.stage,
            )
        # Items that succeeded or were no-fn metadata are removed.
        # Items that failed are also removed (not re-queued).
        self.items = remaining
        return resolved, errors

    def save_metadata(self) -> None:
        """Persist stage + reason + timestamp to disk (not the callables)."""
        data = [
            {
                "stage": i.stage,
                "reason": i.reason,
                "added_at": i.added_at,
            }
            for i in self.items
        ]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def __len__(self) -> int:
        return len(self.items)

    def __bool__(self) -> bool:
        return bool(self.items)

    def __iter__(self):
        return iter(self.items)

    def clear(self) -> None:
        self.items.clear()
