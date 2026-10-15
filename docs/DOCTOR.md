# `llmwikify doctor` — System health check

> **Audience**: users, CI/CD pipelines, and contributors
> **Introduced**: v0.4x (9-check stack); refactored in **v0.40** (Plan B+)
> **Status**: 9 checks, 0 hardcoded paths, every fail has a fix.

`doctor` answers a single question: *will `llmwikify` work for me right now?*
It runs **9 static + runtime checks** against your installation, your wiki,
and your LLM provider, and tells you **what to fix and how** for every failure.

---

## 1. Quick start

```bash
llmwikify doctor                      # All 9 checks (5s with LLM call)
llmwikify doctor --skip-llm           # Skip LLM API call (~1s)
llmwikify doctor --wiki-root /path    # Check a specific wiki project
llmwikify doctor --json               # Machine-readable output for CI
```

| Flag | Effect | Default |
|------|--------|---------|
| `--wiki-root PATH` | Check this wiki (overrides default) | `cwd` (or `wiki.root`) |
| `--skip-llm` | Skip live LLM API test (5s timeout saved) | LLM tested |
| `--json` | Emit JSON instead of human-readable text | text |

> **Tip**: `--wiki-root` is essential when running `doctor` from a directory
> that is *not* your wiki. The flag was broken in earlier v0.40 builds; it is
> fixed in commit `7a155de` — see [§6 Troubleshooting](#6-troubleshooting) if
> you see `path: /home/ll/llmwikify` instead of your wiki.

---

## 2. The 9 checks

| # | Check | Severity on fail | Auto-fixable? |
|---|-------|------------------|---------------|
| 1 | **Config** (`~/.llmwikify/llmwikify.json`) | **FAIL** | yes |
| 2 | **Python** version (≥ 3.10) | **FAIL** | no |
| 3 | **Core deps** (yaml, duckdb, jinja2, llmwikify) | **FAIL** | yes |
| 4 | **Optional extras** (fastapi, fastmcp, watchdog, networkx, markitdown, tiktoken, httpx) | INFO | yes |
| 5 | **LLM connectivity** (5s API call) | **WARN** | no |
| 6 | **Wiki directory** (4 functional + wiki.md-declared subdirs) | **FAIL** if any of 4 missing; **WARN** if declared-only; **INFO** if actual-only | mostly yes |
| 7 | **Permissions** (`~/.llmwikify/` and wiki root writable) | **FAIL** | yes |
| 8 | **WebUI bundle** (`ui/webui/dist/index.html`) | **WARN** | no |
| 9 | **Server health** (`GET /api/health` on `localhost:8765`) | **WARN** | yes |

### Severity rules

- **FAIL** = wiki cannot function. Blocks exit code 0.
- **WARN** = wiki works, but a feature is degraded. Does not block exit 0.
- **INFO** = cosmetic; wiki.md is stale or an optional dep is missing.

---

## 3. Wiki check (the interesting one)

The wiki check (Step 6) used to hardcode `expected = ["wiki.md", ".llmwikify.db", "index.md", "raw"]`,
which made **5/5 production wiki projects** fail the check (because `index.md`
actually lives in `wiki/index.md`, not the project root).

As of v0.40, the check delegates to the `Wiki` class. `Wiki.expected_layout`
parses **`wiki.md`** to extract the page-type subdirectory list, and
`Wiki.layout_diff()` produces a 3-way split:

| Bucket | Meaning | Severity |
|--------|---------|----------|
| `in_both` | declared by `wiki.md` AND exists on disk | OK |
| `declared_only` | declared by `wiki.md` but missing on disk | **WARN** |
| `actual_only` | exists on disk but not declared in `wiki.md` | **INFO** (stale schema) |
| `missing_required` | one of the 4 functional paths missing (`raw/`, `wiki/`, `.llmwikify.db`, `wiki.md`) | **FAIL** |

The parser reads two sections of `wiki.md`:

1. **Directory Structure tree** (box-drawing characters).
   Lines like `├── sources/` under a `wiki/` block.
2. **Page Types table** — markdown table cells containing backtick
   paths like `` `wiki/sources/{slug}.md` ``.

The two sources are merged and deduplicated. **Zero hardcoded page-type
list.** Add a new subdir to your `wiki.md` and doctor tracks it automatically.

> See [`tests/test_doctor_layout.py`](../../tests/test_doctor_layout.py) for
> 5 fixture projects (real user wikis) used to validate the parser.

---

## 4. Recommended actions block

Every fail and every actionable warn carries a **fix dict** with:
- `commands`: shell command(s) that resolve the issue
- `docs`: link into the documentation
- `cost`: estimated time
- `risk`: `low` / `medium` / `high`
- `auto`: whether a future `doctor --fix` (deferred) could safely run it
- `hint` (optional): extra context

In text mode, all actionable items are collected at the bottom of the output:

```
📋 Recommended actions:

  [FAIL 1/1] wiki (4 functional paths missing)
      Fix:   llmwikify init
      Docs:  docs/ONBOARDING.md#init
      Cost:  ~5s    Risk: low    Auto: True
      Hint:  init 自动创建 raw/, wiki/, .llmwikify.db, wiki.md, index.md, log.md
```

In JSON mode, the `fix` field appears on the relevant check:

```json
{
  "category": "wiki",
  "status": "fail",
  "path": "/home/ll/Public/comovement",
  "in_both": [...],
  "declared_only": ["wiki/covenants/", "wiki/risks/"],
  "actual_only": ["wiki/research/"],
  "fix": {
    "commands": ["llmwikify init"],
    "docs":     "docs/ONBOARDING.md#init",
    "cost":     "~5s",
    "risk":     "low",
    "auto":     true
  }
}
```

---

## 5. Exit codes

| Code | Meaning | Common cause |
|------|---------|--------------|
| `0` | All critical checks passed (warnings/info allowed) | healthy install |
| `1` | One or more FAILs | core deps missing, wiki not init'd, etc. |
| `2` | Config file (`~/.llmwikify/llmwikify.json`) missing | run `llmwikify init-llm` |

The exit code reflects **FAILs only**; WARNs and INFOs do not affect the code.

---

## 6. Troubleshooting

### `path: /home/ll/llmwikify` instead of my wiki

**Cause**: `--wiki-root` was passed but ignored. Pre-v0.40 bug; fixed in
commit `7a155de`.

**Fix**: upgrade to v0.40+ (the fix is in `DoctorCommand.run` which now
rebuilds the `Wiki` instance from the flag).

### LLM check times out (5s)

**Cause**: provider unreachable, or key invalid, or base URL wrong.

**Fix**: `llmwikify init-llm` to re-enter credentials. Or check your network.

### Wiki check says `wiki/covenants/`, `wiki/risks/` missing

**Cause**: `wiki.md` declares these in the Page Types table, but the
directories were never created. Not a hard fail — wiki still works.

**Fix**: `mkdir -p wiki/covenants wiki/risks`, or update `wiki.md` to
remove them if you don't need them.

### Wiki check says `wiki/research/` undeclared

**Cause**: you created the directory but didn't update `wiki.md`.

**Fix**: add `research/` to your `wiki.md` Directory Structure tree and
Page Types table. Doctor will then track it.

### All checks pass but Server check says `not running`

**Cause**: `serve` is not running on `localhost:8765`. This is a WARN, not a FAIL.

**Fix**: `llmwikify serve --web --port 8765`. Or ignore — server may
intentionally not be running.

### Config check says `parse error`

**Cause**: `~/.llmwikify/llmwikify.json` is malformed JSON.

**Fix**: `llmwikify init-llm --force` to regenerate. Or hand-edit with
`python -c "import json; json.load(open('/home/llm/.llmwikify/llmwikify.json'))"`.

---

## 7. CI integration

```bash
# Hard gate: fail the pipeline if any FAIL.
llmwikify doctor --skip-llm --json | jq -e '.summary.failed == 0'

# Soft gate: log warnings but don't fail.
llmwikify doctor --skip-llm --json | jq '.summary'

# Auto-fix in CI: extract fix commands from failed checks.
llmwikify doctor --json | jq -r '
  .checks[]
  | select(.fix)
  | .fix.commands[]
'

# Use a different wiki path in CI.
llmwikify doctor --wiki-root "$WIKI_ROOT" --skip-llm
```

The `--json` output is stable: `summary.total`, `summary.passed`,
`summary.failed`, `summary.warnings` are always present. Each check has
`category` + `status` + at least one identifying field. Optional `fix`
field appears only on actionable failures/warnings.

---

## 8. How it differs from related commands

| Command | Reads | Writes | When to use |
|---------|-------|--------|-------------|
| `llmwikify doctor` | env, config, wiki layout | **never** | before running anything; CI gate |
| `llmwikify status` | wiki content (pages, sources) | never | "what's in this wiki?" |
| `llmwikify lint` | page content (dated claims, orphans) | sometimes (`--fix`) | content health check |
| `llmwikify init` | nothing | **always** (creates files) | first-time setup |

Doctor does **not** read wiki page content. It only checks the layout
(directory structure + `wiki.md` schema). For content checks, use
`lint`.

---

## 9. Implementation notes

- `Wiki` class (`src/llmwikify/kernel/wiki/wiki.py`) is the source of truth
  for layout. Doctor is a thin consumer.
- All 9 fix dicts are hardcoded in `src/llmwikify/interfaces/cli/commands/doctor_cmd.py`
  as module-level constants (`_PYTHON_FIX`, `_CORE_DEPS_FIX`, etc.).
- `Wiki._extract_subdirs_from_wiki_md()` is the only place that parses
  `wiki.md`. Other consumers (future `init --verify`, web UI) should call
  it rather than re-implementing the regex.
- `--fix` mode (auto-running low-risk fixes) is **deferred** to a future
  release. The `auto` field in every fix dict marks what would be safe to
  auto-run.
