# Real-World Scenario Tutorial

> Auto-generated from test results.
> LLM: minimax-M3 (current configuration).

---

## 01 Wiki Core

### Step 1.1: Init Wiki ✅

```python
from llmwikify import create_wiki

# Create a wiki at the specified path
wiki = create_wiki("./my-wiki")
print(f"Wiki root: {wiki.root}")
```

**Result:** PASSED

---

### Step 1.2: Write Page ✅

```python
# Write a page to the wiki
wiki.write_page("python-basics", "# Python Basics\n\nPython is a programming language.")

# Read the page back
result = wiki.read_page("python-basics")
print(result["content"])
```

**Result:** PASSED

---

### Step 1.3: Write Multiple Pages ✅

```python
# Write multiple pages
pages = {
    "python": "# Python\n\nA programming language.",
    "ml": "# Machine Learning\n\nUses Python.",
    "data-science": "# Data Science\n\nUses Python and ML.",
}

for name, content in pages.items():
    wiki.write_page(name, content)
```

**Result:** PASSED

---

### Step 1.4: Search ✅

```python
# Search for content
results = wiki.search("Python", limit=10)
for r in results:
    print(f"{r['page']}: {r['snippet']}")
```

**Result:** PASSED

---

### Step 1.5: Build Index ✅

```python
# Build the reference index
idx = wiki.build_index()
print(f"Indexed {idx['total_pages']} pages")
```

**Result:** PASSED

---

### Step 1.6: Bidirectional Links ✅

```python
# Get inbound links (who links to this page)
inbound = wiki.get_inbound_links("python")
print(f"Pages linking to python: {len(inbound)}")

# Get outbound links (what this page links to)
outbound = wiki.get_outbound_links("python")
print(f"Pages linked from python: {len(outbound)}")
```

**Result:** PASSED

---

### Step 1.7: Lint ✅

```python
# Run health check
result = wiki.lint()
print(f"Issues: {len(result['issues'])}")
print(f"Hints: {len(result['hints']['critical'])}")
```

**Result:** PASSED

---

### Step 1.8: Status ✅

```python
# Get wiki status
status = wiki.status()
print(f"Pages: {status['page_count']}")
print(f"Links: {status['link_count']}")
```

**Result:** PASSED

---

## 02 Knowledge Graph

### Step 2.1: Build Index ✅

```python
# Build index for graph analysis
wiki.build_index()
```

**Result:** PASSED

---

### Step 2.2: Analyze Source ✅

```python
# Analyze a source file (requires LLM)
result = wiki.analyze_source("raw/paper.pdf")
print(f"Entities: {len(result.get('entities', []))}")
```

**Result:** PASSED

---

### Step 2.3: Suggest Synthesis ✅

```python
# Get synthesis suggestions (requires LLM)
result = wiki.suggest_synthesis()
print(f"Suggestions: {len(result)}")
```

**Result:** PASSED

---

### Step 2.4: Knowledge Gaps Via Cli ✅

```python
# Check knowledge gaps via CLI
# llmwikify knowledge-gaps
```

**Result:** PASSED

---

### Step 2.5: Graph Analyze Via Cli ✅

```python
# Analyze graph via CLI
# llmwikify graph-analyze --json
```

**Result:** PASSED

---

### Step 2.6: Export Graph Via Cli ✅

```python
# Export graph visualization
# llmwikify export-graph --format html --output graph.html
```

**Result:** PASSED

---

## 03 Multi Wiki

### Step 3.1: Register Wiki ✅

```python
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

config = {"wikis": {"local": [], "discovery": {}}}
registry = WikiRegistry(config)
registry.initialize()

# Register a wiki
registry.register_wiki("my-wiki", "My Wiki", "/path/to/wiki")
```

**Result:** PASSED

---

### Step 3.2: List Wikis ✅

```python
# List all registered wikis
wikis = registry.list_wikis()
for w in wikis:
    print(f"{w.wiki_id}: {w.name}")
```

**Result:** PASSED

---

### Step 3.3: Switch Wiki ✅

```python
# Switch default wiki
registry.set_default_wiki("wiki-c2")
```

**Result:** PASSED

---

### Step 3.4: Unregister Wiki ✅

```python
# Unregister a wiki
registry.unregister_wiki("wiki-d")
```

**Result:** PASSED

---

### Step 3.5: Wiki Discovery ✅

```python
from llmwikify.kernel.multi_wiki.discovery import WikiDiscovery

discovery = WikiDiscovery()
found = discovery.scan("/path/to/wikis")
print(f"Found {len(found)} wikis")
```

**Result:** PASSED

---

## 04 Chat React

### Step 4.1: Health Check ✅

```python
import httpx

# Check server health
response = httpx.get("http://localhost:8765/api/health")
print(response.json())  # {"status": "ok"}
```

**Result:** PASSED

---

### Step 4.2: Auth Optional ✅

```python
# Auth is optional in default config
response = httpx.post(
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "hello"}
)
```

**Result:** PASSED

---

### Step 4.3: Chat Sse ✅

```python
# Chat via SSE streaming
with httpx.stream(
    "POST",
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "What is Python?"},
    headers={"Authorization": "Bearer your-token"}
) as response:
    for line in response.iter_lines():
        if line.startswith("data:"):
            print(line)
```

**Result:** PASSED

---

### Step 4.4: Chat With Wiki Tool ✅

```python
# Chat with wiki tool invocation
response = httpx.post(
    "http://localhost:8765/api/agent/chat",
    json={"session_id": "test", "message": "Search for Python in the wiki"}
)
```

**Result:** PASSED

---

### Step 4.5: Chat Session List ✅

```python
# List chat sessions
response = httpx.get("http://localhost:8765/api/agent/sessions")
print(response.json())
```

**Result:** PASSED

---

## 05 Quant Pipeline

### Step 5.1: Quant Init Via Cli ✅

```python
# Initialize quant directory
# llmwikify quant-init
```

**Result:** PASSED

---

### Step 5.2: Write Factor ✅

```python
import yaml

# Write a factor YAML file
factor = {
    "name": "momentum_20d",
    "L1_logic": "Price momentum over 20 days",
    "L2_computation": "close / close.shift(20) - 1",
}

factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor_path.parent.mkdir(parents=True, exist_ok=True)
factor_path.write_text(yaml.dump(factor))
```

**Result:** PASSED

---

### Step 5.3: List Factors ✅

```python
from llmwikify.reproduction.persist.factor_library import list_factors

factors = list_factors(".")
print(f"Found {len(factors)} factors")
```

**Result:** PASSED

---

### Step 5.4: Read Factor ✅

```python
import yaml

# Read a factor YAML
factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor = yaml.safe_load(factor_path.read_text())
print(factor["L1_logic"])
```

**Result:** PASSED

---

### Step 5.5: Duckdb Schema ✅

```python
import duckdb

# Create factor_values table
conn = duckdb.connect("quant/factor.duckdb")
conn.execute("""
    CREATE TABLE IF NOT EXISTS factor_values (
        date DATE,
        stock VARCHAR,
        factor_name VARCHAR,
        value DOUBLE
    )
""")
```

**Result:** PASSED

---

### Step 5.6: Paper Api ✅

```python
# List papers via API
response = httpx.get("http://localhost:8765/api/paper/list")
print(response.json())
```

**Result:** PASSED

---

### Step 5.7: Factor Library List ✅

```python
# List factors via API
response = httpx.get("http://localhost:8765/api/factor/library/list")
print(response.json())
```

**Result:** PASSED

---

## 06 Lint Rules

### Step 6.1: Dated Claim ✅

```python
# Create page with old date reference
wiki.write_page("old-report", "# Report 2018\n\nRevenue: $10B.")

# Lint will detect dated_claim
result = wiki.lint()
```

**Result:** PASSED

---

### Step 6.2: Potentially Outdated ✅

```python
# Create page with old reference
wiki.write_page("outdated", "# Data\n\nFrom 2019 report.")
```

**Result:** PASSED

---

### Step 6.3: Unsourced Claims ✅

```python
# Create page without source citations
wiki.write_page("claims", "# Claims\n\nMarket grew 15%.")
```

**Result:** PASSED

---

### Step 6.4: Orphan Page ✅

```python
# Create page with no inbound links
wiki.write_page("orphan", "# Orphan\n\nNo one links to me.")
```

**Result:** PASSED

---

### Step 6.5: Brief Mode ✅

```python
# Lint in brief mode (counts only)
result = wiki.lint(mode="brief")
print(f"Total issues: {result['issue_count']}")
```

**Result:** PASSED

---

## 07 Yaml Templates

### Step 7.1: Parse Personal Kb ✅

```python
import yaml

# Parse personal-kb.yaml template
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/personal-kb.yaml").read_text())
print(template["llm"]["provider"])  # "ollama" 
```

**Result:** PASSED

---

### Step 7.2: Parse Project Docs ✅

```python
# Parse project-docs.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/project-docs.yaml").read_text())
```

**Result:** PASSED

---

### Step 7.3: Parse Research Wiki ✅

```python
# Parse research-wiki.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/research-wiki.yaml").read_text())
```

**Result:** PASSED

---

### Step 7.4: Parse Mining News ✅

```python
# Parse mining-news-wiki.yaml
template = yaml.safe_load(Path("examples/07_yaml_templates/yaml_templates/mining-news-wiki.yaml").read_text())
```

**Result:** PASSED

---

### Step 7.5: Custom Config ✅

```python
# Create wiki with custom config
config = {
    "llm": {"provider": "test", "model": "test-model"},
    "orphan_detection": {"exclude_patterns": ["^draft-.*"]},
}
wiki = create_wiki("./wiki", config=config)
```

**Result:** PASSED

---

## 08 Section Anchors

### Step 8.1: Write Target Page ✅

```python
# Write a page with sections
wiki.write_page("python-style", """
# Python Style Guide

## Overview
Python emphasizes code readability.

## Naming
Use `snake_case` for functions.
""")
```

**Result:** PASSED

---

### Step 8.2: Write Source Page ✅

```python
# Write page with [[target#section]] links
wiki.write_page("notes", "# Notes\n\nFollow [[python-style#Naming]] rules.")
```

**Result:** PASSED

---

### Step 8.3: Inbound Links ✅

```python
# Get inbound links with section info
inbound = wiki.get_inbound_links("python-style")
for link in inbound:
    print(f"From: {link['source']}, Section: {link.get('section')}")
```

**Result:** PASSED

---

### Step 8.4: Outbound Links ✅

```python
# Get outbound links with section info
outbound = wiki.get_outbound_links("notes")
for link in outbound:
    print(f"To: {link['target']}, Section: {link.get('section')}")
```

**Result:** PASSED

---

### Step 8.5: Include Context ✅

```python
# Get links with surrounding context
inbound = wiki.get_inbound_links("python-style", include_context=True)
for link in inbound:
    print(f"Context: {link.get('context', '')}")
```

**Result:** PASSED

---

## 09 Ingest Workflow

### Step 9.1: Ingest Single File ✅

```python
# Ingest a single file
result = wiki.ingest_source("path/to/document.md")
print(f"Status: {result.get('status')}")
```

**Result:** PASSED

---

### Step 9.2: Ingest Dry Run ✅

```python
# Ingest with dry-run (CLI)
# llmwikify ingest document.md --dry-run
```

**Result:** PASSED

---

### Step 9.3: Batch Ingest ✅

```python
# Batch ingest from directory (CLI)
# llmwikify batch raw/sources/
```

**Result:** PASSED

---

### Step 9.4: Ingest Creates Raw ✅

```python
# Verify raw/ directory structure after ingest
from pathlib import Path
raw_dir = wiki.root / "raw"
print(f"Raw dir exists: {raw_dir.exists()}")
```

**Result:** PASSED

---

### Step 9.5: Ingest Fts Index ✅

```python
# Search ingested content
results = wiki.search("keyword", limit=5)
for r in results:
    print(f"{r['page']}: {r['snippet']}")
```

**Result:** PASSED

---

## Synthesis Workflow

### Step 10.1: Suggest Synthesis Multi ✅

```python
# Get synthesis suggestions (requires LLM)
result = wiki.suggest_synthesis()
print(f"Suggestions: {len(result.get('suggestions', []))}")
```

**Result:** PASSED

---

### Step 10.2: Knowledge Gaps Basic ✅

```python
# Knowledge gaps via lint with investigations
result = wiki.lint(generate_investigations=True)
print(f"Issues: {result['issue_count']}")
print(f"Investigations: {len(result.get('investigations', {}))}")
```

**Result:** PASSED

---

### Step 10.3: Knowledge Gaps Cli ✅

```python
# Knowledge gaps via CLI
# llmwikify knowledge-gaps --json
```

**Result:** PASSED

---

### Step 10.4: Graph Pagerank ✅

```python
# Graph analysis with PageRank
# llmwikify graph-analyze --json
```

**Result:** PASSED

---

### Step 10.5: Export Graph Formats ✅

```python
# Export graph in multiple formats
# llmwikify export-graph --format html --output graph.html
```

**Result:** PASSED

---

## Multi-Wiki Config

### Step 11.1: Config Parse Wikis ✅

```python
import yaml

# Parse .wiki-config.yaml
config = yaml.safe_load(Path(".wiki-config.yaml").read_text())
print(f"Default wiki: {config['wikis']['default']}")
```

**Result:** PASSED

---

### Step 11.2: Config Local Wikis ✅

```python
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

config = {"wikis": {"local": [{"id": "my-wiki", "path": "."}], "discovery": {}}}
registry = WikiRegistry(config)
registry.initialize()
```

**Result:** PASSED

---

### Step 11.3: Config Discovery ✅

```python
# Parse discovery section
config = {
    "wikis": {
        "discovery": {
            "enabled": True,
            "scan_paths": ["~/wikis"],
            "scan_depth": 2,
        }
    }
}
```

**Result:** PASSED

---

### Step 11.4: Search Cross Wiki ✅

```python
# Cross-wiki search
wikis = registry.list_wikis()
for w in wikis:
    print(f"{w.wiki_id}: {w.name}")
```

**Result:** PASSED

---

## Quant Full Pipeline

### Step 12.1: Quant Init Creates Structure ✅

```python
# Initialize quant directory
# llmwikify quant-init
```

**Result:** PASSED

---

### Step 12.2: Factor Write And Read ✅

```python
import yaml

# Write and read a factor YAML
factor = {"name": "momentum_20d", "L1_logic": "Price momentum"}
factor_path = Path("quant/factors/stock/price/momentum_20d.yaml")
factor_path.parent.mkdir(parents=True, exist_ok=True)
factor_path.write_text(yaml.dump(factor))

loaded = yaml.safe_load(factor_path.read_text())
print(f"Factor: {loaded['name']}")
```

**Result:** PASSED

---

### Step 12.3: Factor Library List ✅

```python
from llmwikify.reproduction.persist.factor_library import list_factors

factors = list_factors(".")
print(f"Found {len(factors)} factors")
```

**Result:** PASSED

---

### Step 12.4: Duckdb Factor Values ✅

```python
import duckdb

# Create and query factor_values table
conn = duckdb.connect("factor.duckdb")
conn.execute(
    "CREATE TABLE IF NOT EXISTS factor_values "
    "(date DATE, stock VARCHAR, factor_name VARCHAR, value DOUBLE)"
)
result = conn.execute("SELECT COUNT(*) FROM factor_values").fetchone()
print(f"Rows: {result[0]}")
```

**Result:** PASSED

---

### Step 12.5: Paper Api Endpoint ✅

```python
# Paper API endpoint
import httpx
response = httpx.get("http://localhost:8765/api/paper/list")
print(response.json())
```

**Result:** PASSED

---

## References Detail

### Step 13.1: References Inbound Outbound ✅

```python
# Get inbound and outbound links
inbound = wiki.get_inbound_links("target")
outbound = wiki.get_outbound_links("source")
print(f"Inbound: {len(inbound)}, Outbound: {len(outbound)}")
```

**Result:** PASSED

---

### Step 13.2: References Detail Mode ✅

```python
# References with detail mode (CLI)
# llmwikify references page-a --detail
```

**Result:** PASSED

---

### Step 13.3: References Section Links ✅

```python
# Section-level references with [[page#section]]
wiki.write_page("guide", "# Guide\n\n## Setup\nSetup content.")
wiki.write_page("notes", "# Notes\n\nSee [[guide#Setup]].")
wiki.build_index()

outbound = wiki.get_outbound_links("notes")
print(f"Links with sections: {len(outbound)}")
```

**Result:** PASSED

---
