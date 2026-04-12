"""Tests for offline prompt evaluation script (Phase 4b)."""

import pytest
import yaml
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from eval_prompts import PromptEvaluator, CheckResult


class TestCheckResult:
    def test_pass_result(self):
        result = CheckResult("test")
        result.pass_item("item 1")
        assert result.status == "PASS"
        assert result.count == 1
        assert result.score == 1.0

    def test_fail_result(self):
        result = CheckResult("test")
        result.pass_item("good")
        result.fail_item("bad")
        assert result.status == "FAIL"
        assert result.count == 2
        assert result.score == 0.5

    def test_warn_does_not_fail(self):
        result = CheckResult("test")
        result.pass_item("good")
        result.warn_item("warning")
        assert result.status == "PASS"
        assert result.score == 1.0

    def test_to_dict(self):
        result = CheckResult("test")
        result.pass_item("good")
        d = result.to_dict()
        assert d["status"] == "PASS"
        assert d["count"] == 1
        assert "good" in d["details"]
        assert isinstance(d["score"], float)


class TestPromptEvaluatorInit:
    def test_default_defaults_dir(self, tmp_path):
        defaults_dir = tmp_path / "prompts" / "_defaults"
        defaults_dir.mkdir(parents=True)
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        assert evaluator.defaults_dir == defaults_dir


class TestTemplateLoading:
    def test_valid_template(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "System content.",
            "user": "User content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_template_loading()
        assert result.status == "PASS"

    def test_invalid_yaml(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text("invalid: yaml: [}")
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_template_loading()
        assert result.status == "FAIL"

    def test_missing_name(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "version": "1.0",
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_template_loading()
        assert result.status == "FAIL"

    def test_ignores_underscore_files(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "_internal.yaml").write_text("invalid")
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_template_loading()
        assert result.status == "PASS"


class TestJinja2Rendering:
    def test_valid_template_renders(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "Hello {{ title }}!",
            "user": "Content: {{ content }}",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_jinja2_rendering()
        assert result.status == "PASS"

    def test_conditional_renders(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "{% if provider == 'ollama' %}OLLAMA{% endif %}",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_jinja2_rendering()
        assert result.status == "PASS"


class TestContextInjection:
    def test_valid_context(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "context_injection": {
                "wiki_index": "_get_index_summary",
                "page_count": "_get_page_count",
            },
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_context_injection()
        assert result.status == "PASS"

    def test_invalid_context(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "context_injection": {"invalid": "_nonexistent"},
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_context_injection()
        assert result.status == "FAIL"


class TestSchemaCoverage:
    def test_known_schema(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "post_process": {"validate_schema": "operations_array"},
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_schema_coverage()
        assert result.status == "PASS"

    def test_unknown_schema(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "post_process": {"validate_schema": "unknown"},
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_schema_coverage()
        assert result.status == "FAIL"


class TestTriggerConfig:
    def test_valid_trigger(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_trigger_config()
        assert result.status == "PASS"

    def test_invalid_trigger_type(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "invalid_type"},
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_trigger_config()
        assert result.status == "FAIL"


class TestCrossReference:
    def test_chain_valid(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "analyze_source.yaml").write_text(yaml.dump({
            "name": "analyze_source",
            "version": "1.0",
            "system": "Analyze.",
            "user": "Content.",
            "post_process": {"required_keys": ["topics", "entities"]},
        }))
        (defaults_dir / "generate_wiki_ops.yaml").write_text(yaml.dump({
            "name": "generate_wiki_ops",
            "version": "1.0",
            "system": "Generate ops.",
            "user": "Analysis: {{ analysis_json }}. Use suggested pages.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_cross_reference()
        assert result.status == "PASS"


class TestProviderOverrides:
    def test_ollama_conditional_renders(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "{% if provider == 'ollama' %}Output JSON{% endif %}",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_provider_overrides()
        assert result.status == "PASS"


class TestPromptMetadata:
    def test_complete_metadata(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "description": "A test prompt",
            "params": {"max_tokens": 1024},
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_prompt_metadata()
        assert result.status == "PASS"
        assert len(result.warnings) == 0

    def test_missing_metadata_warns(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        result = evaluator._check_prompt_metadata()
        assert result.status == "PASS"
        assert len(result.warnings) >= 1


class TestReports:
    def test_text_report(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        results = evaluator.run_all_checks()
        report = evaluator.generate_report(results)
        assert "Prompt Evaluation Report" in report
        assert "Summary:" in report

    def test_json_report(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        results = evaluator.run_all_checks()
        report = evaluator.generate_json_report(results)
        assert "overall_score" in report
        assert "checks" in report
        assert isinstance(report["overall_score"], float)

    def test_json_report_has_all_check_names(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "system": "Content.",
        }))
        evaluator = PromptEvaluator(defaults_dir=defaults_dir)
        results = evaluator.run_all_checks()
        report = evaluator.generate_json_report(results)
        expected_checks = {
            "template_loading", "jinja2_rendering", "context_injection",
            "schema_coverage", "trigger_config", "cross_reference",
            "provider_overrides", "prompt_metadata",
        }
        assert set(report["checks"].keys()) == expected_checks


class TestRunWithBuiltins:
    """Test evaluator against the actual built-in prompt templates."""

    def test_all_checks_pass_with_builtins(self):
        evaluator = PromptEvaluator()
        results = evaluator.run_all_checks()
        # All checks should pass (warnings are OK)
        for name, result in results.items():
            assert result.status == "PASS", f"{name} failed: {result.details}"

    def test_json_report_score_reasonable(self):
        evaluator = PromptEvaluator()
        results = evaluator.run_all_checks()
        report = evaluator.generate_json_report(results)
        assert report["overall_score"] >= 0.90
