# Migration v0.37 → v0.38

> **TL;DR:** v0.38 is the **nanobot v0.2.1 borrowing release**. No
> breaking changes — all public APIs preserved. New primitives
> (`BusAdapter` / `WsSessionMap` / `AgentRunner` / `LLMProviderABC`)
> are available for downstream code to adopt at its own pace.

---

## Required changes

**None.** The v0.38 release is additive. Existing `WikiServer` /
`AgentService` / `ChatOrchestrator` / `ReActEngine` / SSE client
code continues to work without modification.

---

## Recommended changes (opt-in)

### Subscribe to the MessageBus

The new `BusAdapter` mirrors every SSE event to an in-process
`MessageBus`. If you want to react to chat events without parsing
SSE yourself, subscribe to the bus:

```python
from llmwikify.apps.chat.bus import get_default_bus

bus = get_default_bus()
while True:
    msg = await bus.consume_outbound(timeout=1.0)
    if msg is None:
        continue
    if msg.is_stream_delta:
        # ...
        pass
```

### Connect WebSocket clients for low-latency streaming

The `/api/ws/agent` endpoint now routes real chat responses (no
longer just echoes). To migrate an existing polling client:

```typescript
// Before (v0.37 — polling for new events)
// POST /api/agent/chat every few seconds

// After (v0.38 — WebSocket)
const ws = new WebSocket(
  `ws://localhost:8765/api/ws/agent?token=${API_KEY}`,
);
ws.onmessage = (e) => {
  const env = JSON.parse(e.data);
  // env.type is one of: ready, chat_created, attached,
  // delta, stream_end, pong, error
};
```

### Use `ProviderConfig` for typed LLM configuration

```python
# Before (v0.37 — raw dict)
config_dict = {"provider": "minimax", "model": "MiniMax-Text-01", ...}

# After (v0.38 — typed)
from llmwikify.apps.chat.providers.abc import ProviderConfig
cfg = ProviderConfig.from_dict(config_dict)
assert cfg.is_configured()
assert cfg.retry_mode == RetryMode.TRANSIENT
```

The raw dict path still works — `from_dict()` falls back to
defaults on missing / invalid keys.

### Adopt `AgentRunner` for new flows

```python
from llmwikify.apps.chat.agent.agent_runner import AgentRunner

class MyCronSkill(AgentRunner["MySpec", "MyResult"]):
    name = "my-cron-skill"

    def wants_streaming(self) -> bool:
        return False

    async def run_stream(self, spec):
        yield {"type": "progress", "pct": 0}
        # ...
        yield {"type": "done", "result": ...}

    async def run_to_completion(self, spec):
        result = None
        async for ev in self.run_stream(spec):
            if ev["type"] == "done":
                result = ev["result"]
        return MyResult(ok=True, value=result)
```

---

## Behavior changes (BREAKING — by design)

### WebSocket `message` is no longer echo

In v0.37 the WS `message` handler echoed the user's content back as
`{"type": "delta", "content": "[echo] …"}`. In v0.38 it routes to
`ChatOrchestrator.chat()` and fans out the real response stream.

**Impact:** If a client was depending on the echo behavior for
testing or development, set `chat_service=None` when mounting the
WebSocket routes to restore the echo behavior. In production this
parameter is auto-wired by `routes.register_routes()`.

### `set_session_metadata` is now upsert

The DB method `set_session_metadata(session_id, blob)` used to
silently no-op when the session row didn't exist. It is now an
upsert (`INSERT OR IGNORE` + `UPDATE`). If your code was
intentionally relying on the silent-failure semantics (no known
such code exists), audit the change.

---

## Removed (none)

Nothing removed in v0.38. The old `LLMProvider` Protocol +
`BaseLLMProvider` are kept for MiniMax / Xiaomi; migration to the
new ABC is a v0.39 follow-up.

---

## Deprecated (none)

Nothing deprecated in v0.38.

---

## Server / DB prerequisites

No new dependencies. No DB migrations. No config file changes.

---

## See also

- [`docs/releases/v0.38.0.md`](releases/v0.38.0.md) — Full release
  notes (Phase 12 → 19-C).
- [`docs/poc/apply-plan.md`](poc/apply-plan.md) §12–§19 — Design
  rationale for each phase.
- [`docs/MIGRATION_v0.36.md`](MIGRATION_v0.36.md) — v0.36 + v0.37
  migration notes (UUIDs, AbortSignal, regenerate flow).