"""Tests for PromptRegistry."""

import json
import tempfile
from pathlib import Path

import pytest
import yaml

from llmwikify.core.prompt_registry import PromptRegistry, PromptTemplate


@pytest.fixture
def temp_prompts_dir(tmp_path):
    """Create a temporary prompts directory with test templates."""
    defaults_dir = tmp_path / "_defaults"
    defaults_dir.mkdir()
    
    ingest_template = {
        "name": "ingest_source",
        "description": "Test ingest template",
        "version": "1.0",
        "params": {
            "max_tokens": 4096,
            "temperature": 0.1,
        },
        "system": "You are a wiki agent.\n{% if provider == 'ollama' %}Output only JSON.{% endif %}",
        "user": "Process: {{ title }}\nContent: {{ content }}\nMax chars: {{ max_content_chars }}",
    }
    (defaults_dir / "ingest_source.yaml").write_text(yaml.dump(ingest_template))
    
    investigate_template = {
        "name": "investigate_lint",
        "description": "Test investigate template",
        "version": "1.0",
        "params": {
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        "system": "You are an analyst.",
        "user": "Contradictions: {{ contradictions_json }}\nGaps: {{ data_gaps_json }}\nPages: {{ total_pages }}",
    }
    (defaults_dir / "investigate_lint.yaml").write_text(yaml.dump(investigate_template))
    
    return defaults_dir


@pytest.fixture
def custom_prompts_dir(tmp_path):
    """Create a custom prompts directory with override template."""
    custom_override = {
        "name": "ingest_source",
        "description": "Custom ingest override",
        "version": "2.0",
        "params": {
            "max_tokens": 8192,
            "temperature": 0.0,
        },
        "system": "Custom agent for {{ provider }}.",
        "user": "Custom: {{ title }}",
    }
    (tmp_path / "ingest_source.yaml").write_text(yaml.dump(custom_override))
    return tmp_path


class TestPromptRegistryInit:
    def test_default_provider(self):
        registry = PromptRegistry()
        assert registry.provider == "openai"
        assert registry.custom_dir is None
    
    def test_custom_provider(self):
        registry = PromptRegistry(provider="ollama")
        assert registry.provider == "ollama"
    
    def test_custom_dir(self, tmp_path):
        registry = PromptRegistry(custom_dir=tmp_path)
        assert registry.custom_dir == tmp_path


class TestPromptRegistryLoading:
    def test_load_builtin_ingest_template(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        template = registry._load_template("ingest_source")
        
        assert template.name == "ingest_source"
        assert template.version == "1.0"
        assert "wiki agent" in template.system
        assert template.params["max_tokens"] == 4096
    
    def test_load_builtin_investigate_template(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        template = registry._load_template("investigate_lint")
        
        assert template.name == "investigate_lint"
        assert "analyst" in template.system
    
    def test_custom_dir_takes_priority(self, temp_prompts_dir, custom_prompts_dir):
        registry = PromptRegistry(
            provider="openai",
            custom_dir=custom_prompts_dir,
        )
        
        template = registry._load_template("ingest_source")
        assert "Custom agent" in template.system
        assert template.params["max_tokens"] == 8192
    
    def test_file_not_found(self, tmp_path):
        registry = PromptRegistry(custom_dir=tmp_path)
        
        with pytest.raises(FileNotFoundError, match="not found"):
            registry._load_template("nonexistent")
    
    def test_caching(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        
        t1 = registry._load_template("ingest_source")
        t2 = registry._load_template("ingest_source")
        
        assert t1 is t2


class TestPromptRegistryRendering:
    def test_get_messages_openai(self, temp_prompts_dir):
        registry = PromptRegistry(provider="openai", custom_dir=temp_prompts_dir)
        
        messages = registry.get_messages(
            "ingest_source",
            title="Test Doc",
            content="Some content",
            max_content_chars=8000,
        )
        
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "wiki agent" in messages[0]["content"]
        assert "Output only JSON" not in messages[0]["content"]
        assert "Process: Test Doc" in messages[1]["content"]
        assert "Some content" in messages[1]["content"]
    
    def test_get_messages_ollama(self, temp_prompts_dir):
        registry = PromptRegistry(provider="ollama", custom_dir=temp_prompts_dir)
        
        messages = registry.get_messages(
            "ingest_source",
            title="Test Doc",
            content="Some content",
            max_content_chars=8000,
        )
        
        assert "Output only JSON" in messages[0]["content"]
    
    def test_get_messages_investigate(self, temp_prompts_dir):
        registry = PromptRegistry(provider="openai", custom_dir=temp_prompts_dir)
        
        contradictions = [{"type": "value_conflict", "page_a": "A", "page_b": "B"}]
        data_gaps = [{"type": "unsourced", "page": "C"}]
        
        messages = registry.get_messages(
            "investigate_lint",
            contradictions_json=json.dumps(contradictions, indent=2),
            data_gaps_json=json.dumps(data_gaps, indent=2),
            total_pages=42,
        )
        
        assert len(messages) == 2
        assert "Contradictions:" in messages[1]["content"]
        assert "Pages: 42" in messages[1]["content"]
    
    def test_get_messages_missing_variable(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        
        messages = registry.get_messages("ingest_source")
        
        assert "{{ title }}" not in messages[1]["content"]
    
    def test_get_messages_empty_template(self, tmp_path):
        empty_template = {
            "name": "empty",
            "version": "1.0",
            "params": {},
            "system": "",
            "user": "Just user: {{ name }}",
        }
        (tmp_path / "empty.yaml").write_text(yaml.dump(empty_template))
        
        registry = PromptRegistry(custom_dir=tmp_path)
        messages = registry.get_messages("empty", name="Test")
        
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
    
    def test_jinja2_conditionals(self, temp_prompts_dir):
        registry_openai = PromptRegistry(provider="openai", custom_dir=temp_prompts_dir)
        registry_ollama = PromptRegistry(provider="ollama", custom_dir=temp_prompts_dir)
        
        msg_openai = registry_openai.get_messages("ingest_source")
        msg_ollama = registry_ollama.get_messages("ingest_source")
        
        assert "Output only JSON" not in msg_openai[0]["content"]
        assert "Output only JSON" in msg_ollama[0]["content"]


class TestPromptRegistryParams:
    def test_get_params_ingest(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        
        params = registry.get_params("ingest_source")
        
        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.1
    
    def test_get_params_investigate(self, temp_prompts_dir):
        registry = PromptRegistry(custom_dir=temp_prompts_dir)
        
        params = registry.get_params("investigate_lint")
        
        assert params["max_tokens"] == 2048
        assert params["temperature"] == 0.3
    
    def test_custom_dir_params_override(self, temp_prompts_dir, custom_prompts_dir):
        registry = PromptRegistry(
            provider="openai",
            custom_dir=custom_prompts_dir,
        )
        
        params = registry.get_params("ingest_source")
        
        assert params["max_tokens"] == 8192
        assert params["temperature"] == 0.0


class TestPromptRegistryProviderOverrides:
    def test_yaml_provider_override(self, tmp_path):
        template_with_override = {
            "name": "test",
            "version": "1.0",
            "params": {"temperature": 0.1},
            "system": "Default system.",
            "user": "Default user.",
            "overrides": {
                "anthropic": {
                    "system": "Anthropic-specific system.",
                    "params": {"max_tokens": 8192},
                },
                "ollama": {
                    "system": "Ollama-specific system.",
                    "user": "Ollama user.",
                },
            },
        }
        (tmp_path / "test.yaml").write_text(yaml.dump(template_with_override))
        
        registry_openai = PromptRegistry(provider="openai", custom_dir=tmp_path)
        registry_anthropic = PromptRegistry(provider="anthropic", custom_dir=tmp_path)
        registry_ollama = PromptRegistry(provider="ollama", custom_dir=tmp_path)
        
        assert "Default system" in registry_openai._load_template("test").system
        assert "Anthropic-specific" in registry_anthropic._load_template("test").system
        assert "Ollama-specific" in registry_ollama._load_template("test").system
        assert "Ollama user" in registry_ollama._load_template("test").user
        
        assert registry_anthropic.get_params("test").get("max_tokens") == 8192


class TestPromptTemplate:
    def test_default_values(self):
        template = PromptTemplate(name="test", description="", version="1.0")
        
        assert template.params == {}
        assert template.system == ""
        assert template.user == ""
        assert template.document == ""
        assert template.text == ""


class TestRenderDocument:
    def test_render_document(self, tmp_path):
        doc_template = {
            "name": "doc_template",
            "version": "1.0",
            "params": {},
            "system": "",
            "user": "",
            "document": "# Document\n\nVersion: {{ version }}\nProvider: {{ provider }}",
            "text": "",
        }
        (tmp_path / "doc_template.yaml").write_text(yaml.dump(doc_template))
        
        registry = PromptRegistry(provider="openai", custom_dir=tmp_path)
        result = registry.render_document("doc_template", version="2.0")
        
        assert "# Document" in result
        assert "Version: 2.0" in result
        assert "Provider: openai" in result
    
    def test_render_document_with_raw_blocks(self, tmp_path):
        doc_template = {
            "name": "raw_doc",
            "version": "1.0",
            "params": {},
            "document": "Hello {% raw %}{{Topic}}{% endraw %} world: {{ name }}",
        }
        (tmp_path / "raw_doc.yaml").write_text(yaml.dump(doc_template))
        
        registry = PromptRegistry(custom_dir=tmp_path)
        result = registry.render_document("raw_doc", name="Test")
        
        assert "{{Topic}}" in result
        assert "Hello" in result
        assert "world: Test" in result
    
    def test_render_document_empty(self, tmp_path):
        empty_template = {
            "name": "empty_doc",
            "version": "1.0",
            "params": {},
        }
        (tmp_path / "empty_doc.yaml").write_text(yaml.dump(empty_template))
        
        registry = PromptRegistry(custom_dir=tmp_path)
        result = registry.render_document("empty_doc")
        
        assert result == ""


class TestRenderText:
    def test_render_text(self, tmp_path):
        text_template = {
            "name": "text_template",
            "version": "1.0",
            "params": {},
            "text": "Do this: {{ action }}\nProvider: {{ provider }}",
        }
        (tmp_path / "text_template.yaml").write_text(yaml.dump(text_template))
        
        registry = PromptRegistry(provider="ollama", custom_dir=tmp_path)
        result = registry.render_text("text_template", action="analyze")
        
        assert "Do this: analyze" in result
        assert "Provider: ollama" in result
    
    def test_render_text_empty(self, tmp_path):
        empty_template = {
            "name": "empty_text",
            "version": "1.0",
            "params": {},
        }
        (tmp_path / "empty_text.yaml").write_text(yaml.dump(empty_template))
        
        registry = PromptRegistry(custom_dir=tmp_path)
        result = registry.render_text("empty_text")
        
        assert result == ""


class TestGetApiParams:
    def test_filters_non_api_params(self, tmp_path):
        template = {
            "name": "mixed_params",
            "version": "1.0",
            "params": {
                "temperature": 0.1,
                "max_tokens": 4096,
                "max_content_chars": 8000,
                "custom_thing": "value",
            },
        }
        (tmp_path / "mixed_params.yaml").write_text(yaml.dump(template))
        
        registry = PromptRegistry(custom_dir=tmp_path)
        
        api_params = registry.get_api_params("mixed_params")
        all_params = registry.get_params("mixed_params")
        
        assert "temperature" in api_params
        assert "max_tokens" in api_params
        assert "max_content_chars" not in api_params
        assert "custom_thing" not in api_params
        
        assert "max_content_chars" in all_params


class TestBuiltInTemplates:
    def test_ingest_source_template_exists(self):
        registry = PromptRegistry()
        template = registry._load_template("ingest_source")
        
        assert template.name == "ingest_source"
        assert "wiki maintenance agent" in template.system
        assert template.params.get("max_tokens") == 4096
        assert template.params.get("temperature") == 0.1
    
    def test_investigate_lint_template_exists(self):
        registry = PromptRegistry()
        template = registry._load_template("investigate_lint")
        
        assert template.name == "investigate_lint"
        assert "quality analyst" in template.system
        assert template.params.get("max_tokens") == 2048
    
    def test_wiki_schema_template_exists(self):
        registry = PromptRegistry()
        template = registry._load_template("wiki_schema")
        
        assert template.name == "wiki_schema"
        assert "Wiki Schema" in template.document
        assert "version" in template.document
    
    def test_ingest_instructions_template_exists(self):
        registry = PromptRegistry()
        template = registry._load_template("ingest_instructions")
        
        assert template.name == "ingest_instructions"
        assert "source document" in template.text
        assert "## Sources" in template.text
    
    def test_wiki_schema_raw_blocks(self):
        registry = PromptRegistry()
        result = registry.render_document("wiki_schema", version="0.17.0")
        
        assert "{{Topic}}" in result
        assert "{{topic}}" in result
        assert "v0.17.0" in result
        assert "# Wiki Schema" in result
    
    def test_ingest_instructions_render(self):
        registry = PromptRegistry()
        result = registry.render_text("ingest_instructions")
        
        assert "## Sources" in result
        assert "NOT wikilinks" in result
        assert "[Source" in result
        assert "raw/" in result
