# Phase 1 / A — 契约即代码（SSE 事件单一真源）

日期: 2026-11-02 · 分支: v0.41-dev

## 问题

架构评审的 P0-03：SSE 契约前后端漂移。

- 后端 `apps/chat/agent/events.py` 定义 **17** 种事件；
  前端 `ui/webui/src/api.ts` 的 `ChatStreamEvent` union 只有 **12** 种，
  `session_init` / `user_message` / `compacted` / `command_done` / `phase`
  五类在前端**没有对应类型**。
- 契约纯手工双写：无 codegen、无契约测试、CI 不校验。
- 字段级漂移已造成实际缺陷：前端把 `confirmation_required.duration_ms`
  声明为必填，而**两个后端发射点都不发这个字段**（`orchestrator.py:126`
  与 `runner_v2.py:753`）——运行时恒为 `undefined`。
- 重复词表：`apps/chat/agent/unified/events.py` 又抄了一份 16 个 chat 常量。

## 方案

后端 `events.py` 的 `EVENT_SPECS` 成为**唯一真源**：

```
EVENT_SPECS: tuple[EventSpec, ...]
  EventSpec(const, fields, category, extends=None)
  EventField(name, ts_type, required=True)
```

`scripts/gen_webui_types.py` 由它渲染两份产物：

| 产物 | 用途 |
|------|------|
| `ui/webui/src/generated/events.ts` | 前端 union + `CHAT_EVENT_NAMES` 常量表 |
| `docs/api/events.schema.json` | 给非 TypeScript 消费者的 JSON Schema |

前端 `api.ts` 改为 `export type { ChatStreamEvent } from './generated/events'`，
手写 union 删除。`ResearchRunStatus` / `ResearchRunTimelineItem`
移到 `src/types/research.ts`（生成文件需要 import 它，且避免与 `api.ts` 循环）。

## 顺带修掉的漂移

| 发现 | 处理 |
|------|------|
| `unified/events.py` 重复定义 16 个 chat 常量 | 改为纯 re-export，词表只剩一处 |
| `research_runner.EVENT_PHASE = 'phase'` 与 `events.PHASE` 同名不同源 | 改为 `chat_events.PHASE` 别名；phase 规格补 `round`/`reason`/`final_state` 三个可选字段 |
| `confirmation_required.duration_ms` 前端必填、后端不发 | 规格标为可选；前端自身类型本就是 `duration_ms?: number` |

## 回归网

`tests/test_chat_events_contract.py`（13 项）：

1. 每个事件常量都有 `EVENT_SPECS` 条目（漏写则前端永远不知道）
2. 每个 spec 都有对应常量
3. spec 常量都在 `__all__`
4. wire name 不重复
5. 生成的 TS 与 spec 一致
6. 生成的 JSON Schema 与 spec 一致
7. 生成的 TS 覆盖全部 wire name
8. JSON Schema 合法且变体数匹配
9. `--check` 模式退出 0（CI 跑的就是它）
10. `unified/events.py` 与 `events.py` 值一致
11. research 事件来自 `research_runner`
12. **AST 扫描**：chat agent 包内除 `events.py` 外，无模块级常量把 wire name
    赋成字符串（这正是重复词表的产生模式）

## 验证

```
pytest tests/test_chat_events_contract.py -q   → 13 passed
npx tsc --noEmit                                → 0 error
npx vitest run                                  → 76 passed (10 files)
pytest -k "unified or research or event or ..." → 失败清单与改动前逐条一致
ruff check                                      → clean
```

## 下一步（P1-C）

CI 门禁：`gen_webui_types.py --check` 与 `check_architecture.py` 接进
workflow；新增 WebUI CI（`npm ci && tsc && vitest`）；`fail_under` 从 15 提到 80。
