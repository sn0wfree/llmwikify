# Migration v0.35 → v0.36 → v0.37

> **TL;DR:** v0.36 is **hardening** (bug fixes + reliability). v0.37 is **refactor** (ReAct loop
> unification). Most callers need no code changes; downstream code that consumed old 8-char
> UUIDs or relied on single-turn tool calls must update.

---

## v0.36 Migration (BREAKING in some areas)

### Required changes (anyone using UUIDs)

```python
# Before (v0.35)
message_id = msg["id"]  # 8 hex chars, e.g. "a1b2c3d4"
assert len(message_id) == 8

# After (v0.36)
message_id = msg["id"]  # 32 hex chars
assert len(message_id) == 32
```

### Optional changes (recommended)

```typescript
// Webui client
// Before
for await (const ev of chatStream(message, sessionId)) { ... }

// After — add AbortSignal for cancel
const ctrl = new AbortController();
for await (const ev of chatStream(message, sessionId, undefined, ctrl.signal)) { ... }
```

```typescript
// Webui client — regenerate any message
// Before: only last message could be regenerated
// After:
const result = await regenerate(sessionId, messageId);
```

### Behavior to expect

- Tool calls now iterate 1–4 times (was 1).
- Streams may emit `confirmation_required` (pause for user approval).
- Streams may emit `save_warning` (DB write failed but stream continues).
- Streams may emit `timeout` (300s exceeded).
- 429 responses on `/api/agent/*` if rate limit exceeded (60 req/min/IP).

### Optional server config

```bash
# Disable rate limiting (debugging only)
export LLMWIKIFY_RATE_LIMIT_DISABLED=1
```

---

## v0.37 Migration (mostly transparent)

### Required changes

**None.** `ChatService.chat()`, `ResearchEngine.run_research()` etc. keep their public signatures.

### Behavior changes

- Default: ChatService now goes through `ChatReActBridge` (`use_react_engine=True`).
- Fallback: pass `use_react_engine=False` to `AgentService` to use the legacy `aask_with_tools` path.

### New events emitted

| Event | When |
|---|---|
| `reasoning` | LLM chain-of-thought (more consistent than v0.36) |
| `phase` | ResearchEngine domain marker |
| All v0.36 events | (unchanged) |

### Optional: explicit ReAct control

```python
from llmwikify.apps.chat.agent.react_engine import (
    ReActEngine, ReActConfig, SkillAction, SkillContext
)

# Custom ReAct flow
config = ReActConfig(
    max_rounds=8,                # default 4
    timeout_s=60.0,              # default 300.0
    actions=[my_action_1, my_action_2],
    hooks={"on_round_complete": my_hook},
    reason=my_reason_callback,
)

async for event in ReActEngine(config).run(SkillContext(...)):
    ...
```

---

## When something breaks

| Symptom | Likely cause | Fix |
|---|---|---|
| Old UUIDs missing | v0.36 schema change | Re-fetch from DB; old IDs no longer exist |
| Tool call never returns | v0.36 multi-iteration | Add 1–4 iteration budget to your client |
| 429 Too Many Requests | v0.36 rate limit | Back off, or set `LLMWIKIFY_RATE_LIMIT_DISABLED=1` |
| `confirmation_required` event unhandled | v0.36 confirmation flow | Call `approve_and_continue(tool_call_id, true)` |
| ReAct hangs | v0.37 timeout bug | Check `timeout_s` config; default 300s |
| Abort doesn't work | Missing `signal` param | Pass `AbortSignal` to `chatStream()` |
| Stream misses events after abort | Expected behavior | Aborted streams emit no `done` |

---

## Quick checklist

- [ ] Update any code that consumed 8-char UUIDs
- [ ] Add `AbortSignal` support to client wrappers
- [ ] Handle new SSE events: `confirmation_required`, `save_warning`, `timeout`
- [ ] Test regenerate endpoint with non-last messages
- [ ] (v0.37) Verify ChatReActBridge path works (`use_react_engine=True` default)
- [ ] (v0.37) If relying on legacy `aask_with_tools`, set `use_react_engine=False`
- [ ] (v0.37) Update custom `reason` callbacks to 13-step round semantics

---

## See also

- `docs/releases/v0.36.0.md` — Full release notes
- `docs/releases/v0.37.0.md` — Full release notes
- `docs/api/agent.md` — API reference (all events, all endpoints)
- `docs/designs/v0.36-agentchat-hardening.md` — v0.36 design
- `docs/designs/v0.37-react-loop.md` — v0.37 design