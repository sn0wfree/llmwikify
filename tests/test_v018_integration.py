"""Integration tests for Phase 3: chaining, retry, context methods, full flows."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from llmwikify.core.wiki import Wiki
from llmwikify.core.prompt_registry import PromptRegistry


class TestWikiContextMethods:
    """Tests for Wiki's context injection methods."""

    @pytest.fixture
    def initialized_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        return wiki

    def test_get_index_summary_empty(self, tmp_path):
        wiki = Wiki(tmp_path)
        result = wiki._get_index_summary()
        assert result == "(no index)"

    def test_get_index_summary_short(self, initialized_wiki):
        wiki = initialized_wiki
        wiki.index_file.write_text("# Wiki Index\n\n- Page 1: Summary one\n- Page 2: Summary two\n")

        result = wiki._get_index_summary()

        assert "Page 1" in result
        assert "Page 2" in result
        assert len(result) <= 500

    def test_get_index_summary_truncated(self, initialized_wiki):
        wiki = initialized_wiki
        long_content = "# Wiki Index\n\n" + "- X: Item\n" * 100
        wiki.index_file.write_text(long_content)

        result = wiki._get_index_summary()

        assert len(result) <= 500
        assert result.endswith("...")

    def test_get_recent_log_empty(self, tmp_path):
        wiki = Wiki(tmp_path)
        result = wiki._get_recent_log()
        assert result == "(no log)"

    def test_get_recent_log_limited(self, initialized_wiki):
        wiki = initialized_wiki
        lines = "\n".join(f"## [2026-04-{i:02d}] ingest | Source {i}" for i in range(1, 11))
        wiki.log_file.write_text(lines)

        result = wiki._get_recent_log(limit=3)

        assert "Source 8" in result
        assert "Source 9" in result
        assert "Source 10" in result
        assert "Source 7" not in result

    def test_get_recent_log_default_limit(self, initialized_wiki):
        wiki = initialized_wiki
        lines = "\n".join(f"## [2026-04-{i:02d}] ingest | Source {i}" for i in range(1, 8))
        wiki.log_file.write_text(lines)

        result = wiki._get_recent_log()

        entry_count = result.count("ingest")
        assert entry_count == 3

    def test_get_page_count(self, initialized_wiki):
        wiki = initialized_wiki
        (wiki.wiki_dir / "Page1.md").write_text("# Page1")
        (wiki.wiki_dir / "Page2.md").write_text("# Page2")
        (wiki.wiki_dir / "Page3.md").write_text("# Page3")

        result = wiki._get_page_count()
        assert result == 3

    def test_get_page_count_empty(self, initialized_wiki):
        wiki = initialized_wiki
        result = wiki._get_page_count()
        assert result == 0

    def test_get_existing_page_names(self, initialized_wiki):
        wiki = initialized_wiki
        (wiki.wiki_dir / "Alice.md").write_text("# Alice")
        (wiki.wiki_dir / "Bob.md").write_text("# Bob")

        result = wiki._get_existing_page_names()

        assert "Alice" in result
        assert "Bob" in result
        assert wiki._index_page_name not in result
        assert wiki._log_page_name not in result


class TestLLMRetryMechanism:
    """Tests for _call_llm_with_retry."""

    @pytest.fixture
    def temp_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.config["llm"] = {
            "enabled": True, "provider": "openai", "model": "gpt-4",
            "base_url": "http://localhost:11434", "api_key": "test", "timeout": 120,
            "prompt_chaining": {"ingest": False},
        }
        return wiki

    def test_call_llm_with_retry_success_first(self, temp_wiki):
        wiki = temp_wiki
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]
        params = {"temperature": 0.1}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = [{"action": "write_page", "page_name": "X", "content": "# X"}]
            MockClient.from_config.return_value = mock_instance

            result = wiki._call_llm_with_retry("ingest_source", messages, params)

            assert len(result) == 1
            assert mock_instance.chat_json.call_count == 1

    def test_call_llm_with_retry_success_second(self, temp_wiki):
        wiki = temp_wiki
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]
        params = {"temperature": 0.1}

        call_count = 0

        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"invalid": "not_an_array"}
            return [{"action": "write_page", "page_name": "X", "content": "# X"}]

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            result = wiki._call_llm_with_retry("ingest_source", messages, params)

            assert call_count == 2
            assert len(result) == 1

    def test_call_llm_with_retry_exhausted(self, temp_wiki):
        wiki = temp_wiki
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]
        params = {"temperature": 0.1}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = {"invalid": "response"}
            MockClient.from_config.return_value = mock_instance

            with pytest.raises(ValueError, match="failed after 2 attempts"):
                wiki._call_llm_with_retry("ingest_source", messages, params)

    def test_call_llm_with_retry_connection_error(self, temp_wiki):
        wiki = temp_wiki
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]
        params = {"temperature": 0.1}

        call_count = 0

        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("API timeout")
            return [{"action": "log", "operation": "test", "details": "ok"}]

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            result = wiki._call_llm_with_retry("ingest_source", messages, params)

            assert call_count == 2
            assert len(result) == 1

    def test_retry_messages_include_errors(self, temp_wiki):
        wiki = temp_wiki
        messages = [{"role": "system", "content": "test"}, {"role": "user", "content": "test"}]
        params = {"temperature": 0.1}

        captured_messages = []

        def side_effect(msgs, **kwargs):
            captured_messages.append(msgs)
            if len(captured_messages) == 1:
                return {"invalid": True}
            return [{"action": "log", "operation": "test", "details": "ok"}]

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            wiki._call_llm_with_retry("ingest_source", messages, params)

            assert len(captured_messages) == 2
            retry_user_content = captured_messages[1][1]["content"]
            assert "errors" in retry_user_content.lower()


class TestChainingMode:
    """Tests for single vs chained ingest mode."""

    @pytest.fixture
    def temp_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.config["llm"] = {
            "enabled": True, "provider": "openai", "model": "gpt-4",
            "base_url": "http://localhost:11434", "api_key": "test", "timeout": 120,
            "prompt_chaining": {"ingest": False},
        }
        return wiki

    def test_llm_process_source_single_mode(self, temp_wiki):
        wiki = temp_wiki
        source_data = {"content": "Test content", "title": "Test", "source_type": "markdown", "current_index": ""}

        with patch.object(wiki, "_llm_process_source_single", return_value={"status": "success", "operations": [], "mode": "single"}) as mock_single:
            with patch.object(wiki, "_llm_process_source_chained") as mock_chained:
                result = wiki._llm_process_source(source_data)

                mock_single.assert_called_once()
                mock_chained.assert_not_called()
                assert result["mode"] == "single"

    def test_llm_process_source_chained_mode(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        source_data = {"content": "Test content", "title": "Test", "source_type": "markdown", "current_index": ""}

        with patch.object(wiki, "_llm_process_source_chained", return_value={"status": "success", "operations": [], "analysis": {}, "mode": "chained"}) as mock_chained:
            with patch.object(wiki, "_llm_process_source_single") as mock_single:
                result = wiki._llm_process_source(source_data)

                mock_chained.assert_called_once()
                mock_single.assert_not_called()
                assert result["mode"] == "chained"

    def test_chained_returns_analysis(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        source_data = {"content": "Test content", "title": "Test", "source_type": "markdown", "current_index": ""}

        expected_analysis = {"topics": ["AI"], "entities": [], "key_facts": [], "suggested_pages": []}

        with patch.object(wiki, "_llm_process_source_chained", return_value={"status": "success", "operations": [], "analysis": expected_analysis, "mode": "chained"}):
            result = wiki._llm_process_source(source_data)

            assert "analysis" in result
            assert result["analysis"] == expected_analysis

    def test_chained_mode_with_context_injection(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        (wiki.wiki_dir / "Existing.md").write_text("# Existing")
        source_data = {"content": "Test content", "title": "Test", "source_type": "markdown", "current_index": ""}

        captured_messages = []
        analysis_result = {"topics": ["AI"], "entities": [], "key_facts": [], "suggested_pages": [], "cross_refs": [], "content_type": "test"}

        call_count = 0

        def mock_chat_json(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            captured_messages.append(msgs)
            if call_count == 1:
                return analysis_result
            return []

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = mock_chat_json
            MockClient.from_config.return_value = mock_instance

            wiki._llm_process_source(source_data)

            ops_messages = captured_messages[1]
            user_content = ops_messages[1]["content"]
            assert "Existing" in user_content


class TestValidationIntegration:
    """Tests for validation in the full pipeline."""

    @pytest.fixture
    def temp_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.config["llm"] = {
            "enabled": True, "provider": "openai", "model": "gpt-4",
            "base_url": "http://localhost:11434", "api_key": "test", "timeout": 120,
            "prompt_chaining": {"ingest": False},
        }
        return wiki

    def test_single_mode_validation_failure(self, temp_wiki):
        wiki = temp_wiki
        source_data = {"content": "Test", "title": "Test", "source_type": "markdown", "current_index": ""}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = {"not": "an_array"}
            MockClient.from_config.return_value = mock_instance

            with pytest.raises(ValueError, match="failed after 2 attempts|validation failed"):
                wiki._llm_process_source_single(source_data)

    def test_chained_mode_step1_validation_failure(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        source_data = {"content": "Test", "title": "Test", "source_type": "markdown", "current_index": ""}

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = {"missing": "required_keys"}
            MockClient.from_config.return_value = mock_instance

            with pytest.raises(ValueError, match="Analysis validation failed|failed after 2 attempts"):
                wiki._llm_process_source_chained(source_data)

    def test_chained_mode_step2_validation_failure(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        source_data = {"content": "Test", "title": "Test", "source_type": "markdown", "current_index": ""}

        analysis_result = {"topics": ["AI"], "entities": [], "key_facts": [], "suggested_pages": []}
        ops_result = {"not": "an_array"}

        call_count = 0

        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return analysis_result
            return ops_result

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            with pytest.raises(ValueError, match="Operations validation failed|failed after 2 attempts"):
                wiki._llm_process_source_chained(source_data)


class TestConfiguration:
    """Tests for chaining configuration."""

    def test_chaining_default_disabled(self, tmp_path):
        wiki = Wiki(tmp_path)
        assert wiki.config["llm"]["prompt_chaining"]["ingest"] is False

    def test_chaining_explicit_enabled(self, tmp_path):
        config = {
            "llm": {
                "enabled": True, "provider": "openai", "model": "gpt-4",
                "base_url": "http://localhost:11434", "api_key": "test", "timeout": 120,
                "prompt_chaining": {"ingest": True},
            },
        }
        wiki = Wiki(tmp_path, config=config)
        assert wiki.config["llm"]["prompt_chaining"]["ingest"] is True


class TestProviderRendering:
    """Tests for provider-specific prompt rendering."""

    def test_ollama_provider_in_messages(self):
        registry = PromptRegistry(provider="ollama")
        messages = registry.get_messages("analyze_source", title="Test", content="content", current_index="")

        system_content = messages[0]["content"]
        assert "Output ONLY valid JSON" in system_content

    def test_openai_provider_no_ollama_instruction(self):
        registry = PromptRegistry(provider="openai")
        messages = registry.get_messages("analyze_source", title="Test", content="content", current_index="")

        system_content = messages[0]["content"]
        assert "Output ONLY valid JSON" not in system_content


class TestFullIngestFlow:
    """End-to-end integration tests for ingest flows."""

    @pytest.fixture
    def temp_wiki(self, tmp_path):
        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.config["llm"] = {
            "enabled": True, "provider": "openai", "model": "gpt-4",
            "base_url": "http://localhost:11434", "api_key": "test", "timeout": 120,
            "prompt_chaining": {"ingest": False},
        }
        return wiki

    def test_full_ingest_single_flow(self, temp_wiki):
        wiki = temp_wiki
        source_file = wiki.raw_dir / "test_article.md"
        source_file.write_text("# Test Article\n\nThis is a test article about AI.\n\n## Key Points\n- AI is transformative\n- Machine learning is important\n")

        operations_data = [
            {"action": "write_page", "page_name": "Artificial Intelligence", "content": "# Artificial Intelligence\n\nTransformative technology.\n\nSee also: [[Machine Learning]]"},
            {"action": "write_page", "page_name": "Machine Learning", "content": "# Machine Learning\n\nImportant field of AI."},
            {"action": "log", "operation": "ingest", "details": "Ingested test_article.md, created 2 pages"},
        ]

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = operations_data
            MockClient.from_config.return_value = mock_instance

            ingest_result = wiki.ingest_source(str(source_file))
            assert "content" in ingest_result

            llm_result = wiki._llm_process_source(ingest_result)
            assert llm_result["status"] == "success"
            assert llm_result["mode"] == "single"
            assert len(llm_result["operations"]) == 3

            exec_result = wiki.execute_operations(llm_result["operations"])
            assert exec_result["status"] == "completed"
            assert exec_result["operations_executed"] == 3

        wiki.close()

    def test_full_ingest_chained_flow(self, temp_wiki):
        wiki = temp_wiki
        wiki.config["llm"]["prompt_chaining"]["ingest"] = True
        source_file = wiki.raw_dir / "test_article.md"
        source_file.write_text("# Test Article\n\nContent about AI.\n")

        analysis_result = {
            "topics": ["AI"],
            "entities": [{"name": "AI", "type": "concept", "attributes": {}}],
            "key_facts": ["AI is transformative"],
            "suggested_pages": [{"name": "Artificial Intelligence", "summary": "About AI", "priority": "high"}],
            "cross_refs": [],
            "content_type": "technical_article",
        }

        operations_data = [
            {"action": "write_page", "page_name": "Artificial Intelligence", "content": "# Artificial Intelligence\n\nTransformative."},
            {"action": "log", "operation": "ingest", "details": "Ingested test_article.md"},
        ]

        call_count = 0

        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return analysis_result
            return operations_data

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            ingest_result = wiki.ingest_source(str(source_file))
            assert "content" in ingest_result

            llm_result = wiki._llm_process_source(ingest_result)
            assert llm_result["status"] == "success"
            assert llm_result["mode"] == "chained"
            assert "analysis" in llm_result
            assert llm_result["analysis"]["topics"] == ["AI"]
            assert len(llm_result["operations"]) == 2

            exec_result = wiki.execute_operations(llm_result["operations"])
            assert exec_result["status"] == "completed"
            assert exec_result["operations_executed"] == 2

        wiki.close()
