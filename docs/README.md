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

## 🗂 Layout Summary

```
docs/
├── README.md                          # THIS FILE
├── LLM_WIKI_PRINCIPLES.md             # Core (README-referenced)
├── CONFIGURATION_GUIDE.md             # User guides
├── KNOWN_ISSUES.md
├── MCP_SETUP.md
├── MCPORTER_DEPLOYMENT.md
├── QMD_SETUP.md
├── REFERENCE_TRACKING_GUIDE.md
│
├── designs/                           # 24 active/recent feature designs
├── releases/                          # 6 per-version notes (v0.32 → v0.38)
├── research/                          # 1 landscape research doc
├── issues/                            # bug reports + issue tracker
└── archive/
    ├── done/                          # 3 implemented designs
    ├── status/                        # 1 expired status snapshot
    ├── plans/                         # 4 completed version plans
    └── refactor-history/              # 1 refactor roadmap
```
