# Migration Guide

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

*Last updated: 2026-04-10 | Current version: 0.12.6*
