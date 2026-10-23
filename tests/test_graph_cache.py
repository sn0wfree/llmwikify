"""Unit tests for kernel.graph.cache — shared fingerprint cache."""

from __future__ import annotations

import sqlite3
import time

import pytest

from llmwikify.kernel.graph.cache import (
    cache_get,
    cache_invalidate,
    cache_put,
    graph_fingerprint,
    wiki_cache_key,
)


@pytest.fixture
def mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE pages (id INTEGER PRIMARY KEY, page_name TEXT);
        CREATE TABLE page_links (id INTEGER PRIMARY KEY, source_page TEXT, target_page TEXT);
        CREATE TABLE relations (id INTEGER PRIMARY KEY, source TEXT, target TEXT, relation TEXT);
        """
    )
    conn.execute("INSERT INTO pages (page_name) VALUES ('a')")
    conn.execute("INSERT INTO page_links (source_page, target_page) VALUES ('a', 'b')")
    conn.commit()
    yield conn
    conn.close()


class TestFingerprint:
    def test_stable_when_unchanged(self, mem_conn):
        assert graph_fingerprint(mem_conn) == graph_fingerprint(mem_conn)

    def test_changes_on_link_insert(self, mem_conn):
        before = graph_fingerprint(mem_conn)
        mem_conn.execute(
            "INSERT INTO page_links (source_page, target_page) VALUES ('b', 'c')"
        )
        mem_conn.commit()
        assert graph_fingerprint(mem_conn) != before

    def test_none_conn(self):
        assert graph_fingerprint(None) == "no-index"


class TestCache:
    def test_put_get_roundtrip(self, mem_conn):
        fp = graph_fingerprint(mem_conn)
        cache_put("analyze", "w1", fp, {"status": "success"})
        assert cache_get("analyze", "w1", fp, ttl_s=60) == {"status": "success"}

    def test_miss_on_fingerprint_change(self, mem_conn):
        fp = graph_fingerprint(mem_conn)
        cache_put("analyze", "w1", fp, {"v": 1})
        mem_conn.execute("INSERT INTO pages (page_name) VALUES ('x')")
        mem_conn.commit()
        assert cache_get("analyze", "w1", graph_fingerprint(mem_conn), ttl_s=60) is None

    def test_ttl_expiry(self):
        cache_put("viz", "w2", "fp", {"v": 1})
        assert cache_get("viz", "w2", "fp", ttl_s=-1) is None

    def test_kind_and_extra_isolation(self):
        cache_put("analyze", "w3", "fp", {"a": 1})
        cache_put("viz", "w3", "fp", {"v": 1}, extra="page|auto")
        cache_put("viz", "w3", "fp", {"v": 2}, extra="other|full")
        assert cache_get("analyze", "w3", "fp", ttl_s=60) == {"a": 1}
        assert cache_get("viz", "w3", "fp", extra="page|auto", ttl_s=60) == {"v": 1}
        assert cache_get("viz", "w3", "fp", extra="other|full", ttl_s=60) == {"v": 2}
        assert cache_get("viz", "w3", "fp", extra="missing", ttl_s=60) is None

    def test_invalidate_wiki_key(self):
        cache_put("analyze", "wa", "fp", {"a": 1})
        cache_put("analyze", "wb", "fp", {"b": 1})
        cache_invalidate("wa")
        assert cache_get("analyze", "wa", "fp", ttl_s=60) is None
        assert cache_get("analyze", "wb", "fp", ttl_s=60) == {"b": 1}

    def test_invalidate_all(self):
        cache_put("analyze", "wa", "fp", {"a": 1})
        cache_invalidate()
        assert cache_get("analyze", "wa", "fp", ttl_s=60) is None


class TestWikiCacheKey:
    def test_prefers_root(self):
        class W:
            root = "/tmp/w"

        assert wiki_cache_key(W()) == "/tmp/w"

    def test_falls_back_to_id(self):
        w = object()
        assert wiki_cache_key(w) == str(id(w))


class TestFileFingerprint:
    def test_changes_on_edit(self, tmp_path):
        from llmwikify.kernel.graph.cache import cache_invalidate, file_fingerprint

        p = tmp_path / "a.md"
        p.write_text("one", encoding="utf-8")
        fp1 = file_fingerprint(tmp_path)
        p.write_text("two-two", encoding="utf-8")
        cache_invalidate()  # drop fingerprint memo
        fp2 = file_fingerprint(tmp_path)
        assert fp1 != fp2

    def test_missing_dir(self):
        from llmwikify.kernel.graph.cache import file_fingerprint

        assert file_fingerprint(None) == "no-dir"
