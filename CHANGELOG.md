# Changelog

All notable changes to llmwikify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- Incremental index updates
- Web UI (optional)
- Graph visualization (graphviz/Mermaid)

---

## [0.16.0] - 2026-04-11

### Added
- **Smart Investigations** — Contradiction detection and data gap analysis for wiki health:
  - `_detect_potential_contradictions()` — Cross-page contradiction scanning:
    - `value_conflict`: Same entity has different values (e.g., revenue: $10M vs $15M)
    - `year_conflict`: Same event has different years (e.g., launched in 2020 vs 2022)
    - `negation_pattern`: One page asserts X, another asserts not X
  - `_detect_data_gaps()` — Data quality gap detection:
    - `unsourced_claims`: Pages with assertions but no `## Sources` section
    - `vague_temporal`: Pages using vague time references (recently, soon, last year)
  - `_llm_generate_investigations()` — LLM-driven investigation suggestions:
    - Generates specific questions to resolve contradictions
    - Recommends source types to fill data gaps
    - Graceful fallback when LLM not available
- **`lint(generate_investigations=True)`** — Optional enhanced analysis:
  - `investigations.contradictions[]` — Observational hints (max 3), no severity classification
  - `investigations.data_gaps[]` — Observational hints (max 3), no severity classification
  - `investigations.suggested_questions[]` — LLM-generated (only when enabled)
  - `investigations.suggested_sources[]` — LLM-generated (only when enabled)
- **18 new tests** in `test_v016_investigations.py` — Comprehensive coverage

### Changed
- `lint()` return structure now includes `investigations` key (independent from `hints`)
- Investigations are **not** classified as critical/informational — pure observations for LLM judgment

### Principle Coverage
- **Lint: "contradictions between pages"** — ✅ New (value_conflict, year_conflict, negation_pattern)
- **Lint: "data gaps that could be filled with a web search"** — ✅ New (unsourced_claims, vague_temporal)
- **Lint: "suggesting new questions to investigate"** — ✅ New (LLM-generated)
- **Lint: "new sources to look for"** — ✅ New (LLM-generated)
- **Zero domain assumption** — ✅ Investigations are observations, not judgments
- **Pure tool design** — ✅ LLM makes final decisions; `generate_investigations=False` skips LLM calls

---

## [0.15.0] - 2026-04-10

### Added
- **Enhanced `ingest_source()` metadata** — returns rich file metadata for LLM context:
  - `file_type` — detected from extension (markdown, pdf, text, html, etc.)
  - `file_size` — byte size of the raw source file
  - `word_count` — word count of extracted text
  - `has_images` / `image_count` — detects markdown image references
  - `text_extracted` — boolean flag
  - `content_preview` — first 200 chars of extracted text
  - **No summary returned** — respects "LLM reads source" principle
- **Clue-based lint detection** — three new observation types, LLM makes final judgment:
  - `dated_claim` (critical, max 3): Pages referencing years ≥3 years older than latest raw source
  - `topic_overlap` (informational, max 2): Query: pages with ≥85% keyword Jaccard overlap
  - `missing_cross_ref` (informational, max 3): Concepts mentioned in 2+ pages without wikilink
- **`hints` structure in `lint()`** — two-tier classification:
  - `hints.critical[]` — demands attention (max 3)
  - `hints.informational[]` — optional context (max 5)
  - Total max 8 hints per lint pass
- **`_detect_file_type()` helper** — static method for file extension detection

### Changed
- `lint()` return structure now includes `hints: {critical: [...], informational: [...]}`
- All lint hints use observational language (non-directive, respects LLM autonomy)

### Principle Coverage
- **Ingest: "LLM reads source, discusses key takeaways"** — ✅ Enhanced (metadata, not summary)
- **Lint: "stale claims superseded by newer sources"** — ✅ New (dated_claim, clue-based)
- **Lint: "missing cross-references"** — ✅ New (missing_cross_ref, clue-based)
- **Zero domain assumption** — ✅ All hints are observations, not judgments

---

## [0.14.0] - 2026-04-10

### Added
- **`merge_or_replace` parameter** in `synthesize_query()` — replaces `update_existing` with three explicit strategies:
  - `"sink"` (default) — append to sink buffer for later review
  - `"merge"` — LLM reads old content, consolidates, replaces formal page
  - `"replace"` — overwrite the formal page entirely
- **Sink suggestion generation** — each sink entry now includes actionable observations:
  - **Content Gap detection**: compares new answer with formal page to find missing topics
  - **Source quality analysis**: checks for missing citations, new sources, completeness
  - **Query pattern analysis**: detects repeated questions, increasing complexity trends
  - **Knowledge growth suggestions**: identifies new concepts, possible contradictions
- **Sink dedup detection**: flags entries with >70% text similarity to existing sink entries
- **Sink urgency tracking** in `sink_status()`: ok / attention (7d+) / aging (14d+) / stale (30d+)
- **`sink_warnings` in `lint()`**: reports stale/aging sinks that need attention
- **Observational hint format** in `synthesize_query()`: non-directive language respects LLM autonomy

### Changed
- **BREAKING**: `update_existing` parameter removed from `synthesize_query()` and MCP tool
- **BREAKING**: `wiki_synthesize` MCP tool now uses `merge_or_replace` (string enum) instead of `update_existing` (boolean)
- `synthesize_query()` returns `status: "merged"` or `"replaced"` instead of `"updated"`
- Hint format changed from `suggestion` (directive) to `observation` + `options` (non-directive)

---

## [0.13.0] - 2026-04-10

### Added
- **Query Sink feature** — Compound answers without creating duplicate pages
  - When a similar query page exists, new answers append to `sink/` instead of creating timestamped copies
  - Sink files: `sink/Query: Topic.sink.md` — one per formal query page
  - Chronological entries with timestamp, query, answer, and sources
  - Bidirectional linking: sink frontmatter → formal page, formal page frontmatter → sink
- **New methods on Wiki class**:
  - `sink_status()` — overview of all sinks with entry counts
  - `read_sink(page_name)` — read pending entries from a sink file
  - `clear_sink(page_name)` — clear processed entries after merge
  - `_append_to_sink()` — internal method to append entries
  - `_get_sink_info_for_page()` — get sink status for a page
  - `_find_or_create_sink_file()` — find or create sink file
  - `_update_page_sink_meta()` — update formal page frontmatter with sink metadata
- **Enhanced `synthesize_query()`**: returns `status: "sunk"` when answer goes to sink
- **Enhanced `read_page()`**: returns `has_sink` and `sink_entries`, supports reading sink files via `sink/` prefix
- **Enhanced `search()`**: attaches `has_sink` and `sink_entries` to each result
- **Enhanced `lint()`**: includes `sink_status` in return value
- **Enhanced `_update_index_file()`**: shows pending sink entry count in index.md
- **New MCP tool**: `wiki_sink_status` — overview of all query sinks
- **Updated wiki.md template**: documents sink workflow and conventions
- **27 new tests** in `test_sink_flow.py` — comprehensive sink feature coverage

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
