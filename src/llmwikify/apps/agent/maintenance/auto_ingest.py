"""Track A: auto-ingest raw/ new files with direct LLM page write.

Event flow (thread-safe):

    watchdog Observer thread
        └─ FileSystemWatcher._handle_event("created", path)
            └─ on_event callback (still Observer thread!)
                └─ loop.call_soon_threadsafe(_enqueue)  → main asyncio loop
                    └─ debounce window → _process_file (to_thread)
                        ├─ wiki.ingest_source(path)          # extract + archive
                        ├─ wiki._llm_process_source(result)  # LLM ops (blocking)
                        └─ wiki.execute_operations(ops)      # write pages
                            └─ on failure → proposal fallback (content not lost)

Shutdown backlog (B1a): files dropped into raw/ while the server was
down produce no events, so ``start()`` scans raw/ against the persisted
processed-state file (``<wiki_root>/.llmwikify/maintenance/processed.json``)
and replays unprocessed files (capped by ``max_backlog_per_start``).

A file counts as processed only when its mtime+size match the recorded
values — a later modification re-queues it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any

from llmwikify.apps.agent.wiki_dream_editor import WikiDreamProposalManager
from llmwikify.kernel.storage.watcher import SUPPORTED_EXTENSIONS, FileSystemWatcher

from .config import AutoIngestConfig

logger = logging.getLogger(__name__)

_STATE_VERSION = 1


class AutoIngestService:
    """Per-wiki auto-ingest service (one FileSystemWatcher per wiki)."""

    def __init__(
        self,
        wiki: Any,
        wiki_id: str,
        config: AutoIngestConfig,
        llm_semaphore: asyncio.Semaphore,
        loop: asyncio.AbstractEventLoop | None = None,
        proposal_manager: WikiDreamProposalManager | None = None,
    ) -> None:
        self.wiki = wiki
        self.wiki_id = wiki_id
        self.config = config
        self.llm_semaphore = llm_semaphore
        self._loop = loop
        self._watcher: FileSystemWatcher | None = None
        self._proposal_manager = proposal_manager or WikiDreamProposalManager(
            wiki_id=wiki_id,
        )
        # path → (deadline, size_at_last_event); own debounce on top of
        # watchdog events because on_event fires BEFORE the watcher's
        # internal debounce timer.
        self._pending: dict[str, tuple[float, int]] = {}
        # filename → {mtime, size, processed_at}; persisted to disk so
        # the startup backlog scan can skip files handled before (and
        # detect modified-since-processed files).
        self._processed: dict[str, dict[str, Any]] = {}
        self._ingest_lock = asyncio.Lock()
        self.stats: dict[str, Any] = {
            "events": 0,
            "ingested": 0,
            "pages_written": 0,
            "failed": 0,
            "fallback_proposals": 0,
            "skipped": 0,
            "backlog_replayed": 0,
            "backlog_deferred": 0,
            "last_ingest_at": None,
            "last_error": None,
        }

    @property
    def raw_dir(self) -> Path:
        return Path(self.wiki.raw_dir)

    @property
    def _state_file(self) -> Path:
        root = getattr(self.wiki, "root", None)
        base = Path(root) if root else self.raw_dir.parent
        return base / ".llmwikify" / "maintenance" / "processed.json"

    async def start(self) -> bool:
        """Start watching raw/. Returns False if raw/ missing or watchdog absent."""
        raw = self.raw_dir
        if not raw.exists():
            logger.info("[%s] auto_ingest: raw/ not found at %s, skipped", self.wiki_id, raw)
            return False
        self._loop = self._loop or asyncio.get_running_loop()
        self._watcher = FileSystemWatcher(
            watch_dir=raw,
            auto_ingest=False,  # we consume via on_event, not the stub path
            debounce=self.config.debounce_seconds,
        )
        try:
            self._watcher.start(on_event=self._on_watch_event)
        except ImportError:
            logger.warning("[%s] auto_ingest: watchdog not installed, disabled", self.wiki_id)
            self._watcher = None
            return False
        logger.info("[%s] auto_ingest: watching %s", self.wiki_id, raw)
        self._load_processed()
        await self._scan_backlog()
        return True

    async def stop(self) -> None:
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

    # ── event path (Observer thread → main loop) ───────────────────────

    def _file_state(self, path: Path) -> dict[str, Any]:
        try:
            st = path.stat()
            return {"mtime": st.st_mtime, "size": st.st_size}
        except OSError:
            return {}

    def _is_processed(self, path: Path) -> bool:
        rec = self._processed.get(path.name)
        if rec is None:
            return False
        cur = self._file_state(path)
        # same mtime+size → unchanged since processing
        return bool(cur) and cur.get("mtime") == rec.get("mtime") and cur.get("size") == rec.get("size")

    def _mark_processed(self, path: Path) -> None:
        state = self._file_state(path)
        if not state:
            return
        self._processed[path.name] = {**state, "processed_at": time.time()}
        self._save_processed()

    def _load_processed(self) -> None:
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text(encoding="utf-8"))
                files = data.get("files", {}) if data.get("version") == _STATE_VERSION else {}
                if isinstance(files, dict):
                    self._processed = files
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "[%s] auto_ingest: processed state unreadable (%s), starting fresh",
                self.wiki_id, exc,
            )
            self._processed = {}

    def _save_processed(self) -> None:
        """Atomic write (tmp + rename) so a crash never corrupts state."""
        try:
            f = self._state_file
            f.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps({"version": _STATE_VERSION, "files": self._processed})
            fd, tmp = tempfile.mkstemp(dir=f.parent, suffix=".tmp")
            try:
                with open(fd, "w", encoding="utf-8") as fh:
                    fh.write(payload)
                Path(tmp).replace(f)
            finally:
                Path(tmp).unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("[%s] auto_ingest: processed state write failed: %s", self.wiki_id, exc)

    async def _scan_backlog(self) -> None:
        """Replay raw/ files that landed while the server was down."""
        limit = max(0, self.config.max_backlog_per_start)
        backlog: list[Path] = []
        deferred = 0
        try:
            for entry in sorted(self.raw_dir.iterdir()):
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                if self._is_processed(entry):
                    continue
                if len(backlog) < limit:
                    backlog.append(entry)
                else:
                    deferred += 1
        except OSError as exc:
            logger.warning("[%s] auto_ingest: backlog scan failed: %s", self.wiki_id, exc)
            return
        if backlog or deferred:
            logger.info(
                "[%s] auto_ingest: replaying %d backlog file(s)%s",
                self.wiki_id, len(backlog),
                f" ({deferred} deferred past max_backlog_per_start)" if deferred else "",
            )
        for path in backlog:
            self.stats["backlog_replayed"] += 1
            await self._process_file(path)
        if deferred:
            self.stats["backlog_deferred"] = deferred
            logger.warning(
                "[%s] auto_ingest: %d backlog file(s) beyond max_backlog_per_start=%d "
                "left for manual 'llmwikify batch raw/'",
                self.wiki_id, deferred, limit,
            )

    def _on_watch_event(self, event_type: str, path: Path) -> None:
        """watchdog Observer thread context — must not block or touch the loop."""
        self.stats["events"] += 1
        if event_type in ("deleted",):
            self._pending.pop(str(path), None)
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        if self._is_processed(path):
            return
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._schedule_debounce, event_type, path)

    def _schedule_debounce(self, event_type: str, path: Path) -> None:
        """Main loop context: (re)schedule processing after debounce window."""
        key = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            return
        deadline = time.monotonic() + self.config.debounce_seconds
        prev = self._pending.get(key)
        if prev is not None:
            # keep the LATER deadline if events keep arriving
            deadline = max(deadline, prev[0])
        self._pending[key] = (deadline, size)
        self._loop.call_later(self.config.debounce_seconds + 0.1, self._flush_pending)

    def _flush_pending(self) -> None:
        """Main loop context: dispatch files whose debounce window expired."""
        now = time.monotonic()
        due = [k for k, (dl, _s) in self._pending.items() if dl <= now]
        for key in due:
            deadline, size = self._pending.pop(key)
            path = Path(key)
            if self._is_processed(path):
                continue
            # file must have stopped growing within the window
            try:
                if path.stat().st_size != size:
                    self._pending[key] = (time.monotonic() + self.config.debounce_seconds, path.stat().st_size)
                    self._loop.call_later(self.config.debounce_seconds + 0.1, self._flush_pending)
                    continue
            except OSError:
                continue
            asyncio.get_running_loop().create_task(self._process_file(path))

    # ── ingest pipeline ────────────────────────────────────────────────

    async def _process_file(self, path: Path) -> None:
        async with self._ingest_lock:
            # re-check: a concurrent backlog replay + watcher event for the
            # same file both land here; whoever finishes first marks it.
            if self._is_processed(path):
                return
            try:
                result = await asyncio.to_thread(self.wiki.ingest_source, str(path))
            except Exception as exc:
                self.stats["failed"] += 1
                self.stats["last_error"] = f"ingest: {exc}"
                logger.warning("[%s] auto_ingest ingest failed %s: %s", self.wiki_id, path.name, exc)
                return
            self.stats["ingested"] += 1
            self.stats["last_ingest_at"] = time.time()

            if result.get("error"):
                self.stats["failed"] += 1
                self.stats["last_error"] = result["error"]
                return

            if self.config.write_mode == "proposal":
                await self._fallback_to_proposal(result, reason="write_mode=proposal")
                self._mark_processed(path)
                return

            await self._llm_write_pages(path, result)

    async def _llm_write_pages(self, path: Path, ingest_result: dict) -> None:
        """LLM page-writing chain (same as CLI --self-create / batch.py).

        Marks the file processed on every terminal outcome except a hard
        ingest-chain exception: success, no-ops, and fallback-to-proposal
        all count as "content settled" (re-processing would duplicate).
        """
        try:
            async with self.llm_semaphore:
                ops_result = await asyncio.to_thread(
                    self.wiki._llm_process_source, ingest_result,
                )
            ops = ops_result.get("operations", [])
            if not ops:
                self.stats["skipped"] += 1
                self._mark_processed(path)
                return
            exec_result = await asyncio.to_thread(self.wiki.execute_operations, ops)
            executed = exec_result.get("operations_executed", 0)
            self.stats["pages_written"] += executed
            self._mark_processed(path)
            logger.info(
                "[%s] auto_ingest wrote %d ops from %s",
                self.wiki_id, executed, path.name,
            )
        except Exception as exc:
            self.stats["last_error"] = f"llm_write: {exc}"
            logger.warning(
                "[%s] auto_ingest LLM write failed %s: %s — falling back to proposal",
                self.wiki_id, path.name, exc,
            )
            if self.config.fallback_to_proposal:
                await self._fallback_to_proposal(ingest_result, reason=f"llm_write failed: {exc}")
            self._mark_processed(path)

    async def _fallback_to_proposal(self, ingest_result: dict, reason: str) -> None:
        """Content is not lost: file stays archived in raw/, a proposal is queued."""
        try:
            title = ingest_result.get("title") or ingest_result.get("source_name") or "untitled"
            content = ingest_result.get("content", "")
            self._proposal_manager.create_proposal(
                page_name=title,
                edit_type="create",
                content=content,
                reason=f"auto_ingest fallback: {reason}",
                source_entries=[{"source_name": ingest_result.get("source_name", "")}],
            )
            self.stats["fallback_proposals"] += 1
        except Exception as exc:
            self.stats["failed"] += 1
            self.stats["last_error"] = f"proposal_fallback: {exc}"
            logger.warning("[%s] proposal fallback failed: %s", self.wiki_id, exc)

    def status(self) -> dict[str, Any]:
        return {
            "wiki_id": self.wiki_id,
            "watching": bool(self._watcher and self._watcher.is_running),
            "raw_dir": str(self.raw_dir),
            **self.stats,
        }
