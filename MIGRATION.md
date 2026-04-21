# Migration Guide

> **Current version**: 0.30.0

---

## v0.29.x → v0.30.0

### Wiki Class Refactored into Mixins

The `Wiki` class has been split from a single 2,724-line file into 13 files:

| Before | After |
|--------|-------|
| `core/wiki.py` (2,724 lines) | `core/wiki.py` (135 lines) + 12 mixin files (2,603 lines) |

**Migration**: **No action needed.** The public API is completely unchanged. All methods available on `Wiki` instances work exactly as before:

```python
from llmwikify import Wiki  # Still works
from llmwikify.core import Wiki  # Still works

wiki = Wiki(Path("/path/to/wiki"))
wiki.init()
wiki.write_page("Test", "content")
wiki.lint()
wiki.graph_analyze()
# All methods work identically
```

**New exports** (optional, for advanced use):

```python
from llmwikify.core import (
    WikiUtilityMixin, WikiLinkMixin, WikiSchemaMixin, WikiInitMixin,
    WikiPageIOMixin, WikiSourceAnalysisMixin, WikiLLMMixin,
    WikiRelationMixin, WikiIngestMixin, WikiQueryMixin,
    WikiSynthesisMixin, WikiStatusMixin, WikiLintMixin,
)
```

**Import compatibility**: `from llmwikify.core.wiki import extract` still works (re-exported for test compatibility).

### What Changed Internally

- `wiki.py` now only contains `__init__`, lazy properties (`index`, `query_sink`, `ref_index_path`), and `close()`
- All business logic moved to 12 mixin classes, each with a single responsibility
- `WikiLintMixin` delegates to `WikiAnalyzer` (extracted in Phase 1, v0.30.0)
- All 879 Python tests + 38 frontend tests pass without modification

---

## v0.27.x → v0.28.0

### Enhanced Source Pages (P0)

Source pages now use a 6-section format instead of 3:
1. `## Summary` — Document overview
2. `## Key Entities & Relations` — Entity list + relation graph
3. `## Key Claims & Facts` — Claims with confidence + key facts
4. `## Contradictions & Gaps` — Only if detected (optional)
5. `## Cross-References` — `[[wikilink]]` references
6. `## Sources` — Citation with `[Source: Title](raw/filename)`

**Migration**: No action needed for existing wikis. New source pages will use the enhanced format automatically.

### New CLI Commands (P1)

| Command | Description |
|---------|-------------|
| `suggest-synthesis` | Analyze sources and generate cross-source synthesis suggestions |
| `knowledge-gaps` | Detect knowledge gaps, outdated pages, and redundancy |
| `graph-analyze` | Analyze knowledge graph (PageRank, communities, suggested pages) |

**Migration**: No breaking changes. All existing commands work as before.

### AGENTS.md Removed

`AGENTS.md` has been deleted. It was supposed to be removed in v0.26.0 but persisted. All agent instructions now live exclusively in `wiki.md`.

**Migration**: If you have a custom `AGENTS.md`, migrate any unique content to `wiki.md` and delete the file.

---

## v0.24.x → v0.25.0

### Agent-Aware Init

The `init` command now requires `--agent` parameter for full project setup:

```bash
# Full setup with agent config
llmwikify init --agent opencode   # For OpenCode
llmwikify init --agent claude     # For Claude Code
llmwikify init --agent codex      # For OpenAI Codex
llmwikify init --agent generic    # No agent, just wiki structure
```

**Generated files per agent type:**

| Agent | MCP Config | Schema | Git Ignore |
|-------|-----------|--------|------------|
| opencode | `opencode.json` | `wiki.md` | ✓ |
| claude | `.mcp.json` | `wiki.md` | ✓ |
| codex | `.opencode.json` | `wiki.md` | ✓ |
| generic | — | `wiki.md` | ✓ |

**Schema conflict handling:**
- If `wiki.md` already exists: warned, skipped by default
- Use `--force` to overwrite existing files
- Use `--merge` to keep existing wiki.md
- Legacy `WIKI.md` (uppercase) is noted but not removed

**Adding agent config to existing wiki:**
```bash
llmwikify init --agent opencode --force
```
This adds `opencode.json` or `.mcp.json` to an already-initialized wiki without touching wiki pages.

### Raw Source Analysis

Init now auto-analyzes the `raw/` directory and includes statistics (file counts by category) in generated agent files.

---

## v0.23.x → v0.24.0

### Removed CLI Commands

The following commands have been merged into existing commands and no longer exist:

| Removed | Replacement |
|---------|-------------|
| `llmwikify hint` | `llmwikify lint --format=brief` |
| `llmwikify recommend` | `llmwikify lint --format=recommendations` |
| `llmwikify export-index` | `llmwikify build-index --export-only` |

### Removed MCP Tools

Seven graph/relation tools have been merged into two unified tools:

| Removed | Replacement |
|---------|-------------|
| `wiki_relations_neighbors` | `wiki_graph` with `action: query` |
| `wiki_relations_path` | `wiki_graph` with `action: path` |
| `wiki_relations_stats` | `wiki_graph` with `action: stats` |
| `wiki_write_relations` | `wiki_graph` with `action: write` |
| `wiki_export_graph` | `wiki_graph_analyze` with `action: export` |
| `wiki_community_detect` | `wiki_graph_analyze` with `action: detect` |
| `wiki_report` | `wiki_graph_analyze` with `action: report` |

### Removed Configuration Options

- `performance.cache_size` — Was defined but never read. Remove from your `.wiki-config.yaml` if present.
- `llm.prompt_chaining.ingest` — Chained mode is now the only mode. Remove this toggle.
- `files.index` / `files.log` / `files.config` / `files.config_example` — These config options have been removed. `index.md`, `log.md`, and `.wiki-config.yaml` are now hardcoded internal filenames.

### Removed Files

- `utils/helpers.py` — `slugify()` and `now()` were duplicated as `_slugify()` and `_now()` on the `Wiki` class and never imported from `utils`.
- `prompts/_defaults/ingest_source.yaml` — Deprecated single-call LLM path removed. Chained pipeline (`analyze_source` → `generate_wiki_ops`) is now the only mode.

### Refactored

- **QuerySink Extracted**: ~480 lines of sink-related logic moved from `Wiki` to a new dedicated `QuerySink` class (`core/query_sink.py`). The public API (`wiki.read_sink()`, `wiki.clear_sink()`, `wiki.sink_status()`) is unchanged. Internal methods (`_get_sink_info_for_page`, `_append_to_sink`, etc.) are now on `wiki.query_sink`.
- **Wiki Class Reduced**: 2,477 → 2,021 lines.
- **Sink Location**: `sink/` → `wiki/.sink/`. Sink is now a hidden subdirectory of the wiki layer, matching its semantic role as wiki's operation buffer.

### Sink Migration

When upgrading an existing wiki:

1. **Directory move**: On next `wiki.init()`, the old `sink/` directory will NOT be automatically moved. If you have pending sink entries, manually move them:
   ```bash
   mv sink/ wiki/.sink/
   ```

2. **Frontmatter `sink_path`**: Existing pages have `sink_path: sink/X.sink.md`. This is **backward compatible** — the code auto-translates `sink/` to `wiki/.sink/` when reading. No manual update needed.

3. **MCP/CLI paths**: Change `wiki_read_page("sink/X.sink.md")` → `wiki_read_page("wiki/.sink/X.sink.md")`. Old `sink/` paths still work via auto-redirect.

### API Changes

- `Wiki._llm_process_source_single()` removed. `_llm_process_source()` always uses chained mode.
- `Wiki._get_sink_info_for_page()` → `wiki.query_sink.get_info_for_page()` (internal API)
- `Wiki._append_to_sink()` → `wiki.query_sink.append_to_sink()` (internal API)

---

## v0.22.x → v0.23.0

### New Optional Dependencies

v0.23.0 adds a `[graph]` optional dependency for visualization and community detection.

**Migration**: Install if you need graph features:

```bash
pip install llmwikify[graph]
# or
pip install llmwikify[all]
```

### New CLI Commands

- `export-graph` — Export knowledge graph (HTML/SVG/GraphML)
- `community-detect` — Run Leiden/Louvain community detection
- `report` — Generate surprise score report

### No `graph_index.md` Generated

Community detection outputs to stdout/JSON only. No markdown file is written to the wiki directory. This is intentional — there is no consumer (human, LLM, or tool) that needs a persistent markdown representation of community results.

### API Additions

| New Method | Description |
|------------|-------------|
| `Wiki.get_relation_engine()` | Get RelationEngine instance |
| `Wiki.write_relations(relations, source_file=...)` | Write extracted relations |

---

## v0.21.x → v0.22.0

### Database Schema Change

v0.22.0 adds a `relations` table to `.llmwikify.db`:

```sql
CREATE TABLE relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    relation TEXT NOT NULL,
    confidence TEXT NOT NULL CHECK(confidence IN ('EXTRACTED','INFERRED','AMBIGUOUS')),
    source_file TEXT,
    context TEXT,
    wiki_pages TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Migration**: The table is created automatically on first use. No manual migration needed for existing wikis.

### New CLI Subcommand

- `graph-query` — Query knowledge graph relationships
  - Subcommands: `neighbors`, `path`, `stats`, `context`

### Prompt Changes

The `generate_wiki_ops.yaml` prompt now includes relation extraction instructions. If you have custom prompts, you may want to add relation extraction to your templates.

---

## v0.20.x → v0.21.0

### New Optional Dependency

v0.21.0 adds a `[watch]` optional dependency:

```bash
pip install llmwikify[watch]
# or
pip install llmwikify[all]
```

### New CLI Command

- `watch` — Monitor `raw/` directory for file changes
  - Default: notify-only (no auto-ingest)
  - `--auto-ingest` to enable automatic processing
  - `--git-hook` to install/uninstall git post-commit hook

### No Breaking Changes

Existing workflows are unaffected. Watch mode is purely additive.

---

## v0.19.x → v0.20.0

### New Optional Dependency

MarkItDown is an optional dependency. Existing extractors continue to work as fallbacks.

```bash
pip install llmwikify[extractors]
```

### No Breaking Changes

MarkItDown is used automatically when available. If not installed, the system falls back to legacy extractors (pymupdf, trafilatura, etc.).

---

## v0.18.x → v0.19.0

### Prompt System Changes

v0.19.0 introduces `PromptRegistry` and `PrincipleChecker`. If you have custom prompt directories configured via `prompts.custom_dir`, ensure your YAML templates follow the new structure:

```yaml
name: "template_name"
description: "What this template does"
provider_overrides:
  ollama:
    # Ollama-specific adjustments
  openai:
    # OpenAI-specific adjustments
```

### New Configuration

No config changes required. The prompt system is backward-compatible with existing configurations.

---

## v0.17.x → v0.18.0

### Prompts Moved to YAML

All hardcoded prompts are now in `prompts/_defaults/*.yaml`. If you had custom logic that relied on prompt strings in Python code, update to use `PromptRegistry`:

```python
# Old (v0.17.x)
prompt = "Analyze this source and..."

# New (v0.18.0+)
from llmwikify.core import PromptRegistry
registry = PromptRegistry(wiki_root)
prompt = registry.render("analyze_source", context={"title": "doc.pdf"})
```

### Chaining Mode

Two-step ingest is now available. Enable in config:

```yaml
llm:
  prompt_chaining:
    ingest: true
```

---

## v0.13.x → v0.14.0

### BREAKING: `update_existing` Parameter Removed

**v0.13.x**: `synthesize_query(update_existing=True)`  
**v0.14.0+**: `synthesize_query(merge_or_replace="merge")`

**Migration**:

```python
# Old (v0.13.x)
wiki.synthesize_query(query="Q", answer="A", update_existing=True)

# New (v0.14.0+)
wiki.synthesize_query(query="Q", answer="A", merge_or_replace="merge")  # or "replace" or "sink"
```

The three strategies:
- `"sink"` (default) — append to sink buffer
- `"merge"` — consolidate with existing page
- `"replace"` — overwrite entirely

### MCP Tool Change

`wiki_synthesize` MCP tool now uses `merge_or_replace` (string enum) instead of `update_existing` (boolean).

---

## v0.13.0 — Query Sink Feature

### New Methods

| Method | Description |
|--------|-------------|
| `Wiki.sink_status()` | Overview of all query sinks |
| `Wiki.read_sink(page_name)` | Read pending sink entries |
| `Wiki.clear_sink(page_name)` | Clear processed entries |

### New Directory

`sink/` directory is created for pending query updates. No migration needed — it's created on first use.

---

## v0.12.x → v0.13.0

### New Return Fields

`synthesize_query()` now returns `status: "sunk"` when a similar query page exists.

`read_page()` and `search()` now include `has_sink` and `sink_entries` fields.

**Migration**: If your code checks `result["status"]`, handle the new `"sunk"` value.

---

## v0.11.x → v0.12.x

### Breaking Changes

#### 1. Zero Domain Assumption Enforcement (v0.11.1)

**v0.11.0**: Default exclusion patterns were preset (dates, months, quarters, redirect_to, archive dirs)  
**v0.11.1+**: All exclusion patterns are **empty by default**

**Migration**: If you relied on default exclusions, add them to your `.wiki-config.yaml`:

```yaml
orphan_detection:
  exclude_patterns:
    - '^\d{4}-\d{2}-\d{2}$'  # Dates: 2025-07-31
    - '^\d{4}-\d{2}$'        # Months: 2025-07
    - '^\d{4}-q[1-4]$'       # Quarters: 2025-Q1 (case-insensitive)
  exclude_frontmatter:
    - 'redirect_to'
  archive_directories:
    - 'archive'
    - 'logs'
    - 'history'
```

#### 2. wiki.init() API Changes (v0.12.1)

**v0.11.x**: `wiki.init(agent="claude")`  
**v0.12.1+**: `wiki.init(overwrite=False)` — `agent` parameter removed

**Migration**: Remove `agent` parameter. The `overwrite` parameter controls idempotent behavior:

```python
# Old (v0.11.x)
wiki.init(agent="claude")

# New (v0.12.1+)
wiki.init()              # Skips existing files
wiki.init(overwrite=True)  # Recreates index.md and log.md
```

#### 3. ingest_source() Return Format (v0.12.3+)

**v0.11.x**: `ingest_source()` could auto-create wiki pages via LLM  
**v0.12.3+**: `ingest_source()` returns pure data for LLM processing, does NOT auto-create pages

**Migration**: Use the returned data to manually create pages:

```python
# Old (v0.11.x) — may have auto-created pages
result = wiki.ingest_source("document.pdf")

# New (v0.12.3+) — returns data, LLM creates pages
result = wiki.ingest_source("document.pdf")
# result contains: source_name, source_raw_path, content, instructions, etc.
# Use wiki.write_page() to create pages based on LLM analysis
```

#### 4. Raw Source Collection (v0.12.5+)

**v0.12.4 and earlier**: Local files kept in original location  
**v0.12.5+**: All sources collected into `raw/` directory

**Migration**: Update any hardcoded paths to source files. Use `result['source_raw_path']` from `ingest_source()`:

```python
result = wiki.ingest_source("/path/to/document.pdf")
# result['source_raw_path'] → "raw/document.md"
```

#### 5. New Required Fields in ingest_source() Result (v0.12.5+)

New fields added:
- `source_raw_path`: Path relative to wiki root (e.g., `"raw/title.md"`)
- `hint`: Human-readable hint about what happened (saved, copied, already exists)

---

### New Features in v0.12.x

| Version | Feature | Description |
|---------|---------|-------------|
| 0.12.0 | Complete CLI | 15 commands, auto-index, wiki.md template |
| 0.12.1 | Idempotent init | `overwrite` parameter, structured returns |
| 0.12.2 | Search improvements | ON CONFLICT, FTS5 snippets, LIKE fallback |
| 0.12.3 | Pure-data ingest | ingest returns data, no auto-page creation |
| 0.12.4 | Schema tools | wiki_read_schema, wiki_update_schema MCP tools |
| 0.12.5 | Raw collection | All sources into raw/, citation conventions |
| 0.12.6 | **Query compounding** | **wiki_synthesize saves answers as wiki pages** |

### MCP Tools Added

| Tool | Version | Description |
|------|---------|-------------|
| `wiki_recommend` | 0.12.0 | Missing pages and orphan detection |
| `wiki_build_index` | 0.12.0 | Build reference index |
| `wiki_read_schema` | 0.12.4 | Read wiki.md |
| `wiki_update_schema` | 0.12.4 | Update wiki.md |
| `wiki_synthesize` | 0.12.6 | **Save query answer as wiki page** |

---

## v0.10.0 → v0.11.0

### Modular Architecture

**v0.10.0**: Single file `llmwikify.py` (1,965 lines)  
**v0.11.0+**: Modular package structure

**Migration**: Update import paths:

```python
# Old (v0.10.0)
from llmwikify import Wiki

# New (v0.11.0+)
from llmwikify import Wiki, create_wiki
from llmwikify.core import Wiki, WikiIndex
from llmwikify.mcp import MCPServer
```

---

## v0.9.0 → v0.10.0

### Module Rename

**v0.9.0**: Core module named `wiki.py`  
**v0.10.0**: Core module renamed to `llmwikify.py`

**Migration**: Update imports accordingly.

---

*Last updated: 2026-04-21 | Current version: 0.30.0*
