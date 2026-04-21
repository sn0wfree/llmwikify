"""Wiki LLM mixin — LLM calls with retry, source processing, investigation generation."""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class WikiLLMMixin:
    """LLM interaction: chained source processing, retry logic, investigation generation."""

    def _llm_process_source(self, source_data: dict) -> dict:
        """Process source with LLM using chained mode: analyze_source → generate_wiki_ops."""
        from ..llm_client import LLMClient

        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()

        max_content_chars = registry.get_params("analyze_source").get("max_content_chars", 8000)
        content = source_data["content"][:max_content_chars]
        content_truncated = len(source_data["content"]) > max_content_chars

        wiki_schema = ""
        if self.wiki_md_file.exists():
            wiki_schema = self.wiki_md_file.read_text()

        analysis_messages = registry.get_messages(
            "analyze_source",
            title=source_data["title"],
            source_type=source_data["source_type"],
            content=content,
            current_index=source_data.get("current_index", ""),
            max_content_chars=max_content_chars,
            content_truncated=content_truncated,
            wiki_schema=wiki_schema,
        )
        analysis_params = registry.get_api_params("analyze_source")

        analysis = self._call_llm_with_retry("analyze_source", analysis_messages, analysis_params)

        errors = registry.validate_output("analyze_source", analysis)
        if errors:
            raise ValueError(f"Analysis validation failed: {'; '.join(errors)}")

        template = registry._load_template("generate_wiki_ops")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)

        ops_messages = registry.get_messages(
            "generate_wiki_ops",
            **dynamic_context,
            analysis_json=json.dumps(analysis, indent=2),
            current_index=source_data.get("current_index", ""),
        )
        ops_params = registry.get_api_params("generate_wiki_ops")

        operations = self._call_llm_with_retry("generate_wiki_ops", ops_messages, ops_params)

        errors = registry.validate_output("generate_wiki_ops", operations)
        if errors:
            raise ValueError(f"Operations validation failed: {'; '.join(errors)}")

        if not isinstance(operations, list):
            raise ValueError(f"Expected list of operations, got {type(operations).__name__}")

        return {
            "status": "success",
            "operations": operations,
            "relations": analysis.get("relations", []),
            "entities": analysis.get("entities", []),
            "claims": analysis.get("claims", []),
            "analysis": analysis,
            "source_title": source_data["title"],
            "mode": "chained",
        }

    def _call_llm_with_retry(
        self,
        prompt_name: str,
        messages: list[dict[str, str]],
        params: dict,
    ) -> Any:
        """Call LLM with retry on validation failure."""
        from ..llm_client import LLMClient

        client = LLMClient.from_config(self.config)
        registry = self._get_prompt_registry()
        retry_config = registry.get_retry_config(prompt_name)
        max_attempts = retry_config.get("max_attempts", 1)

        last_errors: list[str] = []
        for attempt in range(1, max_attempts + 1):
            try:
                result = client.chat_json(messages, **params)

                errors = registry.validate_output(prompt_name, result)
                if not errors:
                    return result

                last_errors = errors
                if attempt < max_attempts:
                    error_text = "\n".join(f"- {e}" for e in errors)
                    retry_prompt = (
                        f"Your previous response had errors:\n{error_text}\n\n"
                        f"Please fix and return a corrected response."
                    )
                    messages = [
                        messages[0],
                        {"role": "user", "content": retry_prompt},
                    ]

            except (ConnectionError, ValueError) as e:
                last_errors = [str(e)]
                if attempt >= max_attempts:
                    raise

        raise ValueError(
            f"LLM failed after {max_attempts} attempts for '{prompt_name}': "
            f"{'; '.join(last_errors)}"
        )

    def _llm_generate_investigations(
        self,
        contradictions: list[dict],
        data_gaps: list[dict],
    ) -> dict:
        """Use LLM to generate investigation suggestions."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._llm_generate_investigations(contradictions, data_gaps)

    def _llm_detect_gaps(self, context: str) -> list[dict]:
        """Call LLM to detect gaps between wiki schema and current state."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._llm_detect_gaps(context)

    def _fallback_detect_gaps(self) -> list[dict]:
        """Basic gap detection without LLM."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._fallback_detect_gaps()

    def _build_lint_context(self, limit: int = 20) -> str:
        """Build minimal context for LLM lint analysis."""
        from .wiki_analyzer import WikiAnalyzer
        return WikiAnalyzer(self)._build_lint_context(limit)

    def _llm_generate_synthesize_answer(
        self,
        query: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
    ) -> dict:
        """Use LLM to generate a structured answer for a query.
        
        This method reads the provided source pages and raw sources,
        injects wiki context, and calls the LLM to produce a well-structured
        answer suitable for wiki synthesis.
        
        Args:
            query: The question to answer.
            source_pages: Wiki page names to use as context.
            raw_sources: Raw source file paths to use as context.
        
        Returns:
            Dict with 'answer' (str), 'suggested_page_name' (optional str),
            and 'source_citations' (list of page names referenced).
        """
        try:
            from ..llm_client import LLMClient
            client = LLMClient.from_config(self.config)
        except (ImportError, ValueError, OSError):
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": "LLM client not available",
            }

        registry = self._get_prompt_registry()

        source_page_data = []
        for page_name in (source_pages or []):
            page_path = self.wiki_dir / f"{page_name}.md"
            if page_path.exists():
                source_page_data.append({
                    "name": page_name,
                    "content": page_path.read_text(),
                })

        raw_source_data = []
        for raw_path in (raw_sources or []):
            full_path = self.root / raw_path
            if full_path.exists():
                raw_source_data.append({
                    "name": raw_path,
                    "content": full_path.read_text(),
                })

        template = registry._load_template("wiki_synthesize")
        dynamic_context = {}
        if template.context_injection:
            dynamic_context = registry.inject_context(template.context_injection, wiki=self)

        variables = {
            **dynamic_context,
            "query": query,
            "source_pages": source_page_data,
            "raw_sources": raw_source_data,
        }

        messages = registry.get_messages("wiki_synthesize", **variables)
        params = registry.get_api_params("wiki_synthesize")

        try:
            result = client.chat_json(messages, **params)

            errors = registry.validate_output("wiki_synthesize", result)
            if errors:
                return {
                    "answer": "",
                    "suggested_page_name": "",
                    "source_citations": [],
                    "warning": f"LLM output validation failed: {'; '.join(errors)}",
                }

            return {
                "answer": result.get("answer", ""),
                "suggested_page_name": result.get("suggested_page_name", ""),
                "source_citations": result.get("source_citations", []),
            }
        except (ConnectionError, TimeoutError, ValueError, OSError) as e:
            return {
                "answer": "",
                "suggested_page_name": "",
                "source_citations": [],
                "warning": f"LLM synthesis generation failed: {e}",
            }
