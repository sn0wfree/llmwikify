"""Prompt Regression Tests (Phase 4d).

Ensures that prompt template modifications do not change core behavior.
Uses golden sources and mock LLM to verify pipeline outputs satisfy
property-level assertions.
"""

import json
import pytest
import yaml
import importlib.util
from pathlib import Path
from unittest.mock import patch, MagicMock

from llmwikify.core.wiki import Wiki
from llmwikify.core.prompt_registry import PromptRegistry
from llmwikify.core.principle_checker import PrincipleChecker

# Load mock_llm_framework directly
_framework_path = Path(__file__).parent / "fixtures" / "golden_sources" / "mock_llm_framework.py"
_spec = importlib.util.spec_from_file_location("mock_llm_framework", _framework_path)
_mock_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mock_mod)
GoldenTestRunner = _mock_mod.GoldenTestRunner
load_golden_sources = _mock_mod.load_golden_sources


GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden_sources"


class TestPromptRegression:
    """Core regression tests for prompt behavior."""

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

    def test_analyze_source_extracts_topics(self, temp_wiki):
        """analyze_source must extract at least 1 topic."""
        temp_wiki.config["llm"]["prompt_chaining"]["ingest"] = True

        analysis_response = {
            "topics": ["AI", "Machine Learning"],
            "entities": [],
            "key_facts": [],
            "suggested_pages": [],
            "cross_refs": [],
            "content_type": "article",
            "potential_contradictions": [],
            "data_gaps": [],
        }
        ops_response = [
            {"action": "log", "operation": "ingest", "details": "Processed"},
        ]

        call_count = 0
        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            return analysis_response if call_count == 1 else ops_response

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            source_data = {
                "content": "AI is transforming the world.",
                "title": "AI Article",
                "source_type": "markdown",
                "current_index": "",
            }
            result = temp_wiki._llm_process_source(source_data)
            assert result["status"] == "success"
            assert len(result["analysis"]["topics"]) >= 1

    def test_analyze_source_extracts_entities(self, temp_wiki):
        """Given a source with entities, must extract at least 1 entity."""
        temp_wiki.config["llm"]["prompt_chaining"]["ingest"] = True

        analysis_response = {
            "topics": ["tech"],
            "entities": [
                {"name": "OpenAI", "type": "organization", "attributes": {}},
                {"name": "GPT-5", "type": "concept", "attributes": {}},
            ],
            "key_facts": ["OpenAI released GPT-5"],
            "suggested_pages": [],
            "cross_refs": [],
            "content_type": "article",
            "potential_contradictions": [],
            "data_gaps": [],
        }
        ops_response = [
            {"action": "log", "operation": "ingest", "details": "Processed"},
        ]

        call_count = 0
        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            return analysis_response if call_count == 1 else ops_response

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            source_data = {
                "content": "OpenAI released GPT-5 in 2026.",
                "title": "GPT-5 Release",
                "source_type": "markdown",
                "current_index": "",
            }
            result = temp_wiki._llm_process_source(source_data)
            assert result["status"] == "success"
            assert len(result["analysis"]["entities"]) >= 1

    def test_analyze_source_detects_contradiction(self, temp_wiki):
        """Given contradictory source and wiki index, must mark contradiction."""
        temp_wiki.config["llm"]["prompt_chaining"]["ingest"] = True

        analysis_response = {
            "topics": ["AI Safety"],
            "entities": [],
            "key_facts": [],
            "suggested_pages": [],
            "cross_refs": [],
            "content_type": "article",
            "potential_contradictions": [
                "Source claims AI is fully safe, wiki index says challenges remain"
            ],
            "data_gaps": [],
        }
        ops_response = [
            {"action": "log", "operation": "ingest", "details": "Processed"},
        ]

        call_count = 0
        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            return analysis_response if call_count == 1 else ops_response

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            source_data = {
                "content": "AI is completely safe and aligned.",
                "title": "AI Safety",
                "source_type": "markdown",
                "current_index": "- [[AI Safety]] - Major challenges remain in alignment",
            }
            result = temp_wiki._llm_process_source(source_data)
            assert result["status"] == "success"
            assert len(result["analysis"]["potential_contradictions"]) >= 1

    def test_generate_wiki_ops_creates_write_page(self, temp_wiki):
        """Given analysis result, must generate at least 1 write_page operation."""
        temp_wiki.config["llm"]["prompt_chaining"]["ingest"] = True

        analysis_result = {
            "topics": ["AI"],
            "entities": [],
            "key_facts": [],
            "suggested_pages": [
                {"name": "Artificial Intelligence", "summary": "About AI", "priority": "high"}
            ],
            "cross_refs": [],
            "content_type": "article",
            "potential_contradictions": [],
            "data_gaps": [],
        }

        ops_result = [
            {"action": "write_page", "page_name": "Artificial Intelligence", "content": "# AI\n\nContent."},
            {"action": "log", "operation": "ingest", "details": "Created 1 page"},
        ]

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

            source_data = {
                "content": "AI is important.",
                "title": "AI Article",
                "source_type": "markdown",
                "current_index": "",
            }
            result = temp_wiki._llm_process_source(source_data)
            assert result["status"] == "success"
            assert result["mode"] == "chained"
            assert len(result["operations"]) >= 1
            assert result["operations"][0]["action"] == "write_page"

    def test_generate_wiki_ops_includes_log(self, temp_wiki):
        """Generated operations must include at least 1 log operation."""
        temp_wiki.config["llm"]["prompt_chaining"]["ingest"] = True

        analysis_result = {
            "topics": ["AI"],
            "entities": [],
            "key_facts": [],
            "suggested_pages": [{"name": "AI", "summary": "About AI", "priority": "high"}],
            "cross_refs": [],
            "content_type": "article",
            "potential_contradictions": [],
            "data_gaps": [],
        }

        ops_result = [
            {"action": "write_page", "page_name": "AI", "content": "# AI"},
            {"action": "log", "operation": "ingest", "details": "Done"},
        ]

        call_count = 0

        def side_effect(msgs, **kwargs):
            nonlocal call_count
            call_count += 1
            return analysis_result if call_count == 1 else ops_result

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.side_effect = side_effect
            MockClient.from_config.return_value = mock_instance

            source_data = {
                "content": "AI content.",
                "title": "AI",
                "source_type": "markdown",
                "current_index": "",
            }
            result = temp_wiki._llm_process_source(source_data)
            log_ops = [op for op in result["operations"] if op["action"] == "log"]
            assert len(log_ops) >= 1

    def test_synthesize_produces_structured_answer(self, temp_wiki):
        """synthesize must produce an answer with heading structure."""
        mock_response = {
            "answer": "# AI Overview\n\nAI is a broad field.\n\n## Key Points\n\n- Point 1\n- Point 2",
            "suggested_page_name": "Query: AI Overview",
            "source_citations": ["Machine Learning"],
        }

        with patch("llmwikify.llm_client.LLMClient") as MockClient:
            mock_instance = MagicMock()
            mock_instance.chat_json.return_value = mock_response
            MockClient.from_config.return_value = mock_instance

            result = temp_wiki._llm_generate_synthesize_answer("What is AI?")
            assert "warning" not in result
            assert result["answer"].startswith("#")


class TestGoldenSourceIntegration:
    """Tests using golden source files with mock LLM."""

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

    def test_golden_entity_extraction(self, temp_wiki):
        """Golden test 01: Entity extraction from technical article."""
        golden_spec = yaml.safe_load(
            (GOLDEN_DIR / "01_entity_extraction.yaml").read_text()
        )
        runner = GoldenTestRunner()
        result = runner.run_golden_test(golden_spec, temp_wiki)
        assert result.passed, f"Failed checks: {result.failures}"

    def test_golden_contradiction_detection(self, temp_wiki):
        """Golden test 02: Contradiction detection."""
        golden_spec = yaml.safe_load(
            (GOLDEN_DIR / "02_contradiction_detection.yaml").read_text()
        )
        runner = GoldenTestRunner()
        result = runner.run_golden_test(golden_spec, temp_wiki)
        assert result.passed, f"Failed checks: {result.failures}"

    def test_golden_data_gap_detection(self, temp_wiki):
        """Golden test 03: Data gap detection."""
        golden_spec = yaml.safe_load(
            (GOLDEN_DIR / "03_data_gap_detection.yaml").read_text()
        )
        runner = GoldenTestRunner()
        result = runner.run_golden_test(golden_spec, temp_wiki)
        assert result.passed, f"Failed checks: {result.failures}"

    def test_golden_wiki_ops_generation(self, temp_wiki):
        """Golden test 04: Wiki operations generation."""
        golden_spec = yaml.safe_load(
            (GOLDEN_DIR / "04_wiki_ops_generation.yaml").read_text()
        )
        runner = GoldenTestRunner()
        result = runner.run_golden_test(golden_spec, temp_wiki)
        assert result.passed, f"Failed checks: {result.failures}"

    def test_golden_synthesize_answer(self, temp_wiki):
        """Golden test 05: Synthesize structured answer."""
        golden_spec = yaml.safe_load(
            (GOLDEN_DIR / "05_synthesize_answer.yaml").read_text()
        )
        runner = GoldenTestRunner()
        result = runner.run_golden_test(golden_spec, temp_wiki)
        assert result.passed, f"Failed checks: {result.failures}"


class TestAllPromptsLoadable:
    """Verify all prompt templates load without error."""

    def test_all_builtin_prompts_load(self):
        registry = PromptRegistry()
        prompts = [
            "analyze_source", "generate_wiki_ops",
            "ingest_instructions", "investigate_lint", "wiki_schema",
            "wiki_synthesize",
        ]
        for name in prompts:
            template = registry._load_template(name)
            assert template.name == name

    def test_all_prompts_render(self):
        registry = PromptRegistry()
        prompts = [
            ("analyze_source", {"title": "T", "content": "C", "source_type": "md", "current_index": ""}),
            ("generate_wiki_ops", {"analysis_json": "{}", "current_index": ""}),
            ("wiki_synthesize", {"query": "Q?"}),
        ]
        for name, variables in prompts:
            messages = registry.get_messages(name, **variables)
            assert len(messages) >= 1


class TestContextInjectionMethodsExist:
    """Verify all context_injection references resolve to Wiki methods."""

    def test_all_referenced_methods_exist(self):
        import yaml
        defaults_dir = Path(__file__).parent.parent / "src" / "llmwikify" / "prompts" / "_defaults"

        wiki_methods = {
            "_get_index_summary", "_get_recent_log", "_get_page_count",
            "_get_existing_page_names",
        }

        for yaml_file in sorted(defaults_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            data = yaml.safe_load(yaml_file.read_text())
            ctx = data.get("context_injection", {})
            for key, spec in ctx.items():
                method_name = spec if isinstance(spec, str) else spec.get("method", "")
                assert method_name in wiki_methods, (
                    f"{yaml_file.stem}.{key}: method '{method_name}' not in Wiki class"
                )


class TestPromptPrincipleCompliance:
    """Regression test for principle compliance across all prompts."""

    def test_all_prompts_meet_minimum_score(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()

        for name, result in results.items():
            assert result.is_pass, (
                f"{name} has errors: {[v.message for v in result.violations if v.severity == 'error']}"
            )

    def test_overall_score_above_threshold(self):
        checker = PrincipleChecker()
        report = checker.generate_json_report()
        assert report["overall_score"] >= 0.80
