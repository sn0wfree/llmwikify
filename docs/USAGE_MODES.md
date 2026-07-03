# llmwikify Usage Modes

> **Two ways to "make the LLM do work". Pick by use case, not by habit.**

This document explains the two operating modes of llmwikify, when to use
each, and how to mix them. It is the companion to
[`docs/ONBOARDING.md`](./ONBOARDING.md) (which covers the *first* 10
minutes) and `docs/TUTORIAL.md` (which gives step-by-step recipes).

---

## The two paths at a glance

```
                    +----------------------------+
                    |   "I want the LLM to do    |
                    |   work for me"             |
                    +-------------+--------------+
                                  |
                                  v
              +-------------------+----------------------+
              |                                          |
              v                                          v
   +-------------------+                    +-----------------------+
   | Path A:           |                    | Path B:               |
   | Agent mode        |                    | LLM model mode        |
   |                   |                    |                       |
   | External agent    |                    | llmwikify itself      |
   | (opencode /       |                    | calls the LLM via     |
   | claude / codex)   |                    | httpx / openai lib    |
   | calls llmwikify   |                    |                       |
   | via MCP           |                    |                       |
   +-------------------+                    +-----------------------+
```

| Path | One-line description | Typical user |
|------|----------------------|--------------|
| **A. Agent mode** | An external agent (you run locally) drives llmwikify through MCP tools. | Power user who already has opencode / claude / codex set up. |
| **B. LLM model mode** | llmwikify itself talks to the LLM via `~/.llmwikify/llmwikify.json`. | Anyone with an LLM key, no agent installed. |

---

## The 5 dimensions

The two paths differ along 5 axes. Use this table to decide which one
fits a given situation.

| Dimension | Path A (Agent) | Path B (LLM model) |
|-----------|----------------|---------------------|
| **1. Who calls the LLM** | External agent (opencode, claude, codex) | llmwikify (via `foundation.llm`) |
| **2. Where the work happens** | In the agent's terminal / IDE | In a server / batch process / CLI sub-command |
| **3. Interface** | MCP (26 `wiki_*` tools) | Built-in Python API or `httpx` (chat server) |
| **4. Files generated** | `opencode.json` / `.mcp.json` / `.opencode.json` / `.agents/skills/llmwikify/SKILL.md` | `~/.llmwikify/llmwikify.json` |
| **5. Write control** | Agent dialog (human-in-loop) | SSE `confirmation_required` event / `posthoc` mode |

---

## Decision tree

Ask these questions in order; the first "yes" picks a path.

1. **Do you already have opencode / claude / codex installed and want to keep using it?**
   → **A. Agent mode**

2. **Do you need to process 100+ documents unattended (CI, batch)?**
   → **B. LLM model mode** (`batch --self-create`)

3. **Do you want to chat with your wiki and see the LLM reason step-by-step?**
   → **B. LLM model mode** (`serve --web` + chat)

4. **Are you on a server with no TTY / no interactive agent?**
   → **B. LLM model mode** (everything is API-driven)

5. **Do you want fine-grained human review at each wiki operation?**
   → **A. Agent mode** (agent pauses for confirmation)

6. **Otherwise**
   → **A or B, your preference**. Both work; pick what you like.

---

## Setup matrix

| Step | Path A | Path B |
|------|--------|--------|
| 1. Install llmwikify | `pip install 'llmwikify[extractors,web]'` | same |
| 2. Configure LLM | (not required for the agent) | `llmwikify init-llm` or `export OPENAI_API_KEY=...` |
| 3. Initialize a wiki | `llmwikify init --agent <opencode\|claude\|codex>` | `llmwikify init` |
| 4. Verify | `cat opencode.json` shows MCP config | `llmwikify doctor` reports healthy |
| 5. Run the agent | `opencode` (in your terminal) | `llmwikify serve --web --port 8765` (server) |
| 6. Drive the work | Ask the agent: "ingest `raw/`" | `curl /api/agent/chat -d '{"message":"ingest raw/"}'` |

---

## When to mix

The two paths are **not** mutually exclusive. A common combined workflow:

| Phase | Path | Why |
|-------|------|-----|
| Initial build (100 PDFs) | **B** (`batch --self-create`) | Unattended batch, fast |
| Day-to-day curation | **A** (opencode) | Human review at each edit |
| CI health check | **B** (`doctor --json`) | JSON output, no TTY |
| New questions, "what's in my wiki?" | **B** (`serve --web` + chat) | Streaming, conversational |

The data — the `wiki/` markdown tree — is **identical** regardless of
which path wrote it. The LLM just happens to be called by different
processes.

---

## How to verify (3 commands)

```bash
# 1. CLI mode works (Path B, no LLM needed)
llmwikify doctor --skip-llm --json | jq '.summary.failed'
# expect: 0

# 2. Chat mode works (Path B, needs LLM key for real events)
llmwikify serve --web --port 8765 --auth-token test &
curl -sN -H "Authorization: Bearer test" -H "Content-Type: application/json" \
  -d '{"session_id":"verify","message":"list pages"}' \
  http://localhost:8765/api/agent/chat | head -3
# expect: event lines starting with "data: {..."

# 3. Agent mode works (Path A, needs agent CLI)
llmwikify init --agent opencode
cat opencode.json | jq '.mcpServers'
# expect: a "llmwikify" entry pointing to llmwikify serve
```

The end-to-end versions of all three live in
[`examples/09_wiki_build_e2e/`](../examples/09_wiki_build_e2e/).

---

## Common pitfalls

| Pitfall | Fix |
|---------|-----|
| `LLM is not enabled. Set llm.enabled=true in config.` | Run `llmwikify init-llm` (or `init --llm`) |
| `MCP server not responding` (agent mode) | Check that `opencode.json` / `.mcp.json` was written, then restart the agent |
| `auth error (HTTP 401)` from chat | Run `llmwikify doctor` to verify the key works; check `~/.llmwikify/llmwikify.json` |
| Agent edits pages I didn't approve | Switch to `posthoc` mode: `--save-mode posthoc` in `llmwikify serve` |
| `llmwikify: command not found` (Path B in container) | See [`examples/09_wiki_build_e2e/README.md`](../examples/09_wiki_build_e2e/README.md) - the entrypoint sources a venv |

---

## TL;DR

* **Path A** = external agent + MCP = interactive, human-in-loop
* **Path B** = llmwikify + LLM API = scripted, server, CI
* The wiki files are identical
* Most users will mix: batch-build with B, curate with A
* One `pip install` covers both

---

*Last updated: 2026-07-02 · Version: 0.38.0 · Audience: anyone evaluating
llmwikify for the first time, or anyone onboarding a new team member.*
