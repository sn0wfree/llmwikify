"""Tests for Phase 3: metadata, chaining, validation, context injection."""

import pytest
import yaml

from llmwikify.core.prompt_registry import PromptRegistry


@pytest.fixture
def full_template_dir(tmp_path):
    """Create a full set of test templates."""
    analyze = {
        "name": "analyze_source",
        "description": "Extract topics, entities, and key facts",
        "version": "1.0",
        "trigger": {"type": "api_call", "when": "analyze_source"},
        "params": {"max_tokens": 2048, "temperature": 0.1, "max_content_chars": 8000},
        "system": "You are an analyst. {% if provider == 'ollama' %}Output ONLY JSON.{% endif %}",
        "user": "Analyze: {{ title }}\nContent: {{ content }}",
        "post_process": {
            "validate_schema": "analysis_output",
            "required_keys": ["topics", "entities", "key_facts", "suggested_pages"],
            "retry_on_failure": {"max_attempts": 2},
        },
    }
    (tmp_path / "analyze_source.yaml").write_text(yaml.dump(analyze))

    ops = {
        "name": "generate_wiki_ops",
        "description": "Convert analysis to operations",
        "version": "1.0",
        "trigger": {"type": "api_call", "when": "generate_wiki_ops"},
        "params": {"max_tokens": 8192, "temperature": 0.1},
        "system": "You are a planner.",
        "user": "Analysis: {{ analysis_json }}\nIndex: {{ current_index }}",
        "context_injection": {
            "existing_pages": "_get_existing_page_names",
            "page_count": "_get_page_count",
        },
        "post_process": {
            "validate_schema": "operations_array",
            "required_type": "array",
            "retry_on_failure": {"max_attempts": 2},
        },
    }
    (tmp_path / "generate_wiki_ops.yaml").write_text(yaml.dump(ops))

    ingest = {
        "name": "ingest_source",
        "description": "DEPRECATED single-call ingest",
        "version": "1.1",
        "trigger": {"type": "api_call", "when": "ingest_source"},
        "params": {"max_tokens": 4096, "temperature": 0.1},
        "system": "You are an agent.",
        "user": "Ingest: {{ content }}",
        "post_process": {
            "validate_schema": "operations_array",
            "retry_on_failure": {"max_attempts": 2},
        },
    }
    (tmp_path / "ingest_source.yaml").write_text(yaml.dump(ingest))

    disabled_prompt = {
        "name": "old_prompt",
        "version": "1.0",
        "trigger": {"type": "disabled", "when": ""},
        "system": "Old",
        "user": "Old",
    }
    (tmp_path / "old_prompt.yaml").write_text(yaml.dump(disabled_prompt))

    auto_prompt = {
        "name": "auto_prompt",
        "version": "1.0",
        "trigger": {"type": "auto", "when": "wiki_init"},
        "system": "Auto",
        "user": "Auto",
    }
    (tmp_path / "auto_prompt.yaml").write_text(yaml.dump(auto_prompt))

    return tmp_path


class TestTriggerMetadata:
    def test_should_trigger_api_call(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        assert registry.should_trigger("analyze_source", "anything") is True

    def test_should_trigger_auto_match(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        assert registry.should_trigger("auto_prompt", "wiki_init") is True

    def test_should_trigger_auto_no_match(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        assert registry.should_trigger("auto_prompt", "other_event") is False

    def test_should_trigger_disabled(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        assert registry.should_trigger("old_prompt", "anything") is False

    def test_trigger_loaded_from_yaml(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        template = registry._load_template("analyze_source")

        assert template.trigger["type"] == "api_call"
        assert template.trigger["when"] == "analyze_source"

    def test_default_trigger_when_missing(self, tmp_path):
        minimal = {"name": "minimal", "version": "1.0"}
        (tmp_path / "minimal.yaml").write_text(yaml.dump(minimal))

        registry = PromptRegistry(custom_dir=tmp_path)
        template = registry._load_template("minimal")

        assert template.trigger == {"type": "api_call", "when": ""}


class TestPostProcessValidation:
    def test_validate_operations_valid(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        valid_ops = [
            {"action": "write_page", "page_name": "Test", "content": "# Test"},
            {"action": "log", "operation": "ingest", "details": "done"},
        ]

        errors = registry.validate_output("generate_wiki_ops", valid_ops)
        assert errors == []

    def test_validate_operations_not_array(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        errors = registry.validate_output("generate_wiki_ops", {"key": "value"})
        assert len(errors) >= 1
        assert any("Expected array" in e for e in errors)

    def test_validate_operations_unknown_action(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        ops = [{"action": "delete_page", "page_name": "X"}]
        errors = registry.validate_output("generate_wiki_ops", ops)
        assert len(errors) == 1
        assert "unknown action" in errors[0]

    def test_validate_write_page_missing_fields(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        ops = [{"action": "write_page", "page_name": "Test"}]
        errors = registry.validate_output("generate_wiki_ops", ops)
        assert any("missing 'content'" in e for e in errors)

    def test_validate_write_page_missing_name(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        ops = [{"action": "write_page", "content": "# Test"}]
        errors = registry.validate_output("generate_wiki_ops", ops)
        assert any("missing 'page_name'" in e for e in errors)

    def test_validate_analysis_output_valid(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        valid_analysis = {
            "topics": ["AI"],
            "entities": [{"name": "X", "type": "person"}],
            "key_facts": ["fact 1"],
            "suggested_pages": [{"name": "Page", "summary": "S", "priority": "high"}],
        }

        errors = registry.validate_output("analyze_source", valid_analysis)
        assert errors == []

    def test_validate_analysis_missing_keys(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        errors = registry.validate_output("analyze_source", {"topics": []})
        assert any("entities" in e for e in errors)
        assert any("key_facts" in e for e in errors)

    def test_validate_no_post_process(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        errors = registry.validate_output("auto_prompt", "anything")
        assert errors == []

    def test_retry_config(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        config = registry.get_retry_config("analyze_source")
        assert config["max_attempts"] == 2

    def test_retry_config_default(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        config = registry.get_retry_config("auto_prompt")
        assert config["max_attempts"] == 1


class TestContextInjection:
    def test_inject_context_simple(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        class FakeWiki:
            def _get_page_count(self):
                return 42

        wiki = FakeWiki()
        result = registry.inject_context({"count": "_get_page_count"}, wiki)

        assert result["count"] == 42

    def test_inject_context_with_params(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        class FakeWiki:
            def _get_recent_log(self, limit=3):
                return f"Last {limit} entries"

        wiki = FakeWiki()
        result = registry.inject_context(
            {"log": {"method": "_get_recent_log", "limit": 5}},
            wiki,
        )

        assert result["log"] == "Last 5 entries"

    def test_inject_context_unknown_method(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        class FakeWiki:
            pass

        wiki = FakeWiki()
        result = registry.inject_context({"x": "_nonexistent_method"}, wiki)

        assert result["x"] == ""

    def test_inject_context_method_error(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        class FakeWiki:
            def _get_page_count(self):
                raise RuntimeError("DB error")

        wiki = FakeWiki()
        result = registry.inject_context({"count": "_get_page_count"}, wiki)

        assert "context error" in result["count"]
        assert "RuntimeError" in result["count"]

    def test_inject_context_string_spec(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)

        class FakeWiki:
            def _get_existing_page_names(self):
                return ["A", "B"]

        wiki = FakeWiki()
        result = registry.inject_context({"pages": "_get_existing_page_names"}, wiki)

        assert result["pages"] == ["A", "B"]


class TestBuiltInTemplates:
    def test_analyze_source_has_contradiction_instruction(self):
        registry = PromptRegistry()
        template = registry._load_template("analyze_source")

        assert "CONTRADICT" in template.system
        assert "vague or unsupported" in template.system
        assert "data gaps" in template.system

    def test_generate_wiki_ops_has_context_injection(self):
        registry = PromptRegistry()
        template = registry._load_template("generate_wiki_ops")

        assert "existing_pages" in template.context_injection
        assert "page_count" in template.context_injection

    def test_generate_wiki_ops_has_post_process(self):
        registry = PromptRegistry()
        template = registry._load_template("generate_wiki_ops")

        assert template.post_process.get("validate_schema") == "operations_array"
        assert template.post_process.get("retry_on_failure", {}).get("max_attempts") == 2


class TestPromptTemplateMetadata:
    def test_all_metadata_fields_present(self, full_template_dir):
        registry = PromptRegistry(custom_dir=full_template_dir)
        template = registry._load_template("analyze_source")

        assert template.name == "analyze_source"
        assert template.description != ""
        assert template.version == "1.0"
        assert template.trigger == {"type": "api_call", "when": "analyze_source"}
        assert template.preconditions == []
        assert template.context_injection == {}
        assert template.post_process != {}
