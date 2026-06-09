"""Unit tests for ingest_skill pipeline.

Tests the ingest pipeline: extract + write + read orchestration.
No real I/O, all tests use mocks.

Target: 10+ tests, no I/O, mocks for wiki and actions.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills import SkillContext, SkillResult
from llmwikify.apps.chat.skills.pipelines.ingest_skill import (
    IngestSkill,
    _derive_page_name,
    _ingest,
    ingest_skill,
)


# ─── Skill metadata ─────────────────────────────────────────────


class TestIngestSkillMetadata:
    def test_name(self):
        assert ingest_skill.name == "ingest"

    def test_has_ingest_content_action(self):
        assert "ingest_content" in ingest_skill.actions

    def test_action_handler_is_callable(self):
        action = ingest_skill.actions["ingest_content"]
        assert callable(action.handler)

    def test_input_schema_has_url_or_path(self):
        schema = ingest_skill.actions["ingest_content"].input_schema
        assert "url_or_path" in schema["properties"]

    def test_input_schema_has_page_name(self):
        schema = ingest_skill.actions["ingest_content"].input_schema
        assert "page_name" in schema["properties"]

    def test_input_schema_has_content(self):
        schema = ingest_skill.actions["ingest_content"].input_schema
        assert "content" in schema["properties"]


# ─── Page name derivation ────────────────────────────────────────


class TestDerivePageName:
    def test_url_to_page_name(self):
        name = _derive_page_name("https://example.com/my-article")
        assert name == "my_article"

    def test_file_path_to_page_name(self):
        name = _derive_page_name("/path/to/my-doc.md")
        assert name == "my_doc"

    def test_empty_returns_untitled(self):
        name = _derive_page_name("")
        assert name == "untitled"

    def test_long_name_truncated(self):
        name = _derive_page_name("a" * 200)
        assert len(name) <= 100


# ─── Ingest with direct content ──────────────────────────────────


class TestIngestDirectContent:
    @pytest.mark.asyncio
    async def test_ingest_direct_content(self):
        """Direct content should skip extraction."""
        ctx = SkillContext(db=None, config={})
        result = await _ingest(
            {"url_or_path": "", "content": "Hello world", "page_name": "test_page"},
            ctx,
        )
        assert result.status == "ok"
        assert result.data["page_name"] == "test_page"
        assert result.data["extracted"] is False

    @pytest.mark.asyncio
    async def test_ingest_no_content_no_url_fails(self):
        ctx = SkillContext(db=None, config={})
        result = await _ingest({}, ctx)
        assert result.status == "error"


# ─── Ingest with extract ─────────────────────────────────────────


class TestIngestWithExtract:
    @pytest.mark.asyncio
    async def test_ingest_url_derives_page_name(self):
        """URL without page_name should derive one."""
        ctx = SkillContext(db=None, config={})
        # Mock the extract action
        from unittest.mock import AsyncMock, MagicMock, patch

        mock_extract_result = MagicMock()
        mock_extract_result.status = "ok"
        mock_extract_result.data = {
            "content": "Extracted content",
            "page_name": "derived_page",
        }
        mock_extract_skill = MagicMock()
        mock_extract_skill.actions = {
            "extract": MagicMock(handler=AsyncMock(return_value=mock_extract_result))
        }

        with patch(
            "llmwikify.apps.chat.skills.actions.extract_action.extract_skill",
            mock_extract_skill,
        ):
            result = await _ingest(
                {"url_or_path": "https://example.com/article"},
                ctx,
            )
            assert result.status == "ok"
            assert result.data["page_name"] == "derived_page"
            assert result.data["extracted"] is True


# ─── Wiki interaction ────────────────────────────────────────────


class TestIngestWithWiki:
    @pytest.mark.asyncio
    async def test_ingest_writes_to_wiki(self):
        """When wiki is available, content should be written."""
        from unittest.mock import AsyncMock, MagicMock, patch

        class MockWiki:
            def search(self, q, limit=5):
                return []

        ctx = SkillContext(db=None, config={})
        ctx.wiki = MockWiki()

        from unittest.mock import AsyncMock, MagicMock, patch

        # Mock extract
        mock_extract_result = MagicMock()
        mock_extract_result.status = "ok"
        mock_extract_result.data = {"content": "Content", "page_name": "test"}

        # Mock write
        mock_write_result = MagicMock()
        mock_write_result.status = "ok"

        # Mock read
        mock_read_result = MagicMock()
        mock_read_result.status = "ok"
        mock_read_result.data = {"name": "test", "content": "Content"}

        mock_extract_skill = MagicMock()
        mock_extract_skill.actions = {
            "extract": MagicMock(handler=AsyncMock(return_value=mock_extract_result))
        }
        mock_write_skill = MagicMock()
        mock_write_skill.actions = {
            "write_page": MagicMock(handler=AsyncMock(return_value=mock_write_result))
        }
        mock_read_skill = MagicMock()
        mock_read_skill.actions = {
            "read_page": MagicMock(handler=AsyncMock(return_value=mock_read_result))
        }

        with patch(
            "llmwikify.apps.chat.skills.actions.extract_action.extract_skill",
            mock_extract_skill,
        ), patch(
            "llmwikify.apps.chat.skills.actions.write_action.write_skill",
            mock_write_skill,
        ), patch(
            "llmwikify.apps.chat.skills.actions.read_action.read_skill",
            mock_read_skill,
        ):
            result = await _ingest(
                {"url_or_path": "https://example.com/article"},
                ctx,
            )
            assert result.status == "ok"
            assert result.data["written"] is True
            assert result.data["read_back"]["name"] == "test"
