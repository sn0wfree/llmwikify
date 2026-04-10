# Changelog

All notable changes to llmwikify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Planned
- MCP server authentication (API key / token)
- Web UI (optional)
- Graph visualization (graphviz/Mermaid)
- Incremental index updates
- More extractors (Word, Excel)

## [0.10.0] - 2026-04-10

### Changed
- Renamed core module from `wiki.py` to `llmwikify.py` for consistency
- Updated version numbering scheme from `v10.0.0` to `v0.10.0`

### Fixed
- Module import paths in all test files
- Documentation references to core module

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
