# Changelog

All notable changes to llmwikify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Enhanced wiki_lint: contradiction detection, stale claims, data gaps (rules + LLM)
- Enhanced wiki_search: include_content, include_sources, include_links parameters
- Expose wiki_hint as MCP tool
- Incremental index updates
- Web UI (optional)
- Graph visualization (graphviz/Mermaid)

---

## [0.12.6] - 2026-04-10

### Added
- **wiki_synthesize MCP tool** — Query knowledge compounding cycle
  - `synthesize_query()` saves query answers as persistent wiki pages
  - Auto-generates page names: `Query: {Topic}` with date suffix for duplicates
  - Smart duplicate detection via keyword overlap (Jaccard similarity ≥ 0.3)
  - `update_existing=True` revises existing page instead of creating new
  - Auto-appends structured Sources section:
    - Wiki pages as `[[wikilinks]]`
    - Raw sources as `[Source: filename](raw/path)` markdown links
  - Auto-logs to `log.md` with parseable format: `## [timestamp] query | ... → [[page]]`
  - New page auto-indexed in FTS5 and `index.md`
- **27 new tests** in `test_query_flow.py` — comprehensive coverage of synthesize scenarios

---

## [0.12.5] - 2026-04-10

### Added
- **Raw source collection**: All ingest sources unified into `raw/` directory
  - URL/YouTube: extracted text saved to `raw/`
  - Local files outside `raw/`: copied in (cross-platform safe via `read_bytes`/`write_bytes`)
  - Local files already in `raw/`: no copy needed
  - Returns `source_raw_path` and `hint` for LLM guidance
- **Source citation conventions** in generated `wiki.md`:
  - Raw sources cited with standard markdown links: `[Source: Title](raw/filename)`
  - Explicitly prohibits `[[raw/filename]]` wikilink syntax
  - Two approaches: page-level `## Sources` section or inline citations
- **MCP config auto-read**: `MCPServer(wiki)` now reads from `wiki.config["mcp"]` when no explicit config passed

### Changed
- `ingest_source()` now returns `source_raw_path` field alongside `source_name`
- `ingest_source()` instructions updated with citation guidance (step 6-7)
- Log entries for ingest now include raw path: `Source (url): Title → raw/slug.md`

### Testing
- 4 new test cases: raw collection, skip, duplicate, instruction validation
- Total: 83 → 87 tests passing

---

## [0.12.4] - 2026-04-10

### Added
- **wiki_read_schema MCP tool** — Read `wiki.md` (schema/conventions file)
  - Returns content, file path, and hint to save copy before changes
- **wiki_update_schema MCP tool** — Update `wiki.md` with new conventions
  - Validates format (warnings only, does not block)
  - Returns suggestions for post-update actions
- **wiki.md reference in ingest** — `ingest_source()` instructions now direct LLM to `wiki.md` for conventions

### Changed
- `ingest_source()` instructions updated: "See wiki.md for wiki conventions and workflows"

---

## [0.12.3] - 2026-04-10

### Changed
- **Pure-data wiki_ingest**: `ingest_source()` returns extracted data for LLM processing, does NOT automatically create wiki pages
- **URL raw persistence**: URL/YouTube extracted text always saved to `raw/` for persistence
- **Optional LLM smart CLI**: `_llm_process_source()` and `execute_operations()` are optional, only used when LLM client configured
- **Unified error handling**: All operations return structured dicts with `error` key on failure

---

## [0.12.2] - 2026-04-10

### Improved
- **ON CONFLICT for pages table**: `created_at` preserved on updates, only mutable fields changed
- **FTS5 snippet highlighting**: Search results include `**highlighted**` snippets via FTS5 snippet function
- **LIKE fallback**: FTS5 syntax errors gracefully fall back to `LIKE` search

---

## [0.12.1] - 2026-04-10

### Changed
- **Optimized wiki_init**:
  - Removed `agent` parameter (zero domain assumption)
  - Added `overwrite` parameter for idempotent re-initialization
  - Always skips `wiki.md` and config example if they exist
  - Structured return with `created_files`, `skipped_files`, `existing_files`

---

## [0.12.0] - 2026-04-10

### Added
- **Phase 1: Complete CLI commands** — 15 commands total
  - `init`, `ingest`, `write_page`, `read_page`, `search`
  - `lint`, `status`, `log`, `references`, `build-index`
  - `export-index`, `batch`, `hint`, `recommend`, `serve`
- **Auto-index**: `write_page()` automatically updates `index.md`
- **wiki.md template**: Generated on `init()` with conventions and workflows
- **hint command**: Smart suggestions for wiki improvement
- **recommend command**: Missing pages and orphan detection

---

## [0.11.1] - 2026-04-10

### Changed
- **Enforced zero domain assumption**: All exclusion patterns empty by default
  - `default_exclude_patterns`: `[]` (was: dates, months, quarters)
  - `exclude_frontmatter`: `[]` (was: `redirect_to`)
  - `archive_directories`: `[]` (was: archive, logs, history)
- Users must explicitly configure exclusions in `.wiki-config.yaml`

---

## [0.11.0] - 2026-04-10

### Changed
- **Modular package structure** — evolved from single-file `llmwikify.py`
  - `core/wiki.py` — Wiki class (business logic)
  - `core/index.py` — WikiIndex class (FTS5 + reference tracking)
  - `extractors/` — Content extractors (text, pdf, web, youtube)
  - `cli/commands.py` — CLI interface
  - `mcp/server.py` — MCP server
  - `utils/helpers.py` — Utility functions
- **Configuration system**: `config.py` with `load_config()`, `get_default_config()`
- **Public API stability maintained** across refactor

### Added
- Optional dependencies for extractors (`pymupdf`, `trafilatura`, `youtube-transcript-api`)

---

## [0.10.0] - 2026-04-10

### Changed
- Renamed core module from `wiki.py` to `llmwikify.py` for consistency
- Updated version numbering scheme from `v10.0.0` to `v0.10.0`

### Fixed
- Module import paths in all test files
- Documentation references to core module

---

## [0.9.0] - 2026-04-09

### Added
- SQLite FTS5 full-text search
- Bidirectional reference tracking
- MCP server support (8 tools)
- CLI with 15 commands
- Smart recommendations engine
- Configuration system (.wiki-config.yaml)
- Comprehensive test suite (48 tests)

### Features
- Zero core dependencies (standard library only)
- Optional dependencies for extended functionality
- Performance optimized (1000x faster than naive implementation)
- Pure tool design (zero domain assumptions)
