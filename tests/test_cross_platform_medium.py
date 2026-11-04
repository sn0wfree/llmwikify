"""Cross-platform compatibility tests (medium priority).

Covers docs/designs/cross-platform-medium.md:
- _slugify guards Windows reserved device names
- _is_within respects the host filesystem's case sensitivity
- Grep falls back to a pure-Python scan when ripgrep is missing
- resolve_by_name falls back to a case-insensitive match
- git hook installs a Windows .bat variant too
- CLI output degrades to ASCII when the console can't encode emoji
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from llmwikify.apps.chat.skills.workflows.subagent_worker import (
    _grep_fallback,
    _handle_grep,
    _is_within,
)
from llmwikify.interfaces.cli._output import ICON_ERROR, ICON_SUCCESS, _emit
from llmwikify.kernel.storage.watcher import install_git_hook, uninstall_git_hook
from llmwikify.kernel.wiki import Wiki

# ─── _slugify: Windows reserved names ─────────────────────────────


class TestSlugifyWindowsNames:
    def test_plain_slug_unchanged(self):
        assert Wiki._slugify("Hello World") == "hello-world"

    @pytest.mark.parametrize("name", ["con", "CON", "prn", "aux", "nul"])
    def test_reserved_device_name_gets_suffix(self, name: str):
        # _slugify lowercases first
        assert Wiki._slugify(name) == f"{name.lower()}-"

    @pytest.mark.parametrize("name", ["com1", "COM9", "lpt1", "LPT9"])
    def test_reserved_device_name_with_digit(self, name: str):
        assert Wiki._slugify(name) == f"{name.lower()}-"

    def test_reserved_name_only_when_whole_stem(self):
        """'console' is a normal name — only exact device names are reserved."""
        assert Wiki._slugify("Console") == "console"

    def test_trailing_dot_removed(self):
        assert Wiki._slugify("report.") == "report"

    def test_trailing_space_removed(self):
        assert Wiki._slugify("report  ") == "report"

    def test_dot_is_stripped_so_extension_is_safe(self):
        # _slugify removes "." so "con.md" never becomes a reserved name
        assert Wiki._slugify("con.md") == "conmd"


# ─── _is_within ───────────────────────────────────────────────────


class TestIsWithin:
    def test_child_path_is_within(self, tmp_path: Path):
        child = tmp_path / "a" / "b.txt"
        child.parent.mkdir(parents=True)
        child.write_text("x", encoding="utf-8")
        assert _is_within(tmp_path, child)

    def test_root_itself_is_within(self, tmp_path: Path):
        assert _is_within(tmp_path, tmp_path)

    def test_sibling_is_outside(self, tmp_path: Path):
        other = tmp_path.parent / "other_dir"
        other.mkdir(exist_ok=True)
        assert not _is_within(tmp_path, other)

    def test_prefix_sibling_not_mistaken_for_child(self, tmp_path: Path):
        """'/tmp/root' must not match '/tmp/root_sibling'."""
        root = tmp_path / "root"
        root.mkdir()
        sibling = tmp_path / "root_sibling"
        sibling.mkdir()
        assert not _is_within(root, sibling)


# ─── Grep fallback ────────────────────────────────────────────────


class TestGrepFallback:
    def _worktree(self, tmp_path: Path) -> Path:
        wt = tmp_path / "wt"
        wt.mkdir()
        (wt / "a.py").write_text("import os\nprint('hello')\n", encoding="utf-8")
        (wt / "b.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
        return wt

    def test_fallback_finds_matches(self, tmp_path: Path):
        wt = self._worktree(tmp_path)
        result = _grep_fallback("import", wt, 50)
        assert result["match_count"] >= 1
        assert "import os" in result["matches"]

    def test_fallback_respects_max_results(self, tmp_path: Path):
        wt = self._worktree(tmp_path)
        result = _grep_fallback(".", wt, 1)
        assert result["match_count"] == 1
        assert result["truncated"] is True

    def test_fallback_invalid_pattern(self, tmp_path: Path):
        wt = self._worktree(tmp_path)
        result = _grep_fallback("[unclosed", wt, 50)
        assert "error" in result

    def test_handle_grep_without_rg_uses_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When ripgrep is missing, Grep still returns matches."""
        wt = self._worktree(tmp_path)

        def _boom(*a, **k):
            raise FileNotFoundError("rg")

        monkeypatch.setattr(
            "llmwikify.apps.chat.skills.workflows.subagent_worker.subprocess.run", _boom
        )
        result = _handle_grep("import", str(wt), max_results=10, worktree_path=str(wt))
        assert "matches" in result, result
        assert result["match_count"] >= 1


# ─── resolve_by_name case-insensitive fallback ────────────────────


class TestResolveByNameCaseInsensitive:
    def _index(self, tmp_path: Path):
        from llmwikify.kernel.storage.index import WikiIndex

        idx = WikiIndex(tmp_path / "index.db")
        idx.conn.execute(
            "INSERT INTO pages (page_name, file_path) VALUES (?, ?)",
            ("Concepts/Foo", "Concepts/Foo.md"),
        )
        idx.conn.commit()
        return idx

    def test_exact_match(self, tmp_path: Path):
        idx = self._index(tmp_path)
        try:
            assert idx.resolve_by_name("Concepts/Foo") == "Concepts/Foo.md"
        finally:
            idx.close()

    def test_case_insensitive_fallback(self, tmp_path: Path):
        idx = self._index(tmp_path)
        try:
            assert idx.resolve_by_name("concepts/foo") == "Concepts/Foo.md"
        finally:
            idx.close()

    def test_unknown_name_returns_none(self, tmp_path: Path):
        idx = self._index(tmp_path)
        try:
            assert idx.resolve_by_name("nope/none") is None
        finally:
            idx.close()


# ─── git hook Windows variant ────────────────────────────────────


class TestGitHookWindowsVariant:
    def test_install_writes_both_variants(self, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        assert install_git_hook(repo) is True
        hooks = repo / ".git" / "hooks"
        assert (hooks / "post-commit").exists()
        assert (hooks / "post-commit.bat").exists()
        bat = (hooks / "post-commit.bat").read_text(encoding="utf-8")
        assert "Auto-generated by llmwikify" in bat
        assert "llmwikify batch raw" in bat

    def test_uninstall_removes_both(self, tmp_path: Path):
        repo = tmp_path / "repo"
        (repo / ".git").mkdir(parents=True)
        install_git_hook(repo)
        assert uninstall_git_hook(repo) is True
        hooks = repo / ".git" / "hooks"
        assert not (hooks / "post-commit").exists()
        assert not (hooks / "post-commit.bat").exists()

    def test_uninstall_keeps_foreign_hook(self, tmp_path: Path):
        repo = tmp_path / "repo"
        hooks = repo / ".git" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "post-commit").write_text("# user hook\n", encoding="utf-8")
        assert uninstall_git_hook(repo) is False
        assert (hooks / "post-commit").exists()


# ─── CLI output ASCII degradation ─────────────────────────────────


class _AsciiStream(io.StringIO):
    """Stream that pretends it can only encode ASCII."""

    encoding = "ascii"


class _Utf8Stream(io.StringIO):
    """Stream that can encode everything."""

    encoding = "utf-8"


class TestCliOutputEncoding:
    def test_ascii_fallback_when_emoji_unencodable(self):
        buf = _AsciiStream()
        _emit(ICON_SUCCESS, "done", buf)
        out = buf.getvalue()
        assert "✅" not in out
        assert "[OK]" in out
        assert "done" in out

    def test_error_icon_fallback(self):
        buf = _AsciiStream()
        _emit(ICON_ERROR, "boom", buf)
        assert "[X]" in buf.getvalue()

    def test_emoji_kept_when_encodable(self):
        buf = _Utf8Stream()
        _emit(ICON_SUCCESS, "done", buf)
        assert "✅" in buf.getvalue()
