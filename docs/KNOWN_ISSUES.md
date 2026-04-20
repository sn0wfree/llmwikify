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

## ~~4. MCP Server Missing P1 Tools~~ ✅ Resolved

**Resolved in**: v0.29.0

Three new MCP tools added:
- `wiki_suggest_synthesis` — cross-source synthesis suggestions
- `wiki_knowledge_gaps` — knowledge gap, outdated page, and redundancy analysis
- `wiki_graph_analyze(action="analyze")` — PageRank, community analysis, page suggestions

---

## ~~5. MIGRATION.md References Deleted AGENTS.md~~ ✅ Resolved

**Resolved in**: v0.28.0

All AGENTS.md references in MIGRATION.md have been updated to reference wiki.md.

---

## ~~6. CHANGELOG Planned Section Outdated~~ ✅ Resolved

**Resolved in**: v0.29.0

CHANGELOG.md now has a v0.29.0 section documenting Web UI P1 integration.

---

## ~~7. Web UI Not Integrated with P1 Features~~ ✅ Resolved

**Resolved in**: v0.29.0

Web UI now includes an Insights Panel with three tabs (Synthesis, Gaps, Graph) that integrate all P1 features. The graph visualization has been upgraded to use `wiki_graph_analyze('analyze')` for PageRank-based node sizing, community-based coloring, bridge node highlighting, and suggested page display.

---
