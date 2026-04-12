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
    trigger: Dict[str, str] = field(default_factory=lambda: {"type": "api_call", "when": ""})
    preconditions: List[str] = field(default_factory=list)
    context_injection: Dict[str, Any] = field(default_factory=dict)
    post_process: Dict[str, Any] = field(default_factory=dict)


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
            trigger=data.get("trigger", {"type": "api_call", "when": ""}),
            preconditions=data.get("preconditions", []),
            context_injection=data.get("context_injection", {}),
            post_process=data.get("post_process", {}),
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
        if "trigger" in provider_override:
            template.trigger.update(provider_override["trigger"])
        if "context_injection" in provider_override:
            template.context_injection.update(provider_override["context_injection"])
        if "params" in provider_override:
            template.params.update(provider_override["params"])
        if "post_process" in provider_override:
            template.post_process.update(provider_override["post_process"])
    
    def _render(self, template_text: str, variables: Dict[str, Any]) -> str:
        """Render a Jinja2 template string with variables."""
        if not template_text:
            return ""
        
        tmpl = self._env.from_string(template_text)
        return tmpl.render(**variables)
    
    def should_trigger(self, prompt_name: str, event_name: str) -> bool:
        """Check if this prompt should activate for the given event.
        
        trigger.type:
          - "api_call": Always available. Activated by explicit code call.
          - "auto": Auto-triggered when event_name matches trigger.when.
          - "conditional": Only if preconditions pass.
          - "disabled": Never trigger.
        """
        template = self._load_template(prompt_name)
        trigger_type = template.trigger.get("type", "api_call")
        
        if trigger_type == "disabled":
            return False
        
        if trigger_type == "api_call":
            return True
        
        if trigger_type == "auto":
            return event_name == template.trigger.get("when", "")
        
        if trigger_type == "conditional":
            return event_name == template.trigger.get("when", "")
        
        return True
    
    def inject_context(
        self,
        context_spec: Dict[str, Any],
        wiki: Any,
    ) -> Dict[str, Any]:
        """Resolve context injection spec into actual values.
        
        context_spec format:
          - Simple: {"wiki_index": "_get_index_summary"}
          - With params: {"recent_ops": {"method": "_get_recent_log", "limit": 5}}
        """
        result: Dict[str, Any] = {}
        for key, spec in context_spec.items():
            if isinstance(spec, str):
                spec = {"method": spec}
            
            method_name = spec.get("method", key)
            params = {k: v for k, v in spec.items() if k != "method"}
            
            if hasattr(wiki, method_name):
                try:
                    method = getattr(wiki, method_name)
                    if callable(method):
                        result[key] = method(**params)
                    else:
                        result[key] = str(method)
                except Exception as e:
                    result[key] = f"[context error: {method_name}: {type(e).__name__}]"
            else:
                result[key] = ""
        
        return result
    
    def validate_output(self, prompt_name: str, output: Any) -> List[str]:
        """Validate LLM output against post_process rules.
        
        Returns list of error messages. Empty list means valid.
        """
        template = self._load_template(prompt_name)
        pp = template.post_process
        if not pp:
            return []
        
        errors: List[str] = []
        
        if "validate_schema" in pp:
            errors.extend(self._validate_schema(pp["validate_schema"], output))
        
        if "required_keys" in pp and isinstance(output, dict):
            for key in pp["required_keys"]:
                if key not in output:
                    errors.append(f"Missing required key: {key}")
        
        if "required_type" in pp:
            expected = pp["required_type"]
            if expected == "array" and not isinstance(output, list):
                errors.append(f"Expected array, got {type(output).__name__}")
            elif expected == "object" and not isinstance(output, dict):
                errors.append(f"Expected object, got {type(output).__name__}")
        
        return errors
    
    def _validate_schema(self, schema_name: str, output: Any) -> List[str]:
        """Lightweight schema validation without jsonschema library."""
        errors: List[str] = []
        
        if schema_name == "analysis_output":
            if not isinstance(output, dict):
                return [f"Expected object, got {type(output).__name__}"]
            
            for key in ("topics", "entities", "key_facts", "suggested_pages"):
                if key not in output:
                    errors.append(f"Missing required key: {key}")
            
            if "topics" in output and not isinstance(output["topics"], list):
                errors.append("'topics' must be an array")
            if "entities" in output and not isinstance(output["entities"], list):
                errors.append("'entities' must be an array")
            if "suggested_pages" in output and not isinstance(output["suggested_pages"], list):
                errors.append("'suggested_pages' must be an array")
            if "content_type" in output and not isinstance(output["content_type"], str):
                errors.append("'content_type' must be a string")
        
        elif schema_name == "operations_array":
            if not isinstance(output, list):
                return [f"Expected array, got {type(output).__name__}"]
            
            for i, op in enumerate(output):
                if not isinstance(op, dict):
                    errors.append(f"Operation {i}: expected object, got {type(op).__name__}")
                    continue
                
                action = op.get("action")
                if action not in ("write_page", "log"):
                    errors.append(f"Operation {i}: unknown action '{action}'")
                    continue
                
                if action == "write_page":
                    if not op.get("page_name"):
                        errors.append(f"Operation {i}: write_page missing 'page_name'")
                    if not op.get("content"):
                        errors.append(f"Operation {i}: write_page missing 'content'")
                elif action == "log":
                    if not op.get("operation"):
                        errors.append(f"Operation {i}: log missing 'operation'")
                    if not op.get("details"):
                        errors.append(f"Operation {i}: log missing 'details'")
        
        return errors
    
    def get_retry_config(self, prompt_name: str) -> Dict[str, Any]:
        """Get retry configuration for a prompt."""
        template = self._load_template(prompt_name)
        return template.post_process.get("retry_on_failure", {"max_attempts": 1})
