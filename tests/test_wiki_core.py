"""Tests for Wiki core class."""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestWiki:
    """Test Wiki core class."""
    
    def test_init(self, temp_wiki):
        """Test wiki initialization."""
        wiki = Wiki(temp_wiki)
        result = wiki.init()
        
        assert result['status'] == 'created'
        assert 'index.md' in result['created_files']
        assert 'log.md' in result['created_files']
        assert '.wiki-config.yaml.example' in result['created_files']
        assert 'wiki.md' in result['created_files']
        assert 'raw/' in result['skipped_files']
        assert 'wiki/' in result['skipped_files']
        assert (temp_wiki / 'raw').exists()
        assert (temp_wiki / 'wiki').exists()
        assert (temp_wiki / 'wiki' / 'index.md').exists()
        assert (temp_wiki / 'wiki' / 'log.md').exists()
        assert (temp_wiki / '.wiki-config.yaml.example').exists()
        assert (temp_wiki / 'wiki.md').exists()
        
        wiki.close()
    
    def test_init_idempotent(self, temp_wiki):
        """Test that init is idempotent without overwrite."""
        wiki = Wiki(temp_wiki)
        result1 = wiki.init()
        assert result1['status'] == 'created'
        
        result2 = wiki.init()
        assert result2['status'] == 'already_exists'
        assert result2['created_files'] == []
        assert 'raw/' in result2['existing_files']
        assert 'wiki/' in result2['existing_files']
        assert 'index.md' in result2['existing_files']
        assert 'log.md' in result2['existing_files']
        
        wiki.close()
    
    def test_init_overwrite(self, temp_wiki):
        """Test that init with overwrite recreates index and log."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Write custom content to log.md
        (temp_wiki / 'wiki' / 'log.md').write_text("# Custom Log\n")
        
        result = wiki.init(overwrite=True)
        
        assert result['status'] == 'created'
        assert 'index.md' in result['created_files']
        assert 'log.md' in result['created_files']
        assert 'wiki.md' in result['skipped_files']
        assert '.wiki-config.yaml.example' in result['skipped_files']
        
        # log.md should be recreated
        log_content = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert "# Custom Log" not in log_content
        assert "Initialized:" in log_content
        
        wiki.close()
    
    def test_write_page(self, temp_wiki):
        """Test page writing."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.write_page("Test Page", "# Test\n\nContent")
        
        assert "Created" in result
        assert (temp_wiki / 'wiki' / 'Test Page.md').exists()
        
        # Test update
        result2 = wiki.write_page("Test Page", "# Test\n\nUpdated")
        assert "Updated" in result2
        
        wiki.close()
    
    def test_read_page(self, temp_wiki):
        """Test page reading."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Test Page", "# Test\n\nContent")
        result = wiki.read_page("Test Page")
        
        assert 'content' in result
        assert "# Test" in result['content']
        
        # Test not found
        result2 = wiki.read_page("Nonexistent")
        assert 'error' in result2
        
        wiki.close()
    
    def test_append_log(self, temp_wiki):
        """Test log appending."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.append_log("test", "Test operation")
        
        assert "Logged" in result
        assert (temp_wiki / 'wiki' / 'log.md').exists()
        
        log_content = (temp_wiki / 'wiki' / 'log.md').read_text()
        assert "test" in log_content
        assert "Test operation" in log_content
        
        wiki.close()
    
    def test_status(self, temp_wiki):
        """Test status reporting."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Test", "# Test")
        result = wiki.status()
        
        assert result['initialized'] == True
        # page_count includes index.md and log.md
        assert result['page_count'] == 3  # Test + index + log
        
        wiki.close()
    
    def test_lint(self, temp_wiki):
        """Test health check."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create page with broken link
        wiki.write_page("Test", "# Test\n\n[[Nonexistent Page]]")
        
        result = wiki.lint()
        
        assert 'issue_count' in result
        assert result['issue_count'] > 0  # Has broken link and orphan
        
        wiki.close()
    
    def test_search(self, temp_wiki, sample_content):
        """Test full-text search."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Gold Mining", "# Gold Mining\n\nGold content here")
        wiki.write_page("Copper Mining", "# Copper Mining\n\nCopper content here")
        
        results = wiki.search("gold", limit=10)
        
        assert len(results) == 1
        assert 'Gold Mining' in results[0]['page_name']
        
        wiki.close()
    
    def test_build_index(self, temp_wiki):
        """Test index building."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Page A", "# A\n\n[[Page B]]")
        wiki.write_page("Page B", "# B")
        
        result = wiki.build_index(auto_export=True)
        
        # total_pages includes index.md and log.md
        assert result['total_pages'] == 4  # Page A + Page B + index + log
        # Links: Page A → Page B (1) + index.md → Page A, Page B (2) = 3
        assert result['total_links'] == 3
        assert 'json_export' in result
        
        wiki.close()
    
    def test_ingest_source_file(self, temp_wiki):
        """Test source ingestion returns data without auto-creating pages."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create test file
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here")
        
        result = wiki.ingest_source(str(test_file))
        
        assert 'error' not in result
        assert result['source_type'] == 'markdown'
        assert 'Test Document' in result['title']
        assert 'content' in result
        assert 'instructions' in result
        assert 'current_index' in result
        assert result['saved_to_raw'] == False
        assert result['already_exists'] == False
        
        wiki.close()
    
    def test_ingest_saves_url_to_raw(self, temp_wiki, monkeypatch):
        """Test that URL/YouTube sources are saved to raw/."""
        from llmwikify.extractors import ExtractedContent
        
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        mock_result = ExtractedContent(
            text="Article content here",
            source_type="url",
            title="Test Article",
            metadata={"url": "https://example.com/article"}
        )
        from llmwikify.core import wiki as wiki_module
        orig_extract = wiki_module.extract
        wiki_module.extract = lambda *a, **k: mock_result
        
        result = wiki.ingest_source("https://example.com/article")
        
        wiki_module.extract = orig_extract
        
        assert 'error' not in result
        assert result['saved_to_raw'] == True
        assert result['source_name'] == 'test-article.md'
        
        saved_file = temp_wiki / 'raw' / 'test-article.md'
        assert saved_file.exists()
        assert saved_file.read_text() == "Article content here"
        
        wiki.close()
    
    def test_ingest_url_already_exists(self, temp_wiki, monkeypatch):
        """Test that re-ingesting same URL reports already_exists."""
        from llmwikify.extractors import ExtractedContent
        
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        saved_file = temp_wiki / 'raw' / 'test-article.md'
        saved_file.write_text("Existing content")
        
        mock_result = ExtractedContent(
            text="New article content",
            source_type="url",
            title="Test Article",
            metadata={"url": "https://example.com/article"}
        )
        from llmwikify.core import wiki as wiki_module
        orig_extract = wiki_module.extract
        wiki_module.extract = lambda *a, **k: mock_result
        
        result = wiki.ingest_source("https://example.com/article")
        
        wiki_module.extract = orig_extract
        
        assert 'error' not in result
        assert result['already_exists'] == True
        assert result['saved_to_raw'] == False
        assert saved_file.read_text() == "Existing content"
        
        wiki.close()
    
    def test_llm_process_source(self, temp_wiki, monkeypatch):
        """Test LLM processing returns operations list."""
        wiki = Wiki(temp_wiki, config={'llm': {'enabled': True, 'api_key': 'test', 'model': 'gpt-4o'}})
        wiki.init()
        
        operations_data = [
            {"action": "write_page", "page_name": "Test Page", "content": "# Test Page\n\nContent"},
            {"action": "log", "operation": "ingest", "details": "Test source"},
        ]
        
        class MockClient:
            @classmethod
            def from_config(cls, config):
                return cls()
            def chat_json(self, messages):
                return operations_data
        
        import sys
        import llmwikify.llm_client as llm_module
        orig_client = llm_module.LLMClient
        llm_module.LLMClient = MockClient
        sys.modules['llmwikify.llm_client'] = llm_module
        sys.modules['llmwikify.core.llm_client'] = llm_module
        
        source_data = {
            "title": "Test Source",
            "source_type": "text",
            "content": "Some content to analyze",
            "current_index": "",
        }
        
        result = wiki._llm_process_source(source_data)
        
        llm_module.LLMClient = orig_client
        sys.modules['llmwikify.llm_client'] = llm_module
        
        assert result['status'] == 'success'
        assert len(result['operations']) == 2
        assert result['operations'][0]['action'] == 'write_page'
        
        wiki.close()
    
    def test_execute_operations(self, temp_wiki):
        """Test executing LLM-generated operations."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        operations = [
            {"action": "write_page", "page_name": "Test Page", "content": "# Test Page\n\nContent"},
            {"action": "log", "operation": "ingest", "details": "Test source"},
            {"action": "write_page", "page_name": "", "content": ""},  # invalid
        ]
        
        result = wiki.execute_operations(operations)
        
        assert result['status'] == 'completed'
        assert result['operations_executed'] == 3
        assert result['results'][0]['status'] == 'done'
        assert result['results'][1]['status'] == 'done'
        assert result['results'][2]['status'] == 'skipped'
        
        # Verify page was created
        page = temp_wiki / 'wiki' / 'Test Page.md'
        assert page.exists()
        
        wiki.close()
    
    def test_slugify(self):
        """Test slug generation."""
        assert Wiki._slugify("Hello World") == "hello-world"
        assert Wiki._slugify("Special!@# Characters") == "special-characters"
        assert Wiki._slugify("Already-hyphenated") == "already-hyphenated"
    
    def test_no_exclusion_without_config(self, temp_wiki):
        """Verify zero domain assumption: no defaults."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Without config, date pages should NOT be excluded
        assert wiki._should_exclude_orphan('2025-07-31', temp_wiki / 'wiki' / '2025-07-31.md') == False
        assert wiki._should_exclude_orphan('2025-07', temp_wiki / 'wiki' / '2025-07.md') == False
        assert wiki._should_exclude_orphan('2025-Q1', temp_wiki / 'wiki' / '2025-Q1.md') == False
    
    def test_exclusion_with_explicit_config(self, temp_wiki):
        """Verify user-configured patterns work."""
        config = {
            'orphan_detection': {
                'exclude_patterns': [
                    r'^\d{4}-\d{2}-\d{2}$',
                    r'^\d{4}-\d{2}$',
                    r'^\d{4}-q[1-4]$',  # lowercase for case-insensitive matching
                ]
            }
        }
        wiki = Wiki(temp_wiki, config=config)
        wiki.init()
        
        # With explicit config, date pages should be excluded
        assert wiki._should_exclude_orphan('2025-07-31', temp_wiki / 'wiki' / '2025-07-31.md') == True
        assert wiki._should_exclude_orphan('2025-07', temp_wiki / 'wiki' / '2025-07.md') == True
        assert wiki._should_exclude_orphan('2025-Q1', temp_wiki / 'wiki' / '2025-Q1.md') == True
    
    def test_no_redirect_exclusion_without_config(self, temp_wiki):
        """Verify redirect_to is not excluded by default."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        redirect_page = temp_wiki / 'wiki' / 'Redirect.md'
        redirect_page.write_text("""---
redirect_to: target.md
---
# Redirect
""")
        
        # Without config, redirect_to pages should NOT be excluded
        assert wiki._should_exclude_orphan('redirect', redirect_page) == False
    
    def test_redirect_exclusion_with_config(self, temp_wiki):
        """Verify redirect_to works when configured."""
        config = {
            'orphan_detection': {
                'exclude_frontmatter': ['redirect_to']
            }
        }
        wiki = Wiki(temp_wiki, config=config)
        wiki.init()
        
        redirect_page = temp_wiki / 'wiki' / 'Redirect.md'
        redirect_page.write_text("""---
redirect_to: target.md
---
# Redirect
""")
        
        # With explicit config, redirect_to pages should be excluded
        assert wiki._should_exclude_orphan('redirect', redirect_page) == True
    
    def test_should_exclude_orphan_normal_page(self, temp_wiki):
        """Test that normal pages are not excluded from orphan detection."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        normal_page = temp_wiki / 'wiki' / 'Important Page.md'
        normal_page.write_text("# Important")
        
        assert wiki._should_exclude_orphan('important-page', normal_page) == False
    
    def test_should_exclude_orphan_user_config(self, temp_wiki):
        """Test that user-configured patterns are respected."""
        config = {
            'orphan_detection': {
                'exclude_patterns': [r'^draft-.*']
            }
        }
        wiki = Wiki(temp_wiki, config=config)
        wiki.init()
        
        draft_page = temp_wiki / 'wiki' / 'draft-test.md'
        draft_page.write_text("# Draft")
        
        assert wiki._should_exclude_orphan('draft-test', draft_page) == True
    
    def test_lint_respects_config(self, temp_wiki):
        """Test that lint() respects user configuration."""
        config = {
            'orphan_detection': {
                'exclude_patterns': [r'^\d{4}-\d{2}-\d{2}$']
            }
        }
        wiki = Wiki(temp_wiki, config=config)
        wiki.init()
        
        # Create dated page (should be excluded when configured)
        dated = temp_wiki / 'wiki' / '2025-07-31.md'
        dated.write_text("# Daily Summary")
        
        # Create normal page (should be reported)
        wiki.write_page("Orphan Company", "# Company")
        
        result = wiki.lint()
        
        orphan_issues = [i for i in result['issues'] if i.get('type') or i.get('issue_type') == 'orphan_page']
        orphan_names = [i.get('page', '').lower().replace(' ', '-') for i in orphan_issues]
        
        assert 'orphan-company' in orphan_names  # Should report
        assert '2025-07-31' not in orphan_names  # Should NOT report
    
    def test_read_schema(self, temp_wiki):
        """Test reading wiki.md schema."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.read_schema()
        
        assert 'content' in result
        assert 'file' in result
        assert 'hint' in result
        assert '# Wiki Schema' in result['content']
        assert 'wiki.md' in result['file']
        
        wiki.close()
    
    def test_read_schema_has_hint(self, temp_wiki):
        """Test that read_schema includes backup hint."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        result = wiki.read_schema()
        
        assert 'hint' in result
        assert 'Save a copy' in result['hint']
        assert 'before making changes' in result['hint']
        
        wiki.close()
    
    def test_read_schema_not_initialized(self, temp_wiki):
        """Test reading schema before init returns error."""
        wiki = Wiki(temp_wiki)
        
        result = wiki.read_schema()
        
        assert 'error' in result
        assert 'Run init() first' in result['error']
        
        wiki.close()
    
    def test_update_schema(self, temp_wiki):
        """Test updating wiki.md schema."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        original_content = wiki.read_schema()['content']
        new_content = "# New Schema\n\nUpdated conventions\n"
        
        result = wiki.update_schema(new_content)
        
        assert result['status'] == 'updated'
        assert 'file' in result
        assert 'suggestions' in result
        assert result['suggestions'][0].startswith('Review existing')
        
        # Verify content was updated
        read_result = wiki.read_schema()
        assert read_result['content'] == new_content
        
        wiki.close()
    
    def test_update_schema_warnings(self, temp_wiki):
        """Test that update_schema returns warnings for bad format."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Missing title header
        result = wiki.update_schema("Just some text without a title")
        assert 'warnings' in result
        assert any('title header' in w for w in result['warnings'])
        
        # Content too short
        result = wiki.update_schema("# Title\n")
        assert 'warnings' in result
        assert any('too short' in w for w in result['warnings'])
        
        # Good content should have no warnings
        result = wiki.update_schema("# Schema\n\nThis is a proper schema file with enough content to be valid.")
        assert 'warnings' not in result
        
        wiki.close()
    
    def test_update_schema_not_initialized(self, temp_wiki):
        """Test updating schema before init returns error."""
        wiki = Wiki(temp_wiki)
        
        result = wiki.update_schema("# Test\n")
        
        assert 'error' in result
        assert 'Run init() first' in result['error']
