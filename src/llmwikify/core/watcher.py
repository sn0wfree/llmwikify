"""File system watcher for automatic source ingestion."""

import time
import threading
from pathlib import Path
from typing import Optional, Callable, Dict, Set


SUPPORTED_EXTENSIONS: Set[str] = {
    ".pdf", ".md", ".txt", ".html", ".htm",
    ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".svg",
    ".mp3", ".wav", ".m4a",
    ".csv", ".json", ".xml",
    ".epub", ".zip", ".msg",
    ".mp4", ".avi", ".mov",
}


class FileSystemWatcher:
    """Watch a directory for new files and optionally trigger ingest.

    Usage:
        watcher = FileSystemWatcher(
            watch_dir=Path("raw"),
            auto_ingest=False,      # default: just notify
            self_create=False,
            debounce=2.0,
        )
        watcher.start()
        ...
        watcher.stop()
    """

    def __init__(
        self,
        watch_dir: Path,
        auto_ingest: bool = False,
        self_create: bool = False,
        debounce: float = 2.0,
    ):
        self.watch_dir = watch_dir.resolve()
        self.auto_ingest = auto_ingest
        self.self_create = self_create
        self.debounce = debounce

        self._running = False
        self._observer: Optional[object] = None
        self._debounce_timers: Dict[str, threading.Timer] = {}
        self._event_count = 0
        self._ingest_count = 0
        self._on_event: Optional[Callable] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def stats(self) -> dict:
        return {
            "events": self._event_count,
            "ingests": self._ingest_count,
            "watch_dir": str(self.watch_dir),
        }

    def start(self, on_event: Optional[Callable] = None) -> None:
        """Start watching the directory.

        Args:
            on_event: Optional callback(event_type, path) for each event.
        """
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler
        except ImportError:
            raise ImportError(
                "watchdog package is required. "
                "Install with: pip install watchdog"
            )

        self._on_event = on_event
        self._running = True

        class _Handler(FileSystemEventHandler):
            def __init__(self, watcher):
                self.watcher = watcher

            def on_created(self, event):
                if not event.is_directory:
                    self.watcher._handle_event("created", event.src_path)

            def on_modified(self, event):
                if not event.is_directory:
                    self.watcher._handle_event("modified", event.src_path)

            def on_deleted(self, event):
                if not event.is_directory:
                    self.watcher._handle_event("deleted", event.src_path)

            def on_moved(self, event):
                if not event.is_directory:
                    self.watcher._handle_event("moved", event.dest_path)

        handler = _Handler(self)
        self._observer = Observer()
        self._observer.schedule(handler, str(self.watch_dir), recursive=False)
        self._observer.start()

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        # Cancel all pending debounce timers
        for timer in self._debounce_timers.values():
            timer.cancel()
        self._debounce_timers.clear()
        if self._observer:
            self._observer.stop()
            self._observer.join()
            self._observer = None

    def _handle_event(self, event_type: str, path_str: str) -> None:
        """Handle a file system event with debouncing."""
        path = Path(path_str)
        ext = path.suffix.lower()

        # Skip unsupported file types
        if ext not in SUPPORTED_EXTENSIONS:
            return

        self._event_count += 1

        if self._on_event:
            self._on_event(event_type, path)

        # Debounce: cancel existing timer for this path, set a new one
        if path_str in self._debounce_timers:
            self._debounce_timers[path_str].cancel()

        timer = threading.Timer(
            self.debounce,
            self._process_file,
            args=(event_type, path),
        )
        timer.daemon = True
        timer.start()
        self._debounce_timers[path_str] = timer

    def _process_file(self, event_type: str, path: Path) -> None:
        """Process a file after debounce period."""
        if not self._running:
            return

        if self.auto_ingest:
            # Auto-ingest mode: trigger ingest_source
            self._ingest_count += 1
        else:
            # Notify mode: just print
            action = {
                "created": "new file detected",
                "modified": "file modified",
                "deleted": "file deleted",
                "moved": "file moved in",
            }.get(event_type, "change detected")
            print(f"  [{event_type}] {path.name} - {action}")
            if self.self_create:
                print(f"    Tip: run 'llmwikify ingest {path.name} --self-create' to process with LLM")
            else:
                print(f"    Tip: run 'llmwikify ingest {path.name}' to process")
            print(f"    Or start with --auto-ingest to process automatically")

    def trigger_ingest(self, path: Path, wiki=None) -> Optional[dict]:
        """Manually trigger ingest for a specific file.

        Args:
            path: File path to ingest.
            wiki: Wiki instance for ingest_source call.

        Returns:
            Ingest result dict, or None if wiki not provided.
        """
        if wiki is None:
            return None

        self._ingest_count += 1
        try:
            return wiki.ingest_source(str(path))
        except (OSError, ValueError, RuntimeError) as e:
            return {"error": str(e)}


def install_git_hook(wiki_root: Path) -> bool:
    """Install a git post-commit hook that runs batch ingest.

    Args:
        wiki_root: Root directory of the wiki (should be a git repo).

    Returns:
        True if hook was installed, False if not a git repo.
    """
    git_dir = wiki_root / ".git"
    if not git_dir.exists():
        print(f"Not a git repository: {wiki_root}")
        return False

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)
    hook_path = hooks_dir / "post-commit"

    hook_content = """#!/bin/sh
# Auto-generated by llmwikify
# Rebuild knowledge graph after every commit
llmwikify batch raw/ 2>/dev/null || true
"""

    hook_path.write_text(hook_content)
    hook_path.chmod(0o755)
    print(f"Git post-commit hook installed at: {hook_path}")
    return True


def uninstall_git_hook(wiki_root: Path) -> bool:
    """Remove the git post-commit hook.

    Args:
        wiki_root: Root directory of the wiki.

    Returns:
        True if hook was removed, False if not found.
    """
    git_dir = wiki_root / ".git"
    if not git_dir.exists():
        print(f"Not a git repository: {wiki_root}")
        return False

    hook_path = git_dir / "hooks" / "post-commit"
    if hook_path.exists():
        content = hook_path.read_text()
        if "Auto-generated by llmwikify" in content:
            hook_path.unlink()
            print(f"Git post-commit hook removed: {hook_path}")
            return True
        else:
            print(f"Hook exists but was not created by llmwikify. Not removing.")
            return False
    else:
        print(f"No llmwikify git hook found at: {hook_path}")
        return False
