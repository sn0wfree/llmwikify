# Changelog

All notable changes to llmwikify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.30.0] - 2026-04-24

### Added — Phase 2: Wiki Mixin Refactoring (2026-04-21)
- **12 new Mixin classes** extracted from `wiki.py` (2724 → 135 lines, -95%):
  - `WikiUtilityMixin` — slug generation, timestamps, templates, page iteration
  - `WikiLinkMixin` — wikilink resolution, fixing, inbound/outbound links
  - `WikiSchemaMixin` — wiki.md read/update, page type mapping
  - `WikiInitMixin` — directory setup, core files, MCP config, skill files
  - `WikiPageIOMixin` — page CRUD, search, log, index file update
  - `WikiSourceAnalysisMixin` — source analysis, caching, summary pages
  - `WikiLLMMixin` — LLM calls with retry, source processing, synthesis
  - `WikiRelationMixin` — relation engine, graph analysis, operations
  - `WikiIngestMixin` — source ingestion, extraction, raw collection
  - `WikiQueryMixin` — query pages, similarity matching, sink integration
  - `WikiSynthesisMixin` — cross-source synthesis suggestions
  - `WikiStatusMixin` — status reporting, recommendations, hints
  - `WikiLintMixin` — health check (delegates to WikiAnalyzer)
- **Public API unchanged** — all 879 Python tests + 38 frontend tests pass without modification
- **Mixin composition** — `Wiki` class inherits from all 12 mixins in dependency order
- **WikiAnalyzer preserved** — `WikiLintMixin` delegates to `WikiAnalyzer` (Phase 1 extraction)

### Added — Web UI Enhancements (2026-04-22 ~ 2026-04-24)
- **Collapsible Sidebar** — Toggle sidebar visibility, auto-expand groups
- **Pinned Pages** — Quick access to frequently used pages
- **Page Tree Enhancement** — Dynamic colors by page type, type icons, search filtering, sorting options
- **Graph Visualization Upgrade** — D3.js with PageRank-based node sizing, community coloring, bridge node highlighting, suggested pages as dashed nodes
- **Project Metadata Display** — `llmwikify · project-name` format using wiki root directory name
- **Version Display** — `v0.30.0` version number right-aligned in sidebar header
- **Status API Enhancement** — Backend `status()` endpoint returns `version` and `root` fields

### Added — Agent Layer (Completed v0.30.0)
- **8 Agent sub-systems fully implemented**:
  - `WikiAgent` — Main orchestrator class
  - `AgentRunner` — Execution loop and state management
  - `TaskScheduler` — Cron-based scheduled task execution (croniter)
  - `AgentMemory` — Short/long-term memory management
  - `AgentTools` — Wiki tool bindings and MCP integration
  - `HooksSystem` — Event hooks with pre/post operation callbacks
  - `NotificationManager` — User notification system
  - `DreamEditor` — Asynchronous proposal generation with human confirmation flow
- **All 85+ Agent tests passing**
- **Dream Confirmation Flow**: Agent proposes changes → Human reviews/confirms → Changes applied

### Fixed — Code Quality (2026-04-22 ~ 2026-04-24)
- **Mypy Type Checking**: Resolved all core CLI, index, and protocol type errors. Configured optional dependencies.
- **Ruff Lint**: Resolved all lint issues, updated config format.
- **E2E Tests**: Fixed selector issues, added type stubs.
- **Graph Stability**: Improved node position persistence, smooth transitions.

### Changed
- `wiki.py` reduced from 2724 lines to 135 lines (only `__init__` + lazy properties)
- `core/__init__.py` exports all 12 mixin classes alongside `Wiki`, `WikiIndex`, `QuerySink`, `WikiAnalyzer`
- TypeScript API interfaces updated with new optional `version` and `root` fields
- Frontend built and bundled with latest changes

### Architecture
- Mixin files total: 2603 lines across 12 files
- Clear separation of concerns: each mixin has single responsibility
- Independently testable: each mixin can be tested in isolation
- Agent layer fully decoupled from core via MCP protocol
- Web UI fully integrated with MCP REST API

### Tests
- **879+ Python tests passing** (all)
- **38+ Frontend tests passing** (Vitest + React Testing Library)
- **85+ Agent layer tests passing**

## [0.29.0] - 2026-04-17

### Added — Web UI P1 Integration
- **3 new MCP tools**: `wiki_suggest_synthesis`, `wiki_knowledge_gaps`, `wiki_graph_analyze(action="analyze")`
- **Insights Panel** in Web UI sidebar with 3 tabs:
  - **Synthesis** — cross-source reinforced claims, contradictions, knowledge gaps
  - **Gaps** — outdated pages, knowledge gaps, redundant pages detection
  - **Graph** — PageRank hubs, bridge nodes, suggested pages from graph analysis
- **Graph view upgraded** — uses `wiki_graph_analyze('analyze')` instead of per-page fetch:
  - Node sizing based on PageRank centrality score
  - Node coloring by detected community (Leiden/Louvain)
  - Bridge nodes highlighted with orange stroke + indicator
  - Suggested pages shown as dashed-outline ghost nodes
  - Analysis summary overlay showing community count, bridge count, top hubs
- **Health panel expanded** — added "stale pages" indicator alongside broken links and orphans
- **Click-to-load insights** — panels load on demand, refreshable via ↻ button

### Changed
- `wiki_graph_analyze` MCP tool now supports `action="analyze"` for P1.3 graph analysis
- Graph visualization now renders from single API call instead of N sequential requests
- `graph.js` refactored with `buildFromAnalysis()` primary path + `buildFromReferences()` fallback

### Fixed
- Web UI no longer limited to v0.27.0 feature set — all P1 features now accessible
- `heightlightedNodes` typo fixed to `highlightedNodes` in GraphView class

## [0.28.0] - 2026-04-17

### Added — P0: Enhanced Source Page Format
- **Source pages now include 6 structured sections** (was 3):
  1. `## Summary` — Document overview and analytical perspective
  2. `## Key Entities & Relations` — Entity list with types/attributes + relation graph
  3. `## Key Claims & Facts` — Claims with confidence levels + key facts
  4. `## Contradictions & Gaps` — Potential contradictions and data gaps (optional, only if detected)
  5. `## Cross-References` — `[[wikilink]]` references to related wiki pages
  6. `## Sources` — Citation with `[Source: Title](raw/filename)` format
- All 9 `analyze_source` extraction fields now mapped to Source page sections
- `wiki_schema.yaml` updated with complete Source page template example

### Added — P1.1: Cross-Source Synthesis Engine
- **`SynthesisEngine` class** (`core/synthesis_engine.py`) — compares new sources against existing wiki
  - `_find_reinforced_claims()` — detects claims confirmed by multiple sources
  - `_find_new_contradictions()` — finds conflicts between new and existing content
  - `_find_knowledge_gaps()` — identifies topics needing more information
  - `_find_new_entities()` — suggests creating pages for new entities
  - `_find_topic_overlap()` — detects redundant topic coverage
- **`Wiki.suggest_synthesis()` method** — analyze sources and return suggestions (not auto-executed)
  - Respects "stay involved" principle — human decides what to do with suggestions
  - Returns: reinforced claims, contradictions, knowledge gaps, suggested updates, new entities
- **CLI: `llmwikify suggest-synthesis [source]`** — generate cross-source synthesis suggestions
  - `--json` flag for programmatic consumption

### Added — P1.2: Smart Lint 2.0
- **`_detect_outdated_pages()`** — pages referencing years ≥2 years old
- **`_detect_knowledge_gaps()`** — unreferenced entities, isolated source pages without wikilinks
- **`_detect_redundancy()`** — similar page names, potentially duplicate content
- **Lint output enhanced** — investigations now include Contradictions, Data Gaps, Outdated Pages, Knowledge Gaps, Redundancy sections
- **CLI: `llmwikify knowledge-gaps`** — focused knowledge gap analysis command

### Added — P1.3: Knowledge Graph Analyzer
- **`GraphAnalyzer` class** (`core/graph_analyzer.py`) — comprehensive graph analysis
  - PageRank centrality scoring to identify core concepts
  - Hub/Authority node identification (high out-degree / in-degree)
  - Community detection with automatic labeling
  - Bridge node detection (nodes connecting multiple communities)
  - Suggested page generation for orphan concepts and under-connected pages
- **`Wiki.graph_analyze()` method** — run full graph analysis
- **`Wiki.graph_suggested_pages_report()` method** — generate human-readable report
- **CLI: `llmwikify graph-analyze`** — analyze knowledge graph structure
  - `--json` for programmatic output
  - `--report` for detailed suggested pages report

### Changed
- Source page format significantly enriched — from 3 sections to 6 sections
- Lint investigations expanded from 2 to 5 categories
- All new features respect "stay involved" principle — suggestions only, no auto-execution

### Fixed
- Test infrastructure updated for new graph analyzer methods
- CLI command registration for all new P1 features

### Tests
- **24 new tests** across 2 files: `test_p1_features.py` (12) + `test_p1_3_graph_analyzer.py` (12)
- All tests passing: 760 total (was 736)

## [0.27.0] - 2026-04-16

### Changed
- **Wikilink Resolution**: `_resolve_wikilink_target` now uses two-layer strategy (direct path → SQLite index), no longer performs filesystem rglob scans.
- **Index Page Names**: `page_name` in SQLite index now stores full relative paths (e.g., `concepts/Factor Investing` instead of `Factor Investing`), ensuring consistent resolution across all operations.
- **Wikilink Convention**: `wiki_schema.yaml` now requires directory prefix in wikilinks (e.g., `[[concepts/Factor Investing]]` instead of `[[Factor Investing]]`).

### Added
- **`resolve_by_name` Method**: New `WikiIndex.resolve_by_name()` for efficient page resolution via SQL lookup with basename fallback.
- **`fix_wikilinks` Method**: Auto-repair broken wikilinks by adding directory prefix. Supports `dry_run` mode, handles section links and aliases, reports ambiguous matches.
- **`lint(mode="fix")` Auto-Fix**: Running lint with `mode="fix"` now automatically repairs broken wikilinks and reports changes.

### Fixed
- **Graph Export**: Hardcoded entity paths in `graph_export.py` now strip directory prefix before slugifying, fixing clickable entity nodes in HTML export.
- **Orphan Detection Consistency**: Index now uses full paths, matching the format used by `get_inbound_links()` and `get_outbound_links()`.

## [0.26.0] - 2026-04-16

### Added
- **Source Analysis & Caching**: `analyze-source` CLI command and `wiki_analyze_source` MCP tool:
  - Analyzes raw source files and caches LLM extraction results (entities, suggested pages, relations)
  - Cache embedded as HTML comments in source summary pages, keyed by content hash
  - Supports `--all` (analyze all sources) and `--force` (re-analyze changed sources)
- **Schema-Aware Lint Gap Detection**: `lint()` now reads source analysis cache to detect:
  - Missing custom type pages (e.g., Model, MacroFactor) defined in wiki.md
  - Orphan concepts in relations table without wiki pages
  - Missing cross-references and schema non-compliance
- **Ingest Analysis Integration**: `ingest_source()` now returns `analysis` and `lint_hint` fields:
  - `analysis`: LLM-extracted entities, suggested pages, topics, and relations
  - `lint_hint`: Auto-detected gaps (missing suggested pages) with fix suggestions
- **Relations Deduplication**: `add_relation()` in RelationEngine now deduplicates based on (source, target, relation, source_file)
- **Agent-Aware Init**: `llmwikify init --agent <type>` generates a complete project setup in one command:
  - `--agent opencode` → `opencode.json` + skill files + `wiki.md` + `.gitignore`
  - `--agent claude` → `.mcp.json` + `wiki.md` + `.gitignore`
  - `--agent codex` → `.opencode.json` + skill files + `wiki.md` + `.gitignore`
  - `--agent generic` → `wiki.md` + `.gitignore` only
- **Raw Source Analysis**: Init auto-analyzes `raw/` directory structure and includes stats in generated files
- **Schema Conflict Detection**: Warns when `wiki.md` or `WIKI.md` already exists, with `--force`/`--merge` options
- **`mcp` CLI Subcommand**: Start MCP server for Agent interaction (`llmwikify mcp`), default stdio transport
- **`--merge` MCP Config Regeneration**: `llmwikify init --agent <type> --merge` now regenerates MCP config files in addition to merging wiki.md

### Changed
- **Single Schema Source**: AGENTS.md removed. wiki.md is now the single source of truth for all conventions, page types, and workflows. LLM reads wiki.md directly via `wiki_read_schema`.
- **Complexity Reduced**: Removed 3 agent template files, eliminated info duplication between AGENTS.md and wiki.md
- **MCP Server → FastMCP**: Replaced low-level `mcp.server.Server` with FastMCP (`@mcp.tool` decorators). 377 lines → 180 lines. Cleaner API, automatic schema generation, and industry-standard framework.
- **Dependency**: `mcp>=1.0.0` → `fastmcp>=3.0.0`
- **API**: `MCPServer(wiki)` replaced by `create_mcp_server(wiki)` + `serve_mcp(wiki)`
- **`serve` CLI Subcommand**: Reserved for future self-hosted Agent with LLM API integration (no longer MCP server entry point)

### Planned
- Web UI (optional)
- Self-hosted Agent mode (`serve`) — Direct LLM API integration without external Agent
- Incremental index updates
- Stable API guarantee
- Production hardening

---

## [0.24.0] - 2026-04-13

### Changed
- **CLI Simplified**: Removed 3 redundant commands (22 → 19):
  - Removed `hint` — merged into `lint --format=brief`
  - Removed `recommend` — merged into `lint --format=recommendations`
  - Removed `export-index` — merged into `build-index --export-only`
- **`lint` command** now supports `--format` flag:
  - `--format=full` (default) — Full health check (existing behavior)
  - `--format=brief` — Quick suggestions (replaces old `hint`)
  - `--format=recommendations` — Missing and orphan pages (replaces old `recommend`)
- **`build-index` command** now supports `--export-only` flag to export without rebuilding (replaces old `export-index`)

### Removed (Dead Code Cleanup)
- **`ingest_source.yaml` prompt** — Deprecated single-call LLM path fully removed. LLM ingest now always uses the chained `analyze_source → generate_wiki_ops` pipeline
- **`_llm_process_source_single()` method** — Removed. `_llm_process_source()` now always uses chained mode
- **`prompt_chaining.ingest` config option** — Removed. Chained mode is the only mode
- **`performance.cache_size` config option** — Removed. Was defined but never used in any code
- **`files.*` config options** — `files.index`, `files.log`, `files.config`, `files.config_example` removed. These internal filenames are now hardcoded.
- **`utils/helpers.py`** — `slugify()` and `now()` were duplicated as `_slugify()` and `_now()` on the `Wiki` class and never imported from `utils`.

### Refactored
- **QuerySink Extracted**: ~480 lines of sink-related logic moved from `Wiki` (2,477 lines) to a new dedicated `QuerySink` class (`core/query_sink.py`, 444 lines). Wiki is now ~2,021 lines. Public API unchanged; internal methods moved to `wiki.query_sink`.
- **Sink Location**: Moved `sink/` to `wiki/.sink/` — sink is now a hidden subdirectory of the wiki layer, matching its semantic role as wiki's operation buffer. Obsidian auto-hides it; API paths change from `sink/X.sink.md` to `wiki/.sink/X.sink.md` (old paths still work via backward compat layer).

### MCP Server
- **MCP tools simplified**: Merged 7 graph/relation tools into 2 unified tools (21 → 16):
  - `wiki_graph` — `action: query|path|stats|write` — All graph query operations
  - `wiki_graph_analyze` — `action: export|detect|report` — All graph analysis operations

### Breaking Changes
- `llmwikify hint` → use `llmwikify lint --format=brief`
- `llmwikify recommend` → use `llmwikify lint --format=recommendations`
- `llmwikify export-index` → use `llmwikify build-index --export-only`
- MCP tools renamed: `wiki_relations_neighbors`, `wiki_relations_path`, `wiki_relations_stats`, `wiki_write_relations`, `wiki_export_graph`, `wiki_community_detect`, `wiki_report` → `wiki_graph`, `wiki_graph_analyze`
- Sink path: `sink/X.sink.md` → `wiki/.sink/X.sink.md` (old paths auto-redirect for backward compat)

---

## [0.23.0] - 2026-04-12

### Added
- **Graph Visualization** — Export knowledge graph in multiple formats:
  - Interactive HTML (pyvis) — clickable nodes, community color-coding, zoom/pan
  - SVG (graphviz) — static, publication-ready diagrams
  - GraphML (Gephi, yEd compatible) — for advanced analysis
- **Community Detection** — Automatic topic clustering via Leiden/Louvain algorithms:
  - Resolution parameter controls granularity (default 1.0)
  - JSON output for programmatic consumption
  - Handles edge cases: empty graphs, isolated nodes, single nodes
- **Surprise Score Reports** — Multi-dimensional unexpected connection analysis:
  - 5 scoring dimensions: confidence weight, cross-source-type, cross-knowledge-domain, cross-community, peripheral-to-hub
  - Human-readable explanations for each scored connection
  - `report --top N` for top surprising connections
- **CLI Commands** (3 new): `export-graph`, `community-detect`, `report`
- **Optional `[graph]` dependency**: networkx, pyvis, python-louvain
- **13 new tests** in `test_v023_graph.py`

### Principle Coverage
- **"Obsidian's graph view"** — ✅ NetworkX + pyvis interactive HTML export
- **"Organized by category"** — ✅ Leiden community detection
- **"suggesting new questions"** — ✅ Surprise Score highlights unexpected connections
- **"pick what's useful, ignore what isn't"** — ✅ `[graph]` optional dependency
- **"The LLM writes and maintains all of it"** — ✅ No `graph_index.md` generated; community results go to stdout/JSON

---

## [0.22.0] - 2026-04-12

### Added
- **Knowledge Graph Relations** — LLM auto-extracts concept relationships during ingest:
  - 8 relation types: `is_a`, `uses`, `related_to`, `contradicts`, `supports`, `replaces`, `optimizes`, `extends`
  - 3 confidence levels: `EXTRACTED` (explicit), `INFERRED` (deduced), `AMBIGUOUS` (uncertain)
- **RelationEngine** — SQLite-backed relationship management:
  - `add_relation()` / `add_relations()` — Insert single or batch relations
  - `get_neighbors()` — Bidirectional neighbor queries with confidence filtering
  - `get_path()` — Shortest path between concepts (NetworkX BFS)
  - `get_stats()` — Graph statistics (nodes, edges, degree distribution)
  - `get_context()` — Original source context for a relation
  - `detect_contradictions()` — Find conflicting relations (e.g., `supports` vs `contradicts`)
  - `find_orphan_concepts()` — Concepts mentioned but without wiki pages
- **`relations` SQLite table** — Stores source, target, relation, confidence, source_file, context, wiki_pages
- **`Wiki.write_relations()` / `Wiki.get_relation_engine()`** — Public API for relation management
- **`graph-query` CLI subcommand** — `neighbors`, `path`, `stats`, `context` queries
- **26 new tests** in `test_v022_relations.py`

### Principle Coverage
- **"noting where new data contradicts old claims"** — ✅ Contradiction detection between relations
- **"The cross-references are already there"** — ✅ Relation engine auto-extracts concept relationships

---

## [0.21.0] - 2026-04-12

### Added
- **File Watcher** — Monitor `raw/` directory for new file arrivals (watchdog):
  - Event types: created, modified, deleted, moved
  - Debounce support (configurable seconds, default 2)
  - Thread-safe timer-based debouncing
- **Two operating modes**:
  - **Notify-only** (default) — Prints event details with ingest hint (respects "stay involved" principle)
  - **Auto-ingest** (`--auto-ingest`) — Automatically calls `ingest_source()` on new files
- **Git post-commit hook** — Optional installation/removal:
  - Runs `llmwikify batch raw/ --smart` after each commit
  - Clean uninstall restores original hook
- **`watch` CLI command** — `--auto-ingest`, `--smart`, `--debounce`, `--dry-run`, `--git-hook`
- **Optional `[watch]` dependency**: watchdog>=3.0.0
- **23 new tests** in `test_v021_watch.py`

### Principle Coverage
- **"incrementally builds and maintains a persistent wiki"** — ✅ Watch mode automates ingest
- **"stay involved"** — ✅ Default is notify-only; `--auto-ingest` is explicit opt-in
- **"The wiki is just a git repo"** — ✅ Git post-commit hook integration

---

## [0.20.0] - 2026-04-12

### Added
- **MarkItDown Integration** — Unified file extractor for 20+ formats:
  - Office: Word (`.docx`), Excel (`.xlsx`), PowerPoint (`.pptx`)
  - Images: `.jpg`, `.png`, `.gif`, `.bmp`, `.tiff`, `.webp`, `.svg`
  - Audio: `.mp3`, `.wav`, `.m4a` (speech transcription ready)
  - Data: `.csv`, `.json`, `.xml`
  - E-book: `.epub`, Archive: `.zip`, Outlook: `.msg`
- **Graceful fallback strategy**: MarkItdown → legacy extractors → text read → error
- **32 new tests** in `test_v020_markitdown_extractor.py`

### Changed
- `ingest_source()` now uses MarkItDown as primary extractor when available
- `extract()` auto-detection prioritizes MarkItDown for non-text/URL/YouTube sources

---

## [0.19.0] - 2026-04-11

### Added
- **Prompt Harness Engineering** — Systematic prompt quality evaluation:
  - `PromptRegistry` — YAML+Jinja2 template system with provider-specific overrides
  - `PrincipleChecker` — 7 principle compliance checks across all prompts
  - Offline prompt evaluation — 8 automated quality checks
  - Golden Source Framework — 5 test scenarios with mock LLM
  - Prompt regression testing with golden source fixtures
- **Context injection** — Dynamic wiki state injection into prompt templates
- **Post-process validation** — Schema validation with configurable retry attempts
- **Provider overrides** — OpenAI, Ollama, Anthropic-specific prompt variants
- **Chaining mode** — Two-step ingest (`analyze_source` → `generate_wiki_ops`)
- **76 new tests** across 4 test files:
  - `test_v019_principle_checker.py` (34 tests)
  - `test_v019_wiki_synthesize.py` (31 tests)
  - `test_v019_eval_prompts.py` (26 tests)
  - `test_v019_harness_regression.py` (16 tests)

### Principle Coverage
- All 7 LLM Wiki Principles checked programmatically across every prompt template

---

## [0.18.0] - 2026-04-11

### Added
- **Prompt Externalization** — All hardcoded prompts moved to YAML + Jinja2 templates:
  - 8 default templates in `prompts/_defaults/`
  - Custom prompt directory support via config
  - Provider-specific conditional rendering in templates
- **Validation & Retry** — JSON schema validation for LLM responses with configurable retry attempts
- **Chaining Mode** — Two-step ingest pipeline: `analyze_source` (understand content) → `generate_wiki_ops` (plan wiki operations)
- **27 new tests** in `test_v018_integration.py` + `test_v018_prompt_engineering.py`

### Changed
- **BREAKING**: LLM prompts no longer hardcoded in Python; loaded from YAML templates
- `llm_client.py` updated to use `PromptRegistry` for template rendering

---

## [0.17.0] - 2026-04-11

### Added
- **Enhanced CLI** — Additional commands and UX improvements:
  - Improved error messages and progress reporting
  - Batch ingest with `--limit` support
  - Better help text and command grouping
- **Performance tuning** — Database PRAGMA optimizations and batch insert improvements
- **Bug fixes** — Various stability improvements from v0.16.x

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
