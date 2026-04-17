# Known Issues — Pending Fixes

> Auto-generated during v0.27.0 review. Issues marked ✅ have been resolved.

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
