# SSE 契约修复与静默失败治理

> 分支 `feat/auto-doc-ingest` · 2026-07
> 触发：全项目四维审查（架构 / 业务逻辑 / API 契约 / 测试）

## 背景

前端 `ui/webui/src/api.ts` 的 `ChatStreamEvent` 定义了 chat SSE 的消费契约。
审查发现后端部分事件未对齐，以及若干静默失败路径。

## 审查结论

### #1 duration_ms 缺失（确认，修）

契约要求 `tool_call_end` / `tool_call_error` / `confirmation_required`
均携带 `duration_ms: number`（api.ts:38-42）。前端在
AgentChat.tsx:566/574/582 直接读取，缺失时显示 undefined。

| 发射点 | 现状 |
|---|---|
| `runner_v2.py` tool_call_end / 异常 tool_call_error | ✅ 已有（`measure_latency`） |
| `runner_v2.py` confirmation_required (≈L753) | ❌ 缺失 |
| `runner_v2.py` status=error 的 tool_call_error (≈L763) | ❌ 缺失 |
| `runner_v2.py` 空 tool name 的 tool_call_error (≈L660) | ❌ 缺失 |
| `tool_actor.py` 全部 4 类事件 | ❌ 全缺（无计时） |
| `orchestrator.py ChatEvent.confirmation_required` 工厂 | ❌ 无该参数 |

**修法**：统一用 `foundation.utils_timing.measure_latency`。
`runner_v2` 中 confirmation / status-error 分支位于 `with` 块之后，
`get_ms` 仍在函数作用域且返回缓存值，可直接使用；空 name 错误
发生在执行前，填 `0`。`tool_actor` 在 `_execute_tool` 外包一层计时。
工厂方法补 `duration_ms: int = 0` 参数（与 tool_call_end/error 对齐）。

### #2 error / message 字段分裂（误报，不修）

审查曾报告「research 用 `error`、前端读 `message` 导致错误丢失」。
逐链路核实后**不成立**——这是两条独立 SSE 流、两套独立契约：

```
/api/agent/chat ──► AgentChat.tsx        读 event.message  ✅
                    后端 ChatEvent.error / runner_v2 ERROR 均发 message

/api/autoresearch/{id}/stream ──► AutoResearchPanel.tsx  读 ev.error ✅
                    后端 research/{base,engine,actions,report} 均发 error
```

`research_bridge.translate_react_events` 仅被 `apps/research/engine.py`
引用，事件只进 research 流，不进 chat 流。字段各自正确，**无交叉**。

### #4 静默失败：_call_service_method（确认，修）

`runner_v2.py:_call_service_method`：

- 协程分支 `if inspect.iscoroutine(result): return default` —
  **零日志**。若 adapter 方法是 async，`_truncate_messages` /
  `_get_toolspec` 被静默跳过：前者不截断（上下文膨胀），
  后者返回 `[]`（agent 无工具照跑）。
- 异常分支已有 warning，保留。

**修法**：协程分支补 `logger.warning` 并 `result.close()`
（避免 RuntimeWarning: coroutine never awaited）。

### #8 吞异常返回成功（部分修）

**`foundation/extractors/web.py:38`**（修）：

```python
except (requests.RequestException, Exception):  # 等价 except Exception，零日志
    return None
```

抓取失败完全不可观测。**修法**：拆分并补日志——
`RequestException` 记 warning（预期内的网络错误），
其余 `Exception` 记 exception（疑似编程错误）；仍返回 None
（extractor 契约：失败即 None，由调用方决定降级）。

**`skills/actions/_helpers.py` `None → SkillResult.ok({})`**（不改语义）：

AST 扫描确认 0 个 action 裸 `return None`。`None` 来自被调
wiki 方法的 void 成功返回（如写操作）。改成 fail 会破坏 void 语义。
失败路径均通过 raise → `safe_call` 捕获 → `SkillResult.fail`，
不存在「失败报成功」的实证。**仅补 debug 日志**便于排查。

## 不在本次范围

- `timeout` / `phase` / `compacted` 等事件不在 `ChatStreamEvent`
  联合类型中，前端 switch 静默忽略——已知，另行处理。
- research 侧契约保持 `error` 字段不动（AutoResearchPanel 依赖）。

## 验证

- 新增 `tests/test_sse_contract_duration.py`：断言 runner_v2 三类
  事件、tool_actor 四类事件均携带 `duration_ms`。
- 新增静默失败测试：协程分支产生 warning；web 抓取失败产生日志。
- 回归：`test_apps_chat_agent_runner_v2.py`、`test_agent_sse_wire_format.py`、
  `test_unified_chat*.py`。
