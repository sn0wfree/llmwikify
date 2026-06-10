# Scripts

Standalone scripts for the llmwikify project.

> **Note:** These scripts are utilities, not part of the runtime. They run from the project root
> and add `src/` to `sys.path` so they can `import llmwikify.*`.

---

## Available Scripts

| Script | Purpose | Needs LLM? |
|---|---|---|
| `check_architecture.py` | Verify 4-layer architecture contracts | No |
| `check_prompt_principles.py` | Validate prompt design principles | No |
| `eval_prompts.py` | Offline prompt template evaluation | No |
| `smoke_v036.py` | v0.36 AgentChat hardening — real-LLM smoke | **Yes** |
| `smoke_v037.py` | v0.37 Triple ReAct Loop — real-LLM smoke | **Yes** |
| `migrate_db_v1_to_v2.py` | DB schema migration helper | No |
| `migrate_autoresearch_v3_to_v4.py` | AutoResearch migration helper | No |
| `repair_corrupted_ppt_task.py` | PPT task repair | No |
| `fix_swot_slide.py` | SWOT slide fix | No |
| `downgrade_to_v11513.sh` | Downgrade to v1.15.13 | No |
| `install_opencode_*.sh` | Installer scripts | No |

---

## Smoke Scripts (v0.36 / v0.37)

Real-LLM smoke tests for release validation. They are **out-of-band** of the regular pytest
suite because they require:

- A working LLM provider (OpenAI, Anthropic, or local Ollama)
- Network access to the provider's API
- Approximately 2–5 minutes of wall time per script

### Usage

```bash
# Set provider credentials
export OPENAI_API_KEY=sk-...
# or
export ANTHROPIC_API_KEY=sk-ant-...

# Run smoke
python scripts/smoke_v036.py
python scripts/smoke_v037.py
```

### What they do

Each script runs a series of scenarios against a freshly started AgentChat stack. Each scenario:

1. Starts a session
2. Sends a message that exercises a specific v0.36/v0.37 capability
3. Asserts on the SSE stream events
4. Cleans up (closes session, deletes DB rows)

Results are printed as a table and exit code 0 indicates all scenarios passed.

### What they DO NOT do

- Replace unit tests — they are *additional* coverage
- Replace manual UX testing — they verify behavior, not feel
- Run in CI by default — they are release-time only (see `.github/workflows/` if added later)

### When to run

- Before tagging a release (`v0.36.0`, `v0.37.0`, ...)
- After any change to:
  - `apps/chat/agent/*` (ChatService, ChatReActBridge)
  - `apps/chat/base.py` (aask_with_tools)
  - `apps/chat/engine.py` (ResearchEngine)
  - `kernel/llm/*` (LLM provider)
  - `interfaces/server/middleware.py` (rate limit)

### Skipping gracefully

If no API key is found, the script prints a warning and exits with code 0 (so CI without
keys does not break). Set `SMOKE_REQUIRE_KEY=1` to require a key.

---

## Adding a new smoke scenario

For each new release, scenarios should follow this template:

```python
async def s_<name>(ctx: SmokeContext) -> SmokeResult:
    """Short one-line description."""
    # 1. Setup (session, messages)
    # 2. Send / interact
    # 3. Assert on stream events
    # 4. Return result
    return SmokeResult(passed=True, details="...")
```

Register in `SMOKE_SCENARIOS = [...]` at the bottom of the script.

---

## See also

- `docs/designs/v0.36-agentchat-hardening.md` — Phase 6 + Phase 7 (smoke) spec
- `docs/designs/v0.37-react-loop.md` — v0.37 smoke spec
- `docs/releases/v0.36.0.md` — Smoke results (when present)
- `docs/releases/v0.37.0.md` — Smoke results (when present)