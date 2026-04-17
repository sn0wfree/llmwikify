# Known Issues — Pending Fixes

> Auto-generated during scheme3+4 review. Not related to current changes.

---

## 1. Orphan Detection: Index Format Mismatch

**File**: `src/llmwikify/core/index.py` → `_parse_links()`, `get_inbound_links()`

**Problem**: `page_links.target_page` stores the raw wikilink text (e.g., `Factor Investing`), but `get_inbound_links(page_name)` queries with the full path (e.g., `concepts/Factor Investing`). For pages in subdirectories, inbound links are never matched.

**Impact**: Orphan page count is inflated; inbound link stats are inaccurate.

**Fix**: Normalize `target_page` during link parsing, or normalize at query time.

**Severity**: Medium — produces wrong lint results but doesn't corrupt data.

---

## 2. Web UI: `pages_by_type` Rendering Bug

**Files**: `src/llmwikify/core/wiki.py:2089-2099` → `src/llmwikify/web/static/js/app.js:158-190`

**Problem**: `status()` returns `pages_by_type` as a count dictionary:
```json
{"sources": 184, "concepts": 69, "entities": 12}
```
But the JS code iterates it as if values are lists:
```js
for (const [type, pages] of groups) {
    for (const pageName of pages.sort()) { ... }
}
```

**Impact**: Web UI file tree is empty or throws JS error.

**Fix**: Either change `status()` to return page lists per type, or fix the JS to render counts instead of lists.

**Severity**: High — breaks web UI file tree.

---

## 3. Graph Export: Hardcoded Entity Path

**File**: `src/llmwikify/core/graph_export.py:103-106`, `154-157`

**Problem**: Entity page path is hardcoded as `../wiki/entities/{_slugify(node)}.md`. After scheme3+4, node names include directory prefix (e.g., `entities/Gold`), causing `_slugify("entities/Gold")` to produce `entities-gold`, resulting in incorrect path `../wiki/entities/entities-gold.md`.

**Impact**: Entity nodes in graph HTML are not clickable.

**Fix**: Strip directory prefix before slugifying, or look up actual `file_path` from `pages` table.

**Severity**: Low — only affects graph HTML export visual feature.
