"""Regression tests for latent defects found while wiring Track C.

Each of these broke silently: the import resolved to a missing module,
the version fell back to a hardcoded literal, or a UTF-8 file was read
with the platform's default codec.
"""

from __future__ import annotations

import subprocess
import sys

from llmwikify.kernel.storage.backend import _get_version_safe


def test_backend_reports_the_real_version() -> None:
    """``_get_version_safe`` used to import from ``..`` (llmwikify.kernel),
    which has no ``__version__`` — every caller got the literal "0.11.0"."""
    import llmwikify

    assert _get_version_safe() == llmwikify.__version__
    assert _get_version_safe() != "0.11.0"


def test_jieba_stopwords_load_on_any_platform() -> None:
    """The stop-word file is UTF-8; reading it with the platform codec
    (cp936 on Windows) raised UnicodeDecodeError at import time."""
    from llmwikify.kernel.storage import jieba_dict_gen

    assert isinstance(jieba_dict_gen._STOP_WORDS, set)


def test_wiki_graph_tool_import_resolves() -> None:
    """The graph tool imported ``...kernel`` from ``apps.agent.tools``,
    which resolves to ``llmwikify.apps.kernel`` — a module that does not
    exist. The tool raised ModuleNotFoundError when called."""
    from llmwikify.kernel.wiki.engines.relation import RelationEngine

    assert RelationEngine is not None


def test_tool_module_imports_cleanly() -> None:
    """Import the whole tools package in a fresh interpreter."""
    r = subprocess.run(
        [sys.executable, "-c", "import llmwikify.apps.agent.tools"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
