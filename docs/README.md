# llmwikify Documentation

> **Single index for all project documentation** — organized by purpose.

---

## 📘 Core Project Docs (read first)

| Doc | Purpose |
|-----|---------|
| [README.md](../README.md) | Project overview, quick start, features |
| [TUTORIAL.md](TUTORIAL.md) | **5 个端到端使用场景（必读）** |
| [ARCHITECTURE.md](../ARCHITECTURE.md) | Technical architecture, data flows, components |
| [MIGRATION.md](../MIGRATION.md) | Version migration notes |
| [CHANGELOG.md](../CHANGELOG.md) | Version history |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | Development workflow, coding standards |
| [LLM_WIKI_PRINCIPLES.md](LLM_WIKI_PRINCIPLES.md) | Karpathy's original LLM Wiki vision (referenced from README) |

---

## 🛠 User Guides

| Doc | Purpose |
|-----|---------|
| [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) | `.wiki-config.yaml` reference (all options) |
| [MCP_SETUP.md](MCP_SETUP.md) | MCP server setup (general, 20 tools) |
| [MCPORTER_DEPLOYMENT.md](MCPORTER_DEPLOYMENT.md) | MCPorter Bridge deployment guide |
| [QMD_SETUP.md](QMD_SETUP.md) | QMD hybrid search setup |
| [REFERENCE_TRACKING_GUIDE.md](REFERENCE_TRACKING_GUIDE.md) | Wiki reference tracking system |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | Known issues and planned fixes |

---

## 📐 Designs (`docs/designs/`)

Feature/architecture designs — current and historical feature plans. The most
recently active designs live here; completed ones are in `archive/done/`.

| Doc | Topic |
|-----|-------|
| [architecture.html](designs/architecture.html) | High-level system architecture overview |
| [P3_INGEST_LINT_DESIGN.md](designs/P3_INGEST_LINT_DESIGN.md) | Ingest + Lint enhancement design |
| [SINK_DESIGN_DECISIONS.md](designs/SINK_DESIGN_DECISIONS.md) | Query sink feature decisions |
| [WIKI_LLM_PROMPT_ARCHITECTURE.md](designs/WIKI_LLM_PROMPT_ARCHITECTURE.md) | Wiki LLM prompt architecture |
| [WEBUI_UNIFIED_SERVER.md](designs/WEBUI_UNIFIED_SERVER.md) | WebUI unified server design |
| [workflow-optimization-plan.md](designs/workflow-optimization-plan.md) | Chat & Quick Research workflow |
| [AGENT_INTEGRATION_PLAN.md](designs/AGENT_INTEGRATION_PLAN.md) | Agent integration planning |
| [agent-backend-implementation-plan.md](designs/agent-backend-implementation-plan.md) | Agent backend impl plan |
| [agent-framework-design.md](designs/agent-framework-design.md) | Agent framework + Quick Research design |
| [agent-ui-optimization-plan.md](designs/agent-ui-optimization-plan.md) | Agent UI optimization |
| [deep-research-implementation-plan.md](designs/deep-research-implementation-plan.md) | Deep Research implementation plan |
| [MULTI_WIKI_PLAN.md](designs/MULTI_WIKI_PLAN.md) | Multi-wiki management system |
| [autoresearch-structured-reasoning.md](designs/autoresearch-structured-reasoning.md) | AutoResearch structured reasoning framework |
| [chat-redesign-v0.1.md](designs/chat-redesign-v0.1.md) | Chat UI Hermes redesign |
| [deep-research-analysis.md](designs/deep-research-analysis.md) | Quick Research system analysis |
| [deep-research-display-language.md](designs/deep-research-display-language.md) | Quick Research display language |
| [in8-entity-resolution.md](designs/in8-entity-resolution.md) | IN-8 entity resolution for knowledge graph |
| [react-quality-gates.md](designs/react-quality-gates.md) | ReAct quality gates design |
| [react-research-engine.md](designs/react-research-engine.md) | ReAct Research Engine design |
| [stage-pipeline-ui.md](designs/stage-pipeline-ui.md) | StagePipeline UI component plan |
| [ppt-generator.md](designs/ppt-generator.md) | PPT generator design |
| [ppt-v0.6.2-patch1.md](designs/ppt-v0.6.2-patch1.md) | PPT generator v0.6.2 patch |
| [pptchat-harness-v0.7.md](designs/pptchat-harness-v0.7.md) | PPT chat harness design |
| [ashare-strategy-building.md](designs/ashare-strategy-building.md) | A-share quant strategy design |

---

## 🔬 Research (`docs/research/`)

Landscape research, surveys, tool comparisons. Not tied to a specific
project feature; kept for future reference.

| Doc | Topic |
|-----|-------|
| [html-ppt-landscape.md](research/html-ppt-landscape.md) | HTML-first presentation framework landscape (reveal.js, etc.) |

---

## 🐞 Issues (`docs/issues/`)

Bug reports and issue tracking.

| Doc | Type |
|-----|------|
| [issues.md](issues/issues.md) | Issue tracker (historical) |
| [autoresearch-7fe6f04f-partial-completion.json](issues/autoresearch-7fe6f04f-partial-completion.json) | AutoResearch partial-completion bug report |

---

## 📦 Releases (`docs/releases/`)

Per-version release notes. See [CHANGELOG.md](../CHANGELOG.md) for a condensed
timeline; `docs/releases/` for the full feature-by-feature write-up of each
release.

| Release | Title | Status |
|---------|-------|--------|
| [v0.38.0](releases/v0.38.0.md) | Nanobot v0.2.1 Borrowings + Bus+WS Wire | **latest** |
| [v0.37.0](releases/v0.37.0.md) | Triple ReAct Loop 统一 | — |
| [v0.36.0](releases/v0.36.0.md) | AgentChat 全面硬化 | — |
| [v0.33.0](releases/v0.33.0.md) | 5+1-Service Architecture | — |
| [v0.32.5](releases/v0.32.5.md) | Skill Pipeline Split + 3-Facade Database | — |
| [v0.32.0](releases/v0.32.0.md) | Skill Refactor | — |
| [phase-6-11-cumulative](releases/phase-6-11-cumulative.md) | Phases 6-11 commit log (pre-v0.37) | — |

---

## 📦 Archive (`docs/archive/`)

Historical documents kept for reference. Not actively maintained.

### `archive/done/` — designs whose implementation is complete
| Doc | Why archived |
|-----|--------------|
| [wiki-backend-interface.md](archive/done/wiki-backend-interface.md) | Level 2 WikiBackend implemented (cff301f, 624b268) |
| [refactoring-engine-py.md](archive/done/refactoring-engine-py.md) | engine.py refactor done (Phase 2 #5) |
| [cli-help-and-aliases.md](archive/done/cli-help-and-aliases.md) | `mcp` → `serve` alias consolidation done (Phase 3 #6) |

### `archive/status/` — expired status snapshots
| Doc | Why archived |
|-----|--------------|
| [autoresearch-phase1-status.md](archive/status/autoresearch-phase1-status.md) | Phase 1 status snapshot, superseded |

### `archive/plans/` — completed version plans
| Doc | Version |
|-----|---------|
| [PROJECT_STATUS_0.30.0.md](archive/plans/PROJECT_STATUS_0.30.0.md) | v0.30.0 status |
| [auto-research-v0.24.0.md](archive/plans/auto-research-v0.24.0.md) | v0.24.0 auto-research design |
| [v0.15.0.md](archive/plans/v0.15.0.md) | v0.15.0 plan |
| [v021-v023-roadmap.md](archive/plans/v021-v023-roadmap.md) | v0.21–v0.23 roadmap |

### `archive/refactor-history/` — refactor history
| Doc | Description |
|-----|-------------|
| [PLAN.md](archive/refactor-history/PLAN.md) | 7-item refactor + Level 2 WikiBackend (all 8 items done) |

---

## 🔌 API Reference (`docs/api/`)

Per-module API documentation. Generated/synced with source code; serves as the
authoritative reference for individual endpoints.

| Doc | Scope |
|-----|-------|
| [agent.md](api/agent.md) | `AgentChat` REST + SSE endpoints (`/api/agent/*`) |

---

## 🩺 Diagnostics (`docs/diagnostics/`)

Per-module architecture and health diagnostics. Generated when a module's
complexity warrants deep analysis.

| Doc | Scope |
|-----|-------|
| [chat-architecture-2026-06.md](diagnostics/chat-architecture-2026-06.md) | Chat 模块 (115 文件 / ~23,500 行 / 21 张表) 架构诊断 v0.36 时代 |

---

## 🧪 LLM Code Gen (`docs/llm_code_generation/`)

LLM-driven 量化因子代码生成的经验库。Prompt 设计、失败模式、ReAct 流程
优化的累积知识，用于指导 reproduction/ pipeline 改进。

| Doc | Scope |
|-----|-------|
| [README.md](llm_code_generation/README.md) | 索引 |
| [LESSONS_LEARNED.md](llm_code_generation/LESSONS_LEARNED.md) | 项目成果 + 关键教训 |
| [PARSING_FAILURE_MODES.md](llm_code_generation/PARSING_FAILURE_MODES.md) | LLM 代码生成 5 大失败模式 |
| [PROMPT_ENGINEERING.md](llm_code_generation/PROMPT_ENGINEERING.md) | Prompt 设计原则 |
| [REACT_FLOW_OPTIMIZATION.md](llm_code_generation/REACT_FLOW_OPTIMIZATION.md) | ReAct 流程优化策略 |

---

## 📜 Principles (`docs/principles/`)

功能/子系统的开发原则，**不是**设计稿（设计稿在 `designs/`）。

| Doc | Scope |
|-----|-------|
| [reproduction-principles.md](principles/reproduction-principles.md) | 研报复现功能开发原则 v1.1 |

---

## 📋 TODO (`docs/TODO.md`)

跨版本 in-flight 待办清单。当前主要是 reproduction/ Phase 3+ 优化项。

| Doc | Scope |
|-----|-------|
| [TODO.md](TODO.md) | Phase 3+ 优化待办（子因子拆分、sourcing 改进等） |

---

## 🗂 Layout Summary

```
docs/
├── README.md                          # THIS FILE
├── LLM_WIKI_PRINCIPLES.md             # Core (README-referenced)
├── TUTORIAL.md                        # 5 个端到端使用场景
├── CONFIGURATION_GUIDE.md             # User guides
├── KNOWN_ISSUES.md
├── MCP_SETUP.md
├── MCPORTER_DEPLOYMENT.md
├── QMD_SETUP.md
├── REFERENCE_TRACKING_GUIDE.md
│
├── api/                               # API reference (1 doc)
├── diagnostics/                       # Architecture diagnostics (1 doc)
├── llm_code_generation/               # LLM 代码生成经验库 (5 docs)
├── principles/                        # 开发原则 (1 doc)
├── TODO.md                            # in-flight 待办
│
├── designs/                           # 64 active/recent feature designs
├── releases/                          # 7 per-version notes (v0.32 → v0.38)
├── research/                          # 4 landscape research docs
├── issues/                            # bug reports + issue tracker
├── summaries/                         # 4 experiment summaries
└── archive/
    ├── done/                          # 3 implemented designs
    ├── status/                        # 1 expired status snapshot
    ├── plans/                         # 4 completed version plans
    └── refactor-history/              # 1 refactor roadmap
```
