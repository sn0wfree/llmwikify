"""Tests for query sink feature — compound answers without duplicate pages."""

import pytest
from pathlib import Path
import sys
import json
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestSinkDirectoryCreation:
    """Test sink directory is created during init."""

    def test_sink_dir_created_on_init(self, temp_wiki):
        """sink/ directory created during wiki init."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        assert (temp_wiki / 'sink').exists()
        wiki.close()

    def test_sink_dir_in_created_files(self, temp_wiki):
        """sink/ listed in created_files during fresh init."""
        wiki = Wiki(temp_wiki)
        result = wiki.init()

        assert 'sink/' in result['created_files']
        wiki.close()

    def test_sink_dir_skipped_if_exists(self, temp_wiki):
        """sink/ skipped if already exists."""
        (temp_wiki / 'sink').mkdir()

        wiki = Wiki(temp_wiki)
        result = wiki.init()

        assert 'sink/' in result['skipped_files']
        wiki.close()

    def test_sink_dir_attribute_exists(self, temp_wiki):
        """Wiki instance has sink_dir attribute."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        assert hasattr(wiki, 'sink_dir')
        assert wiki.sink_dir == temp_wiki / 'sink'
        wiki.close()


class TestGetSinkInfoForPage:
    """Test query_sink.get_info_for_page method."""

    def test_no_sink_file(self, temp_wiki):
        """Returns has_sink=False when no sink file exists."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        info = wiki.query_sink.get_info_for_page("Query: Gold Mining")

        assert info['has_sink'] is False
        assert info['sink_entries'] == 0
        wiki.close()

    def test_sink_file_with_entries(self, temp_wiki):
        """Returns correct entry count for sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '---\n\n## [2026-04-10 10:00] Query: What is gold mining?\n\nAnswer 1\n'
            '---\n\n## [2026-04-10 11:00] Query: How does gold mining work?\n\nAnswer 2\n'
        )

        info = wiki.query_sink.get_info_for_page("Query: Gold Mining")

        assert info['has_sink'] is True
        assert info['sink_entries'] == 2
        wiki.close()

    def test_sink_file_empty(self, temp_wiki):
        """Returns has_sink=True but 0 entries for empty sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '> All entries processed.\n'
        )

        info = wiki.query_sink.get_info_for_page("Query: Test")

        assert info['has_sink'] is True
        assert info['sink_entries'] == 0
        wiki.close()


class TestFindOrCreateSinkFile:
    """Test query_sink._find_or_create_sink_file method."""

    def test_creates_new_sink_file(self, temp_wiki):
        """Creates sink file with proper frontmatter."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = wiki.query_sink._find_or_create_sink_file("Query: Gold Mining")

        assert sink_file.exists()
        assert sink_file.name == 'Query: Gold Mining.sink.md'

        content = sink_file.read_text()
        assert 'formal_page: "Query: Gold Mining"' in content
        assert 'formal_path: wiki/Query: Gold Mining.md' in content
        assert '# Query Sink: Gold Mining' in content
        wiki.close()

    def test_returns_existing_sink_file(self, temp_wiki):
        """Returns existing sink file without overwriting."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        original_content = '---\nformal_page: "Query: Test"\n---\n\nExisting content\n'
        sink_file.write_text(original_content)

        result = wiki.query_sink._find_or_create_sink_file("Query: Test")

        assert result == sink_file
        assert sink_file.read_text() == original_content
        wiki.close()

    def test_updates_formal_page_sink_meta(self, temp_wiki):
        """Updates formal page frontmatter when creating sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        formal_path = temp_wiki / 'wiki' / 'Query: Gold Mining.md'
        formal_path.write_text(
            '---\ntitle: Gold Mining\n---\n\n# Query: Gold Mining\n\nContent\n'
        )

        wiki.query_sink._find_or_create_sink_file("Query: Gold Mining")

        content = formal_path.read_text()
        assert 'sink_path:' in content
        wiki.close()


class TestAppendToSink:
    """Test query_sink.append_to_sink method."""

    def test_appends_entry_to_sink(self, temp_wiki):
        """Appends query answer to sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        formal_path = temp_wiki / 'wiki' / 'Query: Gold Mining.md'
        formal_path.write_text('# Query: Gold Mining\n\nContent\n')

        sink_path = wiki.query_sink.append_to_sink(
            "Query: Gold Mining",
            "What is gold mining?",
            "Gold mining is the process of extracting gold.",
            ["Gold Mining"],
            [],
        )

        assert sink_path.endswith('Query: Gold Mining.sink.md')

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        content = sink_file.read_text()
        assert '## [' in content
        assert 'Query: What is gold mining?' in content
        assert 'Gold mining is the process of extracting gold.' in content
        wiki.close()

    def test_appends_sources_to_entry(self, temp_wiki):
        """Includes source pages and raw sources in sink entry."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        formal_path = temp_wiki / 'wiki' / 'Query: Test.md'
        formal_path.write_text('# Query: Test\n\nContent\n')

        wiki.query_sink.append_to_sink(
            "Query: Test",
            "Test query?",
            "Answer content.",
            ["Source Page", "Another Page"],
            ["raw/article.md"],
        )

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        content = sink_file.read_text()
        assert '### Sources' in content
        assert '[[Source Page]]' in content
        assert '[[Another Page]]' in content
        assert '[Source: article.md](raw/article.md)' in content
        wiki.close()

    def test_multiple_entries_compound(self, temp_wiki):
        """Multiple appends create multiple entries in same sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        formal_path = temp_wiki / 'wiki' / 'Query: Test.md'
        formal_path.write_text('# Query: Test\n\nContent\n')

        wiki.query_sink.append_to_sink("Query: Test", "Q1", "A1", [], [])
        wiki.query_sink.append_to_sink("Query: Test", "Q2", "A2", [], [])

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        content = sink_file.read_text()

        assert 'Q1' in content
        assert 'A1' in content
        assert 'Q2' in content
        assert 'A2' in content
        wiki.close()


class TestReadSink:
    """Test read_sink method."""

    def test_read_empty_sink(self, temp_wiki):
        """Returns empty status when no sink file exists."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.read_sink("Query: Nonexistent")

        assert result['status'] == 'empty'
        assert result['entries'] == []
        wiki.close()

    def test_read_sink_with_entries(self, temp_wiki):
        """Parses entries from sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '---\n\n## [2026-04-10 10:00] Query: What is gold mining?\n\nGold mining extracts gold.\n'
            '---\n\n## [2026-04-10 11:00] Query: How much gold?\n\nAbout 200,000 tonnes.\n'
        )

        result = wiki.read_sink("Query: Gold Mining")

        assert result['status'] == 'ok'
        assert result['total_entries'] == 2
        assert len(result['entries']) == 2
        assert result['entries'][0]['query'] == 'What is gold mining?'
        assert result['entries'][1]['query'] == 'How much gold?'
        wiki.close()

    def test_read_sink_file_path(self, temp_wiki):
        """Returns relative file path in result."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        result = wiki.read_sink("Query: Test")

        assert 'file' in result
        assert result['file'].endswith('Query: Test.sink.md')
        wiki.close()


class TestClearSink:
    """Test clear_sink method."""

    def test_clear_existing_sink(self, temp_wiki):
        """Clears entries but keeps frontmatter."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        result = wiki.clear_sink("Query: Test")

        assert result['status'] == 'cleared'

        content = sink_file.read_text()
        assert 'formal_page: "Query: Test"' in content
        assert 'All entries processed' in content
        assert '## [' not in content
        wiki.close()

    def test_clear_nonexistent_sink(self, temp_wiki):
        """Returns empty status when no sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.clear_sink("Query: Nonexistent")

        assert result['status'] == 'empty'
        wiki.close()

    def test_clear_updates_formal_page_meta(self, temp_wiki):
        """Updates formal page frontmatter with sink_entries: 0."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        formal_path = temp_wiki / 'wiki' / 'Query: Test.md'
        formal_path.write_text(
            '---\nsink_path: sink/Query: Test.sink.md\nsink_entries: 5\n---\n\n# Query: Test\n\nContent\n'
        )

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        wiki.clear_sink("Query: Test")

        content = formal_path.read_text()
        assert 'sink_entries: 0' in content
        assert 'last_merged:' in content
        wiki.close()


class TestSinkStatus:
    """Test sink_status method."""

    def test_no_sink_directory(self, temp_wiki):
        """Returns empty when no sink directory."""
        wiki = Wiki(temp_wiki)

        result = wiki.sink_status()

        assert result['total_entries'] == 0
        assert result['sinks'] == []
        wiki.close()

    def test_empty_sink_directory(self, temp_wiki):
        """Returns zero sinks when directory is empty."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.sink_status()

        assert result['total_entries'] == 0
        assert result['total_sinks'] == 0
        assert result['sinks'] == []
        wiki.close()

    def test_single_sink_with_entries(self, temp_wiki):
        """Returns correct status for single sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
            '---\n\n## [2026-04-11 10:00] Query: Q2\n\nA2\n'
        )

        result = wiki.sink_status()

        assert result['total_entries'] == 2
        assert result['total_sinks'] == 1
        assert result['sinks'][0]['page_name'] == 'Query: Gold Mining'
        assert result['sinks'][0]['entry_count'] == 2
        assert result['sinks'][0]['oldest_entry'] == '2026-04-10'
        assert result['sinks'][0]['newest_entry'] == '2026-04-11'
        wiki.close()

    def test_multiple_sinks_sorted_by_count(self, temp_wiki):
        """Sinks sorted by entry count descending."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink1 = temp_wiki / 'sink' / 'Query: A.sink.md'
        sink1.write_text(
            '---\nformal_page: "Query: A"\n---\n\n# Sink: A\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        sink2 = temp_wiki / 'sink' / 'Query: B.sink.md'
        sink2.write_text(
            '---\nformal_page: "Query: B"\n---\n\n# Sink: B\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
            '---\n\n## [2026-04-10 11:00] Query: Q2\n\nA2\n'
            '---\n\n## [2026-04-10 12:00] Query: Q3\n\nA3\n'
        )

        result = wiki.sink_status()

        assert result['total_entries'] == 4
        assert result['sinks'][0]['page_name'] == 'Query: B'
        assert result['sinks'][1]['page_name'] == 'Query: A'
        wiki.close()


class TestSynthesizeQueryWithSink:
    """Test synthesize_query sink behavior."""

    def test_sinks_when_similar_page_exists(self, temp_wiki):
        """Status is 'sunk' when similar query page exists."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nGold mining is extraction.")

        result = wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Gold mining involves extracting gold ore.",
        )

        assert result['status'] == 'sunk'
        assert 'sink' in result['message'].lower()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        assert sink_file.exists()
        wiki.close()

    def test_sink_entry_created(self, temp_wiki):
        """Answer appended to sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nGold mining is extraction.")

        wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Gold mining involves extracting gold ore.",
        )

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        content = sink_file.read_text()
        assert 'Gold mining involves extracting gold ore.' in content
        wiki.close()

    def test_sink_hint_provided(self, temp_wiki):
        """Result includes hint with sink suggestion."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nGold mining is extraction.")

        result = wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Gold mining involves extracting gold ore.",
        )

        hint = result['hint']
        if isinstance(hint, str):
            hint_data = json.loads(hint)
        else:
            hint_data = hint

        assert hint_data['action_taken'] == 'appended_to_sink'
        assert 'sink_path' in hint_data
        assert 'similar_page_exists' in hint_data['type'] or hint_data['type'] == 'similar_page_exists'
        wiki.close()

    def test_merge_or_replace_replace(self, temp_wiki):
        """merge_or_replace='replace' updates the formal page directly."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nOld content.")

        result = wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Updated comprehensive content.",
            merge_or_replace="replace",
        )

        assert result['status'] == 'replaced'
        assert result['page_name'] == 'Query: Gold Mining'

        page_path = temp_wiki / 'wiki' / 'Query: Gold Mining.md'
        content = page_path.read_text()
        assert 'Updated comprehensive content.' in content
        wiki.close()

    def test_merge_or_replace_merge(self, temp_wiki):
        """merge_or_replace='merge' also replaces but with merged status."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nOld content.")

        result = wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Merged comprehensive content.",
            merge_or_replace="merge",
        )

        assert result['status'] == 'merged'
        assert result['page_name'] == 'Query: Gold Mining'

        page_path = temp_wiki / 'wiki' / 'Query: Gold Mining.md'
        content = page_path.read_text()
        assert 'Merged comprehensive content.' in content
        wiki.close()

    def test_no_similar_page_creates_new(self, temp_wiki):
        """Creates new page when no similar page exists."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.synthesize_query(
            query="What is quantum computing?",
            answer="Quantum computing uses qubits.",
        )

        assert result['status'] == 'created'
        wiki.close()

    def test_auto_log_sunk_query(self, temp_wiki):
        """Sunk queries are logged with [sink] marker."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nGold mining is extraction.")

        wiki.synthesize_query(
            query="What is gold mining process?",
            answer="Gold mining involves extracting gold ore.",
        )

        log_content = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert '[sink]' in log_content
        assert 'pending merge' in log_content
        wiki.close()


class TestReadPageWithSinkInfo:
    """Test read_page includes sink information."""

    def test_read_page_no_sink(self, temp_wiki):
        """Returns has_sink=False for pages without sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Test Page", "# Test Page\n\nContent")

        result = wiki.read_page("Test Page")

        assert result['has_sink'] is False
        assert result['sink_entries'] == 0
        wiki.close()

    def test_read_page_with_sink(self, temp_wiki):
        """Returns has_sink=True and entry count."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Test", "# Query: Test\n\nContent")

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        result = wiki.read_page("Query: Test")

        assert result['has_sink'] is True
        assert result['sink_entries'] == 1
        wiki.close()

    def test_read_sink_file_directly(self, temp_wiki):
        """Can read sink files via sink/ prefix."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\nContent\n'
        )

        result = wiki.read_page("sink/Query: Test.sink.md")

        assert result['is_sink'] is True
        assert 'Query Sink: Test' in result['content']
        wiki.close()

    def test_read_nonexistent_sink_file(self, temp_wiki):
        """Returns error for nonexistent sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.read_page("sink/Nonexistent.sink.md")

        assert 'error' in result
        wiki.close()


class TestSearchWithSinkInfo:
    """Test search attaches sink information."""

    def test_search_results_have_sink_info(self, temp_wiki):
        """Search results include has_sink and sink_entries."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Gold Mining", "# Gold Mining\n\nGold mining is extraction.")
        wiki.build_index()

        results = wiki.search("gold")

        assert len(results) > 0
        for result in results:
            assert 'has_sink' in result
            assert 'sink_entries' in result
        wiki.close()

    def test_search_results_with_existing_sink(self, temp_wiki):
        """Search shows has_sink=True when sink exists."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Query: Gold Mining\n\nGold mining info.")
        wiki.build_index()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        results = wiki.search("gold")

        for result in results:
            if result['page_name'] == 'Query: Gold Mining':
                assert result['has_sink'] is True
                assert result['sink_entries'] == 1
        wiki.close()


class TestUpdateIndexFileWithSink:
    """Test _update_index_file shows sink markers."""

    def test_index_shows_sink_marker(self, temp_wiki):
        """index.md includes sink entry count."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Query: Gold Mining\n\nContent")

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
            '---\n\n## [2026-04-10 11:00] Query: Q2\n\nA2\n'
        )

        wiki._update_index_file()

        index_content = (temp_wiki / 'wiki' / 'index.md').read_text()
        assert 'pending updates' in index_content
        assert '2' in index_content
        wiki.close()

    def test_index_no_sink_marker(self, temp_wiki):
        """index.md has no sink marker for pages without sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Normal Page", "# Normal Page\n\nContent")

        wiki._update_index_file()

        index_content = (temp_wiki / 'wiki' / 'index.md').read_text()
        assert 'pending updates' not in index_content
        wiki.close()


class TestLintWithSinkStatus:
    """Test lint includes sink_status."""

    def test_lint_returns_sink_status(self, temp_wiki):
        """lint() result includes sink_status."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint()

        assert 'sink_status' in result
        assert 'total_entries' in result['sink_status']
        assert 'sinks' in result['sink_status']
        wiki.close()

    def test_lint_sink_status_with_entries(self, temp_wiki):
        """lint() reflects pending sink entries."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n'
            '# Query Sink: Test\n\n'
            '---\n\n## [2026-04-10 10:00] Query: Q1\n\nA1\n'
        )

        result = wiki.lint()

        assert result['sink_status']['total_entries'] == 1
        wiki.close()


class TestWikiMdTemplate:
    """Test wiki.md includes sink documentation."""

    def test_wiki_md_has_sink_section(self, temp_wiki):
        """wiki.md includes Query Sink section."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki_md = temp_wiki / 'wiki.md'
        content = wiki_md.read_text()

        assert 'Query Sink' in content
        assert 'sink/' in content
        wiki.close()

    def test_wiki_md_has_updated_query_section(self, temp_wiki):
        """wiki.md Answer a Query section mentions sink behavior."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki_md = temp_wiki / 'wiki.md'
        content = wiki_md.read_text()

        assert 'saved to the sink' in content
        assert 'has_sink' in content
        wiki.close()


class TestUpdatePageSinkMeta:
    """Test query_sink._update_page_sink_meta method."""

    def test_updates_existing_frontmatter(self, temp_wiki):
        """Adds sink_path to existing frontmatter."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        page_path = temp_wiki / 'wiki' / 'Query: Test.md'
        page_path.write_text(
            '---\ntitle: Test\ncategory: query\n---\n\n# Query: Test\n\nContent\n'
        )

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n# Query Sink: Test\n\n'
        )

        wiki.query_sink._update_page_sink_meta(page_path, sink_file)

        content = page_path.read_text()
        assert 'sink_path: sink/Query: Test.sink.md' in content
        assert 'title: Test' in content
        assert 'category: query' in content
        wiki.close()

    def test_adds_frontmatter_to_page_without_it(self, temp_wiki):
        """Adds frontmatter to page that has none."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        page_path = temp_wiki / 'wiki' / 'Query: Test.md'
        page_path.write_text('# Query: Test\n\nContent\n')

        sink_file = temp_wiki / 'sink' / 'Query: Test.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Test"\n---\n\n# Query Sink: Test\n\n'
        )

        wiki.query_sink._update_page_sink_meta(page_path, sink_file)

        content = page_path.read_text()
        assert content.startswith('---')
        assert 'sink_path: sink/Query: Test.sink.md' in content
        wiki.close()


class TestSinkSuggestions:
    """Test sink suggestion generation."""

    def test_content_gap_detected(self, temp_wiki):
        """Detects topics in formal page missing from new answer."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page(
            "Query: Gold Mining",
            "# Gold Mining\n\nGold mining involves open-pit extraction and underground methods. Environmental impact is significant."
        )

        suggestions = wiki.query_sink._detect_content_gaps(
            "Gold mining is just extracting gold from the ground.",
            "Query: Gold Mining"
        )

        assert any("Content Gap" in s for s in suggestions)
        wiki.close()

    def test_new_coverage_detected(self, temp_wiki):
        """Detects new topics in answer not in formal page."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nBasic extraction methods.")

        suggestions = wiki.query_sink._detect_content_gaps(
            "Gold mining uses Cyanidation and Heap Leaching with modern Environmental Regulations.",
            "Query: Gold Mining"
        )

        assert any("New Coverage" in s for s in suggestions)
        wiki.close()

    def test_source_quality_no_sources(self, temp_wiki):
        """Flags when answer has no sources."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent. [[Mining Methods]]\n\n[Source](raw/article.md)")

        suggestions = wiki.query_sink._suggest_source_improvements([], [], "Query: Gold Mining")

        assert any("No Sources" in s for s in suggestions)
        wiki.close()

    def test_source_quality_missing_sources(self, temp_wiki):
        """Flags when answer misses sources from formal page."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent. [[Mining Methods]] [[Environmental Law]] [[Safety Regulations]]")

        suggestions = wiki.query_sink._suggest_source_improvements(["Mining Methods"], [], "Query: Gold Mining")

        assert any("Missing Sources" in s for s in suggestions)
        wiki.close()

    def test_query_pattern_repeated(self, temp_wiki):
        """Detects repeated similar queries in sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent.")

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '## [2026-04-10 10:00] Query: What is gold mining?\n\nAnswer 1\n\n'
            '## [2026-04-10 11:00] Query: Gold mining?\n\nAnswer 2\n\n'
            '## [2026-04-10 12:00] Query: Tell me gold mining?\n\nAnswer 3\n\n'
        )

        suggestions = wiki.query_sink._analyze_query_patterns("What is gold mining?", "Query: Gold Mining")

        assert any("Repeated Question" in s for s in suggestions)
        wiki.close()

    def test_knowledge_growth_new_concepts(self, temp_wiki):
        """Detects new concepts mentioned in answer."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nBasic extraction.")

        suggestions = wiki.query_sink._suggest_knowledge_growth(
            "Cyanidation and Heap Leaching and Amalgamation are key processes.",
            "Query: Gold Mining"
        )

        assert any("New Concepts" in s for s in suggestions)
        wiki.close()

    def test_knowledge_growth_contradiction(self, temp_wiki):
        """Detects possible contradiction via negation words."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent.")

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text('---\nformal_page: "Query: Gold Mining"\n---\n\n# Query Sink\n\n')

        suggestions = wiki.query_sink._suggest_knowledge_growth(
            "However, this is not the case and contradicts previous findings.",
            "Query: Gold Mining"
        )

        assert any("Possible Contradiction" in s for s in suggestions)
        wiki.close()


class TestSinkDedup:
    """Test sink duplicate detection."""

    def test_detects_duplicate(self, temp_wiki):
        """Detects high similarity with existing sink entry."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '## [2026-04-10 10:00] Query: What is gold mining?\n\n'
            'Gold mining is the process of extracting gold from ore using various methods.\n\n'
        )

        new_answer = "Gold mining is the process of extracting gold from ore using various methods. Extra detail."
        warning = wiki.query_sink._check_sink_duplicate(sink_file, new_answer)

        assert warning is not None
        assert "High similarity" in warning
        wiki.close()

    def test_no_duplicate_different_content(self, temp_wiki):
        """No duplicate warning for different content."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        sink_file = temp_wiki / 'sink' / 'Query: Gold Mining.sink.md'
        sink_file.write_text(
            '---\nformal_page: "Query: Gold Mining"\n---\n\n'
            '# Query Sink: Gold Mining\n\n'
            '## [2026-04-10 10:00] Query: What is gold mining?\n\n'
            'Gold mining is the process of extracting gold from ore.\n\n'
        )

        new_answer = "Photosynthesis is how plants convert sunlight into energy."
        warning = wiki.query_sink._check_sink_duplicate(sink_file, new_answer)

        assert warning is None
        wiki.close()


class TestSinkUrgency:
    """Test sink urgency tracking."""

    def test_urgency_field_in_sink_status(self, temp_wiki):
        """sink_status returns urgency field for each sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent.")

        wiki.query_sink.append_to_sink("Query: Gold Mining", "Test query", "Test answer", [], [])

        status = wiki.sink_status()

        assert 'urgent_count' in status
        assert len(status['sinks']) > 0
        assert 'urgency' in status['sinks'][0]
        assert status['sinks'][0]['urgency'] == 'ok'
        wiki.close()

    def test_lint_returns_sink_warnings(self, temp_wiki):
        """lint() returns sink_warnings for stale sinks."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nContent.")

        result = wiki.lint()

        assert 'sink_warnings' in result
        assert isinstance(result['sink_warnings'], list)
        wiki.close()
