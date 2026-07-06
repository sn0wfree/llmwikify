# llmwikify End-to-End Playbooks

> **v0.40.0 (2026-07-XX)** — 8 playbooks focused on **Knowledge + Chat + Research
> Assistant**. v0.40 removed `05_paper_to_factor` (moved to
> [quantnodes](https://github.com/sn0wfree/quantnodes) >=4.0).
> Each playbook is a self-contained runnable script + README, no LLM/network required (except 04, 09).

---

## 📋 Playbook Directory

| # | Scenario | Path | Mode | LLM? | Key API |
|---|----------|------|------|------|---------|
| 01 | Personal Reading Notes | [`01_personal_reading_notes/`](01_personal_reading_notes/) | A+B | no | init / ingest / search / write_page / build-index / references / lint |
| 02 | Company Due-Diligence KB | [`02_company_research_kb/`](02_company_research_kb/) | A+B | no | batch ingest / synthesize / GraphAnalyzer / lint |
| 03 | Multi-Wiki Registry | [`03_multi_wiki_registry/`](03_multi_wiki_registry/) | both | no | WikiRegistry / WikiDiscovery / switch / list |
| 04 | Chat SSE Client | [`04_chat_sse_client/`](04_chat_sse_client/) | B | yes | httpx.stream / /api/agent/chat / SSE events |
| **Feature Demos** | | | | | |
| 06 | Lint Rule Triggers | [`06_lint_8_rules/`](06_lint_8_rules/) | both | no | wiki.lint() / 8 rules |
| 07 | YAML Config Templates | [`07_yaml_templates/`](07_yaml_templates/) | both | no | yaml.safe_load / create_wiki |
| 08 | Section-Level Anchors | [`08_section_anchor_tracking/`](08_section_anchor_tracking/) | both | no | get_inbound_links / get_outbound_links |
| **E2E Verification Suite** | | | | | |
| 09 | Wiki Build E2E | [`09_wiki_build_e2e/`](09_wiki_build_e2e/) | both | optional | install check + 10-step CLI + chat SSE + agent CLI (Docker-friendly) |

> **Mode column**: A = Agent mode (opencode/claude/codex), B = LLM model mode
> (llmwikify calls LLM directly). See [`docs/USAGE_MODES.md`](../docs/USAGE_MODES.md).

---

## 🚀 Run All Playbooks

```bash
# 1-3, 6-8 don't need LLM / network
for d in 0[1-3]_* 0[6-8]_*; do
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

---

## 🆕 v0.40 Changes

- **Removed**: `05_paper_to_factor/` (moved to [quantnodes](https://github.com/sn0wfree/quantnodes))
- **Renumbered**: 06-09 shifted to keep 1-4 + 6-9 sequence (no 05)
- **Added** (planned for v0.41+): `10_research_assistant/` (general research via `apps.research`)
- **Added** (planned for v0.41+): `11_chat_with_research/` (chat + research engine demo)

For quant paper reproduction use cases, see the
[quantnodes examples/](https://github.com/sn0wfree/quantnodes/tree/main/examples).