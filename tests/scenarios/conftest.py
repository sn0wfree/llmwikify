# tests/scenarios/conftest.py
"""Shared fixtures for real-world scenario tests."""

import json
import os
import tempfile
from pathlib import Path

import httpx
import pytest


def _is_llm_available() -> bool:
    """Check if LLM API key is available (env var or config file)."""
    if os.environ.get("LLM_API_KEY"):
        return True
    config_path = Path.home() / ".llmwikify" / "llmwikify.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            return bool(data.get("llm", {}).get("api_key"))
        except (json.JSONDecodeError, OSError):
            return False
    return False


def _server_base_url() -> str:
    """Server URL for availability check."""
    return os.environ.get("SERVER_URL", "http://localhost:8765")


def _is_server_available() -> bool:
    """Check if the llmwikify server is reachable at SERVER_URL.

    Used to auto-skip integration tests marked with ``@pytest.mark.requires_server``
    when no server is running (e.g. CI jobs that don't start the server).
    """
    try:
        response = httpx.get(
            f"{_server_base_url()}/api/health", timeout=2.0
        )
        return response.status_code == 200
    except (httpx.HTTPError, httpx.RequestError, OSError):
        return False


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests when their prerequisites are unavailable.

    - ``@pytest.mark.llm`` → skip when no LLM_API_KEY
    - ``@pytest.mark.requires_server`` → skip when no server at SERVER_URL
    """
    skip_llm = pytest.mark.skip(reason="LLM_API_KEY not set")
    skip_server = pytest.mark.skip(
        reason=f"server not available at {_server_base_url()} "
        "(start with `llmwikify serve --port 8765` or set SERVER_URL)"
    )
    has_llm = _is_llm_available()
    has_server = _is_server_available()
    for item in items:
        if not has_llm and "llm" in item.keywords:
            item.add_marker(skip_llm)
        if not has_server and "requires_server" in item.keywords:
            item.add_marker(skip_server)


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
    """Read LLM configuration.

    Priority: env vars (LLM_*) > ~/.llmwikify/llmwikify.json > defaults.
    """
    if os.environ.get("LLM_API_KEY"):
        return {
            "provider": os.environ.get("LLM_PROVIDER", "minimax"),
            "model": os.environ.get("LLM_MODEL", "minimax-M3"),
            "base_url": os.environ.get(
                "LLM_BASE_URL", "https://api.minimaxi.com/v1"
            ),
            "api_key": os.environ.get("LLM_API_KEY"),
        }
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
    """Server URL.

    Priority: SERVER_URL env var (Docker) > localhost (local dev).
    Server must be started before tests that need it.
    """
    return os.environ.get("SERVER_URL", "http://localhost:8765")


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
