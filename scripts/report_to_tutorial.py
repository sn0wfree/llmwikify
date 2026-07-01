#!/usr/bin/env python3
"""Convert pytest test report to tutorial documentation.

Usage:
    python scripts/report_to_tutorial.py tests/test_report.md

Output:
    docs/tutorials/real_world_scenarios.md
"""

import re
import sys
from pathlib import Path


SCENARIO_NAMES = {
    "1_wiki_core": "Wiki Core",
    "2_knowledge_graph": "Knowledge Graph",
    "3_multi_wiki": "Multi-Wiki",
    "4_chat_react": "Chat + ReAct Agent",
    "5_quant_pipeline": "Quant Pipeline",
    "6_lint_rules": "Lint Rules",
    "7_yaml_templates": "YAML Templates",
    "8_section_anchors": "Section Anchors",
    "9_ingest_workflow": "Ingest Workflow",
    "10_synthesis_workflow": "Synthesis Workflow",
    "11_multi_wiki_config": "Multi-Wiki Config",
    "12_quant_full_pipeline": "Quant Full Pipeline",
    "13_references_detail": "References Detail",
    "14_full_ingest_chain": "Full Ingest Chain",
}

# Example code for each test step
EXAMPLE_CODE = {
    "1_1": """from llmwikify import create_wiki

# Create a wiki at the specified path
wiki = create_wiki("./my-wiki")
print(f"Wiki root: {wiki.root}")""",

    "1_2": """# Write a page to the wiki
wiki.write_page("python-basics", "# Python Basics\\n\\nPython is a programming language.")

# Read the page back
result = wiki.read_page("python-basics")
print(result["content"])""",

    "1_3": """# Write multiple pages
pages = {
    "python": "# Python\\n\\nA programming language.",
    "ml": "# Machine Learning\\n\\nUses Python.",
    "data-science": "# Data Science\\n\\nUses Python and ML.",
}

for name, content in pages.items():
    wiki.write_page(name, content)""",

    "1_4": """# Search for content
results = wiki.search("Python", limit=10)
for r in results:
    print(f"{r['page']}: {r['snippet']}")""",

    "1_5": """# Build the reference index
idx = wiki.build_index()
print(f"Indexed {idx['total_pages']} pages")""",

    "1_6": """# Get inbound links (who links to this page)
inbound = wiki.get_inbound_links("python")
print(f"Pages linking to python: {len(inbound)}")

# Get outbound links (what this page links to)
outbound = wiki.get_outbound_links("python")
print(f"Pages linked from python: {len(outbound)}")""",

    "1_7": """# Run health check
result = wiki.lint()
print(f"Issues: {len(result['issues'])}")
print(f"Hints: {len(result['hints']['critical'])}")""",

    "1_8": """# Get wiki status
status = wiki.status()
print(f"Pages: {status['page_count']}")
print(f"Links: {status['link_count']}")""",

    "2_1": """# Build index for graph analysis
wiki.build_index()""",

    "2_2": """# Analyze a source file (requires LLM)
result = wiki.analyze_source("raw/paper.pdf")
print(f"Entities: {len(result.get('entities', []))}")""",

    "2_3": """# Get synthesis suggestions (requires LLM)
result = wiki.suggest_synthesis()
print(f"Suggestions: {len(result)}")""",

    "2_4": """# Check knowledge gaps via CLI
# llmwikify knowledge-gaps""",

    "2_5": """# Analyze graph via CLI
# llmwikify graph-analyze --json""",

    "2_6": """# Export graph visualization
# llmwikify export-graph --format html --output graph.html""",

    "3_1": """from llmwikify.kernel.multi_wiki.registry import WikiRegistry

config = {"wikis": {"local": [], "discovery": {}}}
registry = WikiRegistry(config)
registry.initialize()

# Register a wiki
registry.register_wiki("my-wiki", "My Wiki", "/path/to/wiki")""",

    "3_2": """# List all registered wikis
wikis = registry.list_wikis()
for w in wikis:
    print(f"{w.wiki_id}: {w.name}")""",

    "3_3": """# Switch default wiki
registry.set_default_wiki("wiki-c2")""",

    "3_4": """# Unregister a wiki
registry.unregister_wiki("wiki-d")""",

    "3_5": """from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery

discovery = WikiDiscovery()
found = discovery.scan("/path/to/wikis")
print(f"Found {len(found)} wikis")""",

    "4_1": """import httpx

# Check server health
response = httpx.get("http://localhost:8765/api/health")
print(response.json())  # {"status": "ok"}""",

    "4_2": """# Auth is optional in default config
response = httpx.post(
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "hello"}
)""",

    "4_3": """# Chat via SSE streaming
with httpx.stream(
    "POST",
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "What is Python?"},
    headers={"Authorization": "Bearer your-token"}
) as response:
    for line in response.iter_lines():
        if line.startswith("data:"):
            print(line)""",

    "4_4": """# Chat with wiki tool invocation
response = httpx.post(
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "Search for Python in the wiki"}
)""",

    "4_5": """# List chat sessions
response = httpx.get("http://localhost:8765/api/agent/sessions")
print(response.json())""",

    "5_1": """# Initialize quant directory
# llmwikify quant-init""",

    "5_2": """import yaml

# Write a factor YAML file
factor = {
    "name": "momentum_20d",
    "L1_logic": "Price momentum over 20 days",
    "L2_computation": "close / close.shift(20) - 1",
}

factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor_path.parent.mkdir(parents=True, exist_ok=True)
factor_path.write_text(yaml.dump(factor))""",

    "5_3": """from llmwikify.reproduction.persist.factor_library import list_factors

factors = list_factors(".")
print(f"Found {len(factors)} factors")""",

    "5_4": """import yaml

# Read a factor YAML
factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor = yaml.safe_load(factor_path.read_text())
print(factor["L1_logic"])""",

    "5_5": """import duckdb

# Create factor_values table
conn = duckdb.connect("quant/factor.duckdb")
conn.execute(\"\"\"
    CREATE TABLE IF NOT EXISTS factor_values (
        date DATE,
        stock VARCHAR,
        factor_name VARCHAR,
        value DOUBLE
    )
\"\"\")""",

    "5_6": """# List papers via API
response = httpx.get("http://localhost:8765/api/paper/list")
print(response.json())""",

    "5_7": """# List factors via API
response = httpx.get("http://localhost:8765/api/factor/library/list")
print(response.json())""",

    "6_1": """# Create page with old date reference
wiki.write_page("old-report", "# Report 2018\\n\\nRevenue: $10B.")

# Lint will detect dated_claim
result = wiki.lint()""",

    "6_2": """# Create page with old reference
wiki.write_page("outdated", "# Data\\n\\nFrom 2019 report.")""",

    "6_3": """# Create page without source citations
wiki.write_page("claims", "# Claims\\n\\nMarket grew 15%.")""",

    "6_4": """# Create page with no inbound links
wiki.write_page("orphan", "# Orphan\\n\\nNo one links to me.")""",

    "6_5": """# Lint in brief mode (counts only)
result = wiki.lint(mode="brief")
print(f"Total issues: {result['issue_count']}")""",

    "7_1": """import yaml

# Parse personal-kb.yaml template
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/personal-kb.yaml").read_text())
print(template["llm"]["provider"])  # "ollama" """,

    "7_2": """# Parse project-docs.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/project-docs.yaml").read_text())""",

    "7_3": """# Parse research-wiki.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/research-wiki.yaml").read_text())""",

    "7_4": """# Parse mining-news-wiki.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/mining-news-wiki.yaml").read_text())""",

    "7_5": """# Create wiki with custom config
config = {
    "llm": {"provider": "test", "model": "test-model"},
    "orphan_detection": {"exclude_patterns": ["^draft-.*"]},
}
wiki = create_wiki("./wiki", config=config)""",

    "8_1": """# Write a page with sections
wiki.write_page("python-style", \"\"\"
# Python Style Guide

## Overview
Python emphasizes code readability.

## Naming
Use `snake_case` for functions.
\"\"\")""",

    "8_2": """# Write page with [[target#section]] links
wiki.write_page("notes", "# Notes\\n\\nFollow [[python-style#Naming]] rules.")""",

    "8_3": """# Get inbound links with section info
inbound = wiki.get_inbound_links("python-style")
for link in inbound:
    print(f"From: {link['source']}, Section: {link.get('section')}")""",

    "8_4": """# Get outbound links with section info
outbound = wiki.get_outbound_links("notes")
for link in outbound:
    print(f"To: {link['target']}, Section: {link.get('section')}")""",

    "8_5": """# Get links with surrounding context
inbound = wiki.get_inbound_links("python-style", include_context=True)
for link in inbound:
    print(f"Context: {link.get('context', '')}")""",

    "9_1": """# Ingest a single file
result = wiki.ingest_source("path/to/document.md")
print(f"Status: {result.get('status')}")""",

    "9_2": """# Ingest with dry-run (CLI)
# llmwikify ingest document.md --dry-run""",

    "9_3": """# Batch ingest from directory (CLI)
# llmwikify batch raw/sources/""",

    "9_4": """# Verify raw/ directory structure after ingest
from pathlib import Path
raw_dir = wiki.root / "raw"
print(f"Raw dir exists: {raw_dir.exists()}")""",

    "9_5": """# Search ingested content
results = wiki.search("keyword", limit=5)
for r in results:
    print(f"{r['page']}: {r['snippet']}")""",

    "10_1": """# Get synthesis suggestions (requires LLM)
result = wiki.suggest_synthesis()
print(f"Suggestions: {len(result.get('suggestions', []))}")""",

    "10_2": """# Knowledge gaps via lint with investigations
result = wiki.lint(generate_investigations=True)
print(f"Issues: {result['issue_count']}")
print(f"Investigations: {len(result.get('investigations', {}))}")""",

    "10_3": """# Knowledge gaps via CLI
# llmwikify knowledge-gaps --json""",

    "10_4": """# Graph analysis with PageRank
# llmwikify graph-analyze --json""",

    "10_5": """# Export graph in multiple formats
# llmwikify export-graph --format html --output graph.html""",

    "11_1": """import yaml

# Parse .wiki-config.yaml
config = yaml.safe_load(Path(".wiki-config.yaml").read_text())
print(f"Default wiki: {config['wikis']['default']}")""",

    "11_2": """from llmwikify.kernel.multi_wiki.registry import WikiRegistry

config = {"wikis": {"local": [{"id": "my-wiki", "path": "."}], "discovery": {}}}
registry = WikiRegistry(config)
registry.initialize()""",

    "11_3": """# Parse discovery section
config = {
    "wikis": {
        "discovery": {
            "enabled": True,
            "scan_paths": ["~/wikis"],
            "scan_depth": 2,
        }
    }
}""",

    "11_4": """# Cross-wiki search
wikis = registry.list_wikis()
for w in wikis:
    print(f"{w.wiki_id}: {w.name}")""",

    "12_1": """# Initialize quant directory
# llmwikify quant-init""",

    "12_2": """import yaml

# Write and read a factor YAML
factor = {"name": "momentum_20d", "L1_logic": "Price momentum"}
factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor_path.parent.mkdir(parents=True, exist_ok=True)
factor_path.write_text(yaml.dump(factor))

loaded = yaml.safe_load(factor_path.read_text())
print(f"Factor: {loaded['name']}")""",

    "12_3": """from llmwikify.reproduction.persist.factor_library import list_factors

factors = list_factors(".")
print(f"Found {len(factors)} factors")""",

    "12_4": """import duckdb

# Create and query factor_values table
conn = duckdb.connect("factor.duckdb")
conn.execute(
    "CREATE TABLE IF NOT EXISTS factor_values "
    "(date DATE, stock VARCHAR, factor_name VARCHAR, value DOUBLE)"
)
result = conn.execute("SELECT COUNT(*) FROM factor_values").fetchone()
print(f"Rows: {result[0]}")""",

    "12_5": """# Paper API endpoint
import httpx
response = httpx.get("http://localhost:8765/api/paper/list")
print(response.json())""",

    "13_1": """# Get inbound and outbound links
inbound = wiki.get_inbound_links("target")
outbound = wiki.get_outbound_links("source")
print(f"Inbound: {len(inbound)}, Outbound: {len(outbound)}")""",

    "13_2": """# References with detail mode (CLI)
# llmwikify references page-a --detail""",

    "13_3": """# Section-level references with [[page#section]]
wiki.write_page("guide", "# Guide\\n\\n## Setup\\nSetup content.")
wiki.write_page("notes", "# Notes\\n\\nSee [[guide#Setup]].")
wiki.build_index()

outbound = wiki.get_outbound_links("notes")
print(f"Links with sections: {len(outbound)}")""",
    
    "14_1": """# Step 1: Ingest extracts text, saves to raw/
result = wiki.ingest_source("path/to/document.md")
print(f"Saved to raw: {result.get('saved_to_raw')}")
print(f"Word count: {result.get('word_count')}")""",
    
    "14_2": """# Step 2: analyze-source uses LLM to extract entities/relations
analysis = wiki.analyze_source("raw/document.md")
print(f"Analysis: {analysis}")""",
    
    "14_3": """# Step 3: batch --self-create uses LLM to create pages
# llmwikify batch raw/sources/ --self-create""",
    
    "14_4": """# Step 4: suggest-synthesis generates cross-source recommendations
result = wiki.suggest_synthesis()
print(f"Suggestions: {len(result.get('suggestions', []))}")""",
    
    "14_5": """# Step 5: synthesize creates wiki page from query answer
result = wiki.synthesize_query(
    query="Compare revenue",
    answer="# Revenue Comparison\\n\\nA: $10B, B: $8B.",
    source_pages=["company-a", "company-b"],
    auto_link=True,
)
print(f"Created page: {result.get('page_name')}")""",
    
    "14_6": """# Full chain: ingest → analyze → write → search → lint
# Step 1: ingest
ingest_result = wiki.ingest_source("document.md")

# Step 2: analyze (LLM)
analysis = wiki.analyze_source(f"raw/{ingest_result['source_name']}")

# Step 3: write page
wiki.write_page("analysis", "# Analysis\\n\\nFrom ingested content.")

# Step 4: build index
idx = wiki.build_index()

# Step 5: search
results = wiki.search("analysis", limit=5)

# Step 6: lint
lint_result = wiki.lint()""",
}


def parse_report(report_path: str) -> list[dict]:
    """Parse pytest report and extract test steps."""
    steps = []
    with open(report_path) as f:
        for line in f:
            match = re.match(
                r"tests/scenarios/test_(\d+_\w+)\.py::\w+::test_(\d+)_(\d+)_(\w+)\s+(PASSED|FAILED|SKIPPED)",
                line,
            )
            if match:
                scenario_key = match.group(1)
                step_num = match.group(2)
                substep_num = match.group(3)
                test_name = match.group(4)
                status = match.group(5)

                steps.append(
                    {
                        "scenario_key": scenario_key,
                        "scenario_name": SCENARIO_NAMES.get(
                            scenario_key, scenario_key.replace("_", " ").title()
                        ),
                        "step": f"{step_num}.{substep_num}",
                        "test_key": f"{step_num}_{substep_num}",
                        "name": test_name.replace("_", " ").title(),
                        "status": status,
                    }
                )
    return steps


def generate_tutorial(steps: list[dict]) -> str:
    """Generate tutorial document from test steps."""
    tutorial = [
        "# Real-World Scenario Tutorial",
        "",
        "> Auto-generated from test results.",
        "> LLM: minimax-M3 (current configuration).",
        "",
        "---",
        "",
    ]

    current_scenario = None
    for step in steps:
        scenario_key = step["scenario_key"]
        scenario_name = step["scenario_name"]

        if scenario_key != current_scenario:
            tutorial.append(f"## {scenario_name}")
            tutorial.append("")
            current_scenario = scenario_key

        status_icon = {"PASSED": "✅", "FAILED": "❌", "SKIPPED": "⏭️"}.get(
            step["status"], "❓"
        )

        tutorial.append(f"### Step {step['step']}: {step['name']} {status_icon}")
        tutorial.append("")

        # Add example code
        test_key = step["test_key"]
        if test_key in EXAMPLE_CODE:
            tutorial.append("```python")
            tutorial.append(EXAMPLE_CODE[test_key])
            tutorial.append("```")
            tutorial.append("")

        tutorial.append(f"**Result:** {step['status']}")
        tutorial.append("")
        tutorial.append("---")
        tutorial.append("")

    return "\n".join(tutorial)


def main():
    if len(sys.argv) < 2:
        print("Usage: python report_to_tutorial.py <report.md>")
        sys.exit(1)

    report_path = sys.argv[1]
    steps = parse_report(report_path)

    if not steps:
        print("No test steps found in report.")
        sys.exit(1)

    tutorial = generate_tutorial(steps)

    output_path = Path("docs/tutorials/real_world_scenarios.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(tutorial)

    print(f"✅ Tutorial generated: {output_path}")
    print(f"   Steps: {len(steps)}")


if __name__ == "__main__":
    main()
