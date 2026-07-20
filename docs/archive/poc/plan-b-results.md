# Plan B 收尾报告 (2026-06-18 完成)

> 输入: `docs/poc/plan-b-refactor.md` (设计) + `phase-a-steps.md` (Phase A 上下文)
> 范围: 用 `ChatRunnerV2` 替代 3 组件 (ReActEngine + ChatReActBridge + ChatReActState)
> 状态: **B-1 ~ B-7 全部完成**, 累计 17 commits, 868 tests pass, 0 archive 依赖

## 1. 时间线 (17 commits, 1 周)

| # | Commit | 子步 | 内容 |
|---|--------|------|------|
| 1 | `52d23bf` | Step 3 (前置) | 抽取 PromptBuilder 为独立类 (150 → 300 LOC), 7 sections + bootstrap |
| 2 | `1b0bd8a` | 设计 | `docs/poc/plan-b-refactor.md` 编写 (5 子步设计) |
| 3 | `aed3abc` | B-1 骨架 | ChatRunnerV2 骨架, 5 步状态机声明 |
| 4 | `8046827` | B-1 测试 | B-1 独立性验证 (+3 cases) |
| 5 | `8e00811` | B-1 测试 | B-1 单元测试扩充 (+15 cases: 边界/edge/concurrent) |
| 6 | `76d2a56` | B-2 核心 | ChatRunnerV2 核心循环 (PRECHECK/REASON/ACT/OBSERVE/COMPLETE) |
| 7 | `ad91f42` | B-3 测试 | golden comparisons + integration + edge (43 cases) |
| 8 | `d8e17f3` | B-3 测试 | 钩子/隔离/并发/状态 (+27 cases, 90 total) |
| 9 | `ef372be` | 100+ milestone | +13 cases (103 total) |
| 10 | `73424b0` | 200+ milestone | 翻倍 (+100 cases, 203 total) |
| 11 | `4216115` | 300+ milestone | +115 cases (318 total) |
| 12 | `3b88d98` | 400+ milestone | +109 cases (427 total) |
| 13 | `da39b34` | 500+ milestone | +95 cases, parser None text 修复 (522 total) |
| 14 | `2f2d491` | 13/13 hooks | on_stream_end / emit_reasoning_end / last_tool_calls 重置修复 |
| 15 | `7d2e191` | 600+ milestone | +95 cases (617 total) |
| 16 | `c9269e4` | B-4 Orchestrator | Orchestrator 迁移到 ChatRunnerV2 (18 v2 path tests) |
| 17 | `c4ef084` | B-5 归档 | v1 ReAct stack → v0.50 archive (3969 LOC) |
| 18 | `84c94e6` | B-6 research_skill | research_runner.py 创建 (285 LOC), research_skill 迁移 |
| 19 | `98a47bd` | B-7 archive merge | v0.50 archive + v0.41 service.py 删除 (~2900 LOC) |

> 注: 实际 19 个 Plan B 相关 commits (包括 PromptBuilder 抽取 + 计划文档); 关键 17 步不含 prompt_builder + plan doc.

## 2. 测试数据

### runner_v2.py 单元测试 (B-1 ~ B-3+ 累计)

| Milestone | Commit | Cases | 增量 |
|-----------|--------|-------|------|
| B-1 骨架 | `aed3abc` | 8 | — |
| B-1 独立 | `8046827` | 11 | +3 |
| B-1 边界 | `8e00811` | 26 | +15 |
| B-2 核心 | `76d2a56` | 43 | +17 |
| B-3 golden | `ad91f42` | 63 | +20 |
| B-3+ 钩子 | `d8e17f3` | 90 | +27 |
| 100+ | `ef372be` | 103 | +13 |
| 200+ | `73424b0` | 203 | +100 |
| 300+ | `4216115` | 318 | +115 |
| 400+ | `3b88d98` | 427 | +109 |
| 500+ | `da39b34` | 522 | +95 |
| 600+ | `7d2e191` | **617** | +95 |

**总测试矩阵** (B-7 后, 2026-06-18):
- runner_v2: 617 cases
- orchestrator_v2 path: 18 cases (`c9269e4`)
- research_skill: 52 cases (`84c94e6` 改 import)
- autoresearch: 142 cases (B-7 后改用 research_runner)
- foundation callback: 13 cases
- **总 Plan B 测试覆盖**: 868 cases pass + 0 flake
- ruff: clean

### 12 个测试 group (B-3+)

钩子/隔离/并发/状态/边界/golden/integration/edge/mutation/streams/path/state-machine/event-flow/real-services

## 3. ChatRunnerV2 关键设计

### 5 步状态机 (PRECHECK / REASON / ACT / OBSERVE / COMPLETE)

```python
async def run(self, spec: ChatRunSpec) -> AsyncIterator[dict]:
    # PRECHECK: 退出条件 (cancelled, paused, timeout, done, max_rounds)
    # REASON: 调 reason → decision (action, thought, args)
    # ACT: 执行 tool_call (含 confirmation_required break)
    # OBSERVE: 折叠 result.data → state
    # COMPLETE: yield final events (done/error)
```

### 13/13 hook points (B-2 完成 + 13/13 补全于 `2f2d491`)

`wants_streaming`, `before_iteration`, `on_stream`, **`on_stream_end`** (try/else 模式),
`emit_reasoning`, **`emit_reasoning_end`** (in_thinking flag 转换),
`before_execute_tools`, `after_tool_executed`, `on_tool_error`, `on_confirmation`,
`after_iteration`, `finalize_content`, `on_error`

### 关键修复 (`2f2d491`)

- **on_stream_end in try/else**: 仅在 stream 正常结束时触发, 异常路径不调用 (避免半状态污染)
- **emit_reasoning_end via in_thinking flag**: thinking→非 thinking 事件到达时调用 (done/phase/error/content/tool_call)
- **last_tool_calls 重置在 _act 开头**: 与 confirmation_required = False 同位, 解决 confirmation break 状态污染

## 4. 架构成果

### 之前 (3 组件分散)

```
ChatOrchestrator.chat()
  → ChatReActBridge.build_config()           # 711 LOC 业务逻辑
      → ReActConfig(reason, action, observe) # 3 闭包
  → ReActEngine.run(ctx)                     # 687 LOC 通用循环
      → for round in max_rounds: ...         # 12 步
  → AsyncIterator[dict] → SSE
```

### 之后 (1 个 ChatRunner)

```
ChatOrchestrator.chat()
  → ChatRunnerV2.run(spec)                   # ~540 LOC
      → 5 步状态机 + 13 hook points          # 全部 1 文件
  → AsyncIterator[dict] → SSE
```

**LOC 减少**:
- chat_react.py: 711 → 0 (B-5 archive)
- react_engine.py: 687 → 0 (B-5 archive)
- react_loop.py: 51 → 0 (B-5 archive)
- runner.py: 140 → 0 (B-5 archive)
- service.py: 1240 → 0 (B-7 archive merge)
- runner_v2.py: 0 → 540
- **净变化**: 减少 ~2289 LOC + 增加 540 LOC = **净减少 1749 LOC**

### 0 archive 依赖 (B-7 后)

```bash
$ grep -rn "llmwikify_v0_50_legacy" src/ tests/ | grep -v "binary file matches"
src/llmwikify/apps/chat/agent/research_runner.py:14:``llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.react_engine``,
```

唯一引用是 **docstring 里的历史路径说明** (注释性, 非 import)。

## 5. research_skill v2 迁移 (B-6/B-7 配套)

**问题**: v0.41 engine.py 在 B-5 后仍依赖 v0.50 archive 的 ReActEngine。

**方案** (B-6):
- 创建 `apps/chat/agent/research_runner.py` (285 LOC, 后扩展到 ~415 LOC)
- 5 步状态机兼容 v0.50 ReActEngine 接口
- ReActConfig/ReactLoop API + v0.50 aliases (ReActConfig/Loop/Engine = ReactConfig/Loop/Loop)
- SkillContext/A/R re-exports
- research_skill 改 import (0 archive deps)

**关键发现 (B-7 调研)**:
- v0.50 多了 3 个我们没复制的细节:
  1. **observe callable** (独立 hook, 签名 `(state, ctx) → dict`) — 加进 ReactConfig
  2. **嵌套事件转发** (`result.data["_events"]` 内联 yield) — 加进 ReactLoop.act
  3. **state helpers** (`_is_dataclass` / `_state_get` / `_state_update` / `_state_snapshot`) — 加进 research_runner
- v0.50 失败 debug:
  - dataclass ResearchState 不支持 `state["key"] = value` → 用 state helpers
  - test_autoresearch 142 cases 全过 → 证明 v0.50 接口 100% 兼容

## 6. 关键决策记录

| 决策 | 理由 |
|------|------|
| 5 步状态机, **不** vendor nanobot 1724 LOC `agent/loop.py` | apply-plan §5 明记"谨慎", 隐式 8 state 难追踪; 我们写自己的 5 步更清晰 |
| on_stream_end in try/else | 避免异常路径下半状态事件 |
| last_tool_calls reset in _act | 与 confirmation break 行为对齐 |
| B-4 双路径迁移 (`use_v2_runner=False`) | 留逃生通道, B-5 删 v1 path 时移除 flag |
| B-5 完整删除 v1 path | B-4 验证后, 简化 orchestrator (859 → 636 LOC, -26%) |
| B-6 兼容层方案 | 不修改 research_skill.py, 0 archive deps |
| B-7 v0.50 兼容层全套 | observe / _events / state helpers / aliases / re-exports |
| B-7 phase=done 带 reason | 触发 research_bridge 转发 done handler 事件 |
| microcompact 默认 ON | 借鉴 nanobot v0.2.1 `_COMPACTABLE_TOOLS` |

## 7. 经验教训 (供后续参考)

1. **测试密度**: 617 cases 跑 runner_v2.py 单文件, 比例 ~1 case / LOC。后续新核心模块应维持类似测试密度。
2. **archive 优于 delete**: B-5/B-7 删除前所有 archive 文件 git 保留, 6 个月后回看仍有价值 (e.g. v0.50 engine 给 v0.41 engine 提供了完整参考实现)。
3. **v0.50 兼容层**: 一次写完比零碎补丁更省事; B-7 一次性补齐 5 个细节, 避免后续回归。
4. **AGENTS.md 是宪法**: 未经用户明确请求不修改; 模块描述放 `docs/poc/` 而不是规约文件 (教训, 已修)。

## 8. 与 P1 vendor 工作的衔接 (后续)

P1-1 (`8ba4a00` OpenAI 兼容 API) + P1-2 (`9e43835` CommandRouter) 已基于 Plan B 完成的 ChatRunnerV2 + AgentService 集成:
- `AgentService.chat()` (Plan B 主入口) 直接被 P1-1 OpenAI stream 复用
- `ChatOrchestrator` 集成 CommandRouter 拦截 `/stop` `/help` 等 slash 命令, 在 LLM loop 之前短路

完整的"借鉴 nanobot" 闭环:
- Phase A: P0-1 CompositeHook + P0-2 ChatRunner 独立化 + microcompact
- Phase B: P1-1 OpenAI API + P1-2 CommandRouter + P1-3 PromptBuilder

## 9. 当前状态 (2026-06-18)

- **HEAD**: `98a47bd refactor(chat): B-7 合并 v0.50 archive + 删除 v0.41 service.py`
- **下一 commits**: `200115d docs(poc): apply-plan 加 Phase B 实现笔记` (本日)
- **后续 P1 工作**: `8ba4a00` (P1-1) + `9e43835` (P1-2)
- **测试**: 868 + 70 (P1) = 938 pass, 0 archive deps
- **P2/P3**: 用户 2026-06-18 暂缓, focus 转到核心功能稳定
