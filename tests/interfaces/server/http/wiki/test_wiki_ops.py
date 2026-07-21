"""Tests for wiki/_wiki_ops.py 核心业务处理器。"""

from __future__ import annotations

import logging
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from llmwikify.interfaces.server.http.wiki._wiki_ops import (
    CONFIRMATION_TTL_SECONDS,
    check_remote_wiki_config,
    enrich_status,
    load_wiki_config,
    read_page_with_sink,
    validate_remote_url,
    write_page,
)

# ─── read_page_with_sink ──────────────────────────────────────

class TestReadPageWithSink:
    def test_normal_page(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"title": "test", "content": "..."}
        wiki.query_sink.get_info_for_page.return_value = {"sink_count": 0}
        result = read_page_with_sink(wiki, "test")
        assert result["title"] == "test"
        assert result["sink_count"] == 0

    def test_error_page(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"error": "not found"}
        with pytest.raises(HTTPException) as exc_info:
            read_page_with_sink(wiki, "missing")
        assert exc_info.value.status_code == 404

    def test_non_dict_page(self):
        wiki = MagicMock()
        wiki.read_page.return_value = "raw content"
        wiki.query_sink.get_info_for_page.return_value = {"sink_count": 0}
        result = read_page_with_sink(wiki, "test")
        assert result == "raw content"


# ─── write_page ───────────────────────────────────────────────

class TestWritePage:
    def test_normal_write(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"error": "not found"}
        wiki.write_page.return_value = "ok"
        result = write_page(wiki, "test", "content")
        assert result["page_name"] == "test"
        assert result["message"] == "ok"

    def test_empty_page_name(self):
        wiki = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "", "content")
        assert exc_info.value.status_code == 400
        assert "page_name required" in exc_info.value.detail

    def test_empty_content(self):
        wiki = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "")
        assert exc_info.value.status_code == 400
        assert "content required" in exc_info.value.detail

    def test_value_error(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"error": "not found"}
        wiki.write_page.side_effect = ValueError("Invalid page name: ../etc")
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "../etc", "content")
        assert exc_info.value.status_code == 400
        assert "Invalid page name" in exc_info.value.detail

    def test_conflict_returns_409_with_confirmation_id(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing content", "word_count": 100}
        db = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", db=db, wiki_id="wiki1")
        assert exc_info.value.status_code == 409
        detail = exc_info.value.detail
        assert detail["status"] == "conflict"
        assert "confirmation_id" in detail
        assert len(detail["confirmation_id"]) == 8
        assert detail["existing_page"]["word_count"] == 100
        db.save_confirmation.assert_called_once()
        kwargs = db.save_confirmation.call_args[0][0]
        assert kwargs["wiki_id"] == "wiki1"
        assert kwargs["arguments"]["page_name"] == "test"
        assert kwargs["arguments"]["expires_at"] > time.time()
        assert kwargs["arguments"]["expires_at"] <= time.time() + CONFIRMATION_TTL_SECONDS + 1

    def test_confirm_token_updates_page(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        wiki.write_page.return_value = "Updated page"
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki1",
            "status": "pending",
            "arguments": {"page_name": "test", "expires_at": time.time() + 300},
        }
        result = write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki1")
        assert result["page_name"] == "test"
        assert result["message"] == "Updated page"
        db.delete_confirmation.assert_called_once_with("abc12345")

    def test_invalid_token_returns_400(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        db = MagicMock()
        db.get_confirmation.return_value = None
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="invalid", db=db, wiki_id="wiki1")
        assert exc_info.value.status_code == 400
        assert "Invalid or expired" in exc_info.value.detail

    def test_token_page_name_mismatch_returns_400(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki1",
            "status": "pending",
            "arguments": {"page_name": "other_page", "expires_at": time.time() + 300},
        }
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki1")
        assert exc_info.value.status_code == 400
        assert "does not match page_name" in exc_info.value.detail

    def test_token_wiki_id_mismatch_returns_400(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki_a",
            "status": "pending",
            "arguments": {"page_name": "test", "expires_at": time.time() + 300},
        }
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki_b")
        assert exc_info.value.status_code == 400
        assert "does not match wiki_id" in exc_info.value.detail

    def test_token_expired_returns_400(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki1",
            "status": "pending",
            "arguments": {"page_name": "test", "expires_at": time.time() - 1},
        }
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki1")
        assert exc_info.value.status_code == 400
        assert "expired" in exc_info.value.detail

    def test_reused_approved_token_returns_400(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki1",
            "status": "approved",
            "arguments": {"page_name": "test", "expires_at": time.time() + 300},
        }
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki1")
        assert exc_info.value.status_code == 400
        assert "Invalid or expired" in exc_info.value.detail

    def test_conflict_without_db_returns_503(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", db=None, wiki_id="wiki1")
        assert exc_info.value.status_code == 503
        assert "cannot create confirmation" in exc_info.value.detail

    def test_retry_without_db_returns_503(self):
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        with pytest.raises(HTTPException) as exc_info:
            write_page(wiki, "test", "new content", confirm_token="abc12345", db=None, wiki_id="wiki1")
        assert exc_info.value.status_code == 503
        assert "cannot verify" in exc_info.value.detail

    def test_arguments_stored_as_json_string(self):
        """db.get_confirmation 返回 arguments 为 JSON 字符串，反序列化需正确处理。"""
        wiki = MagicMock()
        wiki.read_page.return_value = {"content": "existing", "word_count": 10}
        wiki.write_page.return_value = "Updated page"
        db = MagicMock()
        db.get_confirmation.return_value = {
            "id": "abc12345",
            "wiki_id": "wiki1",
            "status": "pending",
            "arguments": '{"page_name": "test", "expires_at": ' + str(time.time() + 300) + '}',
        }
        result = write_page(wiki, "test", "new content", confirm_token="abc12345", db=db, wiki_id="wiki1")
        assert result["message"] == "Updated page"
        db.delete_confirmation.assert_called_once_with("abc12345")


# ─── enrich_status ────────────────────────────────────────────

class TestEnrichStatus:
    def test_with_pages_by_type(self):
        status = {"pages_by_type": {"concept": 5, "skill": 3}}
        result = enrich_status(status)
        assert "all_types" in result
        assert set(result["all_types"]) == {"concept", "skill"}

    def test_without_pages_by_type(self):
        status = {"total": 8}
        result = enrich_status(status)
        assert "all_types" not in result

    def test_empty_status(self):
        result = enrich_status({})
        assert "all_types" not in result


# ─── validate_remote_url ──────────────────────────────────────

class TestValidateRemoteUrl:
    def test_allowed_host(self):
        validate_remote_url("https://wiki.example.com", ["*.example.com"])

    def test_blocked_host(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_remote_url("https://evil.com", ["*.example.com"])
        assert exc_info.value.status_code == 400
        assert "not in allowed_remote_hosts" in exc_info.value.detail

    def test_wildcard_allows_all(self):
        validate_remote_url("https://anything.com", ["*"])

    def test_empty_list_disables(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_remote_url("https://wiki.com", [])
        assert exc_info.value.status_code == 400
        assert "disabled" in exc_info.value.detail

    def test_no_scheme(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_remote_url("wiki.example.com", ["*"])
        assert exc_info.value.status_code == 400
        assert "http or https" in exc_info.value.detail

    def test_http_scheme_allowed(self):
        validate_remote_url("http://wiki.example.com", ["*"])

    def test_https_scheme_allowed(self):
        validate_remote_url("https://wiki.example.com", ["*"])

    def test_no_hostname(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_remote_url("https://", ["*"])
        assert exc_info.value.status_code == 400
        assert "hostname" in exc_info.value.detail


# ─── load_wiki_config ─────────────────────────────────────────

class TestLoadWikiConfig:
    def test_default_config(self, monkeypatch, tmp_path):
        from llmwikify.foundation.config import Config
        Config._instance = None
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        result = load_wiki_config()
        assert result == {"allowed_remote_hosts": ["*"]}
        Config._instance = None

    def test_custom_config(self, monkeypatch, tmp_path):
        import json

        from llmwikify.foundation.config import Config
        config_file = tmp_path / ".llmwikify" / "llmwikify.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({
            "wiki": {"allowed_remote_hosts": ["*.example.com"]}
        }))
        Config._instance = None
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        result = load_wiki_config()
        assert result == {"allowed_remote_hosts": ["*.example.com"]}
        Config._instance = None

    def test_missing_wiki_section(self, monkeypatch, tmp_path):
        import json

        from llmwikify.foundation.config import Config
        config_file = tmp_path / ".llmwikify" / "llmwikify.json"
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps({"llm": {}}))
        Config._instance = None
        monkeypatch.setenv("LLMWIKIFY_HOME", str(tmp_path))
        result = load_wiki_config()
        assert result == {"allowed_remote_hosts": ["*"]}
        Config._instance = None


# ─── check_remote_wiki_config ─────────────────────────────────

class TestCheckRemoteWikiConfig:
    def test_warning_log(self, caplog):
        with caplog.at_level(logging.WARNING):
            check_remote_wiki_config(["*"])
        assert "allows all hosts" in caplog.text

    def test_no_warning(self, caplog):
        with caplog.at_level(logging.WARNING):
            check_remote_wiki_config(["*.example.com"])
        assert "allows all hosts" not in caplog.text
