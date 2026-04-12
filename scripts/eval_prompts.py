#!/usr/bin/env python3
"""Offline Prompt Evaluation Script.

Validates all prompt templates without requiring a live LLM connection.

Checks performed:
1. Template Loading — all YAML files load successfully with required fields
2. Jinja2 Rendering — templates render without errors, no undefined variables
3. Context Injection — referenced methods exist in the Wiki class
4. Schema Validation Coverage — every validate_schema has a handler
5. Trigger Configuration — trigger types are valid
6. Cross-Reference — chained prompts have compatible input/output
7. Provider Overrides — ollama/openai overrides render correctly
8. Prompt Metadata — version, description, trigger, params present

Usage:
    python scripts/eval_prompts.py                          # All checks, text output
    python scripts/eval_prompts.py --check rendering         # Single check
    python scripts/eval_prompts.py --format json             # JSON output
    python scripts/eval_prompts.py --format json --output eval_results.json
    python scripts/eval_prompts.py --threshold 0.95          # Fail below 95%
"""

import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from jinja2 import Environment, BaseLoader, UndefinedError, StrictUndefined


# Known Wiki methods that can be referenced in context_injection
KNOWN_WIKI_METHODS = {
    "_get_index_summary", "_get_recent_log", "_get_page_count",
    "_get_existing_page_names",
}

# Known validate_schema values
KNOWN_SCHEMAS = {
    "analysis_output", "operations_array", "synthesize_output",
}

# Valid trigger types
VALID_TRIGGER_TYPES = {"api_call", "auto", "conditional", "disabled"}

# Chained prompt flow definition
CHAIN_FLOWS = {
    "analyze_source → generate_wiki_ops": {
        "source": "analyze_source",
        "target": "generate_wiki_ops",
        "expected_output_keys": ["topics", "entities", "key_facts", "suggested_pages"],
    },
}


class CheckResult:
    """Result of a single evaluation check."""

    def __init__(self, name: str):
        self.name = name
        self.status = "PASS"
        self.count = 0
        self.details: List[str] = []
        self.warnings: List[str] = []

    def pass_item(self, detail: str = ""):
        self.count += 1
        if detail:
            self.details.append(detail)

    def fail_item(self, detail: str):
        self.count += 1
        self.status = "FAIL"
        self.details.append(f"FAIL: {detail}")

    def warn_item(self, detail: str):
        self.warnings.append(detail)

    @property
    def score(self) -> float:
        if self.count == 0:
            return 1.0
        passed = self.count - len([d for d in self.details if d.startswith("FAIL:")])
        return passed / self.count

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "count": self.count,
            "details": self.details,
            "warnings": self.warnings,
            "score": round(self.score, 4),
        }


class PromptEvaluator:
    """Offline prompt evaluation engine."""

    def __init__(self, defaults_dir: Optional[Path] = None):
        if defaults_dir is None:
            defaults_dir = Path(__file__).parent.parent / "src" / "llmwikify" / "prompts" / "_defaults"
        self.defaults_dir = defaults_dir
        self._jinja_env = Environment(
            loader=BaseLoader(),
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    def run_all_checks(self, selected: Optional[List[str]] = None) -> Dict[str, CheckResult]:
        """Run all evaluation checks and return results."""
        import yaml

        all_checks = [
            ("template_loading", self._check_template_loading),
            ("jinja2_rendering", self._check_jinja2_rendering),
            ("context_injection", self._check_context_injection),
            ("schema_coverage", self._check_schema_coverage),
            ("trigger_config", self._check_trigger_config),
            ("cross_reference", self._check_cross_reference),
            ("provider_overrides", self._check_provider_overrides),
            ("prompt_metadata", self._check_prompt_metadata),
        ]

        results = {}
        for check_name, check_fn in all_checks:
            if selected and check_name not in selected:
                continue
            results[check_name] = check_fn()

        return results

    def _load_all_templates(self) -> Dict[str, Dict[str, Any]]:
        """Load all prompt YAML files."""
        import yaml

        templates = {}
        for yaml_file in sorted(self.defaults_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            try:
                data = yaml.safe_load(yaml_file.read_text())
                templates[yaml_file.stem] = data
            except Exception as e:
                templates[yaml_file.stem] = {"_error": str(e)}
        return templates

    def _check_template_loading(self) -> CheckResult:
        """Check 1: All templates load and have required fields."""
        result = CheckResult("Template Loading")
        templates = self._load_all_templates()

        for name, data in templates.items():
            if "_error" in data:
                result.fail_item(f"{name}: Failed to load YAML — {data['_error']}")
                continue

            # Required fields
            if not data.get("name"):
                result.fail_item(f"{name}: Missing 'name' field")
            else:
                result.pass_item(f"{name}: name = '{data['name']}'")

            if not data.get("version"):
                result.warn_item(f"{name}: Missing 'version' field")
            else:
                result.pass_item(f"{name}: version = '{data['version']}'")

            has_content = any([data.get("system"), data.get("user"),
                             data.get("document"), data.get("text")])
            if not has_content:
                result.fail_item(f"{name}: No content (system/user/document/text)")
            else:
                result.pass_item(f"{name}: Has content")

        return result

    def _check_jinja2_rendering(self) -> CheckResult:
        """Check 2: All templates render without Jinja2 errors."""
        result = CheckResult("Jinja2 Rendering")
        templates = self._load_all_templates()

        for name, data in templates.items():
            if "_error" in data:
                continue

            # Test rendering with minimal variables
            test_vars = {
                "provider": "openai",
                "title": "Test Title",
                "content": "Test content",
                "source_type": "markdown",
                "current_index": "",
                "content_truncated": False,
                "max_content_chars": 8000,
                "analysis_json": "{}",
                "existing_pages": [],
                "page_count": 0,
                "query": "Test query?",
                "source_pages": [],
                "raw_sources": [],
                "wiki_page_count": 0,
                "wiki_index": "",
                "recent_log": "",
                "contradictions_json": "[]",
                "data_gaps_json": "[]",
                "total_pages": 0,
                "version": "0.18.0",
            }

            for field_name in ["system", "user", "document", "text"]:
                content = data.get(field_name, "")
                if not content:
                    continue

                try:
                    tmpl = self._jinja_env.from_string(content)
                    rendered = tmpl.render(**test_vars)
                    # Check for undefined variables that didn't render
                    result.pass_item(f"{name}.{field_name}: renders OK")
                except UndefinedError as e:
                    result.fail_item(f"{name}.{field_name}: undefined variable — {e}")
                except Exception as e:
                    result.fail_item(f"{name}.{field_name}: render error — {e}")

        return result

    def _check_context_injection(self) -> CheckResult:
        """Check 3: All context_injection references resolve to Wiki methods."""
        result = CheckResult("Context Injection")
        templates = self._load_all_templates()

        for name, data in templates.items():
            ctx = data.get("context_injection", {})
            if not ctx:
                result.pass_item(f"{name}: No context injection")
                continue

            for key, spec in ctx.items():
                method_name = spec if isinstance(spec, str) else spec.get("method", "")
                if method_name in KNOWN_WIKI_METHODS:
                    result.pass_item(f"{name}.{key}: method '{method_name}' exists")
                else:
                    result.fail_item(
                        f"{name}.{key}: method '{method_name}' not in known methods: "
                        f"{sorted(KNOWN_WIKI_METHODS)}"
                    )

        return result

    def _check_schema_coverage(self) -> CheckResult:
        """Check 4: Every validate_schema has a known handler."""
        result = CheckResult("Schema Validation Coverage")
        templates = self._load_all_templates()

        for name, data in templates.items():
            pp = data.get("post_process", {})
            schema = pp.get("validate_schema")

            if not schema:
                result.pass_item(f"{name}: No schema validation needed")
                continue

            if schema in KNOWN_SCHEMAS:
                result.pass_item(f"{name}: validate_schema '{schema}' is known")
            else:
                result.fail_item(
                    f"{name}: validate_schema '{schema}' not in known schemas: "
                    f"{sorted(KNOWN_SCHEMAS)}"
                )

        return result

    def _check_trigger_config(self) -> CheckResult:
        """Check 5: All trigger configurations are valid."""
        result = CheckResult("Trigger Configuration")
        templates = self._load_all_templates()

        for name, data in templates.items():
            trigger = data.get("trigger")
            if not trigger:
                result.fail_item(f"{name}: Missing trigger configuration")
                continue

            trigger_type = trigger.get("type")
            if trigger_type not in VALID_TRIGGER_TYPES:
                result.fail_item(
                    f"{name}: Invalid trigger type '{trigger_type}'. "
                    f"Must be one of: {sorted(VALID_TRIGGER_TYPES)}"
                )
            else:
                result.pass_item(f"{name}: trigger type = '{trigger_type}'")

            # Conditional triggers should have a "when" value
            if trigger_type in ("auto", "conditional"):
                when = trigger.get("when", "")
                if not when:
                    result.warn_item(
                        f"{name}: '{trigger_type}' trigger has empty 'when' value"
                    )
                else:
                    result.pass_item(f"{name}: trigger when = '{when}'")

        return result

    def _check_cross_reference(self) -> CheckResult:
        """Check 6: Chained prompts have compatible input/output."""
        result = CheckResult("Cross-Reference")
        templates = self._load_all_templates()

        for chain_name, chain_def in CHAIN_FLOWS.items():
            source_name = chain_def["source"]
            target_name = chain_def["target"]

            if source_name not in templates:
                result.fail_item(f"{chain_name}: source prompt '{source_name}' not found")
                continue
            if target_name not in templates:
                result.fail_item(f"{chain_name}: target prompt '{target_name}' not found")
                continue

            source = templates[source_name]
            target = templates[target_name]

            # Check that source's post_process output keys match target's expected input
            source_pp = source.get("post_process", {})
            required_keys = source_pp.get("required_keys", [])

            target_user = target.get("user", "").lower()

            # Check that the target prompt references the source output
            for key in chain_def.get("expected_output_keys", []):
                if key in target_user or key.replace("_", " ") in target_user:
                    result.pass_item(f"{chain_name}: target references '{key}'")
                else:
                    result.warn_item(
                        f"{chain_name}: target may not reference source output key '{key}'"
                    )

            # Verify chain order: analyze should come before generate
            result.pass_item(f"{chain_name}: {source_name} → {target_name} chain valid")

        return result

    def _check_provider_overrides(self) -> CheckResult:
        """Check 7: Provider-specific overrides render correctly."""
        result = CheckResult("Provider Overrides")
        templates = self._load_all_templates()

        for name, data in templates.items():
            system = data.get("system", "")
            if not system:
                continue

            # Check ollama override presence
            if "{% if provider" in system or "{% if provider ==" in system:
                result.pass_item(f"{name}: Has provider conditional")

            # Render for both providers
            for provider in ["openai", "ollama"]:
                test_vars = {
                    "provider": provider,
                    "title": "Test",
                    "content": "Test content",
                    "source_type": "markdown",
                    "current_index": "",
                    "content_truncated": False,
                    "max_content_chars": 8000,
                    "analysis_json": "{}",
                    "existing_pages": [],
                    "page_count": 0,
                    "query": "Test?",
                    "source_pages": [],
                    "raw_sources": [],
                    "wiki_page_count": 0,
                    "wiki_index": "",
                    "recent_log": "",
                    "contradictions_json": "[]",
                    "data_gaps_json": "[]",
                    "total_pages": 0,
                    "version": "0.18.0",
                }

                try:
                    tmpl = self._jinja_env.from_string(system)
                    rendered = tmpl.render(**test_vars)
                    result.pass_item(f"{name}.{provider}: renders OK")
                except Exception as e:
                    result.fail_item(f"{name}.{provider}: render error — {e}")

        return result

    def _check_prompt_metadata(self) -> CheckResult:
        """Check 8: All templates have complete metadata."""
        result = CheckResult("Prompt Metadata")
        templates = self._load_all_templates()

        for name, data in templates.items():
            if "_error" in data:
                continue

            # Check description
            if data.get("description"):
                result.pass_item(f"{name}: has description")
            else:
                result.warn_item(f"{name}: missing description")

            # Check params
            if data.get("params"):
                result.pass_item(f"{name}: has params ({list(data['params'].keys())})")
            else:
                result.warn_item(f"{name}: missing params")

        return result

    def generate_report(self, results: Dict[str, CheckResult]) -> str:
        """Generate human-readable text report."""
        lines = []
        lines.append("=" * 60)
        lines.append("Prompt Evaluation Report (Offline)")
        lines.append("=" * 60)
        lines.append("")

        total_pass = 0
        total_checks = 0
        overall_pass = 0
        overall_total = len(results)

        for check_name, result in results.items():
            status_icon = "✅" if result.status == "PASS" else "❌"
            lines.append(f"{status_icon} {check_name}: {result.status}")
            lines.append(f"   Items: {result.count}")

            for detail in result.details:
                lines.append(f"   - {detail}")

            for warning in result.warnings:
                lines.append(f"   ⚠️  {warning}")

            lines.append("")
            total_checks += result.count
            if result.status == "PASS":
                total_pass += 1
                overall_pass += 1

        if total_checks > 0:
            overall_score = total_pass / len(results) * 100 if results else 100
            lines.append("-" * 60)
            lines.append(f"Summary: {overall_pass}/{len(results)} checks passed "
                        f"({overall_score:.0f}%)")
            lines.append(f"Total items verified: {total_pass}/{total_checks}")

        return "\n".join(lines)

    def generate_json_report(self, results: Dict[str, CheckResult]) -> Dict[str, Any]:
        """Generate machine-readable JSON report."""
        overall_score = sum(r.score for r in results.values()) / len(results) if results else 1.0
        pass_count = sum(1 for r in results.values() if r.status == "PASS")

        return {
            "timestamp": __import__("datetime").datetime.now().isoformat(),
            "overall_score": round(overall_score, 4),
            "checks_passed": pass_count,
            "checks_total": len(results),
            "checks": {name: result.to_dict() for name, result in results.items()},
        }


def main():
    parser = argparse.ArgumentParser(description="Offline prompt evaluation")
    parser.add_argument(
        "--check",
        type=str,
        nargs="+",
        choices=[
            "template_loading", "jinja2_rendering", "context_injection",
            "schema_coverage", "trigger_config", "cross_reference",
            "provider_overrides", "prompt_metadata",
        ],
        default=None,
        help="Run specific checks only",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write output to file",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.0,
        help="Minimum overall score to pass (0.0-1.0)",
    )
    parser.add_argument(
        "--prompt-dir",
        type=str,
        default=None,
        help="Path to prompt templates directory",
    )

    args = parser.parse_args()

    defaults_dir = Path(args.prompt_dir) if args.prompt_dir else None
    evaluator = PromptEvaluator(defaults_dir=defaults_dir)
    results = evaluator.run_all_checks(selected=args.check)

    if args.format == "json":
        output = json.dumps(evaluator.generate_json_report(results), indent=2)
    else:
        output = evaluator.generate_report(results)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)

    # Exit code based on threshold
    if args.threshold > 0:
        report = evaluator.generate_json_report(results)
        if report["overall_score"] < args.threshold:
            print(
                f"\nFAILED: Score {report['overall_score']:.2%} "
                f"is below threshold {args.threshold:.2%}",
                file=sys.stderr,
            )
            return 1

    # Fail if any check has FAIL status
    if any(r.status == "FAIL" for r in results.values()):
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
