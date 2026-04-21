"""Playwright E2E test fixtures for llmwikify Web UI."""

import pytest
import tempfile
import subprocess
import socket
import time
import threading
from pathlib import Path

import uvicorn


@pytest.fixture(scope="session")
def test_wiki():
    """Create temporary wiki with test data."""
    with tempfile.TemporaryDirectory() as td:
        wiki_dir = Path(td)
        wiki = wiki_dir / "wiki"
        wiki.mkdir(parents=True)

        # Create test pages with meaningful content
        pages = {
            "concepts/AI": "# Artificial Intelligence\n\nAI is a broad field of computer science.\n\n[[Machine Learning]] is a subset of AI.",
            "concepts/ML": "# Machine Learning\n\nML uses statistical techniques to give computer systems the ability to learn.\n\nRelated to [[Artificial Intelligence]].",
            "concepts/DL": "# Deep Learning\n\nDeep learning is part of a broader family of ML methods.\n\nSee also [[Machine Learning]].",
            "entities/OpenAI": "# OpenAI\n\nOpenAI is an AI research organization.\n\nWorks on [[Artificial Intelligence]].",
            "entities/Google": "# Google\n\nGoogle is a technology company.\n\nInvests heavily in [[Machine Learning]] and [[Deep Learning]].",
            "index": "# Index\n\nWelcome to the wiki.\n\nPages: [[Artificial Intelligence]], [[Machine Learning]], [[Deep Learning]].",
        }

        for name, content in pages.items():
            page_path = wiki / f"{name}.md"
            page_path.parent.mkdir(parents=True, exist_ok=True)
            page_path.write_text(content)

        # Create wiki.md schema
        (wiki_dir / "wiki.md").write_text("# Wiki Schema\n\nThis is a test wiki.")

        # Create .llmwikify config
        config_dir = wiki_dir / ".llmwikify"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "config.json").write_text('{"wiki_dir": "wiki"}')

        yield wiki_dir


@pytest.fixture(scope="session")
def server_port():
    """Find an available port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def start_server(test_wiki, server_port):
    """Start Unified Server for all tests."""
    from llmwikify.core import Wiki
    from llmwikify.mcp.server import create_unified_server

    wiki = Wiki(test_wiki)
    wiki.build_index()
    app = create_unified_server(wiki)

    url = f"http://127.0.0.1:{server_port}"

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=server_port, log_level="error")

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()

    # Wait for server to be ready
    for _ in range(30):
        try:
            import urllib.request
            urllib.request.urlopen(f"{url}/api/wiki/status", timeout=1)
            break
        except Exception:
            time.sleep(0.2)
    else:
        raise RuntimeError(f"Server failed to start on {url}")

    yield url


@pytest.fixture
def wiki_server(start_server):
    """Return the server URL for tests."""
    return start_server
