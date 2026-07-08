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

    def test_url_encoded_path_components_are_decoded(self, wiki_root):
        # _serve_wiki_file calls unquote(path) before resolving, so encoded
        # path components are decoded first.  This handles CJK filenames in
        # double-encoded URLs from the browser.
        resp = _serve_wiki_file(wiki_root, "raw/%74est.pdf")
        assert resp.path == wiki_root / "raw" / "test.pdf"

    def test_url_encoded_traversal_is_rejected_with_403(self, wiki_root):
        # %2E%2E is decoded to .. by unquote(), then the resolved path
        # escapes the wiki root → 403, NOT 404.
        with pytest.raises(HTTPException) as exc_info:
            _serve_wiki_file(wiki_root, "%2E%2E/%2E%2E/etc/passwd")
        assert exc_info.value.status_code == 403
        assert "escapes" in exc_info.value.detail.lower()

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

    def test_serves_cjk_filename_via_url_encoded_path(self, wiki_root):
        """File with CJK chars in filename is served when the URL component
        is percent-encoded (typical browser behavior)."""
        name = "中文测试.pdf"
        (wiki_root / "raw" / name).write_bytes(b"%PDF-1.4\n")
        # %E4%B8%AD%E6%96%87%E6%B5%8B%E8%AF%95 = 中文测试
        encoded = "%E4%B8%AD%E6%96%87%E6%B5%8B%E8%AF%95.pdf"
        resp = _serve_wiki_file(wiki_root, f"raw/{encoded}")
        assert resp.path == wiki_root / "raw" / name

    def test_serves_cjk_filename_via_raw_unicode_path(self, wiki_root):
        """Decoded CJK chars in path are decoded once by ``unquote()``. A raw
        Unicode path component arrives at the server unencoded and must
        reach the right file."""
        # Some clients (curl on Linux with proper locale) submit raw CJK
        # characters directly. server's unquote() leaves them unchanged,
        # so file is found at the literal path.
        name = "测试文件.png"
        (wiki_root / "raw" / name).write_bytes(b"\x89PNG\r\n\x1a\n")
        resp = _serve_wiki_file(wiki_root, f"raw/{name}")
        assert resp.path == wiki_root / "raw" / name

    def test_png_media_type_is_inferred(self, wiki_root):
        """mimetypes.guess_type picks image/png for .png files so the
        browser does not force-download the asset."""
        resp = _serve_wiki_file(wiki_root, "raw/test.pdf")
        assert resp.media_type == "application/pdf"

    def test_content_disposition_uses_rfc5987_for_cjk_filenames(self, wiki_root):
        """Content-Disposition header uses RFC 5987 ``filename*`` for non-ASCII
        filenames so downloads work in all browsers."""
        name = "中文.pdf"
        (wiki_root / "raw" / name).write_bytes(b"%PDF-1.4\n")
        resp = _serve_wiki_file(wiki_root, "raw/中文.pdf")
        # starlette FileResponse stores headers in resp.headers (Mapping[str, str])
        cd = resp.headers.get("content-disposition", "")
        assert cd.startswith("inline;"), f"missing inline disposition: {cd!r}"
        assert "filename*=UTF-8''" in cd, f"missing RFC 5987: {cd!r}"
        assert "中文" not in cd, f"raw CJK leaked into disposition: {cd!r}"

    def test_content_disposition_is_inline_for_all_files(self, wiki_root):
        """All files use ``inline`` so PDFs/images render in-browser instead
        of triggering a download. This is the fix for Bug 1 (B1.2 inline)."""
        resp = _serve_wiki_file(wiki_root, "raw/test.pdf")
        cd = resp.headers.get("content-disposition", "")
        assert cd.startswith("inline;") is True
        assert "attachment" not in cd, f"unexpected attachment: {cd!r}"
