"""Tests for research save-to-wiki improvements.

Covers:
- Slug collision fix (A1): hash-based naming
- include_sources toggle (A2): tool param + handler behavior
- Inline citation linkification (B1): [[Source:HASH]] -> [[src-HASH|Title]]
- _analyze_impact source count (A2 confirmation preview)
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.apps.agent.core.db import AgentDatabase
from llmwikify.apps.agent.tools import WikiToolRegistry
from llmwikify.core.wiki import Wiki


# ─── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def tmp_wiki_root(tmp_path):
    """Return a temp directory for wiki root."""
    d = tmp_path / "wiki"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def wiki(tmp_wiki_root):
    """Create a real initialized Wiki in a temp dir."""
    w = Wiki(tmp_wiki_root)
    w.init(overwrite=True)
    yield w
    w.close()


@pytest.fixture
def db(tmp_path):
    """Create a temp AgentDatabase with a research session row."""
    database = AgentDatabase(tmp_path / "test_agent.db")
    return database


@pytest.fixture
def registry(wiki, db):
    """Create a WikiToolRegistry with real wiki + temp db."""
    return WikiToolRegistry(wiki, db=db, wiki_id="test_wiki")


def _make_research_session(
    db: AgentDatabase,
    query: str = "Test query?",
    markdown: str = "Report body.",
    sources: list[dict] | None = None,
) -> str:
    """Create a research session in the DB with given sources and a result JSON blob.

    Returns the auto-generated session id.
    """
    result_blob = json.dumps({
        "query": query,
        "markdown": markdown,
        "synthesis_summary": {
            "reinforced_claims": ["claim 1", "claim 2"],
            "contradictions": ["contradiction 1"],
            "knowledge_gaps": ["gap 1"],
        },
    })
    session_id = db.create_research_session(wiki_id="test_wiki", query=query)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute(
            "UPDATE research_sessions SET status='done', result=? WHERE id=?",
            (result_blob, session_id),
        )
        conn.commit()

    if sources:
        for i, src in enumerate(sources):
            db.save_source(
                session_id=session_id,
                sub_query_id=f"sq-{i}",
                source_type=src["source_type"],
                url=src.get("url", ""),
                title=src.get("title", ""),
                content_length=len(src.get("content", "")),
                content_preview=src.get("content", "")[:500],
                content=src.get("content", ""),
            )
    return session_id


# ─── A1: Slug Collision Fix ────────────────────────────────────────────


class TestSourceSlugCollision:
    """slug = src-{md5(url or title)[:12]} must be unique + stable."""

    def test_two_sources_same_title_different_urls(self):
        """Bug fix: title-based slug collided; hash(url) does not."""
        s1 = WikiToolRegistry._source_slug("https://a.com/x", "Same Title")
        s2 = WikiToolRegistry._source_slug("https://b.com/y", "Same Title")
        assert s1 != s2
        assert s1.startswith("src-")
        assert s2.startswith("src-")
        assert len(s1) == len("src-") + 12
        assert len(s2) == len("src-") + 12

    def test_slug_includes_src_prefix(self):
        """Slug must be src-XXX to namespace raw sources away from pages."""
        slug = WikiToolRegistry._source_slug("https://example.com", "Title")
        assert slug.startswith("src-")

    def test_same_url_idempotent(self):
        """Re-saving same source yields same slug (idempotent)."""
        s1 = WikiToolRegistry._source_slug("https://example.com/a", "T1")
        s2 = WikiToolRegistry._source_slug("https://example.com/a", "T2-renamed")
        assert s1 == s2  # URL is stable across title edits

    def test_url_preferred_over_title_when_both_present(self):
        """URL hash is used when available, ignoring title."""
        s_with_url = WikiToolRegistry._source_slug("https://x.com", "Title A")
        s_with_other_url = WikiToolRegistry._source_slug("https://x.com", "Title B")
        assert s_with_url == s_with_other_url

    def test_falls_back_to_title_when_url_empty(self):
        """Empty URL: use title hash."""
        s1 = WikiToolRegistry._source_slug("", "Some Title")
        s2 = WikiToolRegistry._source_slug("", "Some Title")
        assert s1 == s2
        assert s1.startswith("src-")

    def test_returns_none_for_empty_inputs(self):
        """Both empty: skip the source (return None)."""
        assert WikiToolRegistry._source_slug("", "") is None
        assert WikiToolRegistry._source_slug("   ", "   ") is None

    def test_strips_whitespace(self):
        """Leading/trailing whitespace is stripped before hashing."""
        a = WikiToolRegistry._source_slug("  https://x.com  ", "")
        b = WikiToolRegistry._source_slug("https://x.com", "")
        assert a == b


# ─── A1 + handler integration: actual save uses hash-based slugs ──────


class TestHandlerSlugCollisionIntegration:
    """End-to-end: handler writes raw files with hash-based slugs."""

    def test_two_sources_with_same_title_get_distinct_raw_files(
        self, registry, wiki, db, tmp_wiki_root,
    ):
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com/x", "title": "Same Title",
                 "source_type": "web", "content": "Content A", "summary": "A"},
                {"url": "https://b.com/y", "title": "Same Title",
                 "source_type": "web", "content": "Content B", "summary": "B"},
            ],
        )
        result = json.loads(registry._handle_research_save({"session_id": sid}))
        assert result["sources_saved"] == 2

        raw_files = list(wiki.raw_dir.glob("src-*.md"))
        assert len(raw_files) == 2, f"Expected 2 distinct raw files, got {raw_files}"

        contents = {f.read_text() for f in raw_files}
        assert contents == {"Content A", "Content B"}


# ─── A2: include_sources toggle ────────────────────────────────────────


class TestIncludeSourcesToggle:
    """Tool param include_sources gates raw file + index writes."""

    def test_default_true_saves_sources(self, registry, wiki, db):
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com", "title": "A",
                 "source_type": "web", "content": "Content A", "summary": "A"},
            ],
        )
        result = json.loads(registry._handle_research_save({"session_id": sid}))
        assert result["sources_saved"] == 1
        assert result["include_sources"] is True
        assert len(list(wiki.raw_dir.glob("src-*.md"))) == 1

    def test_false_skips_raw_dir_and_index(self, registry, wiki, db):
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com", "title": "A",
                 "source_type": "web", "content": "Content A", "summary": "A"},
                {"url": "https://b.com", "title": "B",
                 "source_type": "web", "content": "Content B", "summary": "B"},
            ],
        )
        result = json.loads(registry._handle_research_save(
            {"session_id": sid, "include_sources": False}
        ))
        assert result["sources_saved"] == 0
        assert result["include_sources"] is False
        assert list(wiki.raw_dir.glob("src-*.md")) == []

    def test_false_still_writes_report_and_synthesis(self, registry, wiki, db):
        """Report and synthesis pages are always written, regardless of toggle."""
        sid = _make_research_session(
            db,
            query="My Test Query",
            sources=[
                {"url": "https://a.com", "title": "A",
                 "source_type": "web", "content": "C", "summary": "S"},
            ],
        )
        registry._handle_research_save(
            {"session_id": sid, "include_sources": False}
        )
        # Report page exists (slugified)
        assert (wiki.wiki_dir / "research" / "my-test-query.md").exists()
        # Synthesis page exists
        assert (wiki.wiki_dir / "synthesis" / "my-test-query.md").exists()

    def test_wiki_sources_always_skipped(self, registry, wiki, db):
        """wiki-typed sources are never re-saved (already in wiki)."""
        sid = _make_research_session(
            db,
            sources=[
                {"url": "", "title": "Existing Wiki Page",
                 "source_type": "wiki", "content": "Wiki content", "summary": "WP"},
            ],
        )
        result = json.loads(registry._handle_research_save({"session_id": sid}))
        assert result["sources_saved"] == 0
        assert list(wiki.raw_dir.glob("src-*.md")) == []

    def test_empty_content_source_skipped(self, registry, wiki, db):
        """Source with empty content does not get a file or index entry."""
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com", "title": "Empty",
                 "source_type": "web", "content": "", "summary": "S"},
            ],
        )
        result = json.loads(registry._handle_research_save({"session_id": sid}))
        assert result["sources_saved"] == 0
        assert list(wiki.raw_dir.glob("src-*.md")) == []

    def test_returns_include_sources_in_response(self, registry, wiki, db):
        """Response includes the toggle value for confirmation display."""
        sid = _make_research_session(db)
        r1 = json.loads(registry._handle_research_save({"session_id": sid}))
        r2 = json.loads(registry._handle_research_save(
            {"session_id": sid, "include_sources": False}
        ))
        # Second call hits "already saved" path; create a fresh session
        # Just check r1 includes the key
        assert "include_sources" in r1
        assert r1["include_sources"] is True


class TestAnalyzeImpactSourceCount:
    """_analyze_impact reports raw_sources_to_save for the toggle preview."""

    def test_true_counts_non_wiki_sources_with_content(self, registry, db):
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com", "title": "A",
                 "source_type": "web", "content": "C", "summary": "S"},
                {"url": "https://b.com", "title": "B",
                 "source_type": "web", "content": "C", "summary": "S"},
                {"url": "", "title": "WikiPage",
                 "source_type": "wiki", "content": "C", "summary": "S"},
            ],
        )
        impact = registry._analyze_impact("research_save_to_wiki", {
            "session_id": sid, "include_sources": True,
        })
        assert impact["include_sources"] is True
        assert impact["raw_sources_to_save"] == 2  # wiki one excluded

    def test_false_reports_zero(self, registry, db):
        sid = _make_research_session(
            db,
            sources=[
                {"url": "https://a.com", "title": "A",
                 "source_type": "web", "content": "C", "summary": "S"},
            ],
        )
        impact = registry._analyze_impact("research_save_to_wiki", {
            "session_id": sid, "include_sources": False,
        })
        assert impact["include_sources"] is False
        assert impact["raw_sources_to_save"] == 0
        assert "sources skipped" in impact["description"]


# ─── B1: Inline citation linkification ────────────────────────────────


class TestBuildSourceLinkMap:
    """_build_source_link_map: hash → {slug, title, url}."""

    def test_empty_input(self):
        assert WikiToolRegistry._build_source_link_map([]) == {}

    def test_url_and_title_both_present(self):
        m = WikiToolRegistry._build_source_link_map([
            {"url": "https://a.com/x", "title": "A Title"},
        ])
        assert len(m) == 1
        h = next(iter(m))
        assert m[h]["slug"].startswith("src-")
        assert m[h]["title"] == "A Title"
        assert m[h]["url"] == "https://a.com/x"

    def test_url_empty_uses_title(self):
        m = WikiToolRegistry._build_source_link_map([
            {"url": "", "title": "Title Only"},
        ])
        assert len(m) == 1
        assert next(iter(m.values()))["title"] == "Title Only"

    def test_source_without_url_or_title_skipped(self):
        m = WikiToolRegistry._build_source_link_map([
            {"url": "", "title": ""},
        ])
        assert m == {}

    def test_title_falls_back_to_url(self):
        """When title is empty, use url as display label."""
        m = WikiToolRegistry._build_source_link_map([
            {"url": "https://a.com/x", "title": ""},
        ])
        h = next(iter(m))
        assert m[h]["title"] == "https://a.com/x"


class TestLinkifySourceCitations:
    """_linkify_source_citations: [[Source:HASH]] → [[src-HASH|Title]]."""

    def test_replaces_matching_hash(self):
        import hashlib
        url = "https://a.com/x"
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        link_map = WikiToolRegistry._build_source_link_map([
            {"url": url, "title": "A Title"},
        ])
        md = f"See [[Source:{h}]] for details."
        out = WikiToolRegistry._linkify_source_citations(md, link_map)
        assert f"[[src-{h}|A Title]]" in out
        assert "[[Source:" not in out

    def test_unmatched_hash_preserved(self):
        """Bogus hash left unchanged (no error)."""
        link_map = WikiToolRegistry._build_source_link_map([
            {"url": "https://a.com", "title": "A"},
        ])
        md = "See [[Source:ffffffffffff]] for something unknown."
        out = WikiToolRegistry._linkify_source_citations(md, link_map)
        assert "[[Source:ffffffffffff]]" in out

    def test_empty_report(self):
        assert WikiToolRegistry._linkify_source_citations("", {}) == ""

    def test_report_without_citations(self):
        out = WikiToolRegistry._linkify_source_citations(
            "No citations here.",
            WikiToolRegistry._build_source_link_map([]),
        )
        assert out == "No citations here."

    def test_empty_link_map_no_replacement(self):
        """Without sources, all citations remain as plain text."""
        out = WikiToolRegistry._linkify_source_citations(
            "See [[Source:abc123def456]].",
            {},
        )
        assert out == "See [[Source:abc123def456]]."

    def test_multiple_citations_same_hash_replaced(self):
        """A hash referenced N times is replaced N times."""
        import hashlib
        url = "https://a.com"
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        link_map = WikiToolRegistry._build_source_link_map([
            {"url": url, "title": "A"},
        ])
        md = f"First [[Source:{h}]] and second [[Source:{h}]]."
        out = WikiToolRegistry._linkify_source_citations(md, link_map)
        assert out.count(f"[[src-{h}|A]]") == 2

    def test_mixed_match_and_miss(self):
        """Mix of known and unknown hashes: replace known, preserve unknown."""
        import hashlib
        known_url = "https://known.com"
        known_h = hashlib.md5(known_url.encode()).hexdigest()[:12]
        link_map = WikiToolRegistry._build_source_link_map([
            {"url": known_url, "title": "Known Title"},
        ])
        md = f"[[Source:{known_h}]] and [[Source:fff000fff000]]."
        out = WikiToolRegistry._linkify_source_citations(md, link_map)
        assert f"[[src-{known_h}|Known Title]]" in out
        assert "[[Source:fff000fff000]]" in out


# ─── Handler integration: linkify + slug + toggle all together ────────


class TestHandlerEndToEndLinkifyAndSlug:
    """Full handler flow: report markdown is linkified, raw files are hash-slugged."""

    def test_full_flow_inline_citations_become_wikilinks(
        self, registry, wiki, db,
    ):
        import hashlib
        url_a = "https://a.com/article"
        url_b = "https://b.com/paper"
        h_a = hashlib.md5(url_a.encode()).hexdigest()[:12]
        h_b = hashlib.md5(url_b.encode()).hexdigest()[:12]
        markdown = (
            f"# Report\n\n"
            f"From [[Source:{h_a}]] and [[Source:{h_b}]].\n"
            f"Unknown: [[Source:ffffffffffff]].\n"
        )
        sid = _make_research_session(
            db,
            query="Linkify Test",
            markdown=markdown,
            sources=[
                {"url": url_a, "title": "Article A",
                 "source_type": "web", "content": "A body", "summary": "s"},
                {"url": url_b, "title": "Paper B",
                 "source_type": "pdf", "content": "B body", "summary": "s"},
            ],
        )

        result = json.loads(registry._handle_research_save({"session_id": sid}))
        assert result["sources_saved"] == 2

        # Report page has linkified citations
        report_path = wiki.wiki_dir / "research" / "linkify-test.md"
        report_text = report_path.read_text()
        assert f"[[src-{h_a}|Article A]]" in report_text
        assert f"[[src-{h_b}|Paper B]]" in report_text
        assert "[[Source:ffffffffffff]]" in report_text  # unknown preserved

        # Raw files use hash-based slugs
        raw_a = wiki.raw_dir / f"src-{h_a}.md"
        raw_b = wiki.raw_dir / f"src-{h_b}.md"
        assert raw_a.exists() and raw_a.read_text() == "A body"
        assert raw_b.exists() and raw_b.read_text() == "B body"

        # Index entries use 'raw/...' file_path
        with sqlite3.connect(wiki.db_path) as conn:
            rows = conn.execute(
                "SELECT page_name, file_path FROM pages WHERE page_name LIKE 'src-%'"
            ).fetchall()
        slugs_to_paths = {r[0]: r[1] for r in rows}
        assert slugs_to_paths[f"src-{h_a}"] == f"raw/src-{h_a}.md"
        assert slugs_to_paths[f"src-{h_b}"] == f"raw/src-{h_b}.md"

    def test_included_false_disables_linkify_too(
        self, registry, wiki, db,
    ):
        """When include_sources=False, raw files are not created, so
        linkified wikilinks would be broken. Linkify is also skipped
        to keep the report consistent (no dangling wikilinks).
        """
        import hashlib
        url = "https://a.com"
        h = hashlib.md5(url.encode()).hexdigest()[:12]
        markdown = f"See [[Source:{h}]]."
        sid = _make_research_session(
            db,
            query="NoSourceSave",
            markdown=markdown,
            sources=[
                {"url": url, "title": "A",
                 "source_type": "web", "content": "C", "summary": "s"},
            ],
        )
        result = json.loads(registry._handle_research_save(
            {"session_id": sid, "include_sources": False}
        ))
        assert result["sources_saved"] == 0
        # No raw files (toggle off)
        assert list(wiki.raw_dir.glob("src-*.md")) == []
        # Report kept [[Source:HASH]] as text — linkify was skipped
        report_path = wiki.wiki_dir / "research" / "nosourcesave.md"
        report_text = report_path.read_text()
        assert f"[[Source:{h}]]" in report_text
        assert "[[src-" not in report_text
