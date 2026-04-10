"""Tests for LLM client."""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llmwikify.llm_client import LLMClient


class TestLLMClientConfig:
    """Test LLM client configuration."""
    
    def test_disabled_raises_error(self):
        config = {"llm": {"enabled": False}}
        with pytest.raises(ValueError, match="not enabled"):
            LLMClient.from_config(config)
    
    def test_missing_api_key_raises(self):
        config = {"llm": {"enabled": True, "api_key": ""}}
        with pytest.raises(ValueError, match="API key not configured"):
            LLMClient.from_config(config)
    
    def test_env_var_api_key(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "test-key-123")
        config = {"llm": {"enabled": True}}
        client = LLMClient.from_config(config)
        assert client.api_key == "test-key-123"
        monkeypatch.delenv("LLM_API_KEY")
    
    def test_env_prefix_syntax(self, monkeypatch):
        monkeypatch.setenv("API_KEY_VAR", "env-key")
        config = {"llm": {"enabled": True, "api_key": "env:API_KEY_VAR"}}
        client = LLMClient.from_config(config)
        assert client.api_key == "env-key"
        monkeypatch.delenv("API_KEY_VAR")
    
    def test_env_overrides_config(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "env-override")
        monkeypatch.setenv("LLM_MODEL", "env-model")
        config = {"llm": {"enabled": True, "api_key": "config-key", "model": "config-model"}}
        client = LLMClient.from_config(config)
        assert client.api_key == "env-override"
        assert client.model == "env-model"
        monkeypatch.delenv("LLM_API_KEY")
        monkeypatch.delenv("LLM_MODEL")
    
    def test_default_base_url(self):
        client = LLMClient(api_key="test")
        assert client.base_url == "https://api.openai.com"
    
    def test_ollama_default_url(self):
        client = LLMClient(provider="ollama", api_key="test")
        assert client.base_url == "http://localhost:11434/v1"


class TestJSONParsing:
    """Test JSON response parsing."""
    
    def test_plain_json(self):
        raw = '{"key": "value"}'
        result = LLMClient._parse_json_response(raw)
        assert result == {"key": "value"}
    
    def test_json_array(self):
        raw = '[{"a": 1}, {"b": 2}]'
        result = LLMClient._parse_json_response(raw)
        assert len(result) == 2
    
    def test_markdown_code_block(self):
        raw = "```json\n{\"key\": \"value\"}\n```"
        result = LLMClient._parse_json_response(raw)
        assert result == {"key": "value"}
    
    def test_markdown_without_lang(self):
        raw = "```\n{\"key\": \"value\"}\n```"
        result = LLMClient._parse_json_response(raw)
        assert result == {"key": "value"}
    
    def test_json_in_text(self):
        raw = "Here is the result:\n[1, 2, 3]\nHope that helps!"
        result = LLMClient._parse_json_response(raw)
        assert result == [1, 2, 3]
    
    def test_invalid_json_raises(self):
        raw = "not json at all"
        with pytest.raises(ValueError, match="Could not parse JSON"):
            LLMClient._parse_json_response(raw)
