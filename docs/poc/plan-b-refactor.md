# Plan B 续: Runner 全量重构 设计文档

> 输入: `phase-a-steps.md` + 现有 `chat_react.py` (711 LOC) + `react_engine.py` (687 LOC)
> 目标: 用统一的 `ChatRunner` 替代当前的 3 组件 (ReActEngine + ChatReActBridge + ChatReActState)
> 时间: 2026-06-17 起 1 周
> 状态: 设计阶段 (待用户确认)

---

## 1. 当前架构分析

### 1.1 3 组件职责

```
┌────────────────────────────────────────────────────────────────────┐
│  ChatReActBridge (711 LOC, chat_react.py)                          │
│  - 3 闭包: reason / action_handler / observe                       │
│  - ChatReActState dataclass (per-turn state)                       │
│  - 3 个 helper: parse_wiki_prefix / microcompact hook / state 合并 │
├────────────────────────────────────────────────────────────────────┤
│  ReActEngine (687 LOC, react_engine.py)                            │
│  - 12 步循环: timeout/cancel/done/reason/act/observe/persist/...  │
│  - 7 lifecycle hooks                                                │
│  - 2 dispatch 模式: skill-action / custom-handler                  │
├────────────────────────────────────────────────────────────────────┤
│  ChatOrchestrator (664 LOC)                                         │
│  - 调用 ChatReActBridge.build_config → ReActConfig                 │
│  - 调 ReActEngine.run(ctx) → AsyncIterator[dict]                   │
│  - yield 给 SSE handler                                            │
└────────────────────────────────────────────────────────────────────┘
```

### 1.2 7 处核心问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | **3 组件分散**: reason/action/observe 是闭包, 状态隐式 | 难追踪, 难测试 |
| 2 | **callback 链脆弱**: 闭包嵌套深, 一处抛错整链挂 | 已用 CompositeHook 缓解 (Step 1) |
| 3 | **state dataclass 字段冗余**: ChatReActState + ReActConfig + SkillContext 三套状态 | 难维护 |
| 4 | **2 套 dispatch**: skill-action / custom-handler | 概念冗余, chat 只用一种 |
| 5 | **microcompact 是 patch 进去的** (chat_react.py:612) | 集成不深 |
| 6 | **ChatOrchestrator 自己又包了一层**: 转换 SSE events | 多余抽象 |
| 7 | **805+918 LOC 测试** 需 mock 整个 ReActConfig + 3 闭包 | 难维护 |

### 1.3 关键耦合点

```python
# 当前: 4 个抽象协作完成 1 个 chat turn
ChatOrchestrator.chat()
  → ChatReActBridge.build_config()           # 711 LOC 业务逻辑
      → ReActConfig(reason, action, observe) # 3 闭包
  → ReActEngine.run(ctx)                     # 687 LOC 通用循环
      → for round in max_rounds: ...         # 12 步
  → AsyncIterator[dict] → SSE
```

**重构目标**: 1 个 ChatRunner 取代 4 个抽象.

---

## 2. 新 ChatRunner 架构

### 2.1 单一类

```python
class ChatRunner:
    """Unified chat agent loop. Replaces ChatReActBridge + ReActEngine
    + ChatReActBridge's state dataclass with one self-contained class.
    """
    
    def __init__(
        self,
        chat_service: Any,
        tool_executor: Any,
        prompt_builder: PromptBuilder,
        config: dict | None = None,
        hook: AgentHook | None = None,
    ) -> None: ...
    
    async def run_stream(
        self, spec: ChatRunSpec,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming events (SSE-compatible)."""
    
    async def run_to_completion(
        self, spec: ChatRunSpec,
    ) -> ChatRunResult:
        """Drain the iterator and return a result."""
```

### 2.2 内部状态机 (5 步, 简化自 12 步)

```
┌─────────────────────────────────────────────────────────────────┐
│  5 步循环 (vs 当前 12 步)                                        │
├─────────────────────────────────────────────────────────────────┤
│  1. PRECHECK  timeout / cancel / done_condition                  │
│  2. REASON    LLM.stream_chat(messages, tools)                   │
│               ├─ text-mode [TOOL_CALL] 解析                      │
│               ├─ truncation (chat._truncate_messages)            │
│               └─ emit message_delta / thinking / tool_call_start │
│  3. ACT       for tool_call in tool_calls:                       │
│               ├─ microcompact (default ON)                       │
│               ├─ ToolExecutor.execute                            │
│               ├─ DB persist (original)                           │
│               ├─ observation generation                          │
│               └─ conversation_messages.append (compacted)         │
│  4. OBSERVE   aggregate observations → summary                   │
│  5. COMPLETE  emit done / error / confirmation_required          │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 数据流 (新)

```
Orchestrator.chat(message, ...)
    ↓ ChatRunSpec
ChatRunner.run_stream(spec)
    ↓
PromptBuilder.build_with_context(ctx)    ← Step 3 已建
    ↓ system_prompt
for round in spec.max_iterations:
    ↓
    1. PRECHECK: timeout/cancel/done?
    ↓
    2. REASON: LLM.stream_chat(messages, tools)
        ↓ for each delta
        emit message_delta / thinking
        ↓
        text-mode parser → tool_calls[]
        emit tool_call_start (if any)
    ↓
    if tool_calls:
        3. ACT: for each tool_call:
            ↓
            microcompact(result) → content
            ↓
            tool_executor.execute(tool_name, args)
            ↓
            db.log_tool_call (original)
            ↓
            observation = summarize(result, tool_name)
            ↓
            conversation_messages.append(tool_msg with compacted content)
            emit tool_call_end
        ↓
        4. OBSERVE: aggregate observations
        ↓
    else:
        break
    ↓
    5. emit round_complete
    ↓
5. COMPLETE: emit done / error
    ↓
yield events to SSE
```

### 2.4 内部状态 (1 个 dataclass, 替代 3 套)

```python
@dataclass(slots=True)
class _RunContext:
    spec: ChatRunSpec
    messages: list[dict[str, Any]]        # mutable conversation
    tools_used: list[str]
    usage: dict[str, int]
    observations: list[str]
    final_content: str | None = None
    stop_reason: str = "in_progress"
    error: str | None = None
    compacted_count: int = 0
    chars_saved: int = 0
    cancelled: bool = False
    paused: bool = False
    started_at: float = field(default_factory=time.monotonic)
```

替代: `ChatReActState` + `ReActConfig.initial_state` + `SkillContext` 三套

### 2.5 CompositeHook 深度集成 (13 钩子点)

```python
class ChatRunner:
    def __init__(self, ..., hook: AgentHook | None = None):
        self.hook = hook or NoOpHook()
    
    async def run_stream(self, spec):
        ctx = _RunContext(spec=spec, messages=list(spec.messages), ...)
        
        for iteration in range(spec.max_iterations):
            # Hook 1: before_iteration
            await self.hook.before_iteration(self._to_hook_ctx(ctx, iteration))
            
            # ... step 2-4 ...
            
            # Hook 2: on_stream (called inside REASON)
            # Hook 3: on_stream_end
            # Hook 4: emit_reasoning
            # Hook 5: emit_reasoning_end
            # Hook 6: before_execute_tools
            # Hook 7: after_tool_executed
            # Hook 8: on_tool_error
            # Hook 9: on_confirmation
            # Hook 10: after_iteration
            # Hook 11: finalize_content (pipeline)
            # Hook 12: on_error
            # Hook 13: wants_streaming
```

---

## 3. 与当前实现的对比

| 维度 | 当前 (3 组件) | 新 (1 ChatRunner) |
|------|----------------|-------------------|
| 总 LOC | 711 + 687 + 664 = 2062 | ~400 |
| 状态 dataclass | 3 套 (ChatReActState + ReActConfig + SkillContext) | 1 (_RunContext) |
| 循环步骤 | 12 (ReActEngine) | 5 (新设计) |
| Callback 闭包 | 3 (reason/action/observe) | 0 (直接方法) |
| 钩子点 | 7 (ReActEngine) | 13 (AgentHook) |
| microcompact | patch 在 chat_react.py:612 | 原生 step 3 ACT |
| CompositeHook 集成 | 无 (Step 1 才加) | 深度集成 (Step 1 完成) |
| 测试 LOC | 805 + 918 = 1723 | ~400 (新测试) |
| 公共 API | 4 个类协作 | 1 个 ChatRunner.run_*() |

---

## 4. 迁移路径 (5 子步, 1 周)

### Step B-1 (今天): 设计文档 + 骨架

- [x] 写 `docs/poc/plan-b-refactor.md` (本文)
- [ ] 创建 `apps/chat/agent/runner_v2.py` 骨架 (~50 LOC)
  - ChatRunnerV2 class, 5 step methods (stub)
  - `_RunContext` dataclass
  - 公共 API: `run_stream`, `run_to_completion`
- [ ] 编译通过, 基础测试 1 case

**风险**: 0 (纯新增, 不改任何现有代码)
**Commit**: `refactor(agent): 新增 ChatRunner v2 骨架 (Plan B B-1)`

### Step B-2 (2 天): 核心循环

- [ ] 实现 5 步方法 (REASON / ACT / OBSERVE 等)
- [ ] 集成 CompositeHook (13 钩子点)
- [ ] 集成 microcompact (原生, 不 patch)
- [ ] 集成 text-mode tool parser
- [ ] 集成 LLM retry (chat._llm_stream_with_retry)
- [ ] 集成 DB persist + observation

**风险**: 中 (逻辑复杂, 需谨慎)
**测试**: ~15 cases (run_stream 事件流, 5 步覆盖, hook 触发)
**Commit**: `feat(agent): ChatRunner v2 核心循环 (Plan B B-2)`

### Step B-3 (1 天): 新测试 + 兼容性

- [ ] 写 `tests/test_apps_chat_agent_runner_v2.py` (~400 LOC, 25 cases)
- [ ] 验证 ChatRunnerV2 与现有 chat 行为一致 (golden test)
- [ ] 跑现有 805+918 react tests 不破坏

**风险**: 低 (新代码独立测试)
**Commit**: `test(agent): ChatRunner v2 测试 + 黄金对比 (Plan B B-3)`

### Step B-4 (1 天): 迁移 Orchestrator

- [ ] `orchestrator.py` 改为使用 ChatRunnerV2
- [ ] 保留 ChatReActBridge 作为回退 (deprecated)
- [ ] 跑 SSE integration test
- [ ] 手动验证: 启动 server, 浏览器 chat

**风险**: 中 (改动核心调用链)
**Commit**: `refactor(agent): Orchestrator 迁移到 ChatRunner v2 (Plan B B-4)`

### Step B-5 (1 天): 清理旧代码

- [ ] 标记 ChatReActBridge / ReActEngine 为 deprecated
- [ ] 删除 `chat_legacy/engine.py` v0.41 archive 的 `_action_incomplete`
- [ ] 重写 react tests 用 ChatRunnerV2 API (805+918 → ~300 LOC)
- [ ] 跑全量回归 (≥ 200 tests)

**风险**: 高 (大文件删除)
**Commit**: `refactor(agent): 删除 chat_react.py + react_engine.py, 重写测试 (Plan B B-5)`

---

## 5. 验收标准 (5 步全完成)

- [ ] ruff clean 全项目
- [ ] pytest 全量 ≥ 200 passed (含新 25 cases)
- [ ] chat_react.py / react_engine.py 已删 (B-5)
- [ ] ChatRunnerV2 单一类, ≤ 500 LOC
- [ ] microcompact 默认 ON
- [ ] CompositeHook 13 钩子点全覆盖
- [ ] SSE 事件 vocabulary 100% 兼容
- [ ] 启动 server, 浏览器验证 chat 正常

---

## 6. 不在本次范围

- A2 (vendor api/server.py) — OpenAI 兼容
- A1 (WebSocket vendor) — 按需
- A4 (bus+session) — 风险高
- Skills 概念迁移 — 不可移植
- DB schema 变更 — v0.41 之后

---

## 7. 待用户决策

1. **是否同意 5 子步迁移路径?**
2. **Step B-1 (今天) 先做骨架还是先做完整实现?**
3. **B-5 重写 805+918 LOC 测试** — 是否拆成多个 sub-PR?
4. **如果中途发现 RunnerV2 不够好** — 保留旧路径的回滚方案?

---

## 8. 风险登记

| 风险 | 缓解 |
|------|------|
| 805+918 测试重写引入回归 | B-3 用 golden test 行为对拍; B-4 跑全量回归 |
| 5 步状态机覆盖不到 corner case | B-2 测试矩阵 ≥ 15 cases; B-3 加 10 case 边界 |
| microcompact 默认 ON 改变现有行为 | B-2 保留 `microcompact=False` 关闭路径 |
| 旧 archive 引用 (chat_legacy/) 未清理 | B-5 统一清理; 不删 archive 本身 (AGENTS.md 规约) |
| Orchestrator 改调用链破坏 SSE 兼容 | B-4 跑 SSE integration test; 保留 ChatReActBridge 1 周 |
