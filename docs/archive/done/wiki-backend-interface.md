# Wiki Backend Interface (Level 2 — Full Backend-ization)

**Status**: planned, not started
**Date**: 2026-06-06
**Goal**: Reduce the `Wiki` god node's in-degree and prepare the codebase for future storage backends (InMemory, Remote, Cloud) without changing the public API.

This is the post-7-item-refactor continuation. The 7-item refactor
(Phases 1-3) reduced `WikiCLI` from the top-10 god nodes
but `Wiki` itself remains at 111 in-degree. This document
captures the full Level 2 backend-ization plan that the team
agreed on.

---

## 1. Background

### 1.1 Current state (post-7-item-refactor)

| Metric | Value |
|--------|-------|
| `Wiki` in-degree | **111** (stable) |
| `Wiki` methods (total) | 100 |
| Mixins | 13 (`wiki_mixin_*.py`) |
| Mixin total LOC | 3,061 |
| Direct fs ops in mixins | **27** (not via `self.write_page()` etc.) |
| `Wiki(tmp_path)` fixture | 22ms each (fs + SQLite) |
| `Wiki(tmp_path)` fixtures in test suite | ~290 |
| Test files using `Wiki(tmp_path)` | 19 |

### 1.2 The god-node problem

`Wiki` is still the central object that 1,044+ call sites
reference. The 13 mixins mostly delegate to engines
(WikiAnalyzer, RelationEngine, SynthesisEngine), but
the 27 direct fs ops in mixin files and the 100-method
surface area keep the in-degree high.

### 1.3 Why Level 2 (full backend-ization)

Three options were considered:

| Option | Storage abstraction | Mixin改造 | Net benefit |
|--------|---------------------|-----------|-------------|
| A: Wiki Facade (mixins deleted, engines own methods) | No | Yes | Modest |
| **B: WikiBackend Interface (this plan)** | **Yes** | **Yes** | **High (架构 + extensibility)** |
| C: Wiki Engines Registry | Partial | Yes | Engine 循环引用 risk |

Level 2 backend-ization is the chosen path because:

1. **清晰抽象**: Storage layer (filesystem, in-memory, remote)
   becomes swappable without touching business logic.
2. **Mixin 无知 backend**: Mixin files call Wiki helper methods
   (which delegate to backend), not the backend directly. This
   keeps the abstraction layered cleanly.
3. **未来可扩展**: Adding `InMemoryBackend` (faster tests),
   `RemoteWikiBackend` (HTTP wikis), or `CloudWikiBackend`
   (S3-backed) becomes a single file each, with no
   modifications to the Wiki class or any of the 13 mixin
   files.
4. **Mixins 抽象边界**: The 27 direct fs ops in mixin files are
   a code smell. The backend-ization cleans this up by making
   all storage go through the Wiki layer.

### 1.4 What is **not** in this plan (deferred)

- **InMemoryBackend**: 1 commit + ~100 LOC, deferred. After
  Level 2 lands, this is a clean add (see §6).
- **RemoteWikiBackend**: Same — 1 commit + ~150 LOC when needed.
- **Replacing `WikiIndex`**: Stays as the SQLite-backed index
  implementation. `InMemoryBackend` (future) can use
  `WikiIndex(db_path=Path(":memory:"))` to get SQLite in-memory
  mode for free.

---

## 2. WikiBackend Protocol (Level 2 API)

13 core methods. The Wiki class calls these primitives; the
concrete backend decides how to store.

```python
# src/llmwikify/core/wiki_backend.py

class WikiBackend(Protocol):
    """Storage layer — only data persistence, no business logic.

    Wiki orchestrates business logic (path resolution, page
    type mapping, content sanitization) and calls these
    primitives for storage. The concrete impl (default
    LocalFileBackend, future InMemoryBackend, etc.) handles
    how data is actually stored.
    """

    root: Path
    wiki_dir: Path
    raw_dir: Path
    index: "WikiIndex"  # SQL-backed (can be :memory: in future)

    # === Pages (4 methods) ===
    def get_page(self, name: str) -> str | None: ...
    def put_page(self, name: str, content: str) -> None: ...
    def delete_page(self, name: str) -> bool: ...
    def list_page_paths(self) -> list[Path]: ...

    # === Index (2 methods) ===
    def get_index(self) -> str: ...
    def put_index(self, content: str) -> None: ...

    # === wiki.md (3 methods) ===
    def get_wiki_md(self) -> str | None: ...
    def put_wiki_md(self, content: str) -> None: ...
    def merge_wiki_md(self, existing: str, new: str) -> str: ...

    # === Log (1 method) ===
    def append_log(self, entry: dict) -> dict: ...

    # === Source analysis cache (2 methods) ===
    def get_source_cache(self, key: str) -> dict | None: ...
    def put_source_cache(self, key: str, hash: str, data: dict) -> None: ...

    # === Page type mapping (1 method) ===
    def get_page_type_mapping(self) -> dict[str, str]: ...
```

**Total**: 13 methods, all storage primitives (no business
logic, no path resolution, no content formatting).

---

## 3. Wiki Class — 1-line Delegations

### 3.1 `__init__` shape

```python
class Wiki:
    def __init__(self, root, config=None, backend=None):
        self.config = config or load_config(self.root)
        # Backend is REQUIRED (no inline fs fallback).
        # 100% backward compatible: default backend is LocalFileBackend.
        self._backend: WikiBackend = backend or LocalFileBackend(root, self.config)

        # Backward-compat attribute aliases — these still exist
        # because 100+ tests and external code reads them.
        # Their values come from the backend.
        self.root = self._backend.root
        self.wiki_dir = self._backend.wiki_dir
        self.raw_dir = self._backend.raw_dir
        self.db_path = self._backend.db_path
        self.index = self._backend.index
        self.index_file = self.wiki_dir / 'index.md'
        self.log_file = self.wiki_dir / 'log.md'
        self.wiki_md_file = self.root / 'wiki.md'
        self.ref_index_path = self.wiki_dir / 'reference_index.json'
        self.sink_dir = self.wiki_dir / '.sink'
        # ... other path attributes (computed once in __init__)
```

### 3.2 22 storage methods → 1-line delegations

| Wiki method | Body after refactor |
|-------------|---------------------|
| `read_page(name, page_type=None)` | resolve path via `page_type` → `self._backend.get_page(name)` → return dict |
| `write_page(name, content, page_type=None)` | validate, sanitize, resolve path → `self._backend.put_page(name, content)` |
| `_wiki_pages()` | `return self._backend.list_page_paths()` |
| `_get_existing_page_names()` | `[p.stem for p in self._backend.list_page_paths()]` |
| `_get_page_count()` | `len(self._backend.list_page_paths())` |
| `append_log(op, details)` | format entry → `self._backend.append_log({...})` |
| `build_index(...)` | (mostly business, partial use of backend) |
| `export_index(path)` | `self._backend.put_index(content); copy to path` |
| `_update_index_file(content)` | `self._backend.put_index(content)` |
| `_find_source_summary_page(rel)` | (mostly business: scan candidates) |
| `_cache_source_analysis(path, hash, data)` | `self._backend.put_source_cache(key, hash, data)` |
| `_get_cached_source_analysis(path)` | `self._backend.get_source_cache(key)` |
| `_load_page_type_mapping()` | `self._backend.get_page_type_mapping()` |
| `_handle_wiki_md_schema(...)` | (orchestration: calls `_get_wiki_md_content` + `_write_wiki_md_content`) |
| `_generate_wiki_md()` | (business: generates default wiki.md content) |
| `_merge_wiki_md(...)` | (orchestration: calls `_get_wiki_md_content` + backend) |
| `_create_core_files()` | (orchestration: calls multiple `_*_wiki_md_content` + `_*_index_content` + `append_log`) |
| `_get_recent_log(limit)` | (orchestration: parses log) |
| `is_initialized()` | (status check, no fs) |
| `close()` | (cleanup, no fs) |
| `_extract_page_summary(...)` | (business: summarizes page content) |
| `_get_source_analysis_summary(...)` | (orchestration: backend read) |

Most become 1-line delegations. A few (the business-heavy
ones like `write_page` with path validation) keep more
orchestration in Wiki but call the backend primitives.

### 3.3 10 new Wiki helper methods (for mixin to use)

Mixin files should **never** call `self._backend.X()` directly.
Instead, they call Wiki helper methods which delegate to the
backend. This keeps the abstraction layered (mixin → Wiki →
backend → fs).

| New Wiki method | Used by mixin for |
|-----------------|-------------------|
| `_get_wiki_md_content()` | reading wiki.md |
| `_write_wiki_md_content(content)` | writing wiki.md |
| `_merge_wiki_md_content(existing, new)` | merging wiki.md |
| `_get_index_content()` | reading index.md |
| `_write_index_content(content)` | writing index.md |
| `_get_log_content()` | reading log.md (full content) |
| `_ensure_raw_dir()` | mkdir raw/ |
| `_find_wiki_page_path(name)` | finding a page by stem name |
| `_get_page_type_mapping()` | (alias of backend call) |
| `_get_source_cache(key)` | (alias of backend call) |

All 10 are 1-line delegations. Total new code: ~30 LOC.

---

## 4. Mixin 改造 — 27 fs ops 改写映射

| File | Ops | Before | After |
|------|-----|--------|-------|
| `wiki_mixin_init.py` | 9 | `self.wiki_md_file.read_text()` | `self._get_wiki_md_content()` |
| `wiki_mixin_init.py` | 4 | `self.wiki_md_file.write_text(...)` | `self._write_wiki_md_content(...)` |
| `wiki_mixin_page_io.py` | 5 | `self.wiki_dir.rglob("*.md")` | `self._wiki_pages()` (existing) |
| `wiki_mixin_page_io.py` | 2 | `self.index_file.write_text(...)` | `self._write_index_content(...)` |
| `wiki_mixin_link.py` | 1 | `self.wiki_dir.rglob(f"{target}.md")` | `self._find_wiki_page_path(target)` |
| `wiki_mixin_query.py` | 1 | `self.wiki_dir.rglob("*.md")` | `self._wiki_pages()` (existing) |
| `wiki_mixin_schema.py` | 3 | `self.wiki_md_file.{read,write}_text()` | `self._{get,write}_wiki_md_content()` |
| `wiki_mixin_source_analysis.py` | 2 | mixed fs + index | `self._get_wiki_md_content()` + `self._get_index_content()` |
| `wiki_mixin_llm.py` | 1 | `self.wiki_md_file.read_text()` | `self._get_wiki_md_content()` |
| `wiki_mixin_ingest.py` | 2 | `self.raw_dir.mkdir()` + `self.index_file.read_text()` | `self._ensure_raw_dir()` + `self._get_index_content()` |
| **Total** | **27** | (mixed) | (unified via Wiki helpers) |

**Example before/after**:

```python
# wiki_mixin_init.py:57-59 (Before)
original_content = self.wiki_md_file.read_text()
if original_content:
    self.wiki_md_file.write_text(merged_content)

# After
original_content = self._get_wiki_md_content()
if original_content:
    self._write_wiki_md_content(merged_content)
```

```python
# wiki_mixin_page_io.py:299 (Before)
for page in sorted(self.wiki_dir.rglob("*.md")):

# After
for page in sorted(self._wiki_pages()):
```

---

## 5. Engines — No Changes Needed

The 3 existing engines (`RelationEngine`, `WikiAnalyzer`,
`SynthesisEngine`) all access Wiki via `self.wiki.X(...)`.
After the refactor:

- `self.wiki.X(...)` is still available (22 methods preserved as
  1-line delegations)
- Engines don't know about `self._backend` (encapsulation)
- No engine code changes needed

The same applies to all 100+ test files that use
`wiki_instance.write_page()` etc.

**唯一** 涉及到 engine 的间接改动是：
- `wiki_analyzer.py` 内部有 17 处 `self.wiki.X` 调用 —— 这些继续工作
- `synthesis_engine.py` 内部有 4 处 `self.wiki.X` 调用 —— 这些继续工作
- `relation_engine.py` 直接用 `self.index`，不接触 wiki —— 不变

---

## 6. Future: InMemoryBackend Add-on

After Level 2 lands, adding `InMemoryBackend` is a clean
**1 commit + ~100 LOC**:

```python
class InMemoryBackend:
    """In-memory storage — for fast tests."""

    def __init__(self):
        self.root = Path("/in-memory-wiki")
        self.wiki_dir = Path("/in-memory-wiki/wiki")
        self.raw_dir = Path("/in-memory-wiki/raw")
        # Reuse WikiIndex with SQLite in-memory mode!
        self.db_path = Path(":memory:")
        self.index = WikiIndex(self.db_path)
        # Pages are pure dict (no fs)
        self._pages: dict[str, str] = {}
        self._log: list[dict] = []
        # ... 13 get/put methods (all O(1) dict ops)
```

**关键 insight**: `WikiIndex(db_path=Path(":memory:"))` 复用现有 SQLite
代码（in-memory 模式是 SQLite 标准特性），**不需要 InMemoryWikiIndex 类**。

**速度提升**: `Wiki(tmp_path)` 22ms → `Wiki(backend=InMemoryBackend())` 0.5ms
(~44× speedup). With ~290 fixtures in the test suite, that's
~6 seconds saved per test run.

---

## 7. Future: RemoteWikiBackend (HTTP-backed)

After Level 2, the codebase already has a `RemoteWiki` class
in `core/remote_wiki.py` (HTTP client). The next refactor
could either:
- **Option A**: Implement `RemoteWikiBackend` that wraps HTTP calls
  to a remote llmwikify server (matches the existing `mcp/` and
  `server/` modules).
- **Option B**: Delete `RemoteWiki` (it's an older abstraction) and
  have the new `RemoteWikiBackend` be the single remote path.

This is **out of scope** for the current plan but is the
next natural step after `InMemoryBackend`.

---

## 8. Commit-by-Commit Execution Plan

### Commit 1: WikiBackend Protocol + LocalFileBackend

**Type**: additive (no behavior change)
**Files**:
- **NEW** `src/llmwikify/core/wiki_backend.py` (~200 LOC)
- **NEW** `tests/test_wiki_backend.py` (~200 LOC, 10 tests)
- 0 changes to Wiki, mixins, or any consumer

**WikiBackend Protocol + LocalFileBackend**:

```python
class WikiBackend(Protocol):
    """... (13 methods, see §2) ..."""

class LocalFileBackend:
    """Default backend: filesystem-based storage.

    Encapsulates all the filesystem I/O that used to be
    inline in Wiki methods. Init sets up paths; methods
    do storage primitives.
    """
    def __init__(self, root, config=None):
        self.config = config or {}
        self.root = root.resolve()
        self.wiki_dir = get_directory(self.root, 'wiki', self.config)
        self.raw_dir = get_directory(self.root, 'raw', self.config)
        self.db_path = get_db_path(self.root, self.config)
        self.index = WikiIndex(self.db_path)
        self._source_cache_dir = self.raw_dir / ".source_cache"
        self._source_cache_dir.mkdir(parents=True, exist_ok=True)
        # 13 method impls (one-liners like get_page / put_page)
```

**Tests (10)**:
1. `test_local_backend_init` — paths configured correctly
2. `test_local_backend_get_put_page` — round-trip page I/O
3. `test_local_backend_delete_page` — returns bool
4. `test_local_backend_list_page_paths` — list all pages
5. `test_local_backend_get_put_index` — index.md round-trip
6. `test_local_backend_get_put_wiki_md` — wiki.md round-trip
7. `test_local_backend_merge_wiki_md` — merge behavior
8. `test_local_backend_append_log` — log format
9. `test_local_backend_source_cache` — cache round-trip
10. `test_local_backend_page_type_mapping` — type→dir parsing
11. `test_local_backend_unicode_filenames` — edge case

**Why this commit standalone?**:
- Pure additive, 0 risk
- Establishes the abstraction before the refactor
- Commit 2 can be bisected against this if there are issues

**Risk**: 🟢 Low

**LOC**: +400 / -0
**Time**: 1-1.5h

---

### Commit 2: Wire Wiki to use backend

**Type**: main refactor (22 method delegations + 27 mixin changes)
**Files**:
- `src/llmwikify/core/wiki.py` — `__init__` + 22 1-line delegations + 10 new helpers
- `src/llmwikify/core/wiki_mixin_init.py` — 13 fs ops → Wiki helpers
- `src/llmwikify/core/wiki_mixin_page_io.py` — 7 fs ops → Wiki helpers
- `src/llmwikify/core/wiki_mixin_link.py` — 1 fs op → Wiki helper
- `src/llmwikify/core/wiki_mixin_query.py` — 1 fs op → Wiki helper
- `src/llmwikify/core/wiki_mixin_schema.py` — 3 fs ops → Wiki helpers
- `src/llmwikify/core/wiki_mixin_source_analysis.py` — 2 fs ops → Wiki helpers
- `src/llmwikify/core/wiki_mixin_llm.py` — 1 fs op → Wiki helper
- `src/llmwikify/core/wiki_mixin_ingest.py` — 2 fs ops → Wiki helpers
- **NEW** `tests/test_wiki_uses_backend.py` (~150 LOC, 8 tests)

**Key design decisions**:

1. **No fallback path** (commit 1 is safer with dual-path, but
   by commit 2 the backend is well-tested)
2. **Mixin files call Wiki helpers, not `self._backend`** —
   keeps the abstraction layered (mixin → Wiki → backend → fs)
3. **Backward-compat storage attributes preserved**:
   `self.root`, `self.wiki_dir`, etc. still exist (their values
   come from `self._backend.X`)
4. **Engines untouched** — they only call `self.wiki.X()` which
   still works

**Tests (8 in test_wiki_uses_backend.py)**:
1. `test_wiki_default_uses_local_backend` — `Wiki(root)` uses LocalFileBackend
2. `test_wiki_accepts_custom_backend` — `Wiki(root, backend=mock)` accepts custom
3. `test_wiki_write_page_uses_backend` — write_page calls backend.put_page
4. `test_wiki_read_page_uses_backend` — read_page calls backend.get_page
5. `test_wiki_index_attribute_is_backend_index` — wiki.index === backend.index
6. `test_wiki_root_path_equals_backend_root` — wiki.root === backend.root
7. `test_mixin_uses_wiki_helpers_not_direct_fs` — grep guard: mixin源码不直接 fs
8. `test_backend_swap_does_not_affect_public_api` — swap backend, API works

**Full test suite verification**: 1821 tests must pass
after this commit (round-trip behavior preservation).

**Risk**: 🟡 Medium
- Wiki helper 方法行为 must match original fs ops exactly
- Mixin 改造 must cover all 27 sites (grep guard catches misses)
- engines 行为 transparent (they don't know about backend)

**Mitigation**:
- Commit 1's 10 round-trip tests validate `LocalFileBackend` behavior
- Commit 2's grep guard catches mixin 漏改
- Full 1821 test suite verifies end-to-end behavior
- Each commit independently revertable

**LOC**: +220 / -90
**Time**: 2-3h

---

## 9. Total Time and LOC Budget

| Commit | LOC Δ | Time | Risk |
|--------|------|------|------|
| 1: Backend Protocol + LocalFileBackend | +400 / -0 | 1-1.5h | 🟢 Low |
| 2: Wire Wiki to use backend | +220 / -90 | 2-3h | 🟡 Medium |
| **Total** | **+620 / -90** | **3-4.5h** | |

**vs 方案 C (Engines Registry)**: 12-15h, ~640 net LOC, 循环引用 risk
**vs 不做**: 0 net LOC 减少, Wiki god node remains at 111 in-degree

---

## 10. Risk Matrix

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| LocalFileBackend 行为与原 Wiki 不一致 | 🟡 Medium | Low | Round-trip tests (Commit 1) + full 1821 suite (Commit 2) |
| Mixin 漏改某处 | 🟡 Medium | Low | grep guard in Commit 2 + suite |
| Engines 行为变化 | 🟢 Low | Very low | engines 只调 `self.wiki.X` — transparent |
| 公共 API 破坏 | 🟢 Low | Low | `Wiki.__init__` 接受 `backend=` 默认 LocalFileBackend |
| 性能 regression | 🟢 Low | Very low | LocalFileBackend 复用现有 fs 代码（无额外开销） |
| Test isolation 问题 | 🟢 Low | Low | 现有 fixture 行为不变（仍是 LocalFileBackend） |

**Overall risk**: 🟡 Medium (well-understood, well-bounded)

---

## 11. Rollback Strategy

Each commit is independently revertable:

**Commit 1 失败**:
- Delete `wiki_backend.py` + `test_wiki_backend.py`
- 0 impact (Wiki unchanged)

**Commit 2 失败**:
- Revert Wiki 22 method delegations (restore inline fs)
- Revert mixin 10 helper calls (restore direct fs)
- LocalFileBackend remains in codebase but unused (no harm)

**Full rollback**: 0 functional change. Codebase returns to
pre-Commit-1 state.

---

## 12. Verification Plan

After Commit 2 lands, run:

```bash
# Full test suite (must be 1821/1821 passing)
python3 -m pytest tests/ --ignore=tests/e2e -q

# graphify-out re-measurement (target: Wiki in-degree reduction)
graphify  # see diff in GRAPH_REPORT.md

# Manual smoke tests
llmwikify --help
llmwikify help  # should show same commands
llmwikify init /tmp/test-wiki
llmwikify write_page "Test" "content"
llmwikify read_page "Test"
llmwikify close
```

---

## 13. Future Roadmap (Post Level 2)

| Priority | Item | Effort | Value |
|----------|------|--------|-------|
| 🟡 Medium | InMemoryBackend + test migration | 1 commit, ~3-4h | 5-6s test speedup |
| 🟢 Low | RemoteWikiBackend (HTTP) | 1 commit, ~6h | Multi-server support |
| 🟢 Low | CloudWikiBackend (S3) | 1 commit, ~8h | Cloud persistence |
| 🟢 Low | WikiCachingBackend (L1 cache) | 1 commit, ~4h | Read-heavy perf |

---

## 14. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-06 | Level 2 chosen over Level 1 | Full abstraction worth the extra effort |
| 2026-06-06 | InMemoryBackend deferred | 5-6s 提速不值 ~100 LOC 维护 |
| 2026-06-06 | Mixin files use Wiki helpers (not self._backend) | Encapsulation preservation |
| 2026-06-06 | No `InMemoryWikiIndex` class | `WikiIndex(:memory:)` 复用现有 SQLite |
| 2026-06-06 | Engines untouched | 17+4 self.wiki.X calls stay transparent |
| 2026-06-06 | `Wiki(tmp_path)` API unchanged | 100% backward compat |

---

## 15. References

- **Original 7-item refactor plan**: `PLAN.md`
- **MCP consolidation plan**: `docs/archive/done/cli-help-and-aliases.md`
- **Engines analysis**: `wiki_analyzer.py`, `relation_engine.py`, `synthesis_engine.py`
- **Mixin files**: `src/llmwikify/core/wiki_mixin_*.py`
- **WikiIndex**: `src/llmwikify/core/index.py`
- **Test fixtures**: `tests/conftest.py`

---

## 16. Open Questions (None)

All design decisions are captured above. The plan is ready to
execute as 2 commits.

**Next step**: Run `git log` to see recent activity, then
`git checkout -b refactor/wiki-backend` to start.
