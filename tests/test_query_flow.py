"""Tests for wiki_synthesize — Query knowledge compounding cycle."""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestSynthesizeQueryBasic:
    """Test basic synthesize_query functionality."""
    
    def test_synthesize_creates_page(self, temp_wiki):
        """Basic: creates a query answer page."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="What is gold mining?",
            answer="# Gold Mining\n\nGold mining is the process of extracting gold.",
        )
        
        assert result['status'] == 'created'
        assert result['page_name'].startswith('Query:')
        assert 'Gold Mining' in result['page_name']
        
        page_path = temp_wiki / 'wiki' / f"{result['page_name']}.md"
        assert page_path.exists()
        
        content = page_path.read_text()
        assert "# Gold Mining" in content
        assert "Gold mining is the process" in content
        
        wiki.close()
    
    def test_synthesize_custom_page_name(self, temp_wiki):
        """Custom page name overrides auto-generation."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="Question",
            answer="# Answer",
            page_name="My Custom Analysis",
        )
        
        assert result['page_name'] == 'My Custom Analysis'
        page = temp_wiki / 'wiki' / 'My Custom Analysis.md'
        assert page.exists()
        
        wiki.close()
    
    def test_synthesize_page_path_in_result(self, temp_wiki):
        """Result includes relative page path."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="Test",
            answer="# Test",
        )
        
        assert 'page_path' in result
        assert result['page_path'].startswith('wiki/')
        assert result['page_path'].endswith('.md')
        
        wiki.close()


class TestSynthesizeWithSources:
    """Test source citation in synthesize_query."""
    
    def test_synthesize_with_wiki_pages(self, temp_wiki):
        """Auto-adds [[wikilinks]] for source_pages in Sources section."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        wiki.write_page("Gold Mining", "# Gold Mining\n\nContent")
        wiki.write_page("Economics", "# Economics\n\nContent")
        
        result = wiki.synthesize_query(
            query="Gold economics?",
            answer="# Analysis\n\nGold mining economics overview.",
            source_pages=["Gold Mining", "Economics"],
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        
        assert '## Sources' in content
        assert '[[Gold Mining]]' in content
        assert '[[Economics]]' in content
        assert '### Query' in content
        assert 'Gold economics?' in content
        assert '### Wiki Pages Referenced' in content
        
        wiki.close()
    
    def test_synthesize_with_raw_sources(self, temp_wiki):
        """Auto-adds markdown links for raw_sources in Sources section."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create a raw source file
        raw_file = temp_wiki / 'raw' / 'research-article.md'
        raw_file.write_text("# Research\n\nContent")
        
        result = wiki.synthesize_query(
            query="Research findings?",
            answer="# Summary\n\nKey findings from research.",
            raw_sources=["raw/research-article.md"],
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        
        assert '## Sources' in content
        assert '### Raw Sources' in content
        assert '[Source: research-article.md](raw/research-article.md)' in content
        
        wiki.close()
    
    def test_synthesize_with_both_sources(self, temp_wiki):
        """Both wiki pages and raw sources in Sources section."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        wiki.write_page("Topic A", "# Topic A\n\nContent")
        
        result = wiki.synthesize_query(
            query="Combined analysis?",
            answer="# Combined\n\nAnalysis combining multiple sources.",
            source_pages=["Topic A"],
            raw_sources=["raw/data.csv", "raw/report.pdf"],
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        
        assert '[[Topic A]]' in content
        assert '[Source: data.csv](raw/data.csv)' in content
        assert '[Source: report.pdf](raw/report.pdf)' in content
        assert '### Wiki Pages Referenced' in content
        assert '### Raw Sources' in content
        
        wiki.close()
    
    def test_synthesize_no_auto_link(self, temp_wiki):
        """auto_link=False does not add Sources section."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        wiki.write_page("Source", "# Source")
        
        result = wiki.synthesize_query(
            query="Question",
            answer="# Answer",
            source_pages=["Source"],
            auto_link=False,
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        assert '[[Source]]' not in content
        assert '## Sources' not in content
        
        wiki.close()
    
    def test_synthesize_empty_sources(self, temp_wiki):
        """No sources provided — Sources section not added."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="Simple question",
            answer="# Simple Answer\n\nJust the answer.",
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        assert '## Sources' not in content
        
        wiki.close()


class TestSynthesizeLogging:
    """Test log.md integration."""
    
    def test_synthesize_auto_log(self, temp_wiki):
        """auto_log=True appends to log.md."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="Test question about mining",
            answer="# Answer",
            auto_log=True,
        )
        
        log = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert 'query' in log
        assert 'Test question about mining' in log
        
        wiki.close()
    
    def test_synthesize_no_auto_log(self, temp_wiki):
        """auto_log=False does not modify log.md."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        original_log = (temp_wiki / 'wiki' / 'log.md').read_text()
        
        wiki.synthesize_query(
            query="Question",
            answer="# Answer",
            auto_log=False,
        )
        
        new_log = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert original_log == new_log
        
        wiki.close()
    
    def test_synthesize_log_format(self, temp_wiki):
        """Log entry follows parseable format with page link."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="Compare A and B",
            answer="# Comparison",
            page_name="Query: A vs B",
        )
        
        log = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert 'query | Compare A and B' in log
        assert '[[Query: A vs B]]' in log
        
        wiki.close()


class TestSynthesizeDuplicateDetection:
    """Test duplicate query detection and handling."""
    
    def test_synthesize_duplicate_creates_timestamp(self, temp_wiki):
        """Similar queries go to sink instead of creating duplicate pages."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result1 = wiki.synthesize_query(
            query="What is gold mining?",
            answer="# Answer 1",
        )
        
        result2 = wiki.synthesize_query(
            query="What is gold mining?",
            answer="# Answer 2",
        )
        
        assert result1['status'] == 'created'
        assert result2['status'] == 'sunk'
        
        sink_file = temp_wiki / 'wiki' / '.sink' / f"{result1['page_name']}.sink.md"
        assert sink_file.exists()
        assert "# Answer 2" in sink_file.read_text()
        
        wiki.close()
    
    def test_synthesize_duplicate_has_hint(self, temp_wiki):
        """Duplicate detection returns hint about existing page and sink."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="Explain quantum computing",
            answer="# Answer 1",
        )
        
        result = wiki.synthesize_query(
            query="Explain quantum computing",
            answer="# Answer 2",
        )
        
        assert result['hint'] != ""
        import json
        hint_data = json.loads(result['hint'])
        assert hint_data['action_taken'] == 'appended_to_sink'
        assert 'sink_path' in hint_data
        assert 'similar_page_exists' in hint_data['type']
        
        wiki.close()
    
    def test_synthesize_replace_existing(self, temp_wiki):
        """merge_or_replace='replace' revises the existing page."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result1 = wiki.synthesize_query(
            query="What is machine learning?",
            answer="# Original Answer\n\nOld content.",
        )
        
        result2 = wiki.synthesize_query(
            query="What is machine learning?",
            answer="# Updated Answer\n\nNew, improved content.",
            merge_or_replace="replace",
        )
        
        assert result2['status'] == 'replaced'
        assert result2['page_name'] == result1['page_name']
        
        # Page should have updated content
        page = temp_wiki / 'wiki' / f"{result2['page_name']}.md"
        content = page.read_text()
        assert "New, improved content" in content
        assert "Old content" not in content
        
        wiki.close()
    
    def test_synthesize_similar_query_detection(self, temp_wiki):
        """Detects semantically similar queries (keyword overlap)."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="Compare gold and silver mining profitability",
            answer="# Gold vs Silver",
            page_name="Query: Gold vs Silver Mining",
        )
        
        # Similar but not identical query
        result = wiki.synthesize_query(
            query="Gold silver mining comparison profits",
            answer="# New comparison",
        )
        
        # Should detect similarity and add suffix
        assert result['hint'] != ""
        assert 'Gold vs Silver Mining' in result['hint']
        
        wiki.close()
    
    def test_find_similar_query_page_in_subdirectory(self, temp_wiki):
        """Finds Query pages nested in subdirectories (rglob coverage)."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create a Query page in a subdirectory
        subdir = temp_wiki / 'wiki' / 'queries'
        subdir.mkdir(parents=True)
        (subdir / "Query: Gold Mining Methods.md").write_text(
            "# Gold Mining Methods\n\nOverview of mining methods.\n\n- Keywords: gold, mining, methods"
        )
        
        result = wiki._find_similar_query_page("Open pit gold mining techniques")
        
        assert result is not None
        assert 'mining' in result['page_name'].lower() or 'gold' in result['page_name'].lower()
        
        wiki.close()
    
    def test_synthesize_different_query_no_detection(self, temp_wiki):
        """Unrelated queries don't trigger duplicate detection."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="What is gold mining?",
            answer="# Gold",
        )
        
        result = wiki.synthesize_query(
            query="How does photosynthesis work?",
            answer="# Photosynthesis",
        )
        
        # No hint about existing pages
        assert result['hint'] == ""
        assert result['page_name'] == 'Query: How Does Photosynthesis Work'
        
        wiki.close()
    
    def test_synthesize_same_day_multiple(self, temp_wiki):
        """Multiple duplicates on same day append to same sink file."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(query="Same question", answer="# 1")
        result2 = wiki.synthesize_query(query="Same question", answer="# 2")
        result3 = wiki.synthesize_query(query="Same question", answer="# 3")
        
        assert result2['status'] == 'sunk'
        assert result3['status'] == 'sunk'
        
        wiki.close()


class TestQueryPageNaming:
    """Test page name generation logic."""
    
    def test_page_name_from_query(self, temp_wiki):
        """Generates readable page name from query."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="compare gold and copper mining economics",
            answer="# Mining Economics",
        )
        
        assert 'Query:' in result['page_name']
        assert 'Compare' in result['page_name'] or 'Gold' in result['page_name']
        
        wiki.close()
    
    def test_page_name_truncated_long_query(self, temp_wiki):
        """Long queries are truncated to 50 chars."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        long_query = "This is a very long query question that should be truncated to a reasonable length for the page name"
        result = wiki.synthesize_query(
            query=long_query,
            answer="# Answer",
        )
        
        # Topic portion should be <= 50 chars
        topic = result['page_name'].replace('Query: ', '')
        assert len(topic) <= 50
        
        wiki.close()
    
    def test_page_name_collision_with_existing(self, temp_wiki):
        """Collision with existing Query: page sinks instead of creating duplicate."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Query: Test Page", "# Existing query page")
        
        result = wiki.synthesize_query(
            query="Test page",
            answer="# Answer",
        )
        
        assert result['status'] == 'sunk'
        sink_file = temp_wiki / 'wiki' / '.sink' / 'Query: Test Page.sink.md'
        assert sink_file.exists()
        
        wiki.close()


class TestFullQueryFlow:
    """Test complete Query compounding cycle: search → read → synthesize → log."""
    
    def test_full_flow(self, temp_wiki):
        """End-to-end query flow with real search and synthesis."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        wiki.write_page("Gold Mining", "# Gold Mining\n\nGold mining is profitable and growing.")
        wiki.write_page("Copper Mining", "# Copper Mining\n\nCopper mining is expanding rapidly.")
        
        # 1. Search
        results = wiki.search("mining", limit=5)
        source_names = [r['page_name'] for r in results]
        
        # 2. Read (simulated — in practice LLM reads content)
        for name in source_names:
            page_data = wiki.read_page(name)
            assert 'content' in page_data
        
        # 3. Synthesize (LLM-generated answer)
        answer = (
            "# Mining Comparison\n\n"
            "Both gold and copper mining are significant industries.\n\n"
            "## Gold Mining\nGold mining is profitable and growing.\n\n"
            "## Copper Mining\nCopper mining is expanding rapidly."
        )
        
        result = wiki.synthesize_query(
            query="Compare gold and copper mining",
            answer=answer,
            source_pages=source_names,
        )
        
        # 4. Verify page created
        assert result['status'] == 'created'
        page = temp_wiki / 'wiki' / f"{result['page_name']}.md"
        assert page.exists()
        
        # 5. Verify sources section
        content = page.read_text()
        assert '## Sources' in content
        assert '### Wiki Pages Referenced' in content
        assert '[[Gold Mining]]' in content
        assert '[[Copper Mining]]' in content
        
        # 6. Verify log
        log = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert 'query | Compare gold and copper mining' in log
        assert f"[[{result['page_name']}]]" in log
        
        wiki.close()
    
    def test_flow_with_raw_sources(self, temp_wiki):
        """Query flow including raw source references."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        wiki.write_page("Market Analysis", "# Market Analysis\n\nData from reports.")
        
        # Create raw sources
        (temp_wiki / 'raw' / 'report-2024.md').write_text("# 2024 Report\n\nData")
        (temp_wiki / 'raw' / 'article.md').write_text("# Article\n\nAnalysis")
        
        answer = "# Market Trends\n\nBased on 2024 data."
        
        result = wiki.synthesize_query(
            query="What are the 2024 market trends?",
            answer=answer,
            source_pages=["Market Analysis"],
            raw_sources=["raw/report-2024.md", "raw/article.md"],
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        
        assert '[[Market Analysis]]' in content
        assert '[Source: report-2024.md](raw/report-2024.md)' in content
        assert '[Source: article.md](raw/article.md)' in content
        assert '### Raw Sources' in content
        
        wiki.close()

    def test_flow_query_page_indexed(self, temp_wiki):
        """Synthesized query page is indexed and searchable."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.synthesize_query(
            query="Unique topic about xyz",
            answer="# Unique Topic\n\nThis is about xyz specifically.",
        )
        
        # The query page should be findable via search
        results = wiki.search("xyz specifically", limit=10)
        
        page_names = [r['page_name'] for r in results]
        assert any('Unique Topic' in name or 'Unique Topic' in name for name in page_names)
        
        wiki.close()


class TestSynthesizeEdgeCases:
    """Test edge cases and error handling."""
    
    def test_synthesize_empty_source_lists(self, temp_wiki):
        """Empty source lists handled gracefully."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="Simple",
            answer="# Simple Answer",
            source_pages=[],
            raw_sources=[],
        )
        
        assert result['status'] == 'created'
        assert result['source_pages'] == []
        assert result['raw_sources'] == []
        
        wiki.close()
    
    def test_synthesize_none_sources(self, temp_wiki):
        """None source lists treated as empty."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="Simple",
            answer="# Answer",
            source_pages=None,
            raw_sources=None,
        )
        
        assert result['status'] == 'created'
        
        wiki.close()
    
    def test_synthesize_special_characters_in_query(self, temp_wiki):
        """Query with special characters handled safely."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.synthesize_query(
            query="What's the C++ vs Python? (performance comparison!)",
            answer="# Comparison",
        )
        
        assert result['status'] == 'created'
        page = temp_wiki / 'wiki' / f"{result['page_name']}.md"
        assert page.exists()
        
        wiki.close()
    
    def test_synthesize_multiline_answer(self, temp_wiki):
        """Multi-line markdown answer preserved correctly."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        answer = """# Complex Analysis

## Section 1

Content here.

## Section 2

- Item 1
- Item 2
- Item 3

### Subsection

More content with `code` and **bold** text.
"""
        
        result = wiki.synthesize_query(
            query="Complex question",
            answer=answer,
        )
        
        content = (temp_wiki / 'wiki' / f"{result['page_name']}.md").read_text()
        assert '## Section 1' in content
        assert '### Subsection' in content
        assert '`code`' in content
        
        wiki.close()
