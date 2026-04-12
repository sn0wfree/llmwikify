"""Tests for Phase 4f: wiki_synthesize prompt externalization."""

import json
import pytest
import yaml
from unittest.mock import patch, MagicMock
from pathlib import Path

from llmwikify.core.prompt_registry import PromptRegistry
from llmwikify.core.wiki import Wiki


class TestWikiSynthesizeTemplate:
    """Tests for the wiki_synthesize.yaml prompt template."""

    def test_template_exists(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert template.name == "wiki_synthesize"

    def test_template_has_trigger(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert template.trigger["type"] == "api_call"
        assert template.trigger["when"] == "synthesize_query"

    def test_template_has_context_injection(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert "wiki_page_count" in template.context_injection
        assert "wiki_index" in template.context_injection
        assert "existing_pages" in template.context_injection
        assert "recent_log" in template.context_injection

    def test_template_has_post_process(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert template.post_process.get("validate_schema") == "synthesize_output"
        assert "answer" in template.post_process.get("required_keys", [])
        assert template.post_process.get("retry_on_failure", {}).get("max_attempts") == 2

    def test_template_has_params(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert template.params.get("max_tokens") == 8192
        assert template.params.get("temperature") == 0.3

    def test_system_has_observational_language_instruction(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert "observational language" in template.system.lower()

    def test_system_has_wikilink_instruction(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert "[[wikilink]]" in template.system

    def test_system_has_no_fabrication_rule(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_synthesize")
        assert "fabricate" in template.system.lower()

    def test_ollama_override_in_system(self):
        registry = PromptRegistry(provider="ollama")
        template = registry._load_template("wiki_synthesize")
        messages = registry.get_messages("wiki_synthesize", query="test")
        system_content = messages[0]["content"]
        assert "IMPORTANT" in system_content

    def test_user_template_renders_query(self):
        registry = PromptRegistry()
        messages = registry.get_messages("wiki_synthesize", query="What is AI?")
        user_content = messages[1]["content"]
        assert "What is AI?" in user_content

    def test_user_template_handles_source_pages(self):
        registry = PromptRegistry()
        source_pages = [
            {"name": "Machine Learning", "content": "# ML\n\nContent about ML."},
            {"name": "Deep Learning", "content": "# DL\n\nContent about DL."},
        ]
        messages = registry.get_messages(
            "wiki_synthesize",
            query="What is AI?",
            source_pages=source_pages,
        )
        user_content = messages[1]["content"]
        assert "Machine Learning" in user_content
        assert "Deep Learning" in user_content

    def test_user_template_handles_raw_sources(self):
        registry = PromptRegistry()
        raw_sources = [
            {"name": "raw/article.md", "content": "Article content."},
        ]
        messages = registry.get_messages(
            "wiki_synthesize",
            query="What is AI?",
            raw_sources=raw_sources,
        )
        user_content = messages[1]["content"]
        assert "raw/article.md" in user_content

    def test_user_template_handles_empty_sources(self):
        registry = PromptRegistry()
        messages = registry.get_messages(
            "wiki_synthesize",
            query="What is AI?",
            source_pages=[],
            raw_sources=[],
        )
        user_content = messages[1]["content"]
        assert "What is AI?" in user_content

    def test_render_messages_with_context(self):
        registry = PromptRegistry()
        messages = registry.get_messages(
            "wiki_synthesize",
            query="What is AI?",
            wiki_page_count=10,
            existing_pages=["AI", "Machine Learning"],
            wiki_index="Index summary",
            recent_log="Recent activity",
        )
        system_content = messages[0]["content"]
        user_content = messages[1]["content"]
        assert "10 pages" in user_content or "Current Wiki State: 10" in user_content


class TestSynthesizeOutputValidation:
    """Tests for synthesize_output schema validation."""

    @pytest.fixture
    def registry(self):
        return PromptRegistry()

    def test_valid_output(self, registry):
        valid = {"answer": "# Test Answer\n\nThis is a comprehensive answer."}
        errors = registry.validate_output("wiki_synthesize", valid)
        assert errors == []

    def test_valid_output_with_extra_keys(self, registry):
        valid = {
            "answer": "# Test Answer\n\nThis is a comprehensive answer about the topic.",
            "suggested_page_name": "Query: Test",
            "source_citations": ["AI"],
        }
        errors = registry.validate_output("wiki_synthesize", valid)
        assert errors == []

    def test_missing_answer_key(self, registry):
        invalid = {"content": "# Test"}
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert any("answer" in e for e in errors)

    def test_answer_not_string(self, registry):
        invalid = {"answer": 123}
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert any("string" in e.lower() for e in errors)

    def test_answer_too_short(self, registry):
        invalid = {"answer": "hi"}
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert any("too short" in e.lower() for e in errors)

    def test_answer_missing_heading(self, registry):
        invalid = {"answer": "This answer has no heading.\n\nSome content here."}
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert any("heading" in e.lower() for e in errors)

    def test_answer_with_heading_valid(self, registry):
        valid = {"answer": "## Sub-heading Start\n\nContent here."}
        errors = registry.validate_output("wiki_synthesize", valid)
        assert errors == []

    def test_answer_empty_string(self, registry):
        invalid = {"answer": ""}
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert len(errors) >= 1

    def test_not_a_dict(self, registry):
        invalid = "just a string"
        errors = registry.validate_output("wiki_synthesize", invalid)
        assert any("object" in e.lower() or "dict" in e.lower() for e in errors)


class TestLLMGenerateSynthesizeAnswer:
    """Tests for Wiki._llm_generate_synthesize_answer."""

    @pytest.fixture
    def temp_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.config["llm"] = {
            "enabled": True,
            "provider": "openai",
            "model": "gpt-4",
            "base_url": "http://localhost:11434",
            "api_key": "test",
            "timeout": 120,
            "prompt_chaining": {"ingest": False},
        }
        return wiki

    def test_returns_warning_when_llm_unavailable(self, temp_wiki):
        temp_wiki.config["llm"]["enabled"] = False
        result = temp_wiki._llm_generate_synthesize_answer("What is AI?")
        assert "warning" in result
        assert result["answer"] == ""

    def test_calls_llm_with_correct_prompt(self, temp_wiki):
        expected_answer = "# AI Overview\n\nAI is a broad field."
        captured_messages = []

        def mock_chat_json(msgs, **kwargs):
            captured_messages.append(msgs)
            return {"answer": expected_answer}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            result = temp_wiki._llm_generate_synthesize_answer("What is AI?")

            assert result["answer"] == expected_answer
            assert len(captured_messages) == 1
            system_content = captured_messages[0][0]["content"]
            assert "observational language" in system_content.lower()

    def test_includes_source_page_content(self, temp_wiki):
        (temp_wiki.wiki_dir / "Machine Learning.md").write_text(
            "# Machine Learning\n\nML is a subset of AI."
        )

        def mock_chat_json(msgs, **kwargs):
            user_content = msgs[1]["content"]
            assert "Machine Learning" in user_content
            assert "ML is a subset of AI" in user_content
            return {"answer": "# Test\n\nContent."}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            temp_wiki._llm_generate_synthesize_answer(
                "What is AI?",
                source_pages=["Machine Learning"],
            )

    def test_includes_raw_source_content(self, temp_wiki):
        article = temp_wiki.raw_dir / "test_article.md"
        article.write_text("# Test Article\n\nSome content about AI.")

        def mock_chat_json(msgs, **kwargs):
            user_content = msgs[1]["content"]
            assert "test_article.md" in user_content
            return {"answer": "# Test\n\nContent."}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            temp_wiki._llm_generate_synthesize_answer(
                "What is AI?",
                raw_sources=["raw/test_article.md"],
            )

    def test_injects_wiki_context(self, temp_wiki):
        (temp_wiki.wiki_dir / "Page1.md").write_text("# Page 1")
        (temp_wiki.wiki_dir / "Page2.md").write_text("# Page 2")

        def mock_chat_json(msgs, **kwargs):
            user_content = msgs[1]["content"]
            assert "Page1" in user_content or "2 pages" in user_content
            return {"answer": "# Test\n\nContent."}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            temp_wiki._llm_generate_synthesize_answer("What is AI?")

    def test_validation_failure_returns_warning(self, temp_wiki):
        def mock_chat_json(msgs, **kwargs):
            return {"not_answer": "missing key"}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            result = temp_wiki._llm_generate_synthesize_answer("What is AI?")

            assert "warning" in result
            assert result["answer"] == ""

    def test_returns_suggested_page_name(self, temp_wiki):
        def mock_chat_json(msgs, **kwargs):
            return {
                "answer": "# AI Overview\n\nAI is a broad field of computer science.",
                "suggested_page_name": "Query: AI Overview",
                "source_citations": ["Machine Learning"],
            }

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            result = temp_wiki._llm_generate_synthesize_answer("What is AI?")

            assert result["suggested_page_name"] == "Query: AI Overview"
            assert result["source_citations"] == ["Machine Learning"]

    def test_llm_exception_returns_warning(self, temp_wiki):
        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = ConnectionError("API timeout")
            MockClient.from_config.return_value = mock_instance

            result = temp_wiki._llm_generate_synthesize_answer("What is AI?")

            assert "warning" in result
            assert result["answer"] == ""
