# foundation LLM 双栈合并 + streamable 拆分

> **日期**: 2026-10-23 · **范围**: 仅 `foundation/` 内部 · **目标版本**: 0.40.7 / 0.41
> **性质**: 结构债偿还（非性能优化）。运行时行为保持 0.40.6 基线。

## 背景

`foundation/llm_client.py`（329 行）与 `foundation/llm/`（client.py 122 行 +
streamable.py 1742 行）形成「双家 + 循环 import」：

```
llm_client.py → llm.budget_decorator → llm/__init__ → streamable → llm_client
                                              ↑ PEP 562 __getattr__ 硬解环
```

- 基类 `LLMClient` 住包外，子类 `StreamableLLMClient(LLMClient)` 住 `llm/`
- `from_config` memo 只挂在基类（lint/gaps 热路径已缓存）
- `streamable.py` 前 1123 行全是 helper，类仅 618 行

## 目标

1. **单一事实源**：客户端/memo/legacy 开关归 `foundation/llm/base.py`
2. **import 无环**：去掉 lazy `__getattr__` 解环
3. **streamable 可读**：1742 → ~620，按职责切 4 文件
4. **零行为变化**：不改 retry/流式/工具契约；kernel 调用方不动

## 非目标

- 不优化冷路径（gaps LLM ~47s）——另题
- 不统一基类 `chat()` 到 `_post_with_retry`（稳定性另题）
- 不删 `llm_client.py`（本 PR 只变薄壳）
- 不改 16 个测试的 import（`streamable` re-export 私有名）
- 不动 `apps/chat/agent/protocols.py` 的 `LLMClient(Protocol)` 同名

## 方案

### Phase A — 合并双栈

| 步 | 动作 |
|----|------|
| A1 | `LLMClient` + `_CLIENT_MEMO` + `_legacy_fallback_enabled` + `clear_llm_client_memo` → **`llm/base.py`** |
| A2 | `llm_client.py` 变 DEPRECATED re-export shim（生产 7 处 + 测试 39 文件不断） |
| A3 | `streamable.py` 改 `from .base import ...`；`llm/__init__.py` 简化 |
| A4 | memo key 共用：`LLMClient.from_config` 与 `build_llm_client` 同一把 key |
| A5 | `ARCHITECTURE.md` 模块树同步 |

### Phase B — 拆 streamable

| 新文件 | 迁入 | 职责 |
|--------|------|------|
| `errors.py`（扩） | `LLMRequestError`、`is_arrearage_response`、429 细分 | 错误分类 |
| `connection.py` | `RetryConfig`、backoff、`RetryMetrics`、`_post_with_retry_*` | HTTP + 重试 |
| `wire.py` | thinking extra_body、role 交替、`_validate_request`、`_format_http_error` | 协议线格式 |
| `sse.py` | `_parse_sse_line`、`_normalize_tool_call_ids` | 流解析 + tool 累积 |
| `streamable.py` | 仅 `StreamableLLMClient` + 兼容 re-export | 客户端编排 |

**tool 累积并入 sse 的理由**：`_parse_sse_line` 与 `_normalize_tool_call_ids` 共享
`tool_call_buffer`（读写就在解析循环内），独立成文件是假解耦。

## 兼容策略

- `llm_client.py` shim：`from llmwikify.foundation.llm_client import LLMClient` 不断
- `streamable.py` re-export 旧名（含 13 个私有符号：`_parse_sse_line`、
  `_post_with_retry_sync`、`_enforce_role_alternation` 等）→ 测试零改动
- `clear_llm_client_memo` / `_legacy_fallback_enabled` 路径不变（测试直采）

## 真实调用面（复核 2026-10-23）

| 入口 | 真实 CALL |
|------|----------:|
| `LLMClient.from_config` | 7（gap_filler×1、analyzer×2、llm mixin×3、source_analysis×1） |
| `build_llm_client()` | 1（codegen_pipeline） |
| `StreamableLLMClient.from_spec` | 2（providers/base、llm/client） |
| `StreamableLLMClient(...)` 直构 | 2（providers/base、xiaomi） |
| `StreamableLLMClient.from_config` | **0**（仅 docstring） |

## 验证门禁

1. `python scripts/check_architecture.py` → 0 violation
2. `ruff check src/llmwikify/foundation/`
3. 测试：`test_foundation_llm_*` / `test_streamable_*` / `test_sse_parse_line` /
   `test_token_budget` / `test_foundation_p0` / `test_xiaomi_provider` / `test_llm_comparison`
4. `grep`：`foundation/llm/` 内无 `from ..llm_client`

## 性能结论

**运行时 ≈ 0 收益**（memo 只惠及 1 处 build_llm_client 调用）。目标是可维护性，
为后续单独优化 `sse.py` / `connection.py` / 冷路径扫清结构障碍。

## 拆除计划（兼容债）

| 债 | 拆除条件 |
|----|---------|
| `llm_client.py` shim | kernel 6 处 caller 改 import 后，下一 minor 删 |
| `streamable` 私有 re-export | 16 个测试改指新模块后删 |

## Commit 切分

1. `docs(design): foundation LLM 双栈合并 + streamable 拆分方案`
2. `refactor(foundation): LLMClient 迁入 llm/base，llm_client 变薄壳`（Phase A）
3. `refactor(foundation): 拆 streamable 为 connection/wire/sse/errors`（Phase B + 文档）
