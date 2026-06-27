# Logging Unification

> Consolidate the project's scattered logging configuration into a single
> L1 foundation entry point, and absorb CodersWheel's timing decorator so
> the implicit external dependency can be dropped from project code.
>
> **Status**: planned
> **Date**: 2026-06-27
> **Branch**: main

---

## 1. Background

A code-reuse audit of the logging system found three concerns:

### 1.1 The only config entry point is buried in the server layer

`setup_logging()` lives in `interfaces/server/core.py` (L4) and is only
called from `WikiServer.run()`. It configures the root logger with a
`RotatingFileHandler` (`~/.llmwikify/agent/server.log`, 10MB x5) plus a
`StreamHandler`, and is idempotent (`if root.handlers: return`).

Consequences:
- CLI, scripts, and tests never trigger it — they get no logging config
  unless they roll their own.
- An L1/L2 module cannot reuse it without importing from L4 (architecture
  violation per `refactor-4layer-architecture.md`).

### 1.2 Five scattered `logging.basicConfig` call sites

Each writes its own format string:

| Site | level | format | datefmt |
|------|-------|--------|---------|
| `scripts/migrate_db_v1_to_v2.py:278` | DEBUG/INFO | `%(message)s` | — |
| `scripts/migrate_autoresearch_v3_to_v4.py:162` | ERROR/INFO | `%(message)s` | — |
| `scripts/migrate_wiki_paths.py:22` | INFO | `%(message)s` | — |
| `tests/ab_testing/test_pass2_adaptive.py:160` | INFO | `%(asctime)s %(levelname)-5s [%(name)s] %(message)s` | `%H:%M:%S` |
| `tests/ab_testing/test_101_quantnodes.py:22` | INFO | `%(asctime)s - %(name)s - %(levelname)s - %(message)s` | — |
| `tests/test_llm_comparison.py:21` | INFO | `%(asctime)s [%(levelname)s] %(message)s` | — |

### 1.3 Implicit CodersWheel dependency for logging + timing

`scripts/run_101_alphas.py` uses `CodersWheel.QuickTool.logger.LoggerHelper`
and `CodersWheel.QuickTool.timer.timer`. CodersWheel is **not** in
`pyproject.toml` — it is an undeclared, implicit dependency.

CodersWheel's `LoggerHelper` (singleton, file+stdout handlers, semantic
`sql()`/`status()` methods, and a `deco(level, timer)` timing decorator) is
weaker than the existing `setup_logging()`: handlers are attached to a named
logger with only Singleton de-dup, the format is hardcoded, and there is no
rotation. The one genuinely useful piece is the **timing decorator**.

---

## 2. Goals

1. One reusable logging entry point in L1 `foundation`.
2. Eliminate the 5 `basicConfig` sites (route through the new entry point).
3. Absorb CodersWheel's timing capability as a standard-logging
   `@log_timing` decorator; drop CodersWheel from project code.
4. Zero behavior change for the server path; preserve each site's
   existing format/level/output via parameters.

Non-goals:
- Touching the wiki domain-level `append_log()` ("log" as data, unrelated
  to Python logging).
- Replacing `_error_logging.log_exception_returning` (complementary:
  one swallows exceptions, the new one times — they coexist).

---

## 3. Design

### 3.1 New module `foundation/logging.py` (L1, no upstream imports)

```python
def setup_logging(
    level: int = logging.INFO,
    log_dir: Path | None = None,          # None + log_file -> ~/.llmwikify/agent
    log_file: str | None = "server.log",  # None -> console-only (no file handler)
    console: bool = True,
    fmt: str | None = None,               # None -> default fmt below
    datefmt: str | None = None,
    force: bool = False,                  # True -> clear existing handlers & reconfigure
) -> None: ...

def log_timing(
    logger: logging.Logger | None = None, # None -> getLogger(fn.__module__)
    level: int = logging.INFO,
    label: str = "",
) -> Callable: ...   # sync + async aware; logs entry + exit + elapsed seconds
```

- Default format: `"%(asctime)s %(levelname)s %(name)s: %(message)s"`.
- Keeps the existing idempotency guard and `RotatingFileHandler`
  (10MB x5). `log_file=None` skips the file handler entirely
  (satisfies the migrate scripts' console-only `%(message)s` mode).
- `force=True` clears existing root handlers before reconfiguring
  (satisfies scripts that re-init the logger after parsing CLI args).
- `log_timing` borrows CodersWheel `deco`'s timing semantics but uses
  standard logging and auto-detects async (same style as
  `_error_logging.py`), living alongside `log_exception_returning`.

### 3.2 Call-site changes

| File | Change |
|------|--------|
| `foundation/logging.py` | **new** `setup_logging` + `log_timing` |
| `foundation/__init__.py` | doc note for the `logging` module |
| `interfaces/server/core.py` | drop local `setup_logging` + `RotatingFileHandler` import; `from llmwikify.foundation.logging import setup_logging` and re-export (keeps `from .core import setup_logging` working) |
| `interfaces/cli/_app.py` `main()` | `setup_logging(log_file=None, console=True)` — console only |
| `scripts/migrate_*.py` (x3) | `basicConfig(...)` -> `setup_logging(level=..., log_file=None, fmt="%(message)s", force=True)` |
| `tests/ab_testing/*` (x2) + `tests/test_llm_comparison.py` | `basicConfig(...)` -> `setup_logging(..., log_file=None, fmt=..., datefmt=...)` |
| `scripts/run_101_alphas.py` | CodersWheel `LoggerHelper`/`timer` -> foundation `setup_logging(log_file=<path>, force=True)` + `getLogger(...)`; `@timer` -> `@log_timing`; remove `from CodersWheel...` imports |

### 3.3 Compatibility

- `server/core.py` re-exports `setup_logging`, so the 33 `WikiServer`
  import sites are unaffected.
- Each migrated site passes its own `fmt`/`datefmt`/`level`, so output is
  byte-identical to before.
- After `run_101_alphas.py` is migrated, project code no longer imports
  CodersWheel (it was never declared in `pyproject.toml`).

---

## 4. Verification

- `ruff check <file>` after each edit.
- `pytest tests/ab_testing/test_pass2_adaptive.py tests/ab_testing/test_101_quantnodes.py tests/test_llm_comparison.py`
- `pytest tests/test_api_multi_wiki.py tests/test_interfaces_server_autocompact_lifespan.py`
  (verify `setup_logging` re-export does not break server imports).
- CLI smoke: run a `llmwikify` subcommand and confirm console logging.

---

## 5. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-06-27 | Put `setup_logging` in L1 `foundation` | Reusable by all layers; respects 4-layer rule |
| 2026-06-27 | Re-export from `server/core.py` | Backward compat for existing imports |
| 2026-06-27 | CLI logs console-only (`log_file=None`) | Avoid polluting `server.log` from CLI runs |
| 2026-06-27 | Absorb CodersWheel `deco` as `log_timing` | Drop implicit, undeclared external dependency |
| 2026-06-27 | Keep `log_exception_returning` separate | Complementary concern (swallow vs time) |
| 2026-06-27 | Do not touch wiki `append_log()` | It is domain data, not Python logging |
