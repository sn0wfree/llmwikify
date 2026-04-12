"""Tests for Principle Compliance Checker (Phase 4c)."""

import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

from llmwikify.core.principle_checker import (
    PrincipleChecker,
    PrincipleViolation,
    PrincipleCheckResult,
    PRINCIPLE_DEFINITIONS,
)


class TestPrincipleViolation:
    def test_violation_creation(self):
        v = PrincipleViolation(
            principle="test",
            prompt_name="test_prompt",
            severity="warning",
            message="test message",
            suggestion="fix it",
        )
        assert v.principle == "test"
        assert v.severity == "warning"
        assert v.suggestion == "fix it"


class TestPrincipleCheckResult:
    def test_is_pass_with_no_violations(self):
        result = PrincipleCheckResult(prompt_name="test")
        assert result.is_pass is True
        assert result.score == 1.0

    def test_is_pass_with_info_violation(self):
        result = PrincipleCheckResult(
            prompt_name="test",
            violations=[PrincipleViolation(
                principle="test", prompt_name="test",
                severity="info", message="info",
            )],
        )
        assert result.is_pass is True

    def test_is_fail_with_error_violation(self):
        result = PrincipleCheckResult(
            prompt_name="test",
            violations=[PrincipleViolation(
                principle="test", prompt_name="test",
                severity="error", message="error",
            )],
        )
        assert result.is_pass is False

    def test_score_calculation(self):
        result = PrincipleCheckResult(
            prompt_name="test",
            passed_checks=3,
            total_checks=4,
        )
        assert result.score == 0.75

    def test_score_with_zero_checks(self):
        result = PrincipleCheckResult(prompt_name="test")
        assert result.score == 1.0


class TestPrincipleDefinitions:
    def test_all_principles_have_keywords(self):
        for name, definition in PRINCIPLE_DEFINITIONS.items():
            assert "keywords" in definition
            assert len(definition["keywords"]) > 0

    def test_all_principles_have_description(self):
        for name, definition in PRINCIPLE_DEFINITIONS.items():
            assert "description" in definition
            assert len(definition["description"]) > 0

    def test_all_principles_have_applies_to(self):
        for name, definition in PRINCIPLE_DEFINITIONS.items():
            assert "applies_to" in definition
            assert isinstance(definition["applies_to"], list)

    def test_known_principles_exist(self):
        expected = {
            "contradiction_detection",
            "fabrication_warning",
            "observational_language",
            "zero_domain_assumption",
            "wikilink_usage",
            "log_operation",
            "data_gap_detection",
        }
        assert set(PRINCIPLE_DEFINITIONS.keys()) == expected


class TestPrincipleCheckerCheckTemplate:
    @pytest.fixture
    def checker(self):
        return PrincipleChecker()

    def test_analyze_source_passes(self, checker):
        from llmwikify.core.prompt_registry import PromptRegistry
        registry = PromptRegistry()
        template = registry._load_template("analyze_source")
        data = {
            "name": "analyze_source",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "analyze_source"},
            "system": template.system,
            "user": template.user,
        }
        result = checker.check_template("analyze_source", data)
        assert result.is_pass is True

    def test_generate_wiki_ops_passes(self, checker):
        from llmwikify.core.prompt_registry import PromptRegistry
        registry = PromptRegistry()
        template = registry._load_template("generate_wiki_ops")
        data = {
            "name": "generate_wiki_ops",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "generate_wiki_ops"},
            "system": template.system,
            "user": template.user,
        }
        result = checker.check_template("generate_wiki_ops", data)
        assert result.is_pass is True

    def test_detects_missing_fabrication_warning(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "You are a test prompt.",
            "user": "Do something.",
        }
        result = checker.check_template("analyze_source", data)
        fabric_violations = [v for v in result.violations if v.principle == "fabrication_warning"]
        assert len(fabric_violations) == 1

    def test_detects_missing_contradiction(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "You are a test prompt.",
            "user": "Do something.",
        }
        result = checker.check_template("ingest_source", data)
        contradiction_violations = [v for v in result.violations if v.principle == "contradiction_detection"]
        assert len(contradiction_violations) == 1

    def test_detects_missing_wikilink(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "You are a test prompt.",
            "user": "Do something.",
        }
        result = checker.check_template("generate_wiki_ops", data)
        wikilink_violations = [v for v in result.violations if v.principle == "wikilink_usage"]
        assert len(wikilink_violations) == 1

    def test_detects_missing_data_gap(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "You are a test prompt.",
            "user": "Do something.",
        }
        result = checker.check_template("analyze_source", data)
        gap_violations = [v for v in result.violations if v.principle == "data_gap_detection"]
        assert len(gap_violations) == 1

    def test_does_not_check_principles_for_unrelated_prompts(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "No wikilinks here.",
            "user": "Do something.",
        }
        result = checker.check_template("ingest_instructions", data)
        wikilink_violations = [v for v in result.violations if v.principle == "wikilink_usage"]
        assert len(wikilink_violations) == 0

    def test_structural_check_missing_name(self, checker):
        data = {
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Do something.",
        }
        result = checker.check_template("test", data)
        name_violations = [v for v in result.violations if v.principle == "name_field"]
        assert len(name_violations) == 1
        assert name_violations[0].severity == "error"

    def test_structural_check_missing_content(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
        }
        result = checker.check_template("test", data)
        content_violations = [v for v in result.violations if v.principle == "content_field"]
        assert len(content_violations) == 1
        assert content_violations[0].severity == "error"

    def test_post_process_without_validate_schema(self, checker):
        data = {
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Do something.",
            "post_process": {"retry_on_failure": {"max_attempts": 2}},
        }
        result = checker.check_template("test", data)
        pp_violations = [v for v in result.violations if v.principle == "post_process_schema"]
        assert len(pp_violations) == 1


class TestPrincipleCheckerCheckAllTemplates:
    def test_all_builtin_templates_checked(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test_prompt.yaml").write_text(yaml.dump({
            "name": "test_prompt",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "System content with contradict and fabricate and [[wikilink]].",
            "user": "User content with observational and log.",
        }))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        results = checker.check_all_templates()
        assert "test_prompt" in results

    def test_ignores_underscore_files(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "_internal.yaml").write_text(yaml.dump({"data": "test"}))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        results = checker.check_all_templates()
        assert "_internal" not in results

    def test_builtins_all_checked(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        expected = {
            "analyze_source",
            "generate_wiki_ops",
            "ingest_instructions",
            "ingest_source",
            "investigate_lint",
            "wiki_schema",
            "wiki_synthesize",
        }
        assert set(results.keys()) == expected


class TestPrincipleCheckerContextInjection:
    def test_valid_context_injection_no_issues(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Test.",
            "context_injection": {
                "wiki_index": "_get_index_summary",
                "page_count": "_get_page_count",
            },
        }))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        issues = checker.check_context_injection()
        assert len(issues) == 0

    def test_invalid_context_injection_reported(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Test.",
            "context_injection": {
                "invalid_key": "_nonexistent_method",
            },
        }))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        issues = checker.check_context_injection()
        assert len(issues) == 1
        assert issues[0]["method"] == "_nonexistent_method"


class TestPrincipleCheckerSchemaCoverage:
    def test_known_schemas_no_issues(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Test.",
            "post_process": {"validate_schema": "operations_array"},
        }))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        issues = checker.check_schema_coverage()
        assert len(issues) == 0

    def test_unknown_schema_reported(self, tmp_path):
        defaults_dir = tmp_path
        (defaults_dir / "test.yaml").write_text(yaml.dump({
            "name": "test",
            "version": "1.0",
            "trigger": {"type": "api_call", "when": "test"},
            "system": "Content.",
            "user": "Test.",
            "post_process": {"validate_schema": "unknown_schema"},
        }))

        checker = PrincipleChecker(defaults_dir=defaults_dir)
        issues = checker.check_schema_coverage()
        assert len(issues) == 1
        assert "unknown_schema" in issues[0]["issue"]


class TestPrincipleCheckerReports:
    def test_generate_text_report(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        report = checker.generate_report(results)
        assert "Prompt Principle Compliance Report" in report
        assert "analyze_source" in report
        assert "Overall:" in report

    def test_generate_json_report(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        report = checker.generate_json_report(results)
        assert "templates_checked" in report
        assert "overall_score" in report
        assert "prompts" in report
        assert isinstance(report["overall_score"], float)

    def test_json_report_has_correct_structure(self):
        checker = PrincipleChecker()
        report = checker.generate_json_report()
        prompt = report["prompts"]["analyze_source"]
        assert "status" in prompt
        assert "score" in prompt
        assert "violations" in prompt
        assert "passed_checks" in prompt
        assert "total_checks" in prompt


class TestPrincipleCheckerBuiltins:
    """Verify built-in templates against known principles."""

    def test_analyze_source_has_contradiction(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        assert results["analyze_source"].is_pass is True
        contradiction_violations = [
            v for v in results["analyze_source"].violations
            if v.principle == "contradiction_detection"
        ]
        assert len(contradiction_violations) == 0

    def test_analyze_source_has_fabrication_warning(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        fabrication_violations = [
            v for v in results["analyze_source"].violations
            if v.principle == "fabrication_warning"
        ]
        assert len(fabrication_violations) == 0

    def test_wiki_synthesize_has_observational_language(self):
        checker = PrincipleChecker()
        results = checker.check_all_templates()
        obs_violations = [
            v for v in results["wiki_synthesize"].violations
            if v.principle == "observational_language"
        ]
        assert len(obs_violations) == 0

    def test_overall_score_above_minimum(self):
        checker = PrincipleChecker()
        report = checker.generate_json_report()
        assert report["overall_score"] >= 0.80
