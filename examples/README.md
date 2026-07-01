# llmwikify End-to-End Playbooks

> **v0.38.0 (2026-06-30)** — 8 playbooks (5 scenarios + 3 feature demos), aligned with [docs/TUTORIAL.md](../docs/TUTORIAL.md)
> Each playbook is a self-contained runnable script + README, no LLM/network required (except 04).

---

## 📋 Playbook Directory

| # | Scenario | Path | Key API |
|---|----------|------|---------|
| 01 | Personal Reading Notes | [`01_personal_reading_notes/`](01_personal_reading_notes/) | init / ingest / search / write_page / build-index / references / lint |
| 02 | Company Due-Diligence KB | [`02_company_research_kb/`](02_company_research_kb/) | batch ingest / synthesize / GraphAnalyzer / lint |
| 03 | Multi-Wiki Registry | [`03_multi_wiki_registry/`](03_multi_wiki_registry/) | WikiRegistry / WikiDiscovery / switch / list |
| 04 | Chat SSE Client | [`04_chat_sse_client/`](04_chat_sse_client/) | httpx.stream / /api/agent/chat / SSE events |
| 05 | Paper → Factor → Backtest | [`05_paper_to_factor/`](05_paper_to_factor/) | write_factor_yaml / list_factors / DuckDB |
| **Feature Demos** | | | |
| 06 | Lint Rule Triggers | [`06_lint_8_rules/`](06_lint_8_rules/) | wiki.lint() / 8 rules |
| 07 | YAML Config Templates | [`07_yaml_templates/`](07_yaml_templates/) | yaml.safe_load / create_wiki |
| 08 | Section-Level Anchors | [`08_section_anchor_tracking/`](08_section_anchor_tracking/) | get_inbound_links / get_outbound_links |

---

## 🚀 Run All Playbooks

```bash
# 1-3, 5-8 don't need LLM / network
for d in 0[1-3]_* 0[5-8]_*; do
    echo "===== $d ====="
    (cd "$d" && python play.py)
    echo
done

# 4 needs a running server first
(cd /tmp/demo-wiki && llmwikify init --agent generic)
(cd /tmp/demo-wiki && llmwikify serve --web --port 8765 --auth-token mysecret &) ; sleep 3
cd 04_chat_sse_client && python play.py
```

---

## 📁 Config Templates

Legacy `*.yaml` templates (`personal-kb.yaml` / `project-docs.yaml` etc.) are kept as
wiki config snippets. Merge with `cat <file> >> .wiki-config.yaml`.

| File | Purpose |
|------|---------|
| `personal-kb.yaml` | Personal knowledge base config snippet |
| `project-docs.yaml` | Project documentation wiki |
| `research-wiki.yaml` | Research knowledge base |
| `mining-news-wiki.yaml` | Industry news wiki |

---

## 🗄️ Legacy Scripts (Migrated)

Historical scripts moved to [`legacy/`](legacy/) directory with **DEPRECATED** banner.
**Do not reference in new code.** See [legacy/README.md](legacy/README.md) for migration paths.

| Old File | Replacement |
|----------|-------------|
| `legacy/basic_usage.py` | `01_personal_reading_notes/` |
| `legacy/run_server.py` | `03_multi_wiki_registry/` + `04_chat_sse_client/` |
| `legacy/mcp_agent.py` | `04_chat_sse_client/` |
| `legacy/integrate_with_django.py` | (reference only, no end-to-end playbook) |
| `legacy/integrate_with_flask.py` | (reference only, no end-to-end playbook) |
| `legacy/Dockerfile.example` | (reference only) |
| `legacy/docker-compose.yml.example` | (reference only) |

---

## 🔍 Which Playbook Should I Use?

```
I want to...
├── Get started: PDF → searchable wiki           → 01
├── Multi-source analysis: reports → knowledge graph → 02
├── One server, multiple wikis                   → 03
├── Let LLM answer questions using my wiki       → 04
├── Quant reproduction: paper → factor → backtest → 05
├── Understand lint rule triggers                → 06
├── See YAML config templates in action          → 07
└── See [[page#section]] anchor tracking         → 08
```

See [docs/TUTORIAL.md §0 Decision Tree](../docs/TUTORIAL.md#0-prerequisites-install-matrix--decision-tree).
