# Phase A 实施步骤 (Progress Doc)

> 开始: 2026-06-17
> 范围: 借鉴 nanobot 设计, 解决 llmwikify chat agent 内部耦合
> 总产出: ~600 LOC 新增, 38 tests, 3 commits

---

## 0. 关键前置发现 (修改原计划)

| 发现 | 影响 |
|------|------|
| **`apps/agent/hooks.py` 已有 CompositeHook** (167 LOC, 零引用) | Step 1 改为 **revive + 现代化**, 不是新建 |
| **conversation_messages** 是 chat_react.py 内的累加器 | Runner 抽象就是替换这个累加器 |
| **event_log.log()** 是当前唯一的"hook-like"调用 | Step 1 优先替代这个 |
| **microcompact 默认改为 ON** (用户决定) | spec.microcompact=True |
| **现有 805+918 LOC 测试** for react_engine/react_loop | Runner 改造时需保留兼容 |

---

## 1. 总览

### 1.1 目标

- 借鉴 nanobot AgentHook + AgentRunner 设计模式
- 不 vendor nanobot 代码 (避免 loguru 等依赖)
- 重用现有 `apps/agent/hooks.py` 孤儿 CompositeHook
- 解决当前 chat_react.py 711 LOC 内嵌循环

### 1.2 三步骤总览

```
Step 1: CompositeHook 现代化    80 LOC  10 tests    2 天
  ├─ Move apps/agent/hooks.py → foundation/callback/composite.py
  ├─ 扩展: 9 hooks (加 streaming/reasoning/finalize)
  ├─ 新增: AgentHookContext dataclass
  └─ 同 P2-3 一并解决 (删除孤儿)

Step 2: ChatRunner 独立化        180 LOC  20 tests   3 天
  ├─ 新建: apps/chat/agent/runner.py
  ├─ ChatRunSpec / ChatRunResult dataclass
  ├─ 抽取: chat_react.py 内嵌 while 循环
  ├─ 集成: microcompact (默认 ON)
  └─ 重构: ChatReActBridge 减 ~200 LOC

Step 3: PromptBuilder 抽取       300 LOC  8 tests    2 天
  ├─ 提升: apps/chat/agent/prompt_builder.py → 独立类
  ├─ 拆分: 7 sections (identity/bootstrap/tool/memory/skills/react/history)
  ├─ 新增: AGENTS.md bootstrap 读取 (复用项目根)
  └─ Orchestrator 减 ~150 LOC

总计: ~560 LOC 新增 + ~350 LOC 抽取, 净增 ~210 LOC, 38 tests
```

### 1.3 现有状态

- `apps/agent/hooks.py`: 167 LOC orphan (已 grep 验证零引用)
- `apps/chat/agent/chat_react.py`: 711 LOC, 内嵌 while 循环
- `apps/chat/agent/orchestrator.py`: 664 LOC, 含 prompt 构造
- `apps/chat/agent/prompt_builder.py`: 150 LOC, 半内嵌
- `apps/chat/agent/react_engine.py`: 687 LOC, 通用 ReAct
- `tests/test_apps_chat_agent_*`: 4 文件, 共 2208 LOC (含 805 + 918 大测试)

---

## 2. Step 1: CompositeHook 现代化

### 2.1 目标

将孤儿 `apps/agent/hooks.py` 移到 `foundation/callback/composite.py`, 扩展到 9 钩子点, 加 AgentHookContext.

### 2.2 现状对照

| 维度 | 现有 (apps/agent/hooks.py) | 目标 (foundation/callback/composite.py) |
|------|---------------------------|-----------------------------------------|
| 基类 | `Hook` (6 方法) | `AgentHook` (9 方法, 默认 no-op) |
| Composite | `CompositeHook` (fan-out + try/except) | 保留 + 改进 (隔离日志结构化) |
| Context | 无 | 新增 `AgentHookContext` (slots dataclass) |
| 错误隔离 | log.warning | 保留 + 可配置 (log or raise) |
| WikiHook | 已实现 | 移到 `integrations/wiki.py` (sub-module) |
| DreamSyncHook | 已实现 | 移到 `integrations/dream.py` |
| AutoIngestHook | 已实现 | 移到 `integrations/auto_ingest.py` |
| 入口 | 零引用 | `Orchestrator` 优先接入 event_log |

### 2.3 文件变更

| 操作 | 文件 | LOC |
|------|------|-----|
| 新建 | `src/llmwikify/foundation/callback/__init__.py` | 5 |
| 新建 | `src/llmwikify/foundation/callback/composite.py` | 80 |
| 新建 | `src/llmwikify/foundation/callback/context.py` | 30 |
| 新建 | `src/llmwikify/foundation/callback/integrations/__init__.py` | 5 |
| 新建 | `src/llmwikify/foundation/callback/integrations/wiki.py` | 25 |
| 新建 | `src/llmwikify/foundation/callback/integrations/dream.py` | 35 |
| 新建 | `src/llmwikify/foundation/callback/integrations/auto_ingest.py` | 35 |
| 新建 | `tests/test_foundation_callback_composite.py` | 150 (10 cases) |
| 删除 | `src/llmwikify/apps/agent/hooks.py` | -167 (P2-3 一并) |

**净增**: 198 LOC 新增 - 167 删除 = **+31 LOC**

### 2.4 9 钩子点设计 (扩展自 nanobot)

```
生命周期阶段 → 钩子点
─────────────────────────────────────────
iteration start    → before_iteration(ctx)
stream start       → wants_streaming() → bool
stream chunk       → on_stream(ctx, delta)
stream end         → on_stream_end(ctx, *, resuming)
reasoning chunk    → emit_reasoning(content)
reasoning end      → emit_reasoning_end()
tool execution     → before_execute_tools(ctx)
                    → after_tool_executed(ctx, tool_call, result) [新增]
                    → on_tool_error(ctx, tool_call, error) [新增]
confirmation       → on_confirmation(ctx, tool_call)
iteration end      → after_iteration(ctx)
finalize           → finalize_content(ctx, content) → str [pipeline]
error              → on_error(ctx, error)
─────────────────────────────────────────
共 13 钩子点 (略多于 nanobot 的 9, 多 4 个 error/confirmation 类)
```

### 2.5 AgentHookContext dataclass

```python
@dataclass(slots=True)
class AgentHookContext:
    iteration: int
    messages: list[dict[str, Any]]
    response: Any | None = None
    usage: dict[str, int] = field(default_factory=dict)
    tool_calls: list[Any] = field(default_factory=list)
    tool_results: list[Any] = field(default_factory=list)
    tool_events: list[dict[str, str]] = field(default_factory=list)
    streamed_content: bool = False
    streamed_reasoning: bool = False
    final_content: str | None = None
    stop_reason: str | None = None
    error: str | None = None
```

### 2.6 测试矩阵 (10 cases)

| # | 测试 | 验证 |
|---|------|------|
| 1 | 默认 AgentHook (no-op) | 9 方法调用不抛错 |
| 2 | CompositeHook fan-out | 3 hooks 都被调用 |
| 3 | 单 hook 抛错 | 其他 hook 仍执行 |
| 4 | fire_pre_run 顺序 | FIFO |
| 5 | AgentHookContext 修改可见 | mutable state 共享 |
| 6 | WikiHook / DreamSyncHook / AutoIngestHook 实例化 | 不抛错 |
| 7 | add / remove by name | 注册表正确 |
| 8 | 空 hooks CompositeHook | fan-out 安全 |
| 9 | 同步钩子抛错隔离 | RuntimeError 不影响 |
| 10 | 异步钩子支持 (预留 async 接口) | 无 await 但签名兼容 |

### 2.7 验收

- [ ] ruff check foundation/callback clean
- [ ] pytest test_foundation_callback_composite.py 10/10 passed
- [ ] pytest 全量 (不破坏现有 28 callback)
- [ ] apps/agent/hooks.py 已删 (P2-3 完成)
- [ ] grep "from apps.agent.hooks" 仍 0 引用
- [ ] Commit: `feat(callback): 迁移并现代化 CompositeHook 抽象`

### 2.8 Status

- [ ] 完成

---

## 3. Step 2: ChatRunner 独立化 (含 microcompact)

### 3.1 目标

将 `chat_react.py` 内嵌的 while 循环抽取为独立的 `ChatRunner`, 支持 microcompact 默认开启.

### 3.2 现状对照

| 维度 | 现有 (chat_react.py) | 目标 (runner.py) |
|------|----------------------|------------------|
| 循环位置 | `ChatReActBridge.run()` 内嵌 | `ChatRunner.run(spec)` |
| 输入 | dict config (散落) | `ChatRunSpec` dataclass |
| 输出 | AsyncIterator[dict] (SSE 耦合) | `ChatRunResult` dataclass |
| Hook | 无 | `AgentHook` (Step 1 集成) |
| 微压缩 | 无 (截断 max_tool_result_chars) | **microcompact 默认 ON** |
| 可测性 | 必须 mock FastAPI + SSE | 纯函数式, 可直接 unit test |

### 3.3 文件变更

| 操作 | 文件 | LOC |
|------|------|-----|
| 新建 | `src/llmwikify/apps/chat/agent/runner.py` | 180 |
| 新建 | `src/llmwikify/apps/chat/agent/spec.py` | 60 (dataclasses) |
| 改 | `src/llmwikify/apps/chat/agent/chat_react.py` | -200 LOC (重构) |
| 改 | `src/llmwikify/apps/chat/agent/orchestrator.py` | +30 LOC (构造 Runner) |
| 新建 | `tests/test_apps_chat_agent_runner.py` | 250 (20 cases) |

**净增**: 320 LOC

### 3.4 ChatRunSpec 字段 (含 microcompact 默认 ON)

| 分组 | 字段 | 默认 |
|------|------|------|
| 必需 | messages, tools, model | — |
| 循环 | max_iterations | 40 |
| 循环 | max_tool_result_chars | 50000 |
| LLM | temperature, max_tokens, reasoning_effort | None |
| 工作区 | workspace, session_key, context_window_tokens | None |
| **钩子** | **hook: AgentHook** | **None** |
| 回调 | progress_callback, retry_wait_callback | None |
| 错误 | error_message, fail_on_tool_error | — |
| **微压缩** | **microcompact** | **True** ← **ON!** |
| **微压缩** | **microcompact_keep_chars** | **1000** |
| **微压缩** | **microcompact_compactable_tools** | **frozenset({read_file, exec, grep, find_files, web_search, web_fetch, list_dir})** |

### 3.5 microcompact 默认 ON 的影响

```
原行为: tool_result > 50000 chars → 截断
新行为: tool_result > 1000 chars + 工具 eligible → 微压缩 + 缓存原始

例:
  read_file("/var/log/syslog", 50000 chars)
  → marker: "[Tool result compacted] Tool: read_file Original: 50000 Kept: 1000 ID: tc_xxx"
  → spec._compacted_results["tc_xxx"] = 完整 50000 chars (per-run 内存)

LLM 看不到 50000 chars, 仅看到 marker (≈200 chars)
Token 节省: ~99%
```

**安全性**:
- `max_tool_result_chars=50000` 仍是最后防线
- 默认 compactable_tools 已排除 write_file/edit_file (小返回)
- per-run 缓存, run 结束即 GC, 无内存泄漏

### 3.6 数据流

```
ChatReActBridge 构造 ChatRunSpec
    ↓
ChatRunner.run(spec)  [新建]
    ↓
Hook.before_iteration(ctx)
    ↓
while iteration < spec.max_iterations:
    ↓
    response = LLM.stream_chat(messages, tools, ...)
    ↓
    Hook.on_stream(ctx, delta)  ← 流式
    ↓
    if not response.tool_calls:
        break
    ↓
    Hook.before_execute_tools(ctx)
    ↓
    for tool_call in response.tool_calls:
        ↓
        result = ToolExecutor.execute(tool_call)
        ↓
        ─── microcompact 分支 (默认 ON) ───
        if (spec.microcompact
            AND tool_call.name in spec.microcompact_compactable_tools
            AND len(result) > spec.microcompact_keep_chars):
            ↓
            spec._compacted_results[tool_call.id] = result
            result = build_marker(...)
            ctx.tool_events.append({"name": tool_call.name, "compacted": True})
        ↓
        if len(result) > spec.max_tool_result_chars:
            result = truncate(result, spec.max_tool_result_chars)
        ↓
        messages.append(tool_message(result))
    ↓
    Hook.after_iteration(ctx)
    ↓
final = Hook.finalize_content(ctx, response.content)
    ↓
return ChatRunResult(final_content=final, messages, tools_used, usage, stop_reason, error)
```

### 3.7 测试矩阵 (20 cases, 含 5 个 microcompact)

| # | 测试 | 验证 |
|---|------|------|
| 1 | 单次迭代无工具 | final_content + stop_reason=completed |
| 2 | 多次迭代有工具 | messages 含 tool result |
| 3 | max_iterations 截断 | stop_reason=max_iterations |
| 4 | 工具抛错 | error 字段, 不中断 |
| 5 | LLM 抛错 | stop_reason=error |
| 6 | Hook fan-out 触发 | 9 方法按生命周期 |
| 7 | Hook 抛错隔离 | 不影响 Runner 主循环 |
| 8 | 工具结果超长截断 | max_tool_result_chars 兜底 |
| 9 | 并发工具执行 | asyncio.gather |
| 10 | 温度/最大 token 透传 | LLM 收到正确参数 |
| 11 | 空 messages | ValueError |
| 12 | 缺少必需字段 | dataclass 校验 |
| 13 | finalize_content pipeline | 后者处理前者输出 |
| 14 | 用量累计 | multi-iteration usage 累加 |
| 15 | 重入安全 | 2 个并发 run 互不干扰 |
| **16** | **microcompact 默认 ON + 大 result + compactable** | **替换 marker, _compacted_results 缓存** |
| **17** | **microcompact ON + non-compactable tool** | **走 max_tool_result_chars 截断** |
| **18** | **microcompact ON + 小 result (≤keep_chars)** | **原样保留** |
| **19** | **marker 元数据正确** | **含 tool_name + 长度 + id** |
| **20** | **microcompact=False 关闭** | **走截断, 不缓存** |

### 3.8 验收

- [ ] ruff check clean
- [ ] pytest test_apps_chat_agent_runner.py 20/20 passed
- [ ] pytest 全量 (805+918 react tests 不破坏)
- [ ] ChatReActBridge LOC 从 711 → ≤500
- [ ] microcompact 默认值 = True
- [ ] Commit: `feat(agent): 抽取 ChatRunner 独立化, 含 microcompact 默认开启`

### 3.9 Status

- [ ] 完成

---

## 4. Step 3: PromptBuilder 抽取

### 4.1 目标

将 `prompt_builder.py` 提升为独立类, 拆分为 7 sections, 新增 AGENTS.md bootstrap 读取.

### 4.2 现状对照

| 维度 | 现有 (prompt_builder.py 内嵌) | 目标 (独立类) |
|------|-------------------------------|---------------|
| 类层级 | 半内嵌于 Orchestrator | 完全独立 |
| Sections | 拼接逻辑分散 | 7 个 _get_xxx 方法 |
| Bootstrap | 无 | AGENTS.md/SOUL.md/USER.md |
| Cache | 无 | mtime-based 5 分钟 |
| 降级 | 无 | try/except per section |

### 4.3 文件变更

| 操作 | 文件 | LOC |
|------|------|-----|
| 改 | `src/llmwikify/apps/chat/agent/prompt_builder.py` | 150 → 300 |
| 改 | `src/llmwikify/apps/chat/agent/orchestrator.py` | -150 LOC (调用改为 PromptBuilder.build) |
| 新建 | `tests/test_apps_chat_agent_prompt_builder.py` | 120 (8 cases) |

**净增**: 120 LOC (含测试)

### 4.4 7 Sections 装配顺序

```
[1] Identity         workspace path, OS, Python ver        [必选]
[2] Bootstrap        AGENTS.md / SOUL.md / USER.md          [可选, mtime cache]
[3] Tool Contract    ReAct rules + 工具名列表                [必选]
[4] Memory           MEMORY.md 摘要                          [可选, from memory_manager]
[5] Skills Summary   always-loaded + index                  [必选]
[6] ReAct Prompt     REACT_SYSTEM_PROMPT                     [必选, 常量]
[7] Recent History   last 50 messages, cap 32k chars         [可选]
```

### 4.5 BuildContext dataclass

```python
@dataclass(slots=True)
class BuildContext:
    channel: str
    workspace: Path | None
    session_summary: str | None
    always_skills: list[str]
    exclude_skills: set[str]
    timezone: str | None
    enable_bootstrap: bool = True
```

### 4.6 测试矩阵 (8 cases)

| # | 测试 | 验证 |
|---|------|------|
| 1 | 完整 ctx → 7 sections | 输出包含所有段 |
| 2 | 缺 AGENTS.md | bootstrap 为空, 不抛错 |
| 3 | memory 为占位符 | 过滤 |
| 4 | always_skills 注入 | section 含完整内容 |
| 5 | history 超 32k | 截断 |
| 6 | section 抛错降级 | 单 section 失败不影响其他 |
| 7 | build_minimal_prompt | 仅 3 sections |
| 8 | enable_bootstrap=False | bootstrap 跳过 |

### 4.7 验收

- [ ] ruff check clean
- [ ] pytest 8/8 passed
- [ ] 全量 pytest 不破坏
- [ ] PromptBuilder 可独立 import 测试
- [ ] Commit: `refactor(agent): 抽取 PromptBuilder 为独立类, 加 7 sections + bootstrap`

### 4.8 Status

- [ ] 完成

---

## 5. 三步协作总览

```
Orchestrator (664 → ~450 LOC)
    ↓
    ├─ PromptBuilder.build(ctx)              ← Step 3
    │       ↓ system_prompt (7 sections)
    ├─ ChatReActBridge.build_spec(...)
    │       ↓ ChatRunSpec (含 microcompact=True)
    ├─ ChatRunner.run(spec)                  ← Step 2
    │       ↓ for each iteration:
    │           CompositeHook.before_iteration(ctx)   ← Step 1
    │               ├─ LoggingHook
    │               ├─ MetricsHook
    │               └─ WikiHook (revived)
    │           ↓
    │           LLM.stream_chat(...)
    │               ↓ delta
    │           CompositeHook.on_stream(ctx, delta)
    │               └─ UIStreamHook → SSE yield
    │           ↓
    │           if tool_calls:
    │               CompositeHook.before_execute_tools
    │                   └─ PersistHook → db.log_tool_call
    │               ↓
    │               for tool_call:
    │                   ToolExecutor.execute(...)
    │                   ↓
    │                   microcompact (默认 ON)
    │                       └─ marker 替换 + 缓存
    │                   ↓
    │                   max_tool_result_chars (兜底)
    │           ↓
    │           CompositeHook.after_iteration
    │       ↓
    │   ChatRunResult
    ↓
SSE events → frontend
```

---

## 6. 整体验收

### 6.1 自动化

- [ ] ruff check src/llmwikify/foundation/callback clean
- [ ] ruff check src/llmwikify/apps/chat/agent clean
- [ ] pytest tests/test_foundation_callback_composite.py 10/10
- [ ] pytest tests/test_apps_chat_agent_runner.py 20/20
- [ ] pytest tests/test_apps_chat_agent_prompt_builder.py 8/8
- [ ] pytest 全量 (≥ 200 + 38 = 238 cases)
- [ ] grep "from apps.agent.hooks" → 0 matches (orphan 已删)

### 6.2 手动

- [ ] 启动 server, curl /api/health
- [ ] 浏览器发起 chat, 验证 SSE 正常
- [ ] 大文件 read_file 调用, 验证 marker 注入 (看 logs)
- [ ] metrics: microcompact 节省 token 数 (从 logs)

### 6.3 提交记录

```
2c59227 feat(llm): 借鉴 nanobot v0.2.1 模式至 streamable.py
???     feat(callback): 迁移并现代化 CompositeHook 抽象           ← Step 1
???     feat(agent): 抽取 ChatRunner 独立化, 含 microcompact 默认开启  ← Step 2
???     refactor(agent): 抽取 PromptBuilder 为独立类, 加 7 sections    ← Step 3
```

---

## 7. 风险登记

| 风险 | 缓解 |
|------|------|
| **microcompact 默认 ON 可能改变现有 chat 行为** | 先在 test 环境跑 24h, 比对 token 用量 |
| **CompositeHook revive 后, 历史代码可能引用了旧路径** | grep 已确认 0 引用 |
| **chat_react.py 重构可能破坏 805+918 测试** | 保留 ChatReActBridge 公共 API, 仅内部实现替换 |
| **AGENTS.md bootstrap 读取可能引入敏感信息泄漏** | 仅读项目根, 不读 ~/.ssh 等敏感路径 |
| **per-run _compacted_results 占用大内存** | spec lifetime = 1 run, 自动 GC |

---

## 8. 待用户决策

1. **Step 1 是否先做?** (最小, 风险最低)
2. **Step 1 + Step 2 一并做?** (2 步绑定, 中等)
3. **Step 1 + Step 2 + Step 3 全部?** (完整 Phase A, 1 周)
4. **仅做 P2 清理先?** (10 unstaged 文件先 commit)

**当前决定**: 用户已说 "开始改造", 默认 Step 1 → Step 2 → Step 3 顺序, 每步单独 commit.
