---
name: llmwikify
description: Manage a persistent, interlinked wiki knowledge base. Ingest sources, search, write pages, track claims, query knowledge graph via CLI.
---

# llmwikify — CLI Skill

Manage a persistent, interlinked wiki knowledge base through structured CLI commands.
The wiki is a git-tracked markdown directory that the LLM incrementally builds from raw sources.

## When to Use This Skill

Use this skill when the user wants to:
- Set up a new knowledge base from documents (PDFs, URLs, articles)
- Search or query an existing wiki
- Ingest new source files into a knowledge base
- Check wiki health (broken links, orphans, stale claims)
- Explore relationships between concepts (knowledge graph)
- Track factual claims with supporting/contradicting evidence

## Prerequisites

```bash
pip install llmwikify
```

Verify installation:
```bash
llmwikify --help
```

## Quick Start

### 1. Initialize a wiki

```bash
llmwikify init --agent opencode
```

This creates:
- `raw/` — source documents directory
- `wiki/` — LLM-maintained pages
- `wiki.md` — conventions and workflows
- `AGENTS.md` — agent instructions
- `opencode.json` — MCP config (optional)

### 2. Ingest sources

Copy files to `raw/` or ingest directly:
```bash
llmwikify ingest raw/article.md
```

### 3. Search the wiki

```bash
llmwikify search "your query"
```

## Core Workflows

### Ingest a Source

```bash
# Basic ingest (extracts text, saves to raw/)
llmwikify ingest raw/article.md

# Smart ingest (requires LLM configured)
llmwikify ingest raw/article.md --smart

# Preview without creating pages
llmwikify ingest raw/article.md --dry-run
```

**Smart ingest workflow:**
1. Extract text from source
2. LLM analyzes content, detects entities, concepts, claims
3. LLM plans wiki page operations
4. Creates/updates pages in `wiki/`
5. Writes graph relations between concepts

### Create/Read Pages

```bash
# Write a page
llmwikify write_page "Page Name" --content "# Title\n\nContent here"

# Write from file
llmwikify write_page "Page Name" --file content.md

# Read a page
llmwikify read_page "Page Name"
```

### Search

```bash
llmwikify search "gold mining" --limit 10
```

Output format:
```
Search results for: gold mining

1. Gold Industry
   Score: 0.95
   Ghana is a leading **gold mining** country in Africa...

2. Mining Regulations
   Score: 0.72
   New **mining** permits take 2+ years to process...
```

### Maintain Wiki Health

```bash
# Full health check
llmwikify lint

# Quick suggestions
llmwikify lint --format brief

# Missing pages and orphans
llmwikify lint --format recommendations

# Status overview
llmwikify status
```

### Query the Knowledge Graph

```bash
# Find neighbors of a concept
llmwikify graph-query neighbors "Ghana"

# Shortest path between concepts
llmwikify graph-query path "Ghana" "Gold Royalty"

# Graph statistics
llmwikify graph-query stats
```

### Export Graph Visualization

```bash
# Interactive HTML (pyvis)
llmwikify export-graph --format html --output graph.html

# Static SVG
llmwikify export-graph --format svg

# Gephi-compatible GraphML
llmwikify export-graph --format graphml
```

### Community Detection

```bash
llmwikify community-detect --algorithm leiden --resolution 1.0
```

### Batch Ingest

```bash
# Ingest all files in a directory
llmwikify batch raw/gold/

# With smart processing
llmwikify batch raw/ --smart

# Limit to first N files
llmwikify batch raw/ --limit 10
```

## Page Types

The wiki organizes pages into categories:

| Type | Location | Purpose |
|------|----------|---------|
| Source | `wiki/sources/` | Summary of an ingested source |
| Entity | `wiki/entities/` | People, orgs, locations, products |
| Concept | `wiki/concepts/` | Theories, frameworks, methods |
| Comparison | `wiki/comparisons/` | Side-by-side analyses |
| Synthesis | `wiki/synthesis/` | Cross-source analysis |
| Claim | `wiki/claims/` | Factual claims with evidence |
| Overview | `wiki/overview.md` | Top-level synthesis |

## Conventions

- Use `[[wikilink]]` syntax for cross-references between wiki pages
- Cite raw sources using standard markdown links, NOT wikilinks
- Keep pages focused on one topic
- Update existing pages instead of creating duplicates
- The LLM owns `wiki/`; humans own `raw/`

## Full CLI Reference

See `resources/cli-reference.md` for complete documentation of all 19 commands, their arguments, output formats, and examples.

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `Wiki not initialized` | No wiki.md found | Run `llmwikify init` first |
| `LLM not configured` | Smart mode without LLM config | Add `llm.enabled: true` to `.wiki-config.yaml` |
| `No results found` | Search query returned nothing | Try different keywords, check spelling |
| `Error: File not found` | Source file doesn't exist | Verify path relative to wiki root |
