"""Principle Compliance Checker for prompt templates.

Checks that all prompt templates in the registry adhere to the
LLM Wiki Principles defined in docs/LLM_WIKI_PRINCIPLES.md.

Layer 1 (automated): Prompt design compliance — checks that system/user
prompts contain required principle instructions (contradiction detection,
fabrication warning, observational language, etc.).

Layer 2 (heuristic): Output compliance — given golden test sources with
known contradictions/data gaps, checks whether the expected LLM output
would satisfy principle requirements.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class PrincipleViolation:
    """A single principle violation found in a prompt template."""
    principle: str
    prompt_name: str
    severity: str  # "error", "warning", "info"
    message: str
    suggestion: str = ""


@dataclass
class PrincipleCheckResult:
    """Result of checking all principles for a prompt."""
    prompt_name: str
    violations: List[PrincipleViolation] = field(default_factory=list)
    passed_checks: int = 0
    total_checks: int = 0

    @property
    def is_pass(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    @property
    def score(self) -> float:
        if self.total_checks == 0:
            return 1.0
        return self.passed_checks / self.total_checks


# Principle definitions with keyword indicators.
# A prompt is considered to "pass" a principle if at least one
# keyword from the list appears in the combined system+user text.
PRINCIPLE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "contradiction_detection": {
        "keywords": ["contradict", "conflict", "disagree", "inconsisten"],
        "description": "Prompt instructs LLM to detect contradictions with existing wiki content.",
        "applies_to": ["analyze_source", "ingest_source", "wiki_synthesize"],
    },
    "fabrication_warning": {
        "keywords": ["fabricate", "make up", "invent", "do not assume", "only extract"],
        "description": "Prompt instructs LLM not to fabricate information not present in sources.",
        "applies_to": ["analyze_source", "generate_wiki_ops", "ingest_source", "wiki_synthesize"],
    },
    "observational_language": {
        "keywords": ["observational", "sources indicate", "according to", "source states",
                      "the document", "the source", "claims that", "states that"],
        "description": "Prompt instructs LLM to use observational rather than definitive language.",
        "applies_to": ["analyze_source", "generate_wiki_ops", "wiki_synthesize", "investigate_lint"],
    },
    "zero_domain_assumption": {
        "keywords": ["no assumption", "explain", "define", "domain-agnostic", "context"],
        "description": "Prompt does not assume prior domain knowledge.",
        "applies_to": ["analyze_source", "investigate_lint"],
    },
    "wikilink_usage": {
        "keywords": ["[[wikilink", "[[", "cross-reference", "cross_ref"],
        "description": "Prompt instructs LLM to use wikilink syntax for cross-references.",
        "applies_to": ["generate_wiki_ops", "ingest_source", "wiki_synthesize"],
    },
    "log_operation": {
        "keywords": ["log", "operation", "append to log"],
        "description": "Prompt instructs LLM to include log operations summarizing actions.",
        "applies_to": ["generate_wiki_ops", "ingest_source"],
    },
    "data_gap_detection": {
        "keywords": ["data gap", "gap", "unclear", "vague", "unsupported", "needs more"],
        "description": "Prompt instructs LLM to identify data gaps and unclear claims.",
        "applies_to": ["analyze_source"],
    },
}


class PrincipleChecker:
    """Checks prompt templates against LLM Wiki Principles."""

    def __init__(self, defaults_dir: Optional[Path] = None):
        if defaults_dir is None:
            defaults_dir = Path(__file__).parent.parent / "prompts" / "_defaults"
        self.defaults_dir = defaults_dir

    def check_all_templates(self) -> Dict[str, PrincipleCheckResult]:
        """Check all prompt templates against all applicable principles."""
        import yaml

        results = {}
        for yaml_file in sorted(self.defaults_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue

            prompt_name = yaml_file.stem
            data = yaml.safe_load(yaml_file.read_text())
            result = self._check_single_template(prompt_name, data)
            results[prompt_name] = result

        return results

    def check_template(self, prompt_name: str, data: Dict[str, Any]) -> PrincipleCheckResult:
        """Check a single loaded template against applicable principles."""
        return self._check_single_template(prompt_name, data)

    def _check_single_template(self, prompt_name: str, data: Dict[str, Any]) -> PrincipleCheckResult:
        result = PrincipleCheckResult(prompt_name=prompt_name)
        combined_text = (
            (data.get("system", "") or "") + "\n" +
            (data.get("user", "") or "") + "\n" +
            (data.get("document", "") or "") + "\n" +
            (data.get("text", "") or "")
        ).lower()

        for principle_name, definition in PRINCIPLE_DEFINITIONS.items():
            applies_to = definition.get("applies_to", [])

            if applies_to and prompt_name not in applies_to:
                continue

            result.total_checks += 1
            keywords = definition["keywords"]
            found = any(kw.lower() in combined_text for kw in keywords)

            if found:
                result.passed_checks += 1
            else:
                result.violations.append(PrincipleViolation(
                    principle=principle_name,
                    prompt_name=prompt_name,
                    severity="warning",
                    message=f"Missing '{principle_name}' instruction. "
                            f"Expected one of: {', '.join(keywords[:3])}",
                    suggestion=f"Add instruction related to {definition['description'].lower()}",
                ))

        # Structural checks
        self._check_structural_integrity(prompt_name, data, result)

        return result

    def _check_structural_integrity(
        self,
        prompt_name: str,
        data: Dict[str, Any],
        result: PrincipleCheckResult,
    ) -> None:
        """Check structural requirements common to all prompts."""
        # Must have name
        result.total_checks += 1
        if data.get("name"):
            result.passed_checks += 1
        else:
            result.violations.append(PrincipleViolation(
                principle="name_field",
                prompt_name=prompt_name,
                severity="error",
                message="Missing 'name' field",
                suggestion="Add 'name' field matching the filename",
            ))

        # Must have version
        result.total_checks += 1
        if data.get("version"):
            result.passed_checks += 1
        else:
            result.violations.append(PrincipleViolation(
                principle="version_field",
                prompt_name=prompt_name,
                severity="warning",
                message="Missing 'version' field",
                suggestion="Add 'version' field (e.g., '1.0')",
            ))

        # Must have trigger
        result.total_checks += 1
        trigger = data.get("trigger")
        if trigger and trigger.get("type") in ("api_call", "auto", "conditional", "disabled"):
            result.passed_checks += 1
        else:
            result.violations.append(PrincipleViolation(
                principle="trigger_field",
                prompt_name=prompt_name,
                severity="warning",
                message=f"Missing or invalid 'trigger' field (got: {trigger})",
                suggestion="Add trigger with type: api_call|auto|conditional|disabled",
            ))

        # Must have content (system/user/document/text)
        result.total_checks += 1
        has_content = any([
            data.get("system"),
            data.get("user"),
            data.get("document"),
            data.get("text"),
        ])
        if has_content:
            result.passed_checks += 1
        else:
            result.violations.append(PrincipleViolation(
                principle="content_field",
                prompt_name=prompt_name,
                severity="error",
                message="No content found (system/user/document/text are all empty)",
                suggestion="Add at least one content field",
            ))

        # post_process validation: if present, validate_schema must be defined
        result.total_checks += 1
        pp = data.get("post_process")
        if pp is None:
            result.passed_checks += 1  # post_process is optional
        elif pp.get("validate_schema"):
            result.passed_checks += 1
        else:
            result.violations.append(PrincipleViolation(
                principle="post_process_schema",
                prompt_name=prompt_name,
                severity="warning",
                message="post_process defined but missing validate_schema",
                suggestion="Add validate_schema to post_process for output validation",
            ))

    def check_context_injection(self) -> List[Dict[str, str]]:
        """Check that all context_injection references resolve to Wiki methods."""
        import yaml

        issues = []
        wiki_methods = {
            "_get_index_summary", "_get_recent_log", "_get_page_count",
            "_get_existing_page_names",
        }

        for yaml_file in sorted(self.defaults_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue

            data = yaml.safe_load(yaml_file.read_text())
            ctx = data.get("context_injection", {})
            if not ctx:
                continue

            for key, spec in ctx.items():
                method_name = spec if isinstance(spec, str) else spec.get("method", "")
                if method_name and method_name not in wiki_methods:
                    issues.append({
                        "prompt": data.get("name", yaml_file.stem),
                        "context_key": key,
                        "method": method_name,
                        "issue": f"Method '{method_name}' not found in known Wiki methods: {wiki_methods}",
                    })

        return issues

    def check_schema_coverage(self) -> List[Dict[str, str]]:
        """Check that all validate_schema values have corresponding validation logic."""
        import yaml

        known_schemas = {
            "analysis_output", "operations_array", "synthesize_output",
        }
        issues = []

        for yaml_file in sorted(self.defaults_dir.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue

            data = yaml.safe_load(yaml_file.read_text())
            pp = data.get("post_process", {})
            schema = pp.get("validate_schema")

            if schema and schema not in known_schemas:
                issues.append({
                    "prompt": data.get("name", yaml_file.stem),
                    "schema": schema,
                    "issue": f"Unknown validate_schema '{schema}'. Known schemas: {known_schemas}",
                })

        return issues

    def generate_report(self, results: Optional[Dict[str, PrincipleCheckResult]] = None) -> str:
        """Generate a human-readable markdown report."""
        if results is None:
            results = self.check_all_templates()

        lines = []
        lines.append("# Prompt Principle Compliance Report\n")
        lines.append(f"Templates checked: {len(results)}\n")

        total_passed = 0
        total_checked = 0
        compliant_count = 0

        for prompt_name, result in sorted(results.items()):
            status = "PASS" if result.is_pass else "WARN"
            score_display = f"{result.passed_checks}/{result.total_checks}"
            lines.append(f"## {prompt_name}: {status} ({score_display})")

            if result.is_pass:
                compliant_count += 1

            total_passed += result.passed_checks
            total_checked += result.total_checks

            if result.violations:
                for v in result.violations:
                    severity_icon = {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(v.severity, "⚪")
                    lines.append(f"- {severity_icon} **{v.principle}**: {v.message}")
                    if v.suggestion:
                        lines.append(f"  - Suggestion: {v.suggestion}")
            else:
                lines.append("- All checks passed ✓")

            lines.append("")

        overall_score = (total_passed / total_checked * 100) if total_checked > 0 else 100
        lines.append("---\n")
        lines.append(f"**Overall: {compliant_count}/{len(results)} templates compliant "
                     f"({total_passed}/{total_checked} checks passed, {overall_score:.0f}%)**")

        # Context injection issues
        ctx_issues = self.check_context_injection()
        if ctx_issues:
            lines.append("\n## Context Injection Issues\n")
            for issue in ctx_issues:
                lines.append(f"- **{issue['prompt']}**: {issue['issue']}")

        # Schema coverage issues
        schema_issues = self.check_schema_coverage()
        if schema_issues:
            lines.append("\n## Schema Coverage Issues\n")
            for issue in schema_issues:
                lines.append(f"- **{issue['prompt']}**: {issue['issue']}")

        return "\n".join(lines)

    def generate_json_report(self, results: Optional[Dict[str, PrincipleCheckResult]] = None) -> Dict[str, Any]:
        """Generate a machine-readable JSON report."""
        if results is None:
            results = self.check_all_templates()

        prompt_results = {}
        total_passed = 0
        total_checked = 0
        compliant_count = 0

        for prompt_name, result in sorted(results.items()):
            violations = [
                {
                    "principle": v.principle,
                    "severity": v.severity,
                    "message": v.message,
                    "suggestion": v.suggestion,
                }
                for v in result.violations
            ]
            prompt_results[prompt_name] = {
                "status": "pass" if result.is_pass else "warn",
                "score": result.score,
                "passed_checks": result.passed_checks,
                "total_checks": result.total_checks,
                "violations": violations,
            }
            if result.is_pass:
                compliant_count += 1
            total_passed += result.passed_checks
            total_checked += result.total_checks

        overall_score = (total_passed / total_checked) if total_checked > 0 else 1.0

        return {
            "templates_checked": len(results),
            "compliant_count": compliant_count,
            "total_passed": total_passed,
            "total_checked": total_checked,
            "overall_score": round(overall_score, 4),
            "prompts": prompt_results,
            "context_injection_issues": self.check_context_injection(),
            "schema_coverage_issues": self.check_schema_coverage(),
        }
