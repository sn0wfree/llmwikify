# tests/scenarios/conftest.py
"""Shared fixtures for real-world scenario tests."""

import json
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory, cleaned up after test."""
    with tempfile.TemporaryDirectory(prefix="llmwikify_test_") as d:
        yield Path(d)


@pytest.fixture
def wiki(temp_dir):
    """Create a temporary wiki instance."""
    from llmwikify import create_wiki

    wiki_path = temp_dir / "test-wiki"
    return create_wiki(wiki_path)


@pytest.fixture
def llm_config():
    """Read LLM configuration from ~/.llmwikify/llmwikify.json."""
    config_path = Path.home() / ".llmwikify" / "llmwikify.json"
    if config_path.exists():
        data = json.loads(config_path.read_text())
        return data.get("llm", {})
    return {
        "provider": "minimax",
        "model": "minimax-M3",
        "base_url": "https://api.minimaxi.com/v1",
    }


@pytest.fixture
def llm_client(llm_config):
    """LLM client for testing."""
    from llmwikify.foundation.llm import LLMClient
    return LLMClient.from_config({"llm": llm_config})


@pytest.fixture
def server_url():
    """Server URL (server must be started before tests)."""
    return "http://localhost:8765"


@pytest.fixture
def test_pdf():
    """Path to test PDF file."""
    return Path(__file__).parent.parent.parent / "raw" / "1601.00991v3.pdf"


@pytest.fixture
def sample_markdown_file():
    """Path to sample markdown file for ingest testing."""
    return Path(__file__).parent.parent / "fixtures" / "sample_doc.md"


@pytest.fixture
def batch_dir():
    """Path to batch sources directory."""
    return Path(__file__).parent.parent / "fixtures" / "batch_sources"


@pytest.fixture
def sample_pages():
    """Sample wiki pages for testing."""
    return {
        "python-basics": "# Python Basics\n\nPython is a programming language.",
        "machine-learning": "# Machine Learning\n\nML is a subset of AI.",
        "data-science": "# Data Science\n\nData science uses Python and ML.",
    }
