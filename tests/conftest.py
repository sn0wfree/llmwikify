"""Pytest configuration and fixtures for llmwikify.py tests."""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llmwikify.foundation.extractors import ExtractedContent
from llmwikify.kernel import Wiki

# 2026-10-15: test_llm_comparison.py 是人工实验脚本（无 test 函数;
# module 级 mkdir 硬编码 /home/ll 本机路径）——CI collection 阶段
# PermissionError 直接崩掉整个 Tests 门禁。排除收集; 手动运行不受影响:
#   python tests/test_llm_comparison.py
collect_ignore = ["test_llm_comparison.py"]


# Phase 19-D (2026-06-22): redirect all chat/agent DB writes to a
# per-session tmp dir so test runs no longer pollute the production
# ``~/.llmwikify/agent/.llmwiki_agent.db``. Previously tests relied
# on ``monkeypatch.setenv("HOME", ...)``, which ``Path.home()``
# ignores on Linux (it consults /etc/passwd, not $HOME).
#
# The autouse=True + scope="session" fixture sets LLMWIKIFY_DATA_DIR
# once for the whole test run, before any test imports
# ``llmwikify.interfaces.server.http.routes``. Tests that need a
# specific data dir can still ``monkeypatch.setenv`` it locally.
@pytest.fixture(autouse=True, scope="session")
def _isolate_llmwikify_data_dir() -> str:
    import os

    tmp_root = Path(tempfile.mkdtemp(prefix="llmwikify_test_data_"))
    os.environ["LLMWIKIFY_DATA_DIR"] = str(tmp_root)
    yield str(tmp_root)
    # Cleanup: best-effort rmtree
    try:
        shutil.rmtree(tmp_root, ignore_errors=True)
    except Exception:
        pass


# Windows: ManagedConnection 单例（get_connection）在测试结束后仍持有
# SQLite 文件句柄，TemporaryDirectory.__exit__ 的 rmtree 会撞
# WinError 32。给临时目录默认 ignore_cleanup_errors=True（py3.10+），
# 并在每个测试结束后关闭全部单例连接，避免句柄跨测试泄漏。
_OrigTempDir = tempfile.TemporaryDirectory


class _TolerantTemporaryDirectory(_OrigTempDir):  # type: ignore[misc,valid-type]
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ignore_cleanup_errors", True)
        super().__init__(*args, **kwargs)


@pytest.fixture(autouse=True, scope="session")
def _patch_temporary_directory():
    tempfile.TemporaryDirectory = _TolerantTemporaryDirectory  # type: ignore[misc]
    yield
    tempfile.TemporaryDirectory = _OrigTempDir  # type: ignore[misc]


@pytest.fixture(autouse=True)
def _close_db_connections_after_test():
    yield
    try:
        from llmwikify.foundation.db import close_all

        close_all()
    except Exception:
        pass


@pytest.fixture
def temp_wiki():
    """Create a temporary wiki directory for testing."""
    temp_dir = tempfile.mkdtemp()
    wiki_root = Path(temp_dir)

    # Initialize directory structure
    (wiki_root / "raw").mkdir()
    (wiki_root / "wiki").mkdir()

    yield wiki_root

    # Cleanup
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def wiki_instance(temp_wiki):
    """Create a Wiki instance with clean initialization."""
    # Ensure clean state
    if (temp_wiki / "wiki").exists():
        import shutil

        shutil.rmtree(temp_wiki / "wiki")
        shutil.rmtree(temp_wiki / "raw")

    (temp_wiki / "raw").mkdir()
    (temp_wiki / "wiki").mkdir()

    wiki = Wiki(temp_wiki)
    wiki.index.initialize()
    yield wiki
    wiki.close()


@pytest.fixture
def sample_content():
    """Sample wiki page content with links."""
    return """# Test Page

This is a test page with [[Another Page]] and [[Third Page|Custom Display]].

## Section

More content with [[Another Page#section|linked to section]].
"""


@pytest.fixture
def sample_pdf_content():
    """Sample extracted PDF content."""
    return ExtractedContent(
        text="Test PDF content\n\nWith multiple pages",
        source_type="pdf",
        title="Test PDF",
        metadata={"page_count": 2},
    )
