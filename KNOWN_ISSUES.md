# Known Issues — Pending Fixes

> Auto-generated during v0.28.0 review. Issues marked ✅ have been resolved.

---

## ~~1. Orphan Detection: Index Format Mismatch~~ ✅ Resolved

**Resolved in**: v0.27.0

`page_links.target_page` now stores full relative paths (e.g., `concepts/Risk Parity`), matching the format used by `get_inbound_links()`. Orphan detection and inbound link stats are now accurate.

---

## ~~2. Web UI: `pages_by_type` Rendering Bug~~ ✅ Resolved

**Resolved in**: v0.28.0

`status()` now returns lists of page names per type (e.g., `{"sources": ["sources/Article 1"]}`), matching the JS expectations in `app.js`. The file tree now renders correctly.

---

## ~~3. Graph Export: Hardcoded Entity Path~~ ✅ Resolved

**Resolved in**: v0.27.0

`graph_export.py` now strips directory prefix before slugifying. Entity nodes in HTML export are now clickable.

---

## 4. MCP Server Missing P1 Tools

**Priority**: High | **Impact**: Agent cannot use new P1 features via MCP

Three new P1 CLI commands lack corresponding MCP tools:

| Missing MCP Tool | Feature | CLI Equivalent |
|-----------------|---------|----------------|
| `wiki_suggest_synthesis` | Cross-source synthesis (P1.1) | `suggest-synthesis` |
| `wiki_knowledge_gaps` | Knowledge gap analysis (P1.2) | `knowledge-gaps` |
| `wiki_graph_analyze` (new action) | Graph PageRank/communities/suggestions (P1.3) | `graph-analyze` |

**Fix**: Add `action="suggest_synthesis"`, `action="knowledge_gaps"`, `action="analyze"` to existing MCP tools or create new tools.

**Workaround**: Use CLI commands directly while MCP tools are being added.

---

## 5. MIGRATION.md References Deleted AGENTS.md

**Priority**: Medium | **Impact**: Documentation inconsistency

`MIGRATION.md` still references `AGENTS.md` in multiple places (lines 25, 27, 40), but AGENTS.md was removed in v0.28.0. All agent instructions now live in `wiki.md`.

**Fix**: Update MIGRATION.md to remove AGENTS.md references, replace with wiki.md only.

---

## 6. CHANGELOG Planned Section Outdated

**Priority**: Low | **Impact**: Roadmap clarity

The Planned section in CHANGELOG.md still lists:
- Web UI (optional) — exists but minimal
- Self-hosted Agent mode (`serve`) — still planned
- Incremental index updates — still planned
- Stable API guarantee — still planned
- Production hardening — still planned

**Fix**: Consider updating status, removing abandoned items, or moving to a separate ROADMAP.md file.

---

## 7. Web UI Not Integrated with P1 Features

**Priority**: Low | **Impact**: User experience

The Web UI (`src/llmwikify/web/server.py`) does not integrate with any P1 features:
- Cross-source synthesis
- Knowledge gap analysis
- Graph analysis (PageRank, community labels, suggestions)

**Fix**: Add API endpoints and UI components for P1 features.

**Workaround**: Use CLI commands or MCP tools (once added) for P1 features.
