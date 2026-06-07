# 4-Layer Architecture Refactor Design

> Comprehensive design document for the post-7-item-refactor
> + Level-2-WikiBackend project restructure. Splits the project
> into foundation/kernel/apps/interfaces layers, adds a frontend
> monorepo layout, and integrates the autoresearch framework
> into the apps/chat/ layer with reuse + optimization.
>
> **Status**: planned, 10 batches across 3 sprints
> **Date**: 2026-06-07
> **Branch**: main
> **Total estimated time**: ~22-27h (2-4 working days)

---

## 1. Background

### 1.1 Current state (post prior refactors)

After 7-item refactor + Level 2 WikiBackend Interface, the project
has:
- 30,194 lines of Python source across 100+ files
- 1,852+ tests passing
- 4 known deprecation shims (planned for v0.33.0 removal)
- A `strategy/` and `fetchers/` empty directory
- A `web/static-legacy-deprecated/` 440K of dead assets
- `autoresearch/` (7.6K LOC) as an independent top-level subproject
- Frontend assets (`web/webui/`, `web/webui-agent/`) embedded in the
  Python package (274M of static assets)
- A flat module structure where `core/` mixes business logic
  with storage abstractions, engines, lint rules, and graph
  algorithms (10.5K in 22 files)

### 1.2 The problem

1. **No architectural layers** — `core/`, `agent/`, `autoresearch/`,
   `web/`, `mcp/`, `server/`, `cli/` are all top-level siblings
   with no enforced dependency direction. Cross-layer imports
   happen (e.g., `autoresearch → agent.backend.providers`).
2. **`core/` is overloaded** — Wiki class, mixins, 3 engines,
   lint, query_sink, WikiBackend, WikiIndex, graph analyzers,
   watcher, multi-wiki — all in one flat namespace.
3. **Frontend bloat in Python package** — 274M of npm-built
   static assets under `src/llmwikify/web/webui*/`.
4. **autoresearch status unclear** — independent fork of
   `agent.backend.research` with 10 file duplicates (one
   bit-for-bit identical), documented as "to be rewritten as
   chat base + harness" but no concrete plan.

### 1.3 Goals

1. **Enforce a 4-layer architecture** (foundation/kernel/apps/
   interfaces) with import-linter contracts.
2. **Clean up `core/`** by splitting into `kernel/wiki/`,
   `kernel/storage/`, `kernel/graph/`, `kernel/search/`,
   `kernel/multi_wiki/`.
3. **Move frontend assets to a top-level `ui/` directory** so
   the Python package no longer contains 274M of static assets.
4. **Integrate `autoresearch/` into `apps/chat/`** with code
   reuse + optimization (no full rewrite).
5. **Preserve backward compatibility** via a centralized
   `_legacy/` shim package — old import paths continue to work
   until v0.33.0 cleanup.
6. **Delete dead code**: 2 empty directories + 1 deprecated
   440K static asset folder.

### 1.4 Non-goals

- **No full autoresearch rewrite** — reuse existing 7.6K code,
  only add 3 new files (ChatBase, Harness, ResearchAgent)
  wrapping it.
- **No performance optimization** (high-risk category excluded
  per user decision).
- **No immediate shim removal** — `agent/`, `mcp/server.py`,
  `server/__init__.py::create_unified_server`, and
  `agent/backend/adapters.py` shims stay in `_legacy/` until
  v0.33.0.
- **No public API breakage** — `llmwikify.core.*`, `llmwikify.cli.*`,
  `llmwikify.web.*`, `llmwikify.agent.*` all continue to work
  via top-level re-exports.

---

## 2. All Decisions (decision log)

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Layer granularity | 4 layers (foundation/kernel/apps/interfaces) | Clean separation, each layer has single responsibility |
| D2 | autoresearch | Reuse existing code + optimize (categories 1+2+3+5, exclude 4) | Avoid 1-2 weeks of rewrite, preserve 7.6K of working code |
| D3 | Dependency enforcement | import-linter | More professional than ruff for layered architecture |
| D4 | Path lookups | Delete old paths (no fallback in `find_webui_dist`) | Cleaner, single source of truth |
| D5 | `web/__init__.py` | Rewrite as `interfaces/web/__init__.py` (4-layer interface declaration) | Consistent with other layer __init__.py |
| D6 | Backward compat shims | Preserve in centralized `_legacy/` | No breakage until v0.33.0 |
| D7 | Dead directories | Delete 3: `strategy/`, `fetchers/`, `web/static-legacy-deprecated/` | Confirmed empty/deprecated |
| D8 | webui-agent | Keep (active at `/agent` route via `_mount_agent_spa`) | 137M but actively mounted and used |
| D9 | Execution pace | Sprint A in batches with pause-and-verify gates | Risk-controlled incremental migration |
| D10 | mixin grouping | MX1: 3 subpackages (core/io/analysis) | Theme-driven, balanced file counts |
| D11 | `apps/agent/` internal | Mirror `agent/backend/` structure (core/tools/memory/notifications/scheduler/providers/routes) | 1:1 migration, low cognitive overhead |
| D12 | Optimization scope | Categories 1+2+3+5, exclude category 4 | Low/medium risk only |
| D13 | C4 (merge) vs C5 (test) order | Interleaved — C5.2 first as safety net, then C4, then C5.3-7 | Refactor with full test coverage |
| D14 | `autoresearch/` rewriting | NOT a full rewrite — wrap as `apps/chat/` with 3 new thin files | Preserve working code |

---

## 3. Target Architecture

### 3.1 Repository layout

```
llmwikify/                                          # repo root
│
├── src/llmwikify/                                  # Python source
│   │
│   ├── foundation/                                 # L1: 平台基础层
│   │   ├── __init__.py
│   │   ├── llm/             ← 现有 src/llmwikify/llm/
│   │   ├── extractors/      ← 现有 src/llmwikify/extractors/
│   │   ├── prompts/         ← 现有 src/llmwikify/prompts/
│   │   ├── templates/       ← 现有 src/llmwikify/templates/
│   │   ├── config.py        ← 现有 src/llmwikify/config.py
│   │   ├── llm_client.py    ← 现有 src/llmwikify/llm_client.py
│   │   └── io.py            ★ NEW: 通用 I/O 工具 (供 chat base 用)
│   │
│   ├── kernel/                                     # L2: 业务内核
│   │   ├── __init__.py
│   │   ├── wiki/
│   │   │   ├── __init__.py
│   │   │   ├── wiki.py      ← 现有 src/llmwikify/core/wiki.py
│   │   │   ├── mixins/      ★ MX1 重组: 3 子包
│   │   │   │   ├── __init__.py
│   │   │   │   ├── core/    # init, utility, schema (3 文件)
│   │   │   │   ├── io/      # page_io, ingest, source_analysis, link (4 文件)
│   │   │   │   └── analysis/ # lint, llm, query, relation, synthesis, status (6 文件)
│   │   │   ├── engines/     # analyzer, relation, synthesis
│   │   │   ├── lint/        ← 现有 src/llmwikify/core/lint/
│   │   │   ├── protocols.py ← 现有 src/llmwikify/core/protocols.py
│   │   │   └── constants.py ← 现有 src/llmwikify/core/constants.py
│   │   ├── storage/         # WikiBackend, WikiIndex, QuerySink, watcher
│   │   ├── graph/           # graph_analyzer, graph_export, graph_visualizer
│   │   ├── search/          # qmd_index, qmd_client
│   │   ├── multi_wiki/      # registry, instance, discovery, remote_wiki
│   │   └── principle_checker.py
│   │
│   ├── apps/                                       # L3: 应用
│   │   ├── __init__.py
│   │   ├── agent/          ★ 沿用 agent/backend 拆法
│   │   │   ├── core/        # db, service, runner, config_manager
│   │   │   ├── tools/       # wiki_tools
│   │   │   ├── memory/      # memory_manager
│   │   │   ├── notifications/ # notification_manager
│   │   │   ├── scheduler/   # wiki_scheduler
│   │   │   ├── providers/   # base, registry, xiaomi, minimax
│   │   │   ├── routes/      # agent, ppt, research FastAPI routes
│   │   │   ├── dream_editor.py
│   │   │   └── hooks.py
│   │   ├── research/       # 现有 src/llmwikify/agent/backend/research 重组
│   │   ├── ppt/            # 现有 src/llmwikify/agent/backend/ppt 重组
│   │   ├── chat/           ★ autoresearch 整体迁入 + 3 新文件
│   │   │   ├── __init__.py
│   │   │   ├── (26 现有 autoresearch 文件 git mv 过来)
│   │   │   ├── base.py            ★ NEW: ChatBase (~150 LOC)
│   │   │   ├── harness.py         ★ NEW: Harness (~100 LOC)
│   │   │   ├── research_agent.py  ★ NEW: 薄包装 (~50 LOC)
│   │   │   ├── _base_research.py  ★ NEW (Sprint C4): 共享基类 ~400 LOC
│   │   │   └── apps_research_ext.py ★ NEW (Sprint C4): 扩展部分 ~600 LOC
│   │   └── autorun/        # scheduler-based 自动任务
│   │
│   ├── interfaces/                                 # L4: 接口
│   │   ├── __init__.py
│   │   ├── cli/             ← 现有 src/llmwikify/cli/
│   │   ├── mcp/             ← 现有 src/llmwikify/mcp/adapter + tools
│   │   ├── server/          ← 现有 src/llmwikify/server/
│   │   └── web/             ← 重写 __init__, 迁 server.py
│   │       ├── __init__.py
│   │       └── server.py
│   │
│   ├── _legacy/                                     # ★ 向后兼容 shim 集中地
│   │   ├── __init__.py
│   │   ├── agent.py            # llmwikify.agent.* → apps/agent.*
│   │   ├── mcp_server.py       # llmwikify.mcp.server → interfaces/mcp/adapter
│   │   ├── adapters.py         # llmwikify.agent.backend.adapters → foundation/llm/streamable
│   │   ├── create_unified_server.py
│   │   └── autoresearch.py     # llmwikify.autoresearch.* → apps/chat.*
│   │
│   └── __init__.py                                  # 顶层 re-export 所有公共 API
│
├── autoresearch/                                    # 🗑️ Sprint C1 删 (全部迁入 apps/chat/)
│
├── ui/                                            # 前端资产 (与 src/ 平级, NOT Python 包)
│   ├── webui/                                    # React 主前端
│   │   ├── src/  dist/  package.json  vite.config.ts
│   └── webui-agent/                              # React Agent UI
│       ├── src/  dist/  package.json  vite.config.ts
│
├── tests/                                         # pytest (测试结构跟着重排)
├── docs/                                          # docs/README.md
├── graphify-out/                                  # 知识图谱
│
├── .import-linter                                 # NEW: 4-layer 强制规则
├── pyproject.toml                                 # 加 import-linter 配置
├── MANIFEST.in
└── README.md
```

### 3.2 Layer dependency rules (strict)

```
interfaces  →  apps  →  kernel  →  foundation
   (L4)        (L3)     (L2)       (L1)
```

Strict prohibitions:
- L1 cannot import from L2/L3/L4
- L2 cannot import from L3/L4
- L3 cannot import from L4
- `apps/chat/` MAY import from `apps/research/`, `apps/agent/`,
  `apps/autorun/` (chat reuses research capabilities)
- `autoresearch/` is OUTSIDE the 4-layer architecture during
  Sprint A and B (kept in place until Sprint C1 moves it)

### 3.3 MX1 mixin grouping (kernel/wiki/mixins/)

13 mixin files split into 3 subpackages by responsibility:

| Subpackage | Files | Responsibility |
|------------|-------|----------------|
| `core/` | init, utility, schema (3) | Wiki lifecycle, path/slug/templates, schema reading |
| `io/` | page_io, ingest, source_analysis, link (4) | Page I/O, content ingestion, source analysis, wikilink resolution |
| `analysis/` | lint, llm, query, relation, synthesis, status (6) | Lint delegation, LLM calls, query, relations, synthesis, status reports |

### 3.4 apps/agent/ internal structure (1:1 with agent/backend/)

```
apps/agent/
├── core/             # db (1387 LOC), service (608 LOC), runner, config_manager
├── tools/            # WikiToolRegistry (836 LOC)
├── memory/           # MemoryManager (138 LOC)
├── notifications/    # NotificationManager (86 LOC)
├── scheduler/        # WikiScheduler (250 LOC)
├── providers/        # base, registry, xiaomi, minimax (140 LOC total)
├── routes/           # agent, ppt, research FastAPI routes
├── dream_editor.py   # standalone
└── hooks.py          # standalone
```

### 3.5 apps/chat/ (autoresearch integrated, no rewrite)

```
apps/chat/
├── (26 existing autoresearch files, git mv — unchanged)
│   ├── engine.py (526)              # 6-step research engine, reused as-is
│   ├── actions.py (864)             # research actions, reused as-is
│   ├── analyzer.py                  # reused (re-export target for agent.backend.research)
│   ├── ... (23 more files, all reused as-is)
│
├── ★ NEW (Sprint C):
│   ├── base.py            # ChatBase — generic chat framework
│   │                        # - session/message management
│   │                        # - streaming output
│   │                        # - tool registration
│   │                        # - LLM provider abstraction
│   │                        # (~150 LOC, thin)
│   │
│   ├── harness.py         # Harness — eval framework
│   │                        # - golden test cases
│   │                        # - LLM-as-judge scoring
│   │                        # - regression detection
│   │                        # - pytest integration via @pytest.mark.harness
│   │                        # (~100 LOC, thin)
│   │
│   ├── research_agent.py  # ResearchAgent(ChatBase) — thin wrapper
│   │                        # - delegates to existing engine
│   │                        # - exposes chat-style interface
│   │                        # - preserves engine.research() backward compat
│   │                        # (~50 LOC)
│   │
│   ├── _base_research.py  # Sprint C4: shared base for the 5 diverged files
│   │                        # - BaseResearchState, BaseQualityGate
│   │                        # - common state machine, retry, logging
│   │                        # (~400 LOC, extracted from quality_gate/report/review/task_manager/config)
│   │
│   └── apps_research_ext.py  # Sprint C4: autoresearch-specific extensions
│                                # - ResearchQualityGate(BaseQualityGate)
│                                # - ResearchReport
│                                # - ReviewExtension
│                                # - TaskManagerExtension
│                                # - ResearchConfigExtension
│                                # (~600 LOC, what was 5 files × ~228 LOC avg)
└── harness_tests/       # Sprint C5: golden tests for chat framework
    ├── __init__.py
    └── golden_research.py
```

### 3.6 import-linter configuration (`.import-linter`)

```ini
[importlinter]
root_package = llmwikify
include_external_packages = True

# 4-layer single-direction dependency
[importlinter:contract:layered]
type = layers
layers = 
    llmwikify.foundation
    llmwikify.kernel
    llmwikify.apps
    llmwikify.interfaces

# L1 subpackages are independent of each other
[importlinter:contract:foundation-isolation]
type = independence
modules = 
    llmwikify.foundation.llm
    llmwikify.foundation.extractors
    llmwikify.foundation.prompts
    llmwikify.foundation.templates
    llmwikify.foundation.config
    llmwikify.foundation.io

# L4 subpackages are independent of each other
[importlinter:contract:interfaces-isolation]
type = independence
modules = 
    llmwikify.interfaces.cli
    llmwikify.interfaces.mcp
    llmwikify.interfaces.server
    llmwikify.interfaces.web

# L3 apps are independent of each other (except chat→research/agent)
[importlinter:contract:apps-isolation]
type = independence
modules = 
    llmwikify.apps.agent
    llmwikify.apps.research
    llmwikify.apps.ppt
    llmwikify.apps.autorun

# apps/chat/ may reuse apps/research/, apps/agent/, apps/autorun/
[importlinter:contract:chat-uses-research-and-agent]
type = allowed
source_modules = 
    llmwikify.apps.chat
allow_modules = 
    llmwikify.apps.research
    llmwikify.apps.agent
    llmwikify.apps.autorun
```

`pyproject.toml` integration:

```toml
[tool.importlinter]
contracts = layered, foundation-isolation, interfaces-isolation, apps-isolation, chat-uses-research-and-agent
```

CI command:
```bash
lint-imports  # fails the build if any contract is violated
```

### 3.7 Path lookup simplification (delete old paths)

`src/llmwikify/interfaces/server/utils/webui.py` (after move):

```python
def find_webui_dist() -> Path | None:
    """Find WebUI dist at ui/webui/dist (post-refactor single location)."""
    pkg_dir = Path(__file__).resolve().parent.parent.parent.parent  # repo root
    candidate = pkg_dir / "ui" / "webui" / "dist"
    if candidate.exists() and (candidate / "index.html").exists():
        return candidate
    return None
```

`src/llmwikify/interfaces/server/http/routes.py` (after move):
`_mount_agent_spa()` only checks `ui/webui-agent/dist` — no fallback.

### 3.8 Backward compatibility shims (`_legacy/`)

```
src/llmwikify/_legacy/
├── __init__.py
├── agent.py            # llmwikify.agent.*  → llmwikify.apps.agent.*
├── mcp_server.py       # llmwikify.mcp.server → llmwikify.interfaces.mcp.adapter
├── adapters.py         # llmwikify.agent.backend.adapters → llmwikify.foundation.llm.streamable
├── create_unified_server.py
└── autoresearch.py     # llmwikify.autoresearch.* → llmwikify.apps.chat.*
```

Top-level `__init__.py` re-exports all public APIs:

```python
# Old paths still work via _legacy re-exports
from ._legacy import (
    agent as _legacy_agent,
    mcp_server as _legacy_mcp_server,
    adapters as _legacy_adapters,
    create_unified_server as _legacy_create_unified_server,
    autoresearch as _legacy_autoresearch,
)

# New canonical APIs always work
from .cli import WikiCLI                    # still works
from .core import Wiki                       # still works (re-exported from kernel)
from .apps.chat import ResearchEngine         # new canonical path
```

---

## 4. Execution Plan (10 batches, 3 sprints)

### Sprint A: Cleanup + Infrastructure (1.5h)

#### Batch A1: Delete dead code + import-linter (35 min, 🟢 0 risk)

1. Delete `src/llmwikify/strategy/` (empty directory)
2. Delete `src/llmwikify/fetchers/` (empty directory)
3. Delete `src/llmwikify/web/static-legacy-deprecated/` (440K, deprecated)
4. Create `.import-linter` at repo root with the configuration in §3.6
5. Add `[tool.importlinter]` section to `pyproject.toml`
6. Add `lint-imports` to CI workflow

**Verification**:
- `pytest tests/ --ignore=tests/e2e -q` → 1852/1852 pass
- `lint-imports` → all green

#### Batch A2: Frontend move + path simplification (45 min, 🟡 medium)

1. `git mv src/llmwikify/web/webui/ ui/webui/`
2. `git mv src/llmwikify/web/webui-agent/ ui/webui-agent/`
3. `git mv src/llmwikify/web/__init__.py src/llmwikify/interfaces/web/__init__.py` (rewrite content)
4. `git mv src/llmwikify/web/server.py src/llmwikify/interfaces/web/server.py`
5. Simplify `src/llmwikify/server/utils/webui.py::find_webui_dist()` — delete fallback, only check `ui/webui/dist`
6. Simplify `src/llmwikify/server/http/routes.py::_mount_agent_spa()` — delete fallback, only check `ui/webui-agent/dist`

**Verification**:
- `pytest` → 1852/1852
- `cd ui/webui && npm run build` produces dist/
- `python -m llmwikify serve` → WebUI loads at `/`, agent UI at `/agent`

#### 🚦 Pause 1
- pytest + lint-imports all green
- Manual: `python -m llmwikify serve` → WebUI accessible

### Sprint B: 4-Layer Restructure (~10h)

#### Batch B1: L1 foundation/ (1h, 🟡 medium)

1. Move `llm/`, `extractors/`, `prompts/`, `templates/`, `config.py`, `llm_client.py` → `foundation/`
2. Create `foundation/io.py` (extract common file/cache/serialization utilities from `query_sink.py`, `graph_analyzer.py`)
3. Update top-level `__init__.py` to re-export from new locations
4. Add new compatibility re-exports in `__init__.py`:
   - `from .foundation.llm.streamable import StreamableLLMClient`
   - `from .foundation.llm import LLMClient` (lazy via PEP 562 `__getattr__`)
   - `from .foundation.config import ...`
   - etc.

**Verification**:
- `pytest` → 1852/1852
- `lint-imports` → all green

#### Batch B2: L4 interfaces/ (2h, 🟡 medium)

1. Move `cli/`, `mcp/`, `server/`, `web/` (Python parts) → `interfaces/`
2. Update cross-package imports:
   - `from ..core` → `from llmwikify.kernel.core` (or via re-export)
   - `from ..agent.backend` → `from llmwikify.apps.agent.*`
3. Update `__init__.py` re-exports
4. Move `_legacy/mcp_server.py`, `_legacy/create_unified_server.py` shims in place

**Verification**:
- `pytest` → 1852/1852
- `lint-imports` → all green
- Manual: `llmwikify init`, `llmwikify serve`, `llmwikify mcp` all work

#### 🚦 Pause 2
- pytest + lint-imports all green
- Manual smoke test of key CLI/MCP/Server commands

#### Batch B3: L2 kernel/ (4h, 🔴 high)

22 files in `core/` → 4 subpackages in `kernel/`:

| Source | Destination |
|--------|-------------|
| `core/wiki.py` | `kernel/wiki/wiki.py` |
| `core/wiki_mixin_*.py` (13 files) | `kernel/wiki/mixins/{core,io,analysis}/` (MX1 grouping) |
| `core/wiki_analyzer.py` | `kernel/wiki/engines/analyzer.py` |
| `core/relation_engine.py` | `kernel/wiki/engines/relation.py` |
| `core/synthesis_engine.py` | `kernel/wiki/engines/synthesis.py` |
| `core/lint/` | `kernel/wiki/lint/` |
| `core/protocols.py` | `kernel/wiki/protocols.py` |
| `core/constants.py` | `kernel/wiki/constants.py` |
| `core/wiki_backend.py` | `kernel/storage/backend.py` |
| `core/index.py` | `kernel/storage/index.py` |
| `core/query_sink.py` | `kernel/storage/query_sink.py` |
| `core/watcher.py` | `kernel/storage/watcher.py` |
| `core/graph_analyzer.py` | `kernel/graph/analyzer.py` |
| `core/graph_export.py` | `kernel/graph/export.py` |
| `core/graph_visualizer.py` | `kernel/graph/visualizer.py` |
| `core/qmd_index.py` | `kernel/search/qmd_index.py` |
| `core/qmd_client.py` | `kernel/search/qmd_client.py` |
| `core/wiki_registry.py` | `kernel/multi_wiki/registry.py` |
| `core/wiki_instance.py` | `kernel/multi_wiki/instance.py` |
| `core/wiki_discovery.py` | `kernel/multi_wiki/discovery.py` |
| `core/remote_wiki.py` | `kernel/multi_wiki/remote.py` |
| `core/principle_checker.py` | `kernel/principle_checker.py` |

Mixins reorganized into MX1 subpackages:

```
kernel/wiki/mixins/
├── core/         # init, utility, schema (3 files)
├── io/           # page_io, ingest, source_analysis, link (4 files)
└── analysis/     # lint, llm, query, relation, synthesis, status (6 files)
```

Cross-package import updates (large mechanical change).

**Verification**:
- `pytest` → 1852/1852
- `lint-imports` → all green

#### Batch B4: L3 apps/ + `_legacy/` shims (3h, 🔴 high)

1. Move `agent/backend/` (12K, 7 subpackages + 2 standalone) → `apps/agent/`
2. Move `agent/backend/research/` → `apps/research/`
3. Move `agent/backend/ppt/` → `apps/ppt/`
4. **Preserve** `agent/` top-level as shim (becomes `_legacy/agent.py`)
5. **Preserve** `mcp/server.py` as shim (`_legacy/mcp_server.py`)
6. **Preserve** `server/__init__.py::create_unified_server` shim
7. **Preserve** `agent/backend/adapters.py` shim
8. Create `_legacy/` package with all shims centralized
9. Update `__init__.py` top-level re-exports

**Verification**:
- `pytest` → 1852/1852
- `lint-imports` → all green
- Backward compat test: `from llmwikify.agent import *` still works

#### 🚦 Pause 3
- pytest 1852/1852
- lint-imports all green
- Backward compat paths verified
- `autoresearch/` still in place (Sprint C will move it)

### Sprint C: autoresearch → apps/chat/ with Reuse + Optimization (~13-19h)

#### Sub-Sprint C1: Move + reuse (30 min, 🟡 medium)

1. `git mv autoresearch/* apps/chat/` (26 files, preserve history)
2. Create 3 new files:
   - `apps/chat/base.py` (ChatBase, ~150 LOC)
   - `apps/chat/harness.py` (Harness, ~100 LOC)
   - `apps/chat/research_agent.py` (thin wrapper, ~50 LOC)
3. Update `apps/chat/__init__.py` to re-export everything
4. Create `_legacy/autoresearch.py` shim: `from llmwikify.apps.chat import *`
5. Delete old `autoresearch/` directory

**No optimization yet** — pure move.

#### Sub-Sprint C2: Category 1 cleanup (2-3h, 🟢 low)

| Task | Time |
|------|------|
| 1.1 Fix `apps/chat/__init__.py:6` contradictory comment (`from llmwikify.agent.backend.research.` incomplete) | 5 min |
| 1.2 Update outdated docstrings (mentioning "agent.backend.research" old location) | 30 min |
| 1.3 Remove unused imports (ruff check) | 15 min |
| 1.4 Apply PEP 604/585 typing modernization | 30 min |
| 1.5 Unify error handling pattern | 1h |

#### Sub-Sprint C3: Category 3 dead code cleanup (30 min, 🟢 low)

| Task | Time |
|------|------|
| 3.1 Check `_json_utils.py` — delete if unused | 10 min |
| 3.2 Check `db_migrations.py` — delete if unused | 10 min |
| 3.3 Check `.pyc` / `__pycache__` accidentally in git | 5 min |
| 3.4 Remove `apps/chat/web_search.py` 1-line re-export (0 diff confirmed) | 5 min |

#### Sub-Sprint C5.1: Coverage check (30 min, 🟢 0)

1. Run `pytest --cov=llmwikify/apps/chat --cov-report=term`
2. Identify modules with < 50% coverage
3. Document gaps in this file under §6 Progress Tracking

#### Sub-Sprint C5.2: Backfill existing tests (1-2h, 🟢 low)

1. Add tests for low-coverage modules in existing `apps/chat/` code
2. Target: bring overall coverage from current → 70%+
3. **Do NOT restructure code** — just add tests against existing structure

#### 🚦 Sub-Pause: Test safety net established

After C5.2, we have full test coverage of the existing structure.
**Now C4 (file merge) is safe to execute.**

#### Sub-Sprint C4: Category 2 file consolidation (4-6h, 🟡 medium)

The 5 diverged files in `apps/chat/` (1140 LOC total) get consolidated
into 2 files (~1000 LOC, 12% reduction) by extracting shared base:

```
Before (5 files, 1140 LOC):
├── quality_gate.py (341)        # vs agent.backend.research: 164-line diff
├── report.py (288)              # vs agent.backend.research: 235-line diff
├── review.py (131)              # vs agent.backend.research: 179-line diff
├── task_manager.py (236)        # vs agent.backend.research: 115-line diff
└── config.py (130)              # vs agent.backend.research: 130-line diff

After (2 files, ~1000 LOC, 12% reduction):
├── _base_research.py   # Shared ~50% (state machine, retry, logging, hooks)
│                         # - BaseResearchState
│                         # - BaseQualityGate
│                         # - BaseReport
│                         # - BaseReview
│                         # - BaseTaskManager
│                         # - BaseConfig
│                         # (~400 LOC)
└── apps_research_ext.py  # autoresearch-specific extensions
                          # - ResearchQualityGate(BaseQualityGate)
                          #   + compute_evidence_score (autoresearch-specific)
                          # - ResearchReport(BaseReport)
                          # - ReviewExtension
                          # - TaskManagerExtension
                          # - ResearchConfigExtension
                          # (~600 LOC)
```

| Task | Time |
|------|------|
| 4.1 Analyze 5 files for true shared code (~50% overlap expected) | 1h |
| 4.2 Design `_base_research.py` interfaces | 1h |
| 4.3 Create `_base_research.py` and move shared code | 1.5h |
| 4.4 Create `apps_research_ext.py` (inherit from Base) | 1h |
| 4.5 Update `__init__.py` to re-export | 30 min |
| 4.6 Cross-file test verification (existing tests must pass) | 1h |

**Risk control**: 5 files' public API fully preserved, only
internal structure changes. All 1852 tests must continue to pass.

#### Sub-Sprint C5.3-5: New tests for chat base + harness (3-4.5h, 🟢 low)

| Task | Tests | Time |
|------|-------|------|
| 5.3 ChatBase unit tests | ~20 | 1-2h |
| 5.4 Harness unit tests | ~15 | 1-1.5h |
| 5.5 ResearchAgent wrapper tests | ~10 | 0.5-1h |

#### Sub-Sprint C5.6: Integration test (1-1.5h, 🟢 low)

End-to-end test: `ResearchAgent.research(query)` produces valid
research output, exercises the full 6-step framework.

#### Sub-Sprint C5.7: Remove obsolete tests (30 min, 🟢 low)

Identify and remove `test_*.py` cases that reference pre-refactor
paths or test removed functionality.

#### 🚦 Final Pause
- `pytest` → 1852 + ~60 new tests = ~1912 pass
- `lint-imports` → all green
- `llmwikify.autoresearch.X` still imports (via `_legacy/`)
- `llmwikify.apps.chat.X` is the new canonical path
- WebUI loads correctly (frontend path clean)
- CLI/MCP/Server all start normally

---

## 5. Risk Matrix

| Risk | Severity | Mitigation |
|------|----------|------------|
| Path changes break external code | 🟡 medium | `_legacy/` shim + top-level re-exports |
| import-linter false positives | 🟡 medium | Enable contracts one at a time, start with disabled |
| 27K+ LOC move introduces typos | 🔴 high | Full test suite per batch + per-file static checks |
| `apps/chat` C4 merge breaks public API | 🔴 high | 5 files preserve API, full test suite as safety net |
| Frontend path not found at runtime | 🟢 low | Dev message: `cd ui/webui && npm run build` |
| `webui-agent` dist missing in dev | 🟢 low | Same as above for `ui/webui-agent/` |
| Backward compat shim has bugs | 🟡 medium | Each shim has explicit test in Sprint A/B/C verification |

**Rollback**: Each batch is independently revertable via `git revert`.

---

## 6. Progress Tracking

> **Update this section as batches complete.** Each batch is one
> or more commits. After each commit, run pytest + lint-imports
> and record results here.

### Batch progress table

| Batch | Status | Commits | pytest | lint-imports | Notes |
|-------|--------|---------|--------|--------------|-------|
| A1 | ⬜ Not started | — | — | — | — |
| A2 | ⬜ Not started | — | — | — | — |
| 🚦 Pause 1 | ⬜ Not started | — | — | — | — |
| B1 | ⬜ Not started | — | — | — | — |
| B2 | ⬜ Not started | — | — | — | — |
| 🚦 Pause 2 | ⬜ Not started | — | — | — | — |
| B3 | ⬜ Not started | — | — | — | — |
| B4 | ⬜ Not started | — | — | — | — |
| 🚦 Pause 3 | ⬜ Not started | — | — | — | — |
| C1 | ⬜ Not started | — | — | — | — |
| C2 | ⬜ Not started | — | — | — | — |
| C3 | ⬜ Not started | — | — | — | — |
| C5.1 | ⬜ Not started | — | — | — | — |
| C5.2 | ⬜ Not started | — | — | — | — |
| 🚦 Sub-pause | ⬜ Not started | — | — | — | — |
| C4 | ⬜ Not started | — | — | — | — |
| C5.3-5 | ⬜ Not started | — | — | — | — |
| C5.6 | ⬜ Not started | — | — | — | — |
| C5.7 | ⬜ Not started | — | — | — | — |
| 🚦 Final | ⬜ Not started | — | — | — | — |

### Coverage tracking (Sprint C5)

| Module | Before C5.1 | After C5.2 | After C5.6 |
|--------|-------------|------------|------------|
| `apps/chat/base.py` (NEW) | N/A | N/A | TBD |
| `apps/chat/harness.py` (NEW) | N/A | N/A | TBD |
| `apps/chat/research_agent.py` (NEW) | N/A | N/A | TBD |
| `apps/chat/engine.py` | TBD | TBD | TBD |
| `apps/chat/_base_research.py` (NEW C4) | N/A | N/A | TBD |
| `apps/chat/apps_research_ext.py` (NEW C4) | N/A | N/A | TBD |
| Overall `apps/chat/` | TBD | ≥70% | TBD |

---

## 7. Time and LOC Budget Summary

| Sprint | Sub-batch | Time | Risk | LOC Δ |
|--------|-----------|------|------|-------|
| A | A1 | 35 min | 🟢 | -440K dead assets |
| A | A2 | 45 min | 🟡 | 0 |
| B | B1 | 1h | 🟡 | 0 |
| B | B2 | 2h | 🟡 | 0 |
| B | B3 | 4h | 🔴 | 0 (restructure) |
| B | B4 | 3h | 🔴 | 0 (restructure) |
| C | C1 | 30 min | 🟡 | +300 (new base/harness/research_agent) |
| C | C2 | 2-3h | 🟢 | -100 (cleanup) |
| C | C3 | 30 min | 🟢 | -200 (dead code) |
| C | C5.1 | 30 min | 🟢 | 0 |
| C | C5.2 | 1-2h | 🟢 | +300-500 (new tests) |
| C | C4 | 4-6h | 🟡 | -140 (12% merge savings) |
| C | C5.3-5 | 3-4.5h | 🟢 | +500-700 (new tests) |
| C | C5.6 | 1-1.5h | 🟢 | 0 |
| C | C5.7 | 30 min | 🟢 | -50 (obsolete tests) |
| **Total** | | **~22-27h** | **Mixed** | **+610 to +1010 net new LOC** |

---

## 8. References

- **Prior refactor plan**: `docs/archive/refactor-history/PLAN.md`
  (the 7-item + Level 2 refactor that preceded this)
- **Code reuse plan**: `docs/designs/code-reuse-modernization.md`
  (recent typing modernization + web_search re-export work)
- **Architecture overview**: `docs/designs/architecture.html`
  (high-level project architecture, visually rendered)
- **LLM Wiki principles**: `docs/LLM_WIKI_PRINCIPLES.md`
- **import-linter docs**: https://import-linter.readthedocs.io/

---

## 9. Open Questions

None — all 14 decisions finalized. Ready to execute when user gives
the go-ahead, batch by batch with pause-and-verify gates.

---

## 10. Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-06-07 | Initial design document | Plan mode consolidation |
