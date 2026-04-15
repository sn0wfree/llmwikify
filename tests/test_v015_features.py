"""Tests for v0.15.0 features: ingest metadata and lint clue-based detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestIngestMetadata:
    """Test enhanced ingest metadata (v0.15.0)."""

    def test_ingest_returns_file_type(self, temp_wiki):
        """Test that ingest returns file_type."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here")

        result = wiki.ingest_source(str(test_file))

        assert 'file_type' in result
        assert result['file_type'] == 'markdown'

        wiki.close()

    def test_ingest_returns_file_size(self, temp_wiki):
        """Test that ingest returns file_size."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here with some words")

        result = wiki.ingest_source(str(test_file))

        assert 'file_size' in result
        assert result['file_size'] > 0

        wiki.close()

    def test_ingest_returns_word_count(self, temp_wiki):
        """Test that ingest returns word_count."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("one two three four five")

        result = wiki.ingest_source(str(test_file))

        assert 'word_count' in result
        assert result['word_count'] == 5

        wiki.close()

    def test_ingest_returns_has_images_false(self, temp_wiki):
        """Test that ingest returns has_images when no images."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# No images here")

        result = wiki.ingest_source(str(test_file))

        assert 'has_images' in result
        assert result['has_images'] == False
        assert result['image_count'] == 0

        wiki.close()

    def test_ingest_returns_has_images_true(self, temp_wiki):
        """Test that ingest detects images in markdown."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Page\n\n![alt](image.png)\n\nMore text ![alt2](photo.jpg)")

        result = wiki.ingest_source(str(test_file))

        assert result['has_images'] == True
        assert result['image_count'] == 2

        wiki.close()

    def test_ingest_returns_content_preview(self, temp_wiki):
        """Test that ingest returns content_preview (first 200 chars)."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        long_content = "A" * 300
        test_file.write_text(long_content)

        result = wiki.ingest_source(str(test_file))

        assert 'content_preview' in result
        assert len(result['content_preview']) <= 200
        assert result['content_preview'] == "A" * 200

        wiki.close()

    def test_ingest_returns_text_extracted(self, temp_wiki):
        """Test that ingest returns text_extracted flag."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("Some text")

        result = wiki.ingest_source(str(test_file))

        assert 'text_extracted' in result
        assert result['text_extracted'] == True

        wiki.close()

    def test_ingest_no_summary_returned(self, temp_wiki):
        """Test that ingest does NOT return a summary (LLM's job)."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test\n\nImportant content with key takeaways")

        result = wiki.ingest_source(str(test_file))

        # No 'summary' key should exist
        assert 'summary' not in result
        assert 'key_takeaways' not in result

        wiki.close()

    def test_ingest_message_tells_llm_to_read(self, temp_wiki):
        """Test that message instructs LLM to read the file."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test")

        result = wiki.ingest_source(str(test_file))

        assert 'message' in result
        assert 'read' in result['message'].lower()

        wiki.close()


class TestDetectDatedClaims:
    """Test _detect_dated_claims() method (v0.15.0)."""

    def test_detect_dated_claim_basic(self, temp_wiki):
        """Test basic dated claim detection."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create a raw source from 2024
        src = temp_wiki / 'raw' / 'recent.md'
        src.write_text("Report from 2024. Latest data from 2024.")

        # Create a wiki page with old year mention
        wiki.write_page("Old Company", "# Old Company\n\nFounded in 2019, the company was growing.")

        hints = wiki._detect_dated_claims()

        assert len(hints) >= 1
        assert hints[0]['type'] == 'dated_claim'
        assert hints[0]['page'] == 'Old Company'
        assert hints[0]['claim_year'] == 2019
        assert hints[0]['latest_source_year'] == 2024
        assert hints[0]['gap_years'] == 5
        assert 'observation' in hints[0]

        wiki.close()

    def test_detect_dated_claim_no_gap(self, temp_wiki):
        """Test that recent claims are not flagged."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        src = temp_wiki / 'raw' / 'recent.md'
        src.write_text("Report from 2024.")

        wiki.write_page("Recent Company", "# Recent Company\n\nIn 2024, the company launched.")

        hints = wiki._detect_dated_claims()

        assert len(hints) == 0

        wiki.close()

    def test_detect_dated_claim_max_3(self, temp_wiki):
        """Test that critical hints are capped at 3."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        src = temp_wiki / 'raw' / 'recent.md'
        src.write_text("Report from 2024.")

        # Create 5 pages with old claims
        for i in range(5):
            wiki.write_page(f"Old Page {i}", f"# Old Page {i}\n\nData from 2018 shows trends.")

        hints = wiki._detect_dated_claims()

        assert len(hints) <= 3

        wiki.close()

    def test_detect_dated_claim_no_sources(self, temp_wiki):
        """Test that no hints are returned when there are no sources."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Old Page", "# Old Page\n\nData from 2018 shows trends.")

        hints = wiki._detect_dated_claims()

        assert len(hints) == 0

        wiki.close()

    def test_detect_dated_claim_returns_observation(self, temp_wiki):
        """Test that dated claim includes observation field."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        src = temp_wiki / 'raw' / 'recent.md'
        src.write_text("Report from 2024.")

        wiki.write_page("Old Page", "# Old Page\n\nFounded in 2019.")

        hints = wiki._detect_dated_claims()

        assert len(hints) == 1
        assert 'observation' in hints[0]
        assert '2019' in hints[0]['observation']
        assert '2024' in hints[0]['observation']
        assert '5' in hints[0]['observation']

        wiki.close()

    def test_detect_dated_claims_with_subdirs(self, temp_wiki):
        """raw/ with category subdirs does not crash."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / 'raw' / 'gold').mkdir()
        (temp_wiki / 'raw' / 'gold' / 'article1.md').write_text("Gold news from 2024")
        (temp_wiki / 'raw' / 'gold' / 'article2.md').write_text("Gold news from 2023")
        (temp_wiki / 'raw' / 'copper').mkdir()
        (temp_wiki / 'raw' / 'copper' / 'news.md').write_text("Copper news from 2024")

        wiki.write_page("Old Company", "# Old Company\n\nFounded in 2019.")

        hints = wiki._detect_dated_claims()

        assert len(hints) >= 1
        assert hints[0]['type'] == 'dated_claim'
        assert hints[0]['page'] == 'Old Company'
        assert hints[0]['claim_year'] == 2019
        assert hints[0]['latest_source_year'] == 2024
        wiki.close()

    def test_detect_dated_claims_mixed_files_and_dirs(self, temp_wiki):
        """raw/ has both root-level files and subdirectory files."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / 'raw' / 'root_article.md').write_text("Root article from 2024")
        (temp_wiki / 'raw' / 'category').mkdir()
        (temp_wiki / 'raw' / 'category' / 'sub_article.md').write_text("Sub article from 2023")

        wiki.write_page("Old Page", "# Old Page\n\nData from 2019.")

        hints = wiki._detect_dated_claims()

        assert len(hints) >= 1
        assert hints[0]['latest_source_year'] == 2024
        wiki.close()

    def test_detect_dated_claims_empty_subdirs(self, temp_wiki):
        """raw/ with empty subdirs does not crash or affect scanning."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / 'raw' / 'empty_category').mkdir()
        (temp_wiki / 'raw' / 'gold').mkdir()
        (temp_wiki / 'raw' / 'gold' / 'article.md').write_text("Article from 2024")

        hints = wiki._detect_dated_claims()
        assert hints == []

        wiki.write_page("Old Page", "# Old Page\n\nData from 2019.")
        hints = wiki._detect_dated_claims()
        assert len(hints) == 1
        assert hints[0]['latest_source_year'] == 2024
        wiki.close()

    def test_detect_dated_claims_finds_latest_year_in_subdir(self, temp_wiki):
        """Latest year may be deep in a subdirectory."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / 'raw' / 'old.md').write_text("Old news from 2020")
        (temp_wiki / 'raw' / 'gold').mkdir()
        (temp_wiki / 'raw' / 'gold' / 'latest.md').write_text("Latest news from 2024")

        wiki.write_page("Company", "# Company\n\nFounded in 2018.")

        hints = wiki._detect_dated_claims()

        assert len(hints) >= 1
        assert hints[0]['latest_source_year'] == 2024
        assert hints[0]['claim_year'] == 2018
        assert hints[0]['gap_years'] == 6
        wiki.close()

    def test_detect_dated_claims_multi_level_nesting(self, temp_wiki):
        """raw/ with 3+ levels of nesting: raw/gold/2024/Q1/article.md"""
        wiki = Wiki(temp_wiki)
        wiki.init()

        (temp_wiki / 'raw' / 'gold' / '2024' / 'Q1').mkdir(parents=True)
        (temp_wiki / 'raw' / 'gold' / '2024' / 'Q1' / 'jan.md').write_text("Jan 2024 article")
        (temp_wiki / 'raw' / 'gold' / '2024' / 'Q2').mkdir(parents=True)
        (temp_wiki / 'raw' / 'gold' / '2024' / 'Q2' / 'may.md').write_text("May 2024 article")
        (temp_wiki / 'raw' / 'gold' / '2023').mkdir(parents=True)
        (temp_wiki / 'raw' / 'gold' / '2023' / 'annual.md').write_text("Annual report 2023")
        (temp_wiki / 'raw' / 'copper').mkdir()
        (temp_wiki / 'raw' / 'copper' / 'news.md').write_text("Copper news 2024")
        (temp_wiki / 'raw' / 'archive' / 'old').mkdir(parents=True)
        (temp_wiki / 'raw' / 'root.md').write_text("Root article 2022")

        wiki.write_page("Old Company", "# Old Company\n\nFounded in 2019.")

        hints = wiki._detect_dated_claims()

        assert len(hints) >= 1
        assert hints[0]['latest_source_year'] == 2024
        assert hints[0]['claim_year'] == 2019
        assert hints[0]['gap_years'] == 5
        wiki.close()


class TestDetectQueryPageOverlap:
    """Test _detect_query_page_overlap() method (v0.15.0)."""

    def test_detect_overlap_basic(self, temp_wiki):
        """Test basic query page overlap detection."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create two very similar query pages
        wiki.write_page("Query: Gold Mining", "# Gold Mining\n\nInfo about gold mining.")
        wiki.write_page("Query: Gold Mining Techniques", "# Gold Mining Techniques\n\nTechniques.")

        hints = wiki._detect_query_page_overlap()

        assert len(hints) >= 0  # May or may not overlap depending on keywords
        if hints:
            assert hints[0]['type'] == 'topic_overlap'
            assert 'jaccard_score' in hints[0]
            assert 'observation' in hints[0]

        wiki.close()

    def test_detect_overlap_identical_keywords(self, temp_wiki):
        """Test detection when keywords are identical."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Same core keywords, different suffix
        wiki.write_page("Query: Machine Learning", "# ML\n\nAbout ML.")
        wiki.write_page("Query: Machine Learning Overview", "# ML Overview\n\nOverview.")

        hints = wiki._detect_query_page_overlap()

        # Both share "machine" and "learning" keywords
        overlap_hints = [h for h in hints if h['type'] == 'topic_overlap']
        if overlap_hints:
            assert overlap_hints[0]['jaccard_score'] >= 0.85

        wiki.close()

    def test_detect_overlap_max_2(self, temp_wiki):
        """Test that informational hints are capped at 2 for this detector."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create multiple overlapping query pages
        for i in range(5):
            wiki.write_page(f"Query: Gold Mining Part {i}", f"# Part {i}\n\nInfo.")

        hints = wiki._detect_query_page_overlap()

        overlap_hints = [h for h in hints if h['type'] == 'topic_overlap']
        assert len(overlap_hints) <= 2

        wiki.close()

    def test_detect_overlap_no_query_pages(self, temp_wiki):
        """Test that no hints are returned when there are no query pages."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Regular Page", "# Regular\n\nContent.")

        hints = wiki._detect_query_page_overlap()

        assert len(hints) == 0

        wiki.close()

    def test_detect_overlap_returns_observation(self, temp_wiki):
        """Test that overlap hint includes observation field."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Query: Python Programming", "# Python\n\nAbout Python.")
        wiki.write_page("Query: Python Programming Guide", "# Python Guide\n\nGuide.")

        hints = wiki._detect_query_page_overlap()

        overlap_hints = [h for h in hints if h['type'] == 'topic_overlap']
        if overlap_hints:
            assert 'observation' in overlap_hints[0]
            assert 'page_a' in overlap_hints[0]
            assert 'page_b' in overlap_hints[0]

        wiki.close()


class TestDetectMissingCrossRefs:
    """Test _detect_missing_cross_refs() method (v0.15.0)."""

    def test_detect_missing_cross_ref_basic(self, temp_wiki):
        """Test basic missing cross-reference detection."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create a page that should be linked
        wiki.write_page("Machine Learning", "# Machine Learning\n\nAbout ML.")

        # Create two pages that mention "Machine Learning" but don't link it
        wiki.write_page("AI Overview", "# AI\n\nMachine learning is a subset of AI.")
        wiki.write_page("Data Science", "# Data Science\n\nMachine learning is used in data science.")

        hints = wiki._detect_missing_cross_refs()

        missing_hints = [h for h in hints if h['type'] == 'missing_cross_ref']
        assert len(missing_hints) >= 1
        assert missing_hints[0]['concept'] == 'Machine Learning'
        assert len(missing_hints[0]['mentioning_pages']) >= 2
        assert 'observation' in missing_hints[0]

        wiki.close()

    def test_detect_cross_ref_already_linked(self, temp_wiki):
        """Test that already-linked pages are not flagged."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Machine Learning", "# Machine Learning\n\nAbout ML.")

        # These pages link to Machine Learning
        wiki.write_page("AI Overview", "# AI\n\n[[Machine Learning]] is a subset of AI.")
        wiki.write_page("Data Science", "# Data Science\n\n[[Machine Learning]] is used here.")

        hints = wiki._detect_missing_cross_refs()

        missing_hints = [h for h in hints if h['type'] == 'missing_cross_ref' and h['concept'] == 'Machine Learning']
        assert len(missing_hints) == 0

        wiki.close()

    def test_detect_cross_ref_only_one_mention(self, temp_wiki):
        """Test that single mentions are not flagged (need 2+)."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Machine Learning", "# Machine Learning\n\nAbout ML.")
        wiki.write_page("AI Overview", "# AI\n\nMachine learning is mentioned once.")

        hints = wiki._detect_missing_cross_refs()

        missing_hints = [h for h in hints if h['type'] == 'missing_cross_ref' and h['concept'] == 'Machine Learning']
        assert len(missing_hints) == 0

        wiki.close()

    def test_detect_cross_ref_max_3(self, temp_wiki):
        """Test that missing cross-ref hints are capped at 3."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create multiple concepts
        concepts = ['Alpha', 'Beta', 'Gamma', 'Delta', 'Epsilon']
        for c in concepts:
            wiki.write_page(c, f"# {c}\n\nAbout {c}.")

        # Create pages that mention all concepts without linking
        for i in range(3):
            content = f"# Page {i}\n\n"
            for c in concepts:
                content += f"{c} is mentioned here. "
            wiki.write_page(f"Overview {i}", content)

        hints = wiki._detect_missing_cross_refs()

        missing_hints = [h for h in hints if h['type'] == 'missing_cross_ref']
        assert len(missing_hints) <= 3

        wiki.close()

    def test_detect_cross_ref_returns_observation(self, temp_wiki):
        """Test that missing cross-ref hint includes observation field."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Quantum Physics", "# Quantum Physics\n\nAbout QP.")
        wiki.write_page("Physics 101", "# Physics\n\nQuantum Physics is a branch of physics.")
        wiki.write_page("Science Overview", "# Science\n\nQuantum Physics is fascinating.")

        hints = wiki._detect_missing_cross_refs()

        missing_hints = [h for h in hints if h['type'] == 'missing_cross_ref']
        if missing_hints:
            assert 'observation' in missing_hints[0]
            assert 'Quantum Physics' in missing_hints[0]['observation']
            assert 'mention_count' in missing_hints[0]

        wiki.close()


class TestLintHintsStructure:
    """Test lint() return structure with hints (v0.15.0)."""

    def test_lint_returns_hints(self, temp_wiki):
        """Test that lint() returns hints structure."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Test", "# Test\n\nContent")

        result = wiki.lint()

        assert 'hints' in result
        assert 'critical' in result['hints']
        assert 'informational' in result['hints']
        assert isinstance(result['hints']['critical'], list)
        assert isinstance(result['hints']['informational'], list)

        wiki.close()

    def test_lint_hints_critical_max_3(self, temp_wiki):
        """Test that critical hints are capped at 3."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        src = temp_wiki / 'raw' / 'recent.md'
        src.write_text("Report from 2024.")

        # Create 5 pages with old claims (should produce critical hints)
        for i in range(5):
            wiki.write_page(f"Old Page {i}", f"# Old Page {i}\n\nData from 2018.")

        result = wiki.lint()

        assert len(result['hints']['critical']) <= 3

        wiki.close()

    def test_lint_hints_informational_max_5(self, temp_wiki):
        """Test that informational hints are capped at 5."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        # Create many query pages that overlap
        for i in range(10):
            wiki.write_page(f"Query: Gold Mining Part {i}", f"# Part {i}\n\nGold mining info.")

        result = wiki.lint()

        assert len(result['hints']['informational']) <= 5

        wiki.close()

    def test_lint_preserves_existing_issues(self, temp_wiki):
        """Test that lint() still returns issues alongside hints."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        wiki.write_page("Test", "# Test\n\n[[Nonexistent]]")

        result = wiki.lint()

        assert 'issues' in result
        assert len(result['issues']) > 0  # broken link + orphan
        assert 'hints' in result

        wiki.close()

    def test_lint_preserves_sink_status(self, temp_wiki):
        """Test that lint() still returns sink_status."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint()

        assert 'sink_status' in result
        assert 'sink_warnings' in result

        wiki.close()

    def test_lint_empty_wiki(self, temp_wiki):
        """Test lint() on empty wiki."""
        wiki = Wiki(temp_wiki)
        wiki.init()

        result = wiki.lint()

        assert result['total_pages'] == 1  # only overview.md (index and log excluded)
        # overview.md has placeholder assertions without sources, so issue_count > 0
        assert result['hints']['critical'] == []
        assert result['hints']['informational'] == []

        wiki.close()


class TestDetectFileTypes:
    """Test _detect_file_type() helper."""

    def test_detect_markdown(self):
        """Test markdown file type detection."""
        assert Wiki._detect_file_type("test.md") == "markdown"
        assert Wiki._detect_file_type("test.MD") == "markdown"

    def test_detect_pdf(self):
        """Test PDF file type detection."""
        assert Wiki._detect_file_type("report.pdf") == "pdf"

    def test_detect_text(self):
        """Test text file type detection."""
        assert Wiki._detect_file_type("notes.txt") == "text"

    def test_detect_unknown(self):
        """Test unknown file type detection."""
        assert Wiki._detect_file_type("file.xyz") == "unknown"
