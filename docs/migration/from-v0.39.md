# Migration Guide: v0.39 → v0.40

> **Scope**: This guide helps users of llmwikify **v0.39 and earlier** upgrade to **v0.40**, which is a **BREAKING** release that strips the quant research pipeline from llmwikify.

---

## TL;DR

llmwikify **v0.40** drops all quant research pipeline content (paper → factor → backtest). That functionality has moved to **[quantnodes v4.0](https://github.com/sn0wfree/quantnodes)** as `quantnodes.research`.

| Old (v0.39) | New (v0.40+) |
|---|---|
| `llmwikify.reproduction.*` | `quantnodes.research.*` (need `pip install quantnodes>=4.0`) |
| `llmwikify reproduce` | `quantnodes reproduce` |
| `llmwikify quant-init` | removed (use `quantnodes research init`) |
| HTTP `/api/{factor,paper,reproduction,strategy}/*` | moved to `quantnodes` server |
| 30 quant scripts in `llmwikify/scripts/` | moved to `quantnodes/scripts/research/` |
| `llmwikify.apps.research` | **unchanged** (still exists, now the canonical research package) |

**No action required** if you only used llmwikify for:
- Wiki / knowledge base
- Chat / agent
- General research assistant
- Web UI / MCP server

**Action required** if you used llmwikify for:
- Quant paper reproduction pipeline
- Factor research / backtest workflows
- `/api/{factor,paper,reproduction,strategy}/*` HTTP endpoints

---

## Step-by-step migration

### 1. Install quantnodes (if you used reproduction)

```bash
pip install 'quantnodes[all]>=4.0'
```

### 2. Update imports in your code

```python
# Old (v0.39)
from llmwikify.reproduction.paper_understanding import run_one_paper
from llmwikify.reproduction.backtest_pkg import run_backtest
from llmwikify.reproduction.common import config
from llmwikify.reproduction.persist.sessions import ReproductionDatabase

# New (v0.40+)
from quantnodes.research.paper_understanding import run_one_paper
from quantnodes.research.backtest_pkg import run_backtest
from quantnodes.research.common import config
from quantnodes.research.persist.sessions import ReproductionDatabase
```

### 3. Update CLI commands

```bash
# Old (v0.39)
llmwikify quant-init --name 101_alphas
llmwikify reproduce --paper-id 1601_00991v3

# New (v0.40+)
quantnodes research init --name 101_alphas
quantnodes reproduce --paper-id 1601_00991v3
```

### 4. Update HTTP API endpoints

If you used any of:

- `POST /api/paper/start`
- `GET /api/paper/list`
- `POST /api/reproduction/start`
- `GET /api/factor/list`
- `GET /api/strategy/list`

These endpoints are now served by `quantnodes`. Install quantnodes and update your client to point at its server (default: `localhost:8765`).

### 5. Update scripts

The 30 quant scripts that lived in `llmwikify/scripts/` have been moved to `quantnodes/scripts/research/`:

```bash
# Old
python -m llmwikify.scripts.run_101_alphas_v2 --alphas 1-101

# New (after pip install quantnodes)
python -m quantnodes.scripts.research.run_101_alphas_v2 --alphas 1-101
```

### 6. Update configuration

`~/.llmwikify/llmwikify.json` previously contained a `quantnodes` section. Move that section to `~/.quantnodes/quantnodes.json` (quantnodes uses its own config directory).

The `research` section (general research assistant, NOT quant) stays in `~/.llmwikify/llmwikify.json`.

---

## What did NOT change

- `llmwikify.Wiki` / `llmwikify.WikiRegistry` / `llmwikify.create_wiki` — same API
- `llmwikify.write_page` / `read_page` / `search` — same API
- `llmwikify.ingest` / `lint` / `serve` — same API
- `llmwikify.apps.research` (general research assistant) — **unchanged**
- `llmwikify.apps.chat` — **unchanged**
- `llmwikify.apps.agent` — **unchanged**
- `llmwikify.kernel` (wiki, multi_wiki, codegen, agent) — **unchanged**
- `llmwikify.foundation` (LLM, callback, prompts, extractors) — **unchanged**
- `llmwikify.interfaces` (CLI, HTTP, MCP, web UI) — **unchanged** (except 4 quant HTTP routes removed)

---

## Architecture overview (v0.40)

```
llmwikify v0.40                           quantnodes v4.0+
─────────────────────                     ─────────────────────
📚 Knowledge Base (Wiki)                  📊 Quant Research
💬 Chat + Skills                          - paper_understanding
🔬 General Research Assistant             - backtest_pkg
🤖 Agent                                  - data_source
                                          - pipeline
                                          - codegen
Kernel (agent / codegen / multi_wiki)      - common / sink / signal_source
Foundation (LLM / callback / extractors)   - prompts
Interfaces (CLI / HTTP / MCP / WebUI)       Foundation (shared via pip)
```

The two projects are now **independent leaf packages**. Neither depends on the other.

---

## FAQ

**Q: I only use llmwikify for the wiki. Do I need to do anything?**
A: No. The wiki API is unchanged.

**Q: I used `llmwikify.reproduction` in my own code. What's the path?**
A: `llmwikify.reproduction.X` → `quantnodes.research.X` (need to install quantnodes).

**Q: Are my old prompts / data still compatible?**
A: Yes. The data format (YAML factor definitions, DuckDB schemas, JSON exports) is identical between `llmwikify.reproduction` (v0.39) and `quantnodes.research` (v4.0+).

**Q: Can I keep using `llmwikify.reproduction` somehow?**
A: No. v0.40 deletes the package entirely. If you can't upgrade, stay on v0.39.

**Q: When did `quantnodes.research` first ship?**
A: As a separate package starting with quantnodes v4.0.0, released alongside llmwikify v0.40.0.

**Q: Where do I report migration issues?**
A: [GitHub Issues](https://github.com/sn0wfree/llmwikify/issues) for llmwikify, or
   [quantnodes/issues](https://github.com/sn0wfree/quantnodes/issues) for the new
   quant package.

---

## See also

- `plan/v0.40-refocus.md` — internal refactor plan
- `CHANGELOG.md` — full v0.40 changelog
- `README.md` — updated project positioning
- [quantnodes repo](https://github.com/sn0wfree/quantnodes) — new home of quant research