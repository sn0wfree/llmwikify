"""Tests for the storage port and the ratchet that guards it.

The wiki layer stores its pages through ``WikiBackend``. This test pins
the primitives the port gained (the generic file operations and the
page-level extras) and the architecture rule that keeps the content I/O
from going around the port again.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from llmwikify.kernel.storage.backend import LocalFileBackend, WikiBackend

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_architecture.py"


@pytest.fixture
def backend(tmp_path: Path) -> LocalFileBackend:
    (tmp_path / "raw").mkdir()
    (tmp_path / "wiki").mkdir()
    return LocalFileBackend(tmp_path)


# ── the protocol ───────────────────────────────────────────────────


def test_the_backend_satisfies_the_protocol(backend: LocalFileBackend) -> None:
    """The shipped backend implements every primitive of the port."""
    assert isinstance(backend, WikiBackend)


def test_every_primitive_is_declared() -> None:
    """A primitive used by the mixins must be part of the protocol."""
    for name in (
        "page_exists",
        "list_page_names",
        "read_file",
        "write_file",
        "delete_file",
        "file_exists",
        "list_files",
        "ensure_dir",
        "dir_exists",
        "list_dirs",
    ):
        assert name in WikiBackend.__dict__, f"{name} is missing from the protocol"


# ── the generic file primitives ────────────────────────────────────


def test_write_and_read_a_file(backend: LocalFileBackend) -> None:
    backend.write_file("raw/report.md", "hello")
    assert backend.read_file("raw/report.md") == "hello"


def test_read_a_missing_file_returns_none(backend: LocalFileBackend) -> None:
    assert backend.read_file("raw/nope.md") is None


def test_write_creates_the_parent_directory(backend: LocalFileBackend) -> None:
    backend.write_file("raw/deep/nested/file.md", "x")
    assert (backend.root / "raw" / "deep" / "nested" / "file.md").exists()


def test_file_exists(backend: LocalFileBackend) -> None:
    backend.write_file("wiki/a.md", "x")
    assert backend.file_exists("wiki/a.md") is True
    assert backend.file_exists("wiki/b.md") is False


def test_delete_a_file(backend: LocalFileBackend) -> None:
    backend.write_file("wiki/a.md", "x")
    assert backend.delete_file("wiki/a.md") is True
    assert backend.delete_file("wiki/a.md") is False
    assert backend.file_exists("wiki/a.md") is False


def test_list_files(backend: LocalFileBackend) -> None:
    backend.write_file("raw/a.md", "x")
    backend.write_file("raw/b.md", "x")
    backend.write_file("wiki/c.md", "x")
    assert backend.list_files("raw") == ["raw/a.md", "raw/b.md"]
    assert "wiki/c.md" in backend.list_files()


def test_list_files_of_a_missing_directory(backend: LocalFileBackend) -> None:
    assert backend.list_files("nope") == []


def test_ensure_dir(backend: LocalFileBackend) -> None:
    backend.ensure_dir("raw/deep")
    assert (backend.root / "raw" / "deep").is_dir()


def test_dir_exists(backend: LocalFileBackend) -> None:
    assert backend.dir_exists("raw") is True
    assert backend.dir_exists("nope") is False


def test_list_dirs(backend: LocalFileBackend) -> None:
    backend.ensure_dir("raw/deep")
    backend.ensure_dir("wiki/concepts")
    dirs = backend.list_dirs("wiki")
    assert "wiki/concepts" in dirs
    assert "wiki/raw" not in dirs


def test_a_path_may_not_escape_the_root(backend: LocalFileBackend) -> None:
    """The logical path is confined to the wiki root."""
    with pytest.raises(ValueError):
        backend.read_file("../outside.md")
    with pytest.raises(ValueError):
        backend.write_file("../outside.md", "x")


# ── the page-level extras ──────────────────────────────────────────


def test_page_exists(backend: LocalFileBackend) -> None:
    backend.put_page("concepts/Risk Parity", "content")
    assert backend.page_exists("concepts/Risk Parity") is True
    assert backend.page_exists("concepts/Nope") is False


def test_list_page_names(backend: LocalFileBackend) -> None:
    backend.put_page("concepts/A", "a")
    backend.put_page("sources/B", "b")
    names = backend.list_page_names()
    assert "concepts/A.md" in names
    assert "sources/B.md" in names


def test_list_page_names_of_an_empty_wiki(backend: LocalFileBackend) -> None:
    assert backend.list_page_names() == []


# ── the architecture rule ──────────────────────────────────────────


def _load_script():
    spec = importlib.util.spec_from_file_location("check_architecture_port", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_architecture_port"] = module
    spec.loader.exec_module(module)
    return module


def test_the_current_tree_has_no_port_violation() -> None:
    """The committed tree routes its content I/O through the port."""
    mod = _load_script()
    assert mod.check_storage_port() == []


def test_a_direct_content_call_is_reported() -> None:
    """A content operation outside the port is a violation."""
    mod = _load_script()
    src = mod.SRC / "kernel" / "wiki" / "mixins" / "io" / "page_io.py"
    original = src.read_text(encoding="utf-8")
    try:
        src.write_text(
            original
            + "\n\ndef _bypass(path):\n    return path.read_text(encoding='utf-8')\n",
            encoding="utf-8",
        )
        violations = mod.check_storage_port()
        assert violations
        assert any("bypasses the storage port" in v for v in violations)
    finally:
        src.write_text(original, encoding="utf-8")


def test_the_allowlist_may_only_get_shorter() -> None:
    """A module that no longer needs the exemption is reported.

    That is what makes the rule a ratchet: the list of modules that
    may still bypass the port cannot silently grow, and an entry that
    has become unnecessary is caught.
    """
    mod = _load_script()
    original = mod._STORAGE_PORT_PENDING
    try:
        # ``protocols.py`` exists and does no content I/O — it must be
        # reported as an unnecessary exemption.
        mod._STORAGE_PORT_PENDING = frozenset(
            set(original) | {"kernel/wiki/protocols.py"}
        )
        violations = mod.check_storage_port()
        assert any("remove it from" in v for v in violations)
    finally:
        mod._STORAGE_PORT_PENDING = original
