"""Unit tests for v0.25 web UI module."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from llmwikify.web.server import create_app, get_static_dir


class TestWebServer:
    """Test web server module."""

    def test_static_dir_exists(self):
        """Static directory should exist."""
        static_dir = get_static_dir()
        assert static_dir.exists()
        assert (static_dir / 'index.html').exists()
        assert (static_dir / 'css' / 'app.css').exists()
        assert (static_dir / 'js' / 'app.js').exists()

    def test_app_creates_successfully(self):
        """App should create without errors."""
        app = create_app('http://127.0.0.1:9999/mcp')
        assert app is not None

    def test_serves_index_html(self):
        """Should serve index.html at root."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/')
        assert resp.status_code == 200
        assert 'html' in resp.headers.get('content-type', '')
        assert 'llmwikify' in resp.text

    def test_serves_css(self):
        """Should serve CSS files."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/css/app.css')
        assert resp.status_code == 200
        assert 'css' in resp.headers.get('content-type', '')

    def test_serves_js(self):
        """Should serve JS files."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/js/app.js')
        assert resp.status_code == 200
        assert 'javascript' in resp.headers.get('content-type', '')

    def test_serves_lib_js(self):
        """Should serve library JS files."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/lib/marked.min.js')
        assert resp.status_code == 200
        assert 'javascript' in resp.headers.get('content-type', '')

    def test_health_endpoint_unavailable_mcp(self):
        """Health endpoint should return 503 when MCP is down."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/api/health')
        assert resp.status_code == 503
        data = resp.json()
        assert data['status'] == 'degraded'

    def test_rpc_proxy_invalid_json(self):
        """RPC proxy should handle invalid JSON."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.post('/api/rpc', content='not json', headers={'Content-Type': 'text/plain'})
        assert resp.status_code == 400

    def test_html_contains_required_elements(self):
        """Index HTML should contain required elements."""
        from starlette.testclient import TestClient
        app = create_app('http://127.0.0.1:9999/mcp')
        client = TestClient(app)

        resp = client.get('/')
        html = resp.text
        
        assert 'search-input' in html
        assert 'file-tree' in html
        assert 'preview-content' in html
        assert 'editor' in html
        assert 'backlinks-list' in html
        assert 'marked.min.js' in html
        assert 'app.js' in html


class TestCLIWebArgs:
    """Test CLI web arguments."""

    def test_serve_help_contains_web(self):
        """serve --help should mention --web."""
        from llmwikify.cli.commands import main
        import io
        from unittest.mock import patch

        help_output = io.StringIO()
        with patch('sys.argv', ['llmwikify', 'serve', '--help']):
            with patch('sys.stdout', help_output):
                with pytest.raises(SystemExit):
                    main()

        output = help_output.getvalue()
        assert '--web' in output
        assert '--web-port' in output
        assert '--mcp-port' in output
