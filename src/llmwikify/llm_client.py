"""Lightweight LLM client for OpenAI-compatible APIs."""

import os
import re
import json
from typing import Optional, List, Dict, Any


class LLMClient:
    """Minimal client for OpenAI-compatible APIs.
    
    Supports any provider with a /v1/chat/completions endpoint:
    OpenAI, Ollama, LocalAI, vLLM, LM Studio, etc.
    """
    
    def __init__(
        self,
        provider: str = "openai",
        base_url: str = "",
        api_key: str = "",
        model: str = "gpt-4o",
    ):
        self.provider = provider
        self.base_url = base_url.rstrip("/") if base_url else self._default_base_url(provider)
        self.api_key = api_key
        self.model = model
    
    @staticmethod
    def _default_base_url(provider: str) -> str:
        defaults = {
            "openai": "https://api.openai.com",
            "ollama": "http://localhost:11434/v1",
            "lmstudio": "http://localhost:1234/v1",
        }
        return defaults.get(provider, "https://api.openai.com")
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "LLMClient":
        """Create from merged config (supports env var overrides)."""
        llm_cfg = config.get("llm", {})
        
        # Check if LLM is enabled
        if not llm_cfg.get("enabled", False):
            raise ValueError("LLM is not enabled. Set llm.enabled=true in config.")
        
        # Resolve API key: env:VAR_NAME syntax or literal value
        api_key = llm_cfg.get("api_key", "")
        if isinstance(api_key, str) and api_key.startswith("env:"):
            var_name = api_key[4:]
            api_key = os.environ.get(var_name, "")
        
        # Env var overrides
        api_key = os.environ.get("LLM_API_KEY", api_key)
        base_url = os.environ.get("LLM_BASE_URL", llm_cfg.get("base_url", ""))
        model = os.environ.get("LLM_MODEL", llm_cfg.get("model", "gpt-4o"))
        provider = os.environ.get("LLM_PROVIDER", llm_cfg.get("provider", "openai"))
        
        if not api_key:
            raise ValueError("LLM API key not configured. Set api_key or LLM_API_KEY env var.")
        
        return cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )
    
    def chat(self, messages: List[Dict[str, str]], json_mode: bool = False) -> str:
        """Send chat completion request.
        
        Args:
            messages: List of {role, content} dicts
            json_mode: If True, request JSON response format
        
        Returns:
            Assistant response text
        """
        try:
            import requests
        except ImportError:
            raise ImportError("requests is required for LLM client: pip install requests")
        
        url = f"{self.base_url}/v1/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        
        payload = {
            "model": self.model,
            "messages": messages,
        }
        
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"LLM API request failed: {e}")
        except (KeyError, IndexError) as e:
            raise ValueError(f"Unexpected LLM API response format: {e}")
    
    def chat_json(self, messages: List[Dict[str, str]]) -> Any:
        """Send chat completion and parse JSON response.
        
        Handles markdown code blocks: ```json\n{...}\n```
        """
        raw = self.chat(messages, json_mode=True)
        return self._parse_json_response(raw)
    
    @staticmethod
    def _parse_json_response(raw: str) -> Any:
        """Extract JSON from potentially markdown-wrapped response."""
        # Try direct parse
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        
        # Try extracting from markdown code block
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try finding JSON array or object in text
        for pattern in (r"\[.*\]", r"\{.*\}"):
            match = re.search(pattern, raw, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        
        raise ValueError(f"Could not parse JSON from LLM response:\n{raw}")
