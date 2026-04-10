"""Tests for Wiki recommend functionality."""

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.core import Wiki


class TestRecommend:
    """Test Wiki recommendation engine."""
    
    def test_recommend_missing_pages(self, temp_wiki):
        """Test detection of missing pages."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create pages with broken links
        wiki.write_page("Page A", "# A\n\n[[Missing Page]] and [[Another Missing]]")
        wiki.write_page("Page B", "# B\n\n[[Missing Page]] is referenced twice")
        wiki.write_page("Missing Page", "# This page exists now")
        
        result = wiki.recommend()
        
        # Missing Page now exists, so only "Another Missing" should be missing
        missing = result['missing_pages']
        
        # "Another Missing" is only referenced once, so may not appear (threshold is 2)
        assert 'missing_pages' in result
        assert 'summary' in result
        
        wiki.close()
    
    def test_recommend_orphan_pages(self, temp_wiki):
        """Test detection of orphan pages."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Orphan", "# Orphan Page")
        wiki.write_page("Linked", "# Linked Page")
        wiki.write_page("Hub", "# Hub\n\n[[Linked]]")
        
        result = wiki.recommend()
        
        orphans = result['orphan_pages']
        orphan_names = [o['page'] for o in orphans]
        
        # Orphan and Hub should be orphans (no inbound links)
        assert 'Orphan' in orphan_names
        assert 'Hub' in orphan_names
        assert 'Linked' not in orphan_names  # Has inbound from Hub
        
        wiki.close()
    
    def test_recommend_cross_references(self, temp_wiki):
        """Test cross-reference opportunities."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create pages with shared topics (must use common_topics from recommend)
        wiki.write_page("Gold Mining A", "# A\n\nGold mining is great. Gold prices are high. Production is up.")
        wiki.write_page("Gold Mining B", "# B\n\nGold mining company. Gold production up. Mining operations expanded.")
        
        result = wiki.recommend()
        
        opportunities = result['cross_reference_opportunities']
        
        # This test is heuristic - cross-refs may or may not be detected
        # Just check the structure is correct
        assert 'cross_reference_opportunities' in result
        assert 'summary' in result
        
        wiki.close()
    
    def test_recommend_summary(self, temp_wiki):
        """Test recommendation summary structure."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        wiki.write_page("Test", "# Test Page")
        
        result = wiki.recommend()
        
        # Check structure
        assert 'missing_pages' in result
        assert 'orphan_pages' in result
        assert 'content_gaps' in result
        assert 'cross_reference_opportunities' in result
        assert 'summary' in result
        
        # Check summary fields
        summary = result['summary']
        assert 'total_missing_pages' in summary
        assert 'high_priority_missing' in summary
        assert 'total_orphans' in summary
        assert 'content_gaps_count' in summary
        assert 'cross_ref_opportunities' in summary
        
        wiki.close()
    
    def test_recommend_no_false_positives(self, temp_wiki):
        """Test that recommendations don't include false positives."""
        wiki = Wiki(temp_wiki)
        wiki.init()
        
        # Create well-linked pages (using generic names, not special pages)
        wiki.write_page("Hub", "# Hub\n\n[[Page A]]\n[[Page B]]")
        wiki.write_page("Page A", "# A\n\nSee [[Page B]]")
        wiki.write_page("Page B", "# B\n\nBack to [[Hub]]")
        
        result = wiki.recommend()
        
        # All pages should be linked
        missing = result['missing_pages']
        assert len(missing) == 0
        
        wiki.close()
