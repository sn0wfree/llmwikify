# Known Issues

## Current Issues (v0.30.1)

| # | Issue | Priority | Workaround | Planned Fix |
|---|---|---|-------|------------|
| 1 | **FastAPI lifespan deprecation warning** — `@app.on_event("shutdown")` is deprecated in favor of lifespan handlers. Generates runtime warnings. | Low | None needed — functionality works. Warning is cosmetic. | v0.31.0 — Migrate to FastAPI `lifespan` context manager |

---

## Resolved Issues

### v0.30.0–v0.30.1
| # | Issue | Resolved In |
|---|---|---|
| 1 | **27+ silent exception catches** — `except Exception:` with no logging | v0.30.1 |
| 2 | **Health check AttributeError** — `wiki.initialized` attribute doesn't exist | v0.30.1 |
| 3 | **Missing type annotations** — `Wiki.__init__`, `Wiki.close()`, `MCPAdapter.asgi_app` | v0.30.1 |
| 4 | **Zero test coverage gaps** — `relation_engine.py`, `server/*` had no tests | v0.30.1 |

### v0.28.0–v0.29.0 (Archived)
| # | Issue | Resolved In |
|---|---|---|
| 1 | Orphan Detection: Index Format Mismatch | v0.27.0 |
| 2 | Web UI: `pages_by_type` Rendering Bug | v0.28.0 |
| 3 | Graph Export: Hardcoded Entity Path | v0.27.0 |
| 4 | MCP Server Missing P1 Tools | v0.29.0 |
| 5 | MIGRATION.md References Deleted AGENTS.md | v0.28.0 |
| 6 | CHANGELOG Planned Section Outdated | v0.29.0 |
| 7 | Web UI Not Integrated with P1 Features | v0.29.0 |

---

New issues discovered during development should be reported on [GitHub Issues](https://github.com/sn0wfree/llmwikify/issues).
