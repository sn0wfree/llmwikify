"""Tests for Agent layer components."""

import asyncio

import pytest


def _run_async(coro):
    """Run async coroutine, handling nested event loop issues."""
    try:
        return asyncio.run(coro)
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        raise


from llmwikify.kernel import Wiki


@pytest.fixture
def wiki_root(tmp_path):
    root = tmp_path / "test_wiki"
    root.mkdir()
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "wiki" / ".sink").mkdir()
    db_path = root / ".llmwikify.db"
    wiki = Wiki(root)
    wiki.init()
    return wiki


