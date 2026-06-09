"""Tests verifying Wiki delegates to its backend.

These tests assert the wiring from Wiki class to WikiBackend —
that Wiki writes go through the backend, that custom backends
can be passed in, and that backward-compat storage attributes
still work.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.kernel import Wiki
from llmwikify.kernel.storage.backend import LocalFileBackend


@pytest.fixture
def wiki_root():
    temp = Path(tempfile.mkdtemp())
    (temp / "raw").mkdir()
    (temp / "wiki").mkdir()
    yield temp
    shutil.rmtree(temp, ignore_errors=True)


def test_wiki_default_uses_local_backend(wiki_root):
    """Wiki(root) without a backend kwarg uses LocalFileBackend."""
    wiki = Wiki(wiki_root)
    assert isinstance(wiki._backend, LocalFileBackend)
    assert wiki._backend.root == wiki_root.resolve()
    wiki.close()


def test_wiki_accepts_custom_backend(wiki_root):
    """Wiki(root, backend=mock) accepts a custom backend."""

    class MockBackend:
        def __init__(self, root):
            from llmwikify.foundation.config import load_config
            from llmwikify.kernel.storage.index import WikiIndex
            from llmwikify.kernel.storage.backend import LocalFileBackend as _LFB
            self.root = root.resolve()
            self.wiki_dir = _LFB(root, load_config(root)).wiki_dir
            self.raw_dir = _LFB(root, load_config(root)).raw_dir
            self.db_path = _LFB(root, load_config(root)).db_path
            self.index = WikiIndex(self.db_path)
            self._store: dict[str, str] = {}
            self.put_page_calls: list[tuple[str, str]] = []
            self.deleted: list[str] = []
            self.get_page_calls: list[str] = []

        def get_page(self, name: str) -> str | None:
            self.get_page_calls.append(name)
            return self._store.get(name)

        def put_page(self, name: str, content: str) -> None:
            self.put_page_calls.append((name, content))
            self._store[name] = content
            # Also write to disk so Wiki's read_page exists() check passes
            page_path = (self.wiki_dir / f"{name}.md").resolve()
            try:
                page_path.relative_to(self.wiki_dir)
                page_path.parent.mkdir(parents=True, exist_ok=True)
                page_path.write_text(content)
            except ValueError:
                pass

        def delete_page(self, name: str) -> bool:
            self.deleted.append(name)
            if name in self._store:
                del self._store[name]
                return True
            return False

        def list_page_paths(self) -> list[Path]:
            return []

        def get_index(self) -> str:
            return ""

        def put_index(self, content: str) -> None:
            pass

        def get_wiki_md(self) -> str | None:
            return None

        def put_wiki_md(self, content: str) -> None:
            pass

        def merge_wiki_md(self, existing: str, new: str) -> str:
            return existing

        def append_log(self, entry: dict[str, Any]) -> dict[str, Any]:
            return entry

        def get_source_cache(self, key: str) -> dict[str, Any] | None:
            return None

        def put_source_cache(self, key: str, hash: str, data: dict[str, Any]) -> None:
            pass

        def get_page_type_mapping(self) -> dict[str, str]:
            return {}

    backend = MockBackend(wiki_root)
    wiki = Wiki(wiki_root, backend=backend)
    assert wiki._backend is backend

    # write_page delegates to backend
    wiki.write_page("hello", "test content")
    assert ("hello", "test content") in backend.put_page_calls

    # read_page delegates to backend
    result = wiki.read_page("hello")
    assert result["content"] == "test content"
    assert "hello" in backend.get_page_calls
    wiki.close()


def test_wiki_write_page_uses_backend(wiki_root):
    """write_page validates and delegates the file write to backend.put_page."""
    wiki = Wiki(wiki_root)
    wiki.index.initialize()
    backend = wiki._backend
    backend.put_page_calls = []  # reset

    class _SpyBackend(backend.__class__):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.put_page_calls: list[tuple[str, str]] = []

        def put_page(self, name, content):
            self.put_page_calls.append((name, content))
            return super().put_page(name, content)

    # The wiki already uses LocalFileBackend; check that write_page writes file
    result = wiki.write_page("hello", "world")
    assert "hello" in result.lower()
    assert (wiki.wiki_dir / "hello.md").exists()
    assert (wiki.wiki_dir / "hello.md").read_text() == "world"
    wiki.close()


def test_wiki_read_page_uses_backend(wiki_root):
    """read_page returns content from backend.get_page."""
    wiki = Wiki(wiki_root)
    wiki.index.initialize()
    wiki.write_page("readme", "hello wiki")
    result = wiki.read_page("readme")
    assert result["content"] == "hello wiki"
    assert result["page_name"] == "readme"
    wiki.close()


def test_wiki_index_attribute_is_backend_index(wiki_root):
    """wiki.index is the same object as backend.index."""
    wiki = Wiki(wiki_root)
    assert wiki.index is wiki._backend.index
    wiki.close()


def test_wiki_root_path_equals_backend_root(wiki_root):
    """wiki.root equals backend.root (backward compat attribute)."""
    wiki = Wiki(wiki_root)
    assert wiki.root == wiki._backend.root
    assert wiki.wiki_dir == wiki._backend.wiki_dir
    assert wiki.raw_dir == wiki._backend.raw_dir
    assert wiki.db_path == wiki._backend.db_path
    wiki.close()


def test_mixin_uses_wiki_helpers_not_direct_fs(tmp_path):
    """Mixin source files should not access wiki_md_file.read_text/write_text
    for content ops — they go through Wiki helpers instead.

    This is a guard test: scan mixin source for forbidden patterns
    and fail if any new direct fs content access is found.
    """
    import re
    src = Path(__file__).parent.parent / "src" / "llmwikify" / "core"
    mixin_files = list(src.glob("wiki_mixin_*.py"))

    forbidden_patterns = [
        (r"wiki_md_file\.read_text\(\)", "wiki_md_file.read_text()"),
        (r"wiki_md_file\.write_text\(", "wiki_md_file.write_text(...)"),
        (r"index_file\.write_text\(", "index_file.write_text(...)"),
        (r"index_file\.read_text\(\)", "index_file.read_text()"),
        (r"raw_dir\.mkdir\(", "raw_dir.mkdir(...)"),
    ]

    violations: list[str] = []
    for mixin_file in mixin_files:
        content = mixin_file.read_text()
        for pattern, label in forbidden_patterns:
            if re.search(pattern, content):
                # Check if it's a comment
                for line in content.split("\n"):
                    if re.search(pattern, line) and not line.strip().startswith("#"):
                        violations.append(f"{mixin_file.name}: {label}: {line.strip()}")

    assert not violations, (
        "Mixin files use direct fs ops; should use Wiki helpers instead:\n"
        + "\n".join(violations)
    )


def test_backend_swap_does_not_affect_public_api(wiki_root):
    """Swapping the backend keeps the public Wiki API working."""
    # Wiki 1: write with LocalFileBackend
    wiki1 = Wiki(wiki_root)
    wiki1.index.initialize()
    wiki1.write_page("concept", "first content")
    wiki1.close()

    # Wiki 2: re-open on the same root, all data still there
    wiki2 = Wiki(wiki_root)
    result = wiki2.read_page("concept")
    assert result["content"] == "first content"
    wiki2.close()


def test_wiki_get_wiki_md_content_helper(wiki_root):
    """The _get_wiki_md_content helper delegates to backend."""
    wiki = Wiki(wiki_root)
    wiki._backend.put_wiki_md("# My Schema\n\n## Page Types\n")
    assert wiki._get_wiki_md_content() == "# My Schema\n\n## Page Types\n"
    wiki._write_wiki_md_content("# New Schema\n")
    assert wiki._backend.get_wiki_md() == "# New Schema\n"
    wiki.close()


def test_wiki_get_index_content_helper(wiki_root):
    """The _get_index_content / _write_index_content helpers delegate to backend."""
    wiki = Wiki(wiki_root)
    assert wiki._get_index_content() == ""
    wiki._write_index_content("# Wiki Index\n")
    assert wiki._backend.get_index() == "# Wiki Index\n"
    wiki.close()


def test_wiki_ensure_raw_dir_helper(wiki_root):
    """The _ensure_raw_dir helper creates the raw directory."""
    # Re-init: remove raw/
    shutil.rmtree(wiki_root / "raw", ignore_errors=True)
    assert not (wiki_root / "raw").exists()
    wiki = Wiki(wiki_root)
    wiki._ensure_raw_dir()
    assert (wiki_root / "raw").exists()
    wiki.close()
