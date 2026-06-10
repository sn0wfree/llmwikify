# AgentChat API Reference

> **Version:** v0.36.0 (2026-06-09)
> **Base path:** `/api/agent`
> **Auth:** none (loopback only; production deployment should add a reverse proxy with auth)

AgentChat provides streaming chat, regeneration, confirmation flow, session/message/tool-call
persistence, dream proposal review, and edit history. All streaming endpoints use Server-Sent Events
(SSE) and accept `AbortSignal` for cancellation.

---

## 1. Chat Endpoints

### 1.1 `POST /api/agent/sessions/{session_id}/chat`

Stream a chat response for the given session. SSE format.

**Path params:**

| Name | Type | Description |
|---|---|---|
| `session_id` | string | Session identifier (created via `POST /api/agent/sessions` or auto-created) |

**Request body (JSON):**

```json
{
  "message": "string, user message",
  "wiki_id": "string, optional, default wiki id"
}
```

**Response:** `200 OK`, `Content-Type: text/event-stream`

**SSE event types:**

| Event | Payload | Description |
|---|---|---|
| `session_created` | `{session_id}` | First event, confirms session id |
| `message_delta` | `{delta: string}` | Streamed assistant content chunk |
| `thinking` | `{content: string}` | LLM reasoning / chain-of-thought |
| `tool_call_start` | `{id, name, arguments}` | Tool invocation begins |
| `tool_call_end` | `{id, result}` | Tool invocation finished |
| `tool_call_error` | `{id, error}` | Tool invocation failed |
| `confirmation_required` | `{tool_call_id, name, arguments}` | Tool needs user approval |
| `save_warning` | `{error_count}` | DB persistence failed but stream continues |
| `done` | `{usage, finish_reason}` | Stream complete |
| `error` | `{message, code}` | Fatal error |
| `timeout` | `{elapsed_s}` | Stream exceeded 300s |

**Behavior notes (v0.36):**

- `AbortSignal` supported via `signal` option in client wrapper (`chatStream(message, signal)`).
  Cancellation emits no further events; in-flight tool calls are best-effort cancelled.
- First-chunk failure is retried up to 3 times with exponential backoff (1s/2s/4s).
- 15-second heartbeat (`ping`) keeps connection alive through proxies.
- Hard timeout: 300 seconds. Exceeding it emits a `timeout` event and closes.

**Example (curl):**

```bash
curl -N -X POST http://localhost:8765/api/agent/sessions/abc-123/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"summarize the home page","wiki_id":"default"}'
```

---

### 1.2 `POST /api/agent/sessions/{session_id}/regenerate` (v0.36 新增)

Regenerate the assistant response at a given position. Truncates the conversation to the user
message just before the target assistant message and runs a new chat turn.

**Path params:**

| Name | Type | Description |
|---|---|---|
| `session_id` | string | Session identifier |

**Request body (JSON):**

```json
{
  "message_id": "string, target assistant message id",
  "wiki_id": "string, optional"
}
```

**Response:** SSE stream in the same format as `chat`.

**Behavior notes:**

- The target message must be an assistant message.
- All messages after the preceding user message are removed (cascade delete via FK).
- Stream behavior and event types match `chat`.

---

### 1.3 `POST /api/agent/confirmations/{tool_call_id}/approve`

Approve a tool that requires confirmation and resume the stream.

**Request body (JSON):**

```json
{
  "approved": true,
  "arguments": {} // optional override
}
```

**Response:** SSE stream in the same format as `chat`.

**Behavior notes:**

- If `approved=false`, the tool is rejected and the assistant produces a final response.
- Supports `AbortSignal` for cancellation.
- SSE reconnect supported (same retry policy as `chat`).

---

## 2. Session Endpoints

### 2.1 `GET /api/agent/sessions`

List all sessions for the current data directory.

**Response:**

```json
[
  {"id": "string", "title": "string", "created_at": "ISO-8601", "updated_at": "ISO-8601"}
]
```

---

### 2.2 `POST /api/agent/sessions`

Create a new session.

**Request body (JSON):**

```json
{
  "title": "string, optional"
}
```

**Response:** `201 Created`, `{id, title, created_at, updated_at}`

---

### 2.3 `GET /api/agent/sessions/{session_id}`

Fetch session metadata.

**Response:** `{id, title, created_at, updated_at, message_count}`

---

### 2.4 `DELETE /api/agent/sessions/{session_id}`

Cascade delete: removes session + messages + tool_calls + context_entries in a single
transaction.

**Response:** `204 No Content`

---

### 2.5 `GET /api/agent/sessions/{session_id}/messages`

List messages in chronological order (ASC).

**Response:**

```json
[
  {"id": "string", "role": "user|assistant|system", "content": "string", "created_at": "ISO-8601"}
]
```

---

## 3. Dream Proposal Endpoints

### 3.1 `GET /api/agent/dream-proposals`

List pending dream proposals across all wikis.

**Response:**

```json
[
  {
    "id": "string",
    "wiki_id": "string",
    "title": "string",
    "rationale": "string",
    "created_at": "ISO-8601"
  }
]
```

---

### 3.2 `POST /api/agent/dream-proposals/{id}/approve`

Approve a dream proposal; the system will create the proposed wiki page.

**Response:** `200 OK`, `{page_id, page_url}`

---

### 3.3 `POST /api/agent/dream-proposals/{id}/reject`

Reject a dream proposal.

**Response:** `204 No Content`

---

## 4. Edit History Endpoints

### 4.1 `GET /api/agent/edit-history`

List recent edit events.

**Response:**

```json
[
  {"id": "string", "wiki_id": "string", "page_path": "string", "action": "string", "timestamp": "ISO-8601"}
]
```

---

## 5. Notification Endpoints

### 5.1 `GET /api/agent/notifications`

List pending notifications.

---

## 6. System Endpoints

### 6.1 `GET /api/agent/health`

Health check.

**Response:** `{status: "ok"}`

---

## 7. Rate Limiting (v0.36 新增)

All `/api/agent/*` endpoints are subject to **per-IP rate limiting**:

- Default: 60 requests / minute / IP
- Token bucket algorithm
- Exceeded → `429 Too Many Requests` + `Retry-After: <seconds>` header
- Disable via env var: `LLMWIKIFY_RATE_LIMIT_DISABLED=1`

---

## 8. Cross-Cutting Concerns

### 8.1 SSE Reconnect (v0.36 新增)

Client-side reconnect policy (handled in `chatStream` / `approveAndContinue`):

- Up to 3 retries
- Backoff: 1s → 2s → 4s
- Retries only when no event has been received yet (avoids duplicate events)
- `AbortError` does not trigger reconnect

### 8.2 MemoryManager Integration (v0.36)

- `ConversationStore.alist()` — chat history retrieval (async)
- `ContextStore.aadd()` — tool result persistence (async, best-effort)
- `UserPreferenceStore.aall()` — user preferences injected into system prompt
- `MemoryIndex.asearch()` — top-3 relevant history injected into system prompt

System prompt composition (6 sections):

1. Role + strategy
2. Wiki context (current page / available pages)
3. User preferences
4. Tool list
5. Current date
6. Relevant history (from MemoryIndex)

### 8.3 Cascade Delete (v0.36)

`DELETE /api/agent/sessions/{id}` removes in one transaction:

- chat_sessions row
- chat_messages rows
- chat_tool_calls rows (FK to messages)
- chat_context_entries rows (FK to messages)

`PRAGMA foreign_keys = ON` is set at connection time.

---

## 9. Event Type Reference (Complete)

| Event | Direction | Notes |
|---|---|---|
| `session_created` | server → client | Always first |
| `message_delta` | server → client | Streamed text |
| `thinking` | server → client | Chain-of-thought |
| `tool_call_start` | server → client | Tool begins |
| `tool_call_end` | server → client | Tool success |
| `tool_call_error` | server → client | Tool failure (non-fatal) |
| `confirmation_required` | server → client | Pauses stream |
| `save_warning` | server → client | DB persistence failed |
| `done` | server → client | Stream complete |
| `error` | server → client | Fatal |
| `timeout` | server → client | 300s exceeded |
| `ping` | server → client | 15s heartbeat (no payload) |

---

## 10. Client SDK (TypeScript)

```typescript
import { chatStream, approveAndContinue, regenerate } from "@/api";

// Basic chat
const ctrl = new AbortController();
for await (const event of chatStream("hello", { signal: ctrl.signal })) {
  if (event.type === "message_delta") process.stdout.write(event.delta);
  if (event.type === "done") break;
  if (event.type === "confirmation_required") {
    await approveAndContinue(event.tool_call_id, true);
  }
}

// Cancel
ctrl.abort();

// Regenerate (any assistant message)
for await (const event of regenerate(sessionId, messageId)) { /* same events */ }
```

---

## 11. Future Endpoints (planned)

- `POST /api/agent/sessions/{id}/feedback` — explicit user feedback per turn
- `GET /api/agent/sessions/{id}/memory` — inspect MemoryManager state for a session
- `POST /api/agent/regenerate-config` — change regeneration strategy (full / retry-with-same-context)

---

— end of v0.36.0 reference —