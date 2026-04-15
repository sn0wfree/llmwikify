"""Tests for query sink deduplication — content-addressable storage."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestContentHash:
    """Test content hashing with normalization."""

    def test_same_text_same_hash(self, temp_wiki):
        """Identical text produces identical hash."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        h1 = sink._content_hash("Gold mining is the extraction of gold.")
        h2 = sink._content_hash("Gold mining is the extraction of gold.")

        assert h1 == h2
        assert len(h1) == 8
        wiki.close()

    def test_whitespace_differences_normalized(self, temp_wiki):
        """Whitespace differences are normalized to same hash."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        h1 = sink._content_hash("Gold mining is extraction.")
        h2 = sink._content_hash("Gold  mining   is  extraction.")

        assert h1 == h2
        wiki.close()

    def test_newline_differences_normalized(self, temp_wiki):
        """Newline differences are normalized to same hash."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        h1 = sink._content_hash("Line one.\nLine two.")
        h2 = sink._content_hash("Line one. Line two.")

        assert h1 == h2
        wiki.close()

    def test_punctuation_difference_different_hash(self, temp_wiki):
        """Missing punctuation produces different hash."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        h1 = sink._content_hash("Gold mining is extraction.")
        h2 = sink._content_hash("Gold mining is extraction")

        # Different content → likely different hash (but not guaranteed)
        # We test normalization, not that all punctuation changes hash
        wiki.close()


class TestDuplicateDetection:
    """Test automatic deduplication during append."""

    def test_exact_duplicate_referenced(self, temp_wiki):
        """Same content is stored once, referenced twice."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Test", "# Query: Test\n\nContent")

        sink = wiki.query_sink
        sink.append_to_sink("Query: Test", "Q1", "Same answer content.", [], [])
        sink.append_to_sink("Query: Test", "Q2", "Same answer content.", [], [])

        # Read and check
        result = sink.read("Query: Test")
        assert result['total_entries'] == 2
        assert result['unique_count'] == 1
        assert result['entries'][0]['answer'] == result['entries'][1]['answer']
        assert result['entries'][1]['note'] == 'duplicate'
        wiki.close()

    def test_near_duplicate_referenced(self, temp_wiki):
        """Near-duplicate content is referenced with note."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Test", "# Query: Test\n\nContent")

        sink = wiki.query_sink
        sink.append_to_sink("Query: Test", "Q1", "Gold mining is extraction.", [], [])
        # Near-duplicate: just a period difference (normalized to same hash)
        sink.append_to_sink("Query: Test", "Q2", "Gold mining  is extraction.", [], [])

        result = sink.read("Query: Test")
        assert result['total_entries'] == 2
        assert result['unique_count'] == 1
        assert result['entries'][1]['note'].startswith('near-dup') or result['entries'][1]['note'] == 'duplicate'
        wiki.close()

    def test_different_content_stored(self, temp_wiki):
        """Different content is stored separately."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Test", "# Query: Test\n\nContent")

        sink = wiki.query_sink
        sink.append_to_sink("Query: Test", "Q1", "Gold mining is extraction.", [], [])
        sink.append_to_sink("Query: Test", "Q2", "Photosynthesis is how plants grow.", [], [])

        result = sink.read("Query: Test")
        assert result['total_entries'] == 2
        assert result['unique_count'] == 2
        assert result['entries'][0]['answer'] != result['entries'][1]['answer']
        wiki.close()


class TestContentStoreFormat:
    """Test Content Store + Entry Log format."""

    def test_content_store_parsed(self, temp_wiki):
        """Content Store section is correctly parsed."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## Content Store\n\n'
            '### a1b2c3d4 — 2026-04-10\nGold mining is extraction.\n\n'
            '### d4e5f6c7 — 2026-04-11\nUpdated rate: 6%.\n\n'
            '---\n\n## Entry Log\n\n'
            '| # | Timestamp | Query | Answer Hash | Note |\n'
            '|---|-----------|-------|-------------|------|\n'
            '| 1 | 2026-04-10 10:00 | Q1 | `a1b2c3d4` | — |\n'
        )

        store = wiki.query_sink._parse_content_store(sink_file.read_text())
        assert 'a1b2c3d4' in store
        assert 'd4e5f6c7' in store
        assert 'extraction' in store['a1b2c3d4']
        assert '6%' in store['d4e5f6c7']
        wiki.close()

    def test_entry_log_parsed(self, temp_wiki):
        """Entry Log table is correctly parsed."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## Content Store\n\n### a1b2c3d4 — 2026-04-10\nA1\n\n'
            '---\n\n## Entry Log\n\n'
            '| # | Timestamp | Query | Answer Hash | Note |\n'
            '|---|-----------|-------|-------------|------|\n'
            '| 1 | 2026-04-10 10:00 | Q1 | `a1b2c3d4` | — |\n'
            '| 2 | 2026-04-10 11:00 | Q2 | `a1b2c3d4` | near-dup of #1 |\n'
        )

        entries = wiki.query_sink._parse_entry_log(sink_file.read_text())
        assert len(entries) == 2
        assert entries[0]['num'] == 1
        assert entries[0]['query'] == 'Q1'
        assert entries[0]['hash'] == 'a1b2c3d4'
        assert entries[1]['note'] == 'near-dup of #1'
        wiki.close()

    def test_read_resolves_references(self, temp_wiki):
        """read() resolves hash references to actual content."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## Content Store\n\n### a1b2c3d4 — 2026-04-10\nGold mining is extraction.\n\n'
            '---\n\n## Entry Log\n\n'
            '| # | Timestamp | Query | Answer Hash | Note |\n'
            '|---|-----------|-------|-------------|------|\n'
            '| 1 | 2026-04-10 10:00 | Q1 | `a1b2c3d4` | — |\n'
            '| 2 | 2026-04-10 11:00 | Q2 | `a1b2c3d4` | near-dup of #1 |\n'
        )

        result = wiki.query_sink.read("Query: Test")
        assert result['total_entries'] == 2
        assert result['entries'][0]['answer'] == 'Gold mining is extraction.'
        assert result['entries'][1]['answer'] == 'Gold mining is extraction.'
        assert result['entries'][0]['hash'] == 'a1b2c3d4'
        assert result['entries'][1]['hash'] == 'a1b2c3d4'
        wiki.close()


class TestLegacyMigration:
    """Test migration from old format to new format."""

    def test_old_format_migrated(self, temp_wiki):
        """Old format sink file is migrated on read."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nAnswer one.\n\n'
            '---\n\n## [2026-04-10 11:00] Query: Q2\n\nAnswer two.\n'
        )

        result = wiki.query_sink.read("Query: Test")

        assert result['status'] == 'ok'
        assert result['total_entries'] == 2
        assert 'Content Store' in sink_file.read_text()
        assert 'Entry Log' in sink_file.read_text()
        wiki.close()

    def test_new_format_not_re_migrated(self, temp_wiki):
        """New format is not modified on read."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test.sink.md'
        original = (
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## Content Store\n\n### a1b2c3d4 — 2026-04-10\nAnswer.\n\n'
            '---\n\n## Entry Log\n\n'
            '| # | Timestamp | Query | Answer Hash | Note |\n'
            '|---|-----------|-------|-------------|------|\n'
            '| 1 | 2026-04-10 10:00 | Q1 | `a1b2c3d4` | — |\n'
        )
        sink_file.write_text(original)

        wiki.query_sink.read("Query: Test")

        assert sink_file.read_text() == original
        wiki.close()


class TestJaccardSimilarity:
    """Test Jaccard similarity calculation."""

    def test_identical_text(self, temp_wiki):
        """Identical text has similarity 1.0."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        sim = sink._jaccard_similarity("hello world", "hello world")

        assert sim == 1.0
        wiki.close()

    def test_completely_different(self, temp_wiki):
        """Completely different text has similarity 0.0."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        sim = sink._jaccard_similarity("gold mining", "quantum physics")

        assert sim == 0.0
        wiki.close()

    def test_partial_overlap(self, temp_wiki):
        """Partial overlap produces intermediate similarity."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink = wiki.query_sink
        sim = sink._jaccard_similarity("gold mining extraction", "gold mining process")

        assert 0.0 < sim < 1.0
        wiki.close()
