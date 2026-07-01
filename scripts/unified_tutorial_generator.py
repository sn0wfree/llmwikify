#!/usr/bin/env python3
"""Unified tutorial generator: parses test files with AST and generates
a single TUTORIAL.md.

This is the single source of truth for llmwikify tutorial documentation.
Test docstrings become tutorial content. Test code becomes examples.

Usage:
    python scripts/unified_tutorial_generator.py

Output:
    docs/TUTORIAL.md
"""

import ast
import re
from pathlib import Path


# Scenario number → name mapping (for header ordering)
SCENARIO_ORDER = [
    (1, "Wiki Core", "wiki_core"),
    (2, "Knowledge Graph", "knowledge_graph"),
    (3, "Multi-Wiki", "multi_wiki"),
    (4, "Chat + ReAct Agent", "chat_react"),
    (5, "Quant Pipeline", "quant_pipeline"),
    (6, "Lint Rules (Playbook 06)", "lint_rules"),
    (7, "YAML Templates (Playbook 07)", "yaml_templates"),
    (8, "Section Anchors (Playbook 08)", "section_anchors"),
    (9, "Ingest Workflow", "ingest_workflow"),
    (10, "Synthesis Workflow", "synthesis_workflow"),
    (11, "Multi-Wiki Config", "multi_wiki_config"),
    (12, "Quant Full Pipeline", "quant_full_pipeline"),
    (13, "References Detail", "references_detail"),
    (14, "Full Ingest Chain", "full_ingest_chain"),
]

SCENARIOS_DIR = Path(__file__).parent.parent / "tests" / "scenarios"


def parse_docstring_sections(docstring: str) -> dict[str, str]:
    """Parse structured docstring into sections.

    Recognized sections: ## Background, ## Architecture, ## Troubleshooting,
    ## Expected Output, ## Step description, etc.
    """
    if not docstring:
        return {}

    sections = {}
    current_section = "description"
    current_content = []

    for line in docstring.split("\n"):
        # Check for section header
        match = re.match(r"^##\s+(.+)$", line.strip())
        if match:
            if current_content or current_section != "description":
                sections[current_section] = "\n".join(current_content).strip()
            current_section = match.group(1).strip().lower().replace(" ", "_")
            current_content = []
        else:
            current_content.append(line)

    if current_content:
        sections[current_section] = "\n".join(current_content).strip()

    return sections


def extract_mermaid(content: str) -> tuple[str, str]:
    """Extract Mermaid diagram from content, return (before, mermaid_or_empty)."""
    mermaid_match = re.search(
        r"```mermaid\n(.*?)\n```", content, re.DOTALL
    )
    if mermaid_match:
        return "", mermaid_match.group(1)
    return content, ""


def extract_code_from_method(node: ast.FunctionDef) -> str:
    """Extract executable code from test method, skipping docstrings and assertions."""
    code_lines = []
    for stmt in node.body:
        # Skip docstrings (Expr with Constant string at the start)
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if isinstance(stmt.value.value, str):
                continue
        # Skip standalone Assert statements
        if isinstance(stmt, ast.Assert):
            continue
        # Get source line
        if hasattr(ast, "unparse"):
            try:
                line = ast.unparse(stmt)
                # Filter out lines that are assertion checks
                filtered = "\n".join(
                    ln for ln in line.split("\n")
                    if not ln.lstrip().startswith("assert ")
                )
                if filtered.strip():
                    code_lines.append(filtered)
            except Exception:
                pass
    return "\n".join(code_lines)


def parse_test_file(file_path: Path) -> dict | None:
    """Parse a test file and extract structured information."""
    try:
        source = file_path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return None

    # Get module docstring
    module_doc = ast.get_docstring(tree)
    module_sections = parse_docstring_sections(module_doc) if module_doc else {}

    # Find test class
    test_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            test_class = node
            break

    if not test_class:
        return None

    class_doc = ast.get_docstring(test_class)
    class_sections = parse_docstring_sections(class_doc) if class_doc else {}

    # Extract test methods
    methods = []
    for node in test_class.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            method_doc = ast.get_docstring(node)
            method_sections = (
                parse_docstring_sections(method_doc) if method_doc else {}
            )
            code = extract_code_from_method(node)

            # Parse step number from method name (e.g., test_1_1_init_wiki)
            match = re.match(
                r"test_(\d+)_(\d+)_(\w+)", node.name
            )
            if match:
                step_num, substep_num, step_name = match.groups()
                methods.append(
                    {
                        "step": f"{step_num}.{substep_num}",
                        "name": step_name.replace("_", " ").title(),
                        "sections": method_sections,
                        "code": code,
                    }
                )

    return {
        "module_sections": module_sections,
        "class_sections": class_sections,
        "methods": methods,
    }


def clean_expected_output(text: str) -> str:
    """Clean up expected output text by stripping code fences."""
    # Remove leading/trailing code fences
    text = re.sub(r"^```\w*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def render_scenario_section(
    num: int, name: str, slug: str, data: dict
) -> str:
    """Render one scenario section."""
    lines = [
        f"## Scenario {num}: {name}",
        "",
    ]

    # Module-level Background
    if "background" in data["module_sections"]:
        bg = data["module_sections"]["background"]
        lines.extend(["### Background", "", bg, ""])

    # Module-level Architecture
    if "architecture" in data["module_sections"]:
        arch = data["module_sections"]["architecture"]
        lines.extend(["### Architecture", "", arch, ""])

    # Module-level Troubleshooting
    if "troubleshooting" in data["module_sections"]:
        ts = data["module_sections"]["troubleshooting"]
        lines.extend(["### Troubleshooting", "", ts, ""])

    # Steps
    for method in data["methods"]:
        lines.append(f"### Step {method['step']}: {method['name']}")
        lines.append("")

        # Method description
        if "description" in method["sections"]:
            lines.append(method["sections"]["description"])
            lines.append("")

        # Expected output
        if "expected_output" in method["sections"]:
            output = clean_expected_output(method["sections"]["expected_output"])
            lines.extend(
                [
                    "**Expected Output:**",
                    "",
                    "```",
                    output,
                    "```",
                    "",
                ]
            )

        # Code example
        if method["code"]:
            lines.extend(
                [
                    "**Code:**",
                    "",
                    "```python",
                    method["code"],
                    "```",
                    "",
                ]
            )

    return "\n".join(lines)


def generate_tutorial() -> str:
    """Generate the unified TUTORIAL.md."""
    header = [
        "# llmwikify End-to-End Tutorial",
        "",
        "> **Auto-generated from test files** — tests are the source of truth.",
        "> **Executable**: `pytest tests/scenarios/ -v` to verify all steps.",
        "> **Version**: v0.38.0 (2026-07-01)",
        "",
        "This tutorial is generated from `tests/scenarios/test_*.py`. Each test",
        "step is an executable, verifiable example. The test docstring describes",
        "the *why*; the test code shows the *how*.",
        "",
        "## Table of Contents",
        "",
    ]

    # Table of contents
    for num, name, _ in SCENARIO_ORDER:
        header.append(f"- [Scenario {num}: {name}](#scenario-{num}-{name.lower().replace(' ', '-').replace('+', 'plus')})")

    header.extend(
        [
            "",
            "---",
            "",
        ]
    )

    sections = []
    for num, name, slug in SCENARIO_ORDER:
        # Try multiple name patterns
        candidates = list(SCENARIOS_DIR.glob(f"test_{num:02d}_*.py"))
        if not candidates:
            sections.append(
                f"## Scenario {num}: {name}\n\n*(Test file not found)*\n"
            )
            continue

        data = parse_test_file(candidates[0])
        if not data:
            sections.append(
                f"## Scenario {num}: {name}\n\n*(Failed to parse test file)*\n"
            )
            continue

        sections.append(render_scenario_section(num, name, slug, data))

    # Appendix
    appendix = [
        "---",
        "",
        "## Appendix A: TUTORIAL.md Concepts",
        "",
        "Cross-references to detailed concepts:",
        "",
        "- **Prerequisites**: see [TUTORIAL.md](TUTORIAL.md) §0 (Install Matrix + Decision Tree)",
        "- **Configuration Priority**: see [TUTORIAL.md](TUTORIAL.md) Appendix A",
        "- **CLI vs Python API**: see [TUTORIAL.md](TUTORIAL.md) Appendix B",
        "- **MCP Client Integration**: see [TUTORIAL.md](TUTORIAL.md) Appendix C",
        "",
        "## Appendix B: How to Use This Tutorial",
        "",
        "1. **Read the Background** of each scenario to understand the use case",
        "2. **Review the Architecture** diagram to see data flow",
        "3. **Execute the steps** via `pytest tests/scenarios/ -v`",
        "4. **Check Troubleshooting** if a step fails",
        "",
        "## Appendix C: Companion Playbooks",
        "",
        "Runnable examples in [`examples/01_~08_`](../examples/README.md):",
        "",
        "- 01: Personal Reading Notes",
        "- 02: Company Research KB",
        "- 03: Multi-Wiki Registry",
        "- 04: Chat SSE Client",
        "- 05: Paper to Factor",
        "- 06: Lint 8 Rules",
        "- 07: YAML Templates",
        "- 08: Section Anchor Tracking",
        "",
    ]

    return "\n".join(header + sections + appendix)


def main():
    output_path = Path("docs/TUTORIAL.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tutorial = generate_tutorial()
    output_path.write_text(tutorial)

    print(f"✅ Tutorial generated: {output_path}")
    print(f"   Length: {len(tutorial.splitlines())} lines")
    print(f"   Scenarios: {len(SCENARIO_ORDER)}")


if __name__ == "__main__":
    main()
