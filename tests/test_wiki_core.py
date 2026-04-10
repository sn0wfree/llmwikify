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
        # Remove pre-created directories
        import shutil
        if (temp_wiki / 'wiki').exists():
            shutil.rmtree(temp_wiki / 'wiki')
        if (temp_wiki / 'raw').exists():
            shutil.rmtree(temp_wiki / 'raw')
        
        wiki = Wiki(temp_wiki)
        result = wiki.init(agent="claude")
        
        assert "Wiki initialized" in result
        assert (temp_wiki / 'raw').exists()
        assert (temp_wiki / 'wiki').exists()
        assert (temp_wiki / 'wiki' / 'index.md').exists()
        assert (temp_wiki / 'wiki' / 'log.md').exists()
        assert (temp_wiki / '.wiki-config.yaml.example').exists()
        
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
        assert result['total_links'] == 1
        assert 'json_export' in result
        
        wiki.close()
    
    def test_ingest_source_file(self, temp_wiki):
        """Test source ingestion from file."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create test file
        test_file = temp_wiki / 'raw' / 'test.md'
        test_file.write_text("# Test Document\n\nContent here")
        
        result = wiki.ingest_source(str(test_file))
        
        assert 'error' not in result
        assert result['source_type'] == 'markdown'
        assert 'Test Document' in result['title']
        
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
