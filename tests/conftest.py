"""Pytest configuration and fixtures for llmwikify.py tests."""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.core import Wiki
from llmwikify.extractors import ExtractedContent


@pytest.fixture
def temp_wiki():
    """Create a temporary wiki directory for testing."""
    temp_dir = tempfile.mkdtemp()
    wiki_root = Path(temp_dir)

    # Initialize directory structure
    (wiki_root / 'raw').mkdir()
    (wiki_root / 'wiki').mkdir()

    yield wiki_root

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def wiki_instance(temp_wiki):
    """Create a Wiki instance with clean initialization."""
    # Ensure clean state
    if (temp_wiki / 'wiki').exists():
        import shutil
        shutil.rmtree(temp_wiki / 'wiki')
        shutil.rmtree(temp_wiki / 'raw')

    (temp_wiki / 'raw').mkdir()
    (temp_wiki / 'wiki').mkdir()

    wiki = Wiki(temp_wiki)
    wiki.index.initialize()
    yield wiki
    wiki.close()


@pytest.fixture
def sample_content():
    """Sample wiki page content with links."""
    return """# Test Page

This is a test page with [[Another Page]] and [[Third Page|Custom Display]].

## Section

More content with [[Another Page#section|linked to section]].
"""


@pytest.fixture
def sample_pdf_content():
    """Sample extracted PDF content."""
    return ExtractedContent(
        text="Test PDF content\n\nWith multiple pages",
        source_type="pdf",
        title="Test PDF",
        metadata={"page_count": 2}
    )
