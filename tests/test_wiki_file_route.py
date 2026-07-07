"""Tests for wiki file serving route + path traversal protection.

The file-serving route (``GET /api/wiki/{wiki_id}/file/{path}``) must
reject any request whose resolved path escapes the wiki root.
"""

import pytest
from fastapi import HTTPException

from llmwikify.interfaces.server.http.routes import _serve_wiki_file


class TestServeWikiFile:
    @pytest.fixture
    def wiki_root(self, tmp_path):
        (tmp_path / "raw").mkdir()
        (tmp_path / "wiki").mkdir()
        (tmp_path / "raw" / "test.pdf").write_bytes(b"%PDF-1.4\n")
        (tmp_path / "wiki" / "page.md").write_text("---\ntitle: Page\n---\n")
        return tmp_path

    def test_serves_pdf_file(self, wiki_root):
        resp = _serve_wiki_file(wiki_root, "raw/test.pdf")
        assert resp.path == wiki_root / "raw" / "test.pdf"
        assert resp.path.read_bytes().startswith(b"%PDF-1.4")

    def test_serves_markdown_file(self, wiki_root):
        resp = _serve_wiki_file(wiki_root, "wiki/page.md")
        assert resp.path == wiki_root / "wiki" / "page.md"
        assert b"title: Page" in resp.path.read_bytes()

    def test_rejects_traversal_with_dotdot(self, wiki_root):
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "../../../etc/passwd")
        assert exc_info.value.status_code == 403
        assert "escapes" in exc_info.value.detail.lower()

    def test_url_encoded_dots_are_treated_as_literal_filename(self, wiki_root):
        # FastAPI's path param decoder preserves %2E as literal, so a request
        # like ``/file/%2E%2E/etc/passwd`` is a different (non-existent)
        # filename — 404, NOT 403. This documents the behavior.
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "%2E%2E/%2E%2E/etc/passwd")
        assert exc_info.value.status_code == 404

    def test_returns_404_for_missing_file(self, wiki_root):
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "raw/nonexistent.pdf")
        assert exc_info.value.status_code == 404

    def test_returns_400_for_empty_path(self, wiki_root):
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "")
        assert exc_info.value.status_code == 400

    def test_rejects_when_resolved_path_is_directory(self, wiki_root):
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "raw")
        assert exc_info.value.status_code == 404
        assert "File not found" in exc_info.value.detail

    def test_rejects_symlink_escape(self, wiki_root, tmp_path):
        outside = tmp_path.parent / "outside-secret.txt"
        outside.write_text("secret")
        link = wiki_root / "wiki" / "sneaky.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "wiki/sneaky.txt")
        assert exc_info.value.status_code == 403