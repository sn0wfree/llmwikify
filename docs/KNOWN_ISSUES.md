# Known Issues

> **Last updated**: 2026-06-30 (v0.38.0)
>
> 与 v0.30 时代的快照相比，本表已剔除所有已 resolved 的项；当前 active
> issue 数量为 0。详细历史见 [docs/issues/issues.md](issues/issues.md)
> （含 Quick Research 子系统 P0/P1/P2 完整追踪）。

---

## Current Issues (v0.38.0)

**无 P0/P1 active issues。** v0.36–v0.38 期间所有高优先级 bug 已闭环
（详见 [CHANGELOG.md](../../CHANGELOG.md)），最近一次 release notes
[docs/releases/v0.38.0.md](releases/v0.38.0.md) 涵盖完整修复清单。

如果新发现 issue，请到 [GitHub Issues](https://github.com/sn0wfree/llmwikify/issues)
提交（issue tracker 模板已同步更新）。

---

## Resolved Issues

### v0.31 → v0.38（lifespan 迁移在 v0.33 完成）

| # | Issue | Resolved In | Notes |
|---|---|---|---|
| 1 | **FastAPI lifespan deprecation warning** — `@app.on_event("shutdown")` 已迁移到 `lifespan` context manager（[interfaces/server/core.py:165](../../src/llmwikify/interfaces/server/core.py)）。DreamScheduler 启动/停止也由 lifespan 接管。 | v0.33 (Phase 7) | 不再产生 deprecation warning |
| 2 | **`MCPServer` Python API 废弃** — 旧 `MCPServer(wiki).serve()` 已删除，统一到 `WikiServer` + `llmwikify serve` CLI。 | v0.33 (Phase 6-11) | 见 [CONFIGURATION_GUIDE §server](CONFIGURATION_GUIDE.md#7-server-unified-server--mcp--rest--webui) |
| 3 | **MCP 工具集 20 → 26** — 增 6 个 multi-wiki 工具 + 2 个 scoped 变体。 | v0.31 (multi-wiki) | 见 [MCP_SETUP §Available Tools](MCP_SETUP.md#-available-tools-26-total) |
| 4 | **CLI/Agent 路径 ingest 对齐** — `wiki_mixin_ingest.py` + `wiki_mixin_llm.py` + `wiki_mixin_source_analysis.py` 统一使用 `section_metadata + lint_hint`。 | v0.36 (AgentChat hardening) | IN-3 已闭环 |
| 5 | **`core/` / `web/` / `_legacy/` backward-compat shim 删除** — 37+9+4 个 shim 文件清除，所有 caller 已迁到 `kernel/`。 | v0.35 | PR-9 系列 |
| 6 | **Quick Research 报告持久化 bug** — 报告/review 中断后未落库；现在 `report → DB` 同步写入。 | v0.37 (ReAct loop 统一) | DR-13 |
| 7 | **SSE 流断线后无法自动 resume** — 改为 exponential backoff 重连。 | v0.37 | DR-7 |
| 8 | **Ingest 事务原子性** — 写入前快照 + 失败回滚。 | v0.36 | IN-5 |

### v0.30.0–v0.30.1（archived）

| # | Issue | Resolved In |
|---|---|---|
| 1 | **27+ silent exception catches** — `except Exception:` 无日志 | v0.30.1 |
| 2 | **Health check AttributeError** — `wiki.initialized` 不存在 | v0.30.1 |
| 3 | **Missing type annotations** — `Wiki.__init__` / `Wiki.close()` / `MCPAdapter.asgi_app` | v0.30.1 |
| 4 | **Zero test coverage gaps** — `relation_engine.py` / `server/*` 无测试 | v0.30.1 |

### v0.28.0–v0.29.0（archived）

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

新发现的 issue 请到
[GitHub Issues](https://github.com/sn0wfree/llmwikify/issues) 提交。
