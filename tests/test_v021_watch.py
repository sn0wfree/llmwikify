"""Tests for v0.21.0 Watch mode."""

import pytest
import sys
import time
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core.watcher import (
    FileSystemWatcher,
    install_git_hook,
    uninstall_git_hook,
    SUPPORTED_EXTENSIONS,
)


class TestSupportedExtensions:
    def test_common_extensions(self):
        assert ".pdf" in SUPPORTED_EXTENSIONS
        assert ".md" in SUPPORTED_EXTENSIONS
        assert ".txt" in SUPPORTED_EXTENSIONS
        assert ".docx" in SUPPORTED_EXTENSIONS
        assert ".xlsx" in SUPPORTED_EXTENSIONS
        assert ".jpg" in SUPPORTED_EXTENSIONS
        assert ".mp3" in SUPPORTED_EXTENSIONS
        assert ".html" in SUPPORTED_EXTENSIONS

    def test_unsupported_extension(self):
        assert ".exe" not in SUPPORTED_EXTENSIONS
        assert ".bin" not in SUPPORTED_EXTENSIONS


class TestFileSystemWatcher:
    @pytest.fixture
    def watch_dir(self, tmp_path):
        d = tmp_path / "raw"
        d.mkdir()
        return d

    def test_watcher_init(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        assert watcher.watch_dir == watch_dir.resolve()
        assert watcher.auto_ingest is False
        assert watcher.self_create is False
        assert watcher.debounce == 2.0
        assert watcher.is_running is False

    def test_watcher_with_options(self, watch_dir):
        watcher = FileSystemWatcher(
            watch_dir, auto_ingest=True, self_create=True, debounce=5.0
        )
        assert watcher.auto_ingest is True
        assert watcher.self_create is True
        assert watcher.debounce == 5.0

    def test_stats_initial(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        stats = watcher.stats
        assert stats["events"] == 0
        assert stats["ingests"] == 0
        assert "watch_dir" in stats

    def test_start_stop_without_watchdog(self, watch_dir):
        """Should raise ImportError if watchdog not installed."""
        watcher = FileSystemWatcher(watch_dir)
        with patch.dict(sys.modules, {"watchdog.observers": None}):
            with pytest.raises(ImportError, match="watchdog package is required"):
                watcher.start()

    def test_unsupported_file_type_ignored(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        watcher._handle_event("created", str(watch_dir / "test.exe"))
        assert watcher._event_count == 0

    def test_supported_file_type_counted(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        watcher._handle_event("created", str(watch_dir / "test.pdf"))
        assert watcher._event_count == 1

    def test_notify_mode_prints_hint(self, watch_dir, capsys):
        watcher = FileSystemWatcher(watch_dir, debounce=0.1)
        watcher._running = True
        watcher._handle_event("created", str(watch_dir / "test.pdf"))
        time.sleep(0.3)
        captured = capsys.readouterr()
        assert "new file detected" in captured.out

    def test_auto_ingest_increments_counter(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir, auto_ingest=True, debounce=0.1)
        watcher._running = True
        watcher._handle_event("created", str(watch_dir / "test.pdf"))
        time.sleep(0.3)
        assert watcher._ingest_count >= 1

    def test_dry_run_does_nothing(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        # dry_run is handled by CLI, watcher itself just processes
        assert watcher.is_running is False

    def test_stop_cancels_timers(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir, debounce=1.0)
        watcher._running = True
        watcher._handle_event("created", str(watch_dir / "test.pdf"))
        assert len(watcher._debounce_timers) > 0
        watcher.stop()
        assert len(watcher._debounce_timers) == 0

    def test_on_event_callback(self, watch_dir):
        events = []
        def on_event(event_type, path):
            events.append((event_type, path.name))

        watcher = FileSystemWatcher(watch_dir, debounce=0.1)
        watcher._on_event = on_event
        watcher._handle_event("created", str(watch_dir / "test.pdf"))
        time.sleep(0.05)
        assert len(events) == 1
        assert events[0][0] == "created"
        assert events[0][1] == "test.pdf"

    def test_multiple_files_debounced(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir, debounce=0.2)
        watcher._running = True
        # Rapid fire
        for i in range(5):
            watcher._handle_event("created", str(watch_dir / f"test{i}.pdf"))
        # Wait for debounce
        time.sleep(0.5)
        assert watcher._event_count == 5

    def test_trigger_ingest_without_wiki(self, watch_dir):
        watcher = FileSystemWatcher(watch_dir)
        result = watcher.trigger_ingest(Path("test.pdf"))
        assert result is None

    def test_modified_event(self, watch_dir, capsys):
        watcher = FileSystemWatcher(watch_dir, debounce=0.1)
        watcher._running = True
        watcher._handle_event("modified", str(watch_dir / "test.md"))
        time.sleep(0.3)
        captured = capsys.readouterr()
        assert "file modified" in captured.out

    def test_deleted_event(self, watch_dir, capsys):
        watcher = FileSystemWatcher(watch_dir, debounce=0.1)
        watcher._running = True
        watcher._handle_event("deleted", str(watch_dir / "test.md"))
        time.sleep(0.3)
        captured = capsys.readouterr()
        assert "file deleted" in captured.out


class TestGitHook:
    @pytest.fixture
    def git_dir(self, tmp_path):
        git = tmp_path / ".git" / "hooks"
        git.mkdir(parents=True)
        return git.parent.parent

    def test_install_git_hook(self, git_dir):
        result = install_git_hook(git_dir)
        assert result is True
        hook = git_dir / ".git" / "hooks" / "post-commit"
        assert hook.exists()
        assert "Auto-generated by llmwikify" in hook.read_text()

    def test_uninstall_git_hook(self, git_dir):
        install_git_hook(git_dir)
        result = uninstall_git_hook(git_dir)
        assert result is True
        hook = git_dir / ".git" / "hooks" / "post-commit"
        assert not hook.exists()

    def test_uninstall_nonexistent_hook(self, git_dir):
        result = uninstall_git_hook(git_dir)
        assert result is False

    def test_install_not_git_repo(self, tmp_path):
        result = install_git_hook(tmp_path / "notgit")
        assert result is False

    def test_uninstall_not_git_repo(self, tmp_path):
        result = uninstall_git_hook(tmp_path / "notgit")
        assert result is False

    def test_uninstall_foreign_hook(self, git_dir):
        hook = git_dir / ".git" / "hooks" / "post-commit"
        hook.write_text("#!/bin/sh\n# Some other hook\n")
        result = uninstall_git_hook(git_dir)
        assert result is False
        assert hook.exists()  # Should not be removed
