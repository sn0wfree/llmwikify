# M1 Decision: Skip Vendor, Borrow Patterns Only

> Date: 2026-06-17
> Refs: `m1-research.md`

---

## Decision

**SKIP M1 vendor of `nanobot/providers/base.py`.**

Reasons:
1. nanobot base.py = 843 LOC, llmwikify apps/chat/providers/ = 323 LOC total
2. nanobot OpenAICompatProvider = 1267+ LOC, llmwikify streamable.py = 1238 LOC (already mature)
3. Abstract shape mismatch: ABC `chat()→LLMResponse` vs Protocol `from_config()→StreamableLLMClient`
4. Vendor requires migrating 2 provider files + ~30 tests + introducing `loguru` + `json_repair` deps
5. Net LOC change: **+2700** (vendor) vs **+170** (borrow patterns)

---

## Decision Matrix

| 方案 | LOC 净增 | 新依赖 | 测试改动 | 风险 | 推荐 |
|---|---|---|---|---|---|
| A. Vendor `base.py` 843 LOC | +2700 | loguru, json_repair | ~200 LOC 重写 | 🔴 高 | ❌ |
| B. Vendor 3 dataclass (~50 LOC) | +50 | 0 | ~30 调用点迁移 | 🟡 中 | ❌ |
| **C. Borrow patterns (~170 LOC)** | **+170** | **0** | **~50 LOC 新增** | **🟢 低** | **✅** |
| D. Skip M1 entirely, go M6 | 0 | 0 | 0 | 🟢 无 | ✅ (backup) |

---

## Adopted Approach: C (Borrow Patterns)

From nanobot base.py / openai_compat_provider.py, borrow these patterns to `streamable.py`:

### Pattern 1: 429 精细分类 (~80 LOC)
```python
# In src/llmwikify/foundation/llm/streamable.py

_NON_RETRYABLE_429_TOKENS = frozenset({
    "insufficient_quota", "quota_exceeded", "quota_exhausted",
    "billing_hard_limit_reached", "insufficient_balance",
    "credit_balance_too_low", "billing_not_active",
    "payment_required",
})

_RETRYABLE_429_TOKENS = frozenset({
    "rate_limit_exceeded", "rate_limit_error", "too_many_requests",
    "request_limit_exceeded", "overloaded_error",
})


def _is_retryable_429(error_type: str | None, error_code: str | None, content: str) -> bool:
    """Distinguish billing failures (don't retry) from rate limits (retry)."""
    for token in (error_type, error_code):
        if token and token in _NON_RETRYABLE_429_TOKENS:
            return False
        if token and token in _RETRYABLE_429_TOKENS:
            return True
    lowered = content.lower()
    if any(m in lowered for m in ("insufficient_quota", "quota_exceeded", "billing")):
        return False
    if any(m in lowered for m in ("rate_limit", "too many requests", "retry after")):
        return True
    return True  # unknown 429 → wait + retry
```

### Pattern 2: Arrearage 检测 (~40 LOC)
```python
def is_arrearage_response(error_status_code: int | None, error_type: str | None, error_code: str | None, content: str) -> bool:
    """Detect billing/quota errors that won't clear on retry."""
    if error_status_code == 402:
        return True
    for token in (error_type, error_code):
        if token and token in _NON_RETRYABLE_429_TOKENS:
            return True
    lowered = (content or "").lower()
    return any(marker in lowered for marker in (
        "insufficient quota", "quota exceeded", "out of credits",
        "billing hard limit", "payment required",
    ))
```

### Pattern 3: Thinking style map (~30 LOC)
```python
_THINKING_STYLE_BUILDERS = {
    "thinking_type": lambda on: {"thinking": {"type": "enabled" if on else "disabled"}},
    "enable_thinking": lambda on: {"enable_thinking": on},
    "reasoning_split": lambda on: {"reasoning_split": on},
}

# Per-provider spec:
MINIMAX_THINKING_STYLE = "reasoning_split"  # matches current default
XIAOMI_THINKING_STYLE = "reasoning_split"   # llmwikify current (vs nanobot thinking_type)
```

### Pattern 4: Role alternation hardening (~20 LOC)
```python
def _enforce_role_alternation(messages: list[dict]) -> list[dict]:
    """Merge consecutive same-role + drop trailing assistant + recover with synthetic user."""
    # ... existing logic ...
    # NEW: if removing trailing assistants left only system msgs, convert last popped → user
    # NEW: if first non-system is bare assistant, insert synthetic user msg
    return merged
```

**Total addition: ~170 LOC, 0 vendor files, 0 new deps.**

---

## Implementation Plan (when approved)

### Single commit, scope: streamable.py + 2 provider files

```
src/llmwikify/foundation/llm/streamable.py    +170 -10  (4 patterns + minor refactor)
src/llmwikify/apps/chat/providers/minimax.py  +5  -2   (use thinking_style map)
src/llmwikify/apps/chat/providers/xiaomi.py   +5  -2   (use thinking_style map)
tests/test_apps_chat_providers_borrow.py      +60 0    (NEW: 5 用例)
```

### Commit message
```
feat(llm): borrow retry patterns from nanobot (Pattern A)

借鉴 nanobot v0.2.1 base.py 的 4 个模式到 streamable.py:
- 429 精细分类 (billing vs rate_limit)
- Arrearage 检测 (402 + billing tokens)
- Thinking style map (reasoning_split/thinking_type/enable_thinking)
- Role alternation hardening (trailing assistant → synthetic user)

变更: streamable.py +170, minimax.py +5, xiaomi.py +5, +1 测试文件 5 用例.
不引入新依赖, 不 vendor 外部代码. M1 范围缩为"借模式", 不 vendor base.py.

参考: docs/poc/m1-research.md, docs/poc/m1-decision.md
```

---

## Verification

- `pytest tests/test_apps_chat_providers_borrow.py` 5 用例全过
- `pytest tests/test_apps_chat_providers_minimax.py tests/test_apps_chat_providers_xiaomi.py` 现有测试不受影响
- `ruff check src/llmwikify/foundation/llm/streamable.py src/llmwikify/apps/chat/providers/` 干净
- 真实 MiniMax API 调用: `python -c "from llmwikify.apps.chat.providers import create_llm; c = create_llm({'enabled': True, 'provider': 'minimax', 'api_key': 'env:MINIMAX_API_KEY'}); print(c.provider, c.model)"` 正常输出

---

## What This Decision Does NOT Cover

- M6 (agent loop import) — separate decision, next phase
- Adding OpenAI Responses API support — defer to M6 if needed
- Adding new providers (Anthropic, OpenAI direct, Bedrock) — defer to M6+
- nanobot config schema (TOML/YAML) — defer to M4 if at all
- WebSocket channel (nanobot's `channels/websocket/`) — defer to M3
