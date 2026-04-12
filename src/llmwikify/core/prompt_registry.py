"""Prompt template registry with provider-specific overrides.

Uses YAML + Jinja2 for flexible, provider-aware prompt management.
Resolution order: user custom > built-in defaults with provider override applied.
"""

from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field

import yaml
from jinja2 import Environment, BaseLoader


@dataclass
class PromptTemplate:
    """A loaded prompt template with metadata."""
    name: str
    description: str
    version: str
    params: Dict[str, Any] = field(default_factory=dict)
    system: str = ""
    user: str = ""
    document: str = ""
    text: str = ""


API_PARAMS = {"temperature", "max_tokens", "top_p", "top_k", "stop", "presence_penalty", "frequency_penalty"}


class PromptRegistry:
    """Manages prompt templates with provider-specific overrides."""
    
    def __init__(
        self,
        provider: str = "openai",
        custom_dir: Optional[Path] = None,
    ):
        self.provider = provider
        self.custom_dir = custom_dir
        self._defaults_dir = Path(__file__).parent.parent / "prompts" / "_defaults"
        
        self._env = Environment(
            loader=BaseLoader(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        
        self._cache: Dict[str, PromptTemplate] = {}
    
    def get_messages(
        self,
        prompt_name: str,
        **variables: Any,
    ) -> List[Dict[str, str]]:
        """Load a prompt, render with Jinja2, return messages list."""
        template = self._load_template(prompt_name)
        
        render_vars = {**variables, "provider": self.provider}
        
        system_text = self._render(template.system, render_vars)
        user_text = self._render(template.user, render_vars)
        
        messages = []
        if system_text.strip():
            messages.append({"role": "system", "content": system_text})
        if user_text.strip():
            messages.append({"role": "user", "content": user_text})
        
        return messages
    
    def get_api_params(self, prompt_name: str) -> Dict[str, Any]:
        """Return only API-compatible generation params."""
        template = self._load_template(prompt_name)
        return {k: v for k, v in template.params.items() if k in API_PARAMS}
    
    def get_params(self, prompt_name: str) -> Dict[str, Any]:
        """Return all params (API + prompt-level)."""
        template = self._load_template(prompt_name)
        return dict(template.params)
    
    def render_document(
        self,
        prompt_name: str,
        **variables: Any,
    ) -> str:
        """Render a document-type template (e.g., wiki.md schema)."""
        template = self._load_template(prompt_name)
        render_vars = {**variables, "provider": self.provider}
        return self._render(template.document, render_vars)
    
    def render_text(
        self,
        prompt_name: str,
        **variables: Any,
    ) -> str:
        """Render a text-type template (e.g., ingest instructions)."""
        template = self._load_template(prompt_name)
        render_vars = {**variables, "provider": self.provider}
        return self._render(template.text, render_vars)
    
    def _load_template(self, prompt_name: str) -> PromptTemplate:
        """Load and cache a prompt template from file."""
        if prompt_name in self._cache:
            return self._cache[prompt_name]
        
        yaml_path = self._find_prompt_file(prompt_name)
        if not yaml_path:
            raise FileNotFoundError(
                f"Prompt template '{prompt_name}' not found in "
                f"{self._defaults_dir} or {self.custom_dir}"
            )
        
        data = yaml.safe_load(yaml_path.read_text())
        
        template = PromptTemplate(
            name=data.get("name", prompt_name),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            params=data.get("params", {}),
            system=data.get("system", ""),
            user=data.get("user", ""),
            document=data.get("document", ""),
            text=data.get("text", ""),
        )
        
        self._apply_provider_override(template, data)
        self._cache[prompt_name] = template
        return template
    
    def _find_prompt_file(self, prompt_name: str) -> Optional[Path]:
        """Find prompt YAML file, checking custom dir first."""
        filename = f"{prompt_name}.yaml"
        
        if self.custom_dir and (self.custom_dir / filename).exists():
            return self.custom_dir / filename
        
        if (self._defaults_dir / filename).exists():
            return self._defaults_dir / filename
        
        return None
    
    def _apply_provider_override(
        self,
        template: PromptTemplate,
        data: Dict[str, Any],
    ) -> None:
        """Apply provider-specific overrides from YAML data."""
        overrides = data.get("overrides", {})
        provider_override = overrides.get(self.provider, {})
        
        if "system" in provider_override:
            template.system = provider_override["system"]
        if "user" in provider_override:
            template.user = provider_override["user"]
        if "document" in provider_override:
            template.document = provider_override["document"]
        if "text" in provider_override:
            template.text = provider_override["text"]
        if "params" in provider_override:
            template.params.update(provider_override["params"])
    
    def _render(self, template_text: str, variables: Dict[str, Any]) -> str:
        """Render a Jinja2 template string with variables."""
        if not template_text:
            return ""
        
        tmpl = self._env.from_string(template_text)
        return tmpl.render(**variables)
