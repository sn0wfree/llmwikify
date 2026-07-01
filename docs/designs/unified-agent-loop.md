# Unified Agent Loop 设计文档

> 日期：2026-06-26
> 状态：设计完成（v2），待实施
> 作者：基于 llmwikify 团队讨论

---

## 背景

llmwikify 有三套独立的 agent 系统：

| 系统 | 文件 | 用途 |
|---|---|---|
| **Chat Agent** | `apps/chat/agent/runner_v2.py` (918 行) | Wiki QA、研究、因子讨论 |
| **Codegen Agent** | `reproduction/codegen/react_engine.py` (476 行) | LLM 生成因子代码 |
| **Research Agent** | `apps/chat/agent/research_runner.py` (431 行) | 自动化研究流程 |

三套系统各自实现 ReAct 循环，状态机、Hook 系统、消息格式、事件类型全部不兼容。

### 原始问题

1. Chat Agent 用 OpenAI function-calling，Codegen Agent 用 raw text，**无法共享工具**
2. OperatorLookupTool（162 个算子查询）只能在 Chat Agent 中使用，**Codegen 无法访问**
3. 新增 agent 模式需要从零实现整套循环，**扩展困难**
4. 三套 Hook 系统（AgentHook 13 点 / ReactConfig 7 hooks / progress_callback），**维护成本高**

### 讨论过程

1. **run_101_alphas 优化**：删除 IC 双重提取（#5）+ df_pl 预构建复用（#6）→ commit `f590a97`
2. **OperatorLookupTool 集成**：创建 QuantToolAdapter，注册到 CompositeToolRegistry → commit `244f0ec`
3. **状态机对比分析**：Chat 5步 vs Codegen 4步 vs Research 5步，差异在 DECIDE/PERSIST/FINALIZE
4. **统一架构设计**：策略模式（Reasoner / Actor / Decider）+ 统一循环
5. **设计评审**：修 God Object / 流式 / OBSERVE / DECIDE / Hook 问题
6. **StepHandler 抽象**：统一接口 + Pipeline 组合 + 预置 Steps + 注册表
7. **评审修正**：正视 Chat/Codegen 复杂度差异，引入 StreamingHandler

---

## 设计目标

1. **一套循环**：`UnifiedAgentLoop` 替代三套独立循环
2. **自由组合**：Reasoner + Actor + Decider 可任意拼装
3. **流式支持**：Chat 的 LLM streaming 不降级
4. **向后兼容**：旧代码改为 delegate，测试不动
5. **易于扩展**：新增无状态 mode ~10 行，有状态 mode ~80 行
6. **正视差异**：不强行统一不兼容的接口，承认两种 handler 类型

---

## 架构

### 核心抽象：两种 handler 类型

```
StepHandler（无状态、单次调用、单次返回）
  → Pipeline（串行组合）
  → CodegenReasoner / CodeActor / Deciders / 共享组件

StreamingHandler（有状态、流式、多次 yield）
  → ChatReasoner（内部用 TextModeParser）
  → ToolActor（内部用 microcompact 双输出）

UnifiedAgentLoop 统一编排两种 handler
```

**为什么两种？**

| 组件 | 行为 | 适合 |
|---|---|---|
| LLMCallStep (sync) | 调一次返回一次 | StepHandler ✅ |
| ExtractCodeStep | 调一次返回一次 | StepHandler ✅ |
| ValidateSyntaxStep | 调一次返回一次 | StepHandler ✅ |
| CheckFieldStep | 调一次返回一次 | StepHandler ✅ |
| TextModeParser | **有状态，流式，多次输出** | StreamingHandler ✅ |
| microcompact | **双输出**（压缩给 LLM，原始给前端） | StreamingHandler ✅ |

强行把 TextModeParser 装进步骤接口 = 用杯子装水龙头。

### 目录结构

```
src/llmwikify/apps/chat/agent/unified/
├── __init__.py
├── core.py              # StepHandler + StreamingHandler + StepResult + Pipeline + UnifiedContext + UnifiedHook
├── spec.py              # BaseSpec / ChatSpec / CodegenSpec / ReasonResponse / ActResult / UnifiedResult
├── loop.py              # UnifiedAgentLoop（编排两种 handler + run_to_completion + execution_context）
├── registry.py          # AgentModeConfig + register_mode + create_agent_loop
├── hook_adapter.py      # AgentHookAdapter（13 点完整映射）
│
├── steps/               # 15 个无状态 Steps（StepHandler）
│   ├── __init__.py
│   ├── llm.py           # LLMCallStep + ExtractJSONStep
│   ├── code.py          # ExtractCodeStep + ValidateSyntaxStep + ValidateSafetyStep
│   │                    # + ExecuteCodeStep + ValidateAndExecuteStep + CodeExecResult
│   ├── feedback.py      # BuildFeedbackStep + TruncateStep
│   ├── checks.py        # CheckFieldStep + CheckEmptyStep + CheckToolCallsStep + CheckSuccessStep
│   └── transforms.py    # MapStep + WrapStep
│
├── handlers/            # 有状态 Handlers（StreamingHandler）
│   ├── __init__.py
│   ├── chat_reasoner.py # ChatReasoner（内部 TextModeParser + 流式 LLM）
│   └── tool_actor.py    # ToolActor（内部 microcompact 双输出）
│
├── pipelines/           # 无状态 Pipeline 组合（StepHandler）
│   ├── __init__.py
│   └── codegen.py       # CodegenReasoner(Pipeline) + CodeActor(StepHandler)
│
└── events.py            # 统一事件常量（合并 chat + research，re-export 兼容）
```

---

## 详细设计

### 1. 核心抽象（core.py）

#### StepResult — 统一的步骤输出

```python
@dataclass
class StepResult:
    output: Any = None
    events: list[dict] = field(default_factory=list)
    success: bool = True
    error: str | None = None

    @staticmethod
    def ok(output=None, events=None): ...
    @staticmethod
    def fail(error, events=None): ...
```

#### StepHandler — 无状态步骤接口

```python
class StepHandler(ABC):
    """无状态、单次调用的步骤。

    适用于：LLM 调用、代码提取、语法检查、字段检查、数据转换等。
    不适用于：流式解析、有状态循环、双输出。

    用法：
        step = ExtractCodeStep()
        result = await step.handle(llm_text, spec, ctx)
        # result.output = code str
    """
    @abstractmethod
    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        ...
```

#### StreamingHandler — 有状态流式接口

```python
class StreamingHandler(ABC):
    """有状态、流式的 handler。

    适用于：Chat Reasoner（TextModeParser 状态机）、Tool Actor（microcompact 双输出）。
    与 StepHandler 的区别：有生命周期，内部管理状态，yield 多次。

    用法：
        handler = ChatReasoner(chat_service)
        async for event in handler.stream(messages, spec, ctx):
            if isinstance(event, StepResult):
                response = event.output
            else:
                yield event  # 透传给 SSE
    """
    @abstractmethod
    async def stream(
        self, input: Any, spec: Any, ctx: Any,
    ) -> AsyncIterator[dict | StepResult]:
        """yield SSE events，最后一个 yield StepResult(output=结果)"""
        ...
        yield StepResult()  # pragma: no cover
```

#### Pipeline — Steps 串行组合

```python
class Pipeline(StepHandler):
    """步骤流水线 — 串行执行多个 StepHandler。

    上一个 step 的 output 作为下一个 step 的 input。
    任一 step 失败 → 整体失败（fail-fast）。
    events 累积。

    用法：
        pipeline = Pipeline(LLMCallStep(client), ExtractCodeStep())
        result = await pipeline.handle(messages, spec, ctx)
    """
    def __init__(self, *steps: StepHandler):
        self._steps = steps

    async def handle(self, input, spec, ctx):
        current = input
        all_events = []
        for step in self._steps:
            result = await step.handle(current, spec, ctx)
            all_events.extend(result.events)
            if not result.success:
                return StepResult.fail(result.error, all_events)
            current = result.output
        return StepResult.ok(current, all_events)
```

#### UnifiedHook — 统一 Hook 接口

```python
class UnifiedHook:
    """统一 hook 接口 — 所有 mode 共用。

    比 AgentHook 13 点更通用，适用于 Chat/Codegen/Research。
    AgentHook 通过 AgentHookAdapter 桥接到此接口。
    """
    def wants_streaming(self) -> bool:
        return False
    def before_iteration(self, ctx): pass
    def on_reason_start(self, ctx): pass
    def on_reason_end(self, ctx, response): pass
    def on_stream(self, ctx, delta): pass
    def emit_reasoning(self, ctx, content): pass
    def emit_reasoning_end(self, ctx): pass
    def on_act_start(self, ctx): pass
    def on_act_end(self, ctx, result): pass
    def after_tool_executed(self, ctx, tool_call, result): pass
    def on_tool_error(self, ctx, tool_call, error): pass
    def on_confirmation(self, ctx, tool_call): pass
    def on_observe(self, ctx): pass
    def on_error(self, ctx, error): pass
    def finalize(self, ctx, content): return content
    def after_iteration(self, ctx): pass
```

#### UnifiedContext — Loop 内部状态

```python
@dataclass
class UnifiedContext:
    spec: Any  # BaseSpec
    messages: list[dict] = field(default_factory=list)
    iteration: int = 0
    start_time: float = 0.0
    stop_reason: str = ""
    error: str | None = None
    final_content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    compacted_count: int = 0
    last_output: Any = None

    def __post_init__(self):
        if isinstance(self.spec, BaseSpec):
            self.messages = list(self.spec.messages)
        self.start_time = time.monotonic()

    @property
    def elapsed_sec(self) -> float:
        return time.monotonic() - self.start_time

    @property
    def tools(self) -> list[dict] | None:
        if hasattr(self.spec, "tool_registry") and self.spec.tool_registry:
            reg = self.spec.tool_registry
            if hasattr(reg, "get_tool_specs"):
                return reg.get_tool_specs()
        return None
```

### 2. 数据结构（spec.py）

#### Spec（继承，不用 God Object）

```python
@dataclass
class BaseSpec:
    messages: list[dict[str, Any]]
    max_iterations: int = 10
    timeout_seconds: float = 0
    temperature: float = 0.3

@dataclass
class ChatSpec(BaseSpec):
    tool_registry: Any = None
    session_id: str = ""
    wiki_id: str | None = None
    workspace: Any = None  # Path
    microcompact: bool = True
    microcompact_keep_chars: int = 1000
    microcompact_compactable_tools: frozenset[str] = frozenset()
    hook: Any | None = None  # AgentHook
    goal_active_predicate: Callable[[], bool] | None = None

@dataclass
class CodegenSpec(BaseSpec):
    df: Any = None  # pl.DataFrame
    factor_name: str = ""
    formula_brief: str = ""
    max_repair_rounds: int = 3
    system_prompt: str = ""
```

#### ReasonResponse — Reasoner 输出

```python
@dataclass
class ReasonResponse:
    raw_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # Chat 用
    code: str | None = None                                # Codegen 用
    action: str | None = None                              # Research 用
    thought: str = ""
    thinking: str = ""
    is_valid: bool = True
    error: str | None = None
```

#### ActResult — Actor 输出

```python
@dataclass
class ActResult:
    success: bool
    output: Any = None
    error: str | None = None
    error_kind: str = "none"
    tool_name: str = ""
    code: str = ""
    needs_confirmation: bool = False
    messages_to_inject: list[dict] = field(default_factory=list)
    tool_calls_for_next_round: list[dict] = field(default_factory=list)
```

#### UnifiedResult — Loop 最终输出

```python
@dataclass
class UnifiedResult:
    final_content: str | None = None
    code: str | None = None
    factor_series: Any = None
    stop_reason: str = "completed"
    error: str | None = None
    iterations: int = 0
    tools_used: list[str] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    state_trace: list[dict] = field(default_factory=list)
    elapsed_sec: float = 0.0
    compacted_count: int = 0
```

### 3. 预置 Steps（steps/）— 15 个无状态步骤

#### llm.py

```python
class LLMCallStep(StepHandler):
    """LLM 调用（同步模式）。

    输入: messages (list[dict])
    输出: raw response text (str)
    """
    def __init__(self, llm_client, max_retries=3): ...

class ExtractJSONStep(StepHandler):
    """从 LLM 响应提取 JSON。
    输入: text (str) → 输出: dict
    """
```

#### code.py

```python
@dataclass
class CodeExecResult:
    success: bool
    code: str = ""
    series: Any = None  # pl.Series
    error: str | None = None
    error_kind: str = "none"

class ExtractCodeStep(StepHandler):
    """从 LLM 响应提取 Python 代码。输入: text → 输出: code str"""

class ValidateSyntaxStep(StepHandler):
    """Python 语法检查。输入: code → 输出: code"""

class ValidateSafetyStep(StepHandler):
    """CodeSandbox 安全检查。输入: code → 输出: code"""

class ExecuteCodeStep(StepHandler):
    """执行 compute_factor 代码。输入: code → 输出: CodeExecResult
    从 spec 取 df (CodegenSpec.df)
    """

class ValidateAndExecuteStep(Pipeline):
    """代码验证+执行流水线。输入: code → 输出: CodeExecResult"""
    def __init__(self):
        super().__init__(ValidateSyntaxStep(), ValidateSafetyStep(), ExecuteCodeStep())
```

#### feedback.py

```python
class BuildFeedbackStep(StepHandler):
    """构建错误 feedback 消息。
    输入: CodeExecResult → 输出: message dict ({"role": "user", "content": ...})
    """

class TruncateStep(StepHandler):
    """截断文本。
    输入: text → 输出: text[:max_len]
    """
    def __init__(self, max_len: int = 600): ...
```

#### checks.py

```python
class CheckFieldStep(StepHandler):
    """通用字段检查 — Decider 基础组件。
    用法：CheckFieldStep(field="success", equals=True)
    输入: Any → 输出: (bool, str)
    """
    def __init__(self, field: str, equals: Any = True, stop_reason: str = ""): ...

class CheckEmptyStep(StepHandler):
    """检查列表/字段是否为空。
    输入: Any → 输出: (bool, str)
    """
    def __init__(self, field: str, stop_reason: str = ""): ...

class CheckToolCallsStep(StepHandler):
    """Decider: REASON 后检查 tool_calls。输入: ReasonResponse → (bool, str)"""

class CheckSuccessStep(StepHandler):
    """Decider: ACT 后检查 success。输入: ActResult → (bool, str)"""
```

#### transforms.py

```python
class MapStep(StepHandler):
    """转换 output。用法：MapStep(lambda r: ActResult(success=r.success))"""

class WrapStep(StepHandler):
    """包装 output 到指定类型。用法：WrapStep(ReasonResponse, code=lambda x: x)"""
```

### 4. 有状态 Handlers（handlers/）

#### chat_reasoner.py — ChatReasoner(StreamingHandler)

```python
class ChatReasoner(StreamingHandler):
    """Chat REASON: 流式 LLM 调用 + TextModeParser 解析。

    有状态：TextModeParser 内部维护 buffer。
    流式：逐 chunk yield MESSAGE_DELTA / THINKING events。
    输出：最后一个 yield StepResult(output=ReasonResponse)。

    构造时依赖：chat_service（LLM 客户端）、prompt_builder
    运行时依赖：从 ChatSpec 取 tool_registry, session_id 等
    """
    def __init__(self, chat_service, prompt_builder=None):
        self._chat_service = chat_service
        self._prompt_builder = prompt_builder

    async def stream(self, messages, spec, ctx):
        from llmwikify.apps.chat.agent.text_mode_tool import TextModeParser
        parser = TextModeParser()

        tool_calls = []
        accumulated = ""
        thinking = ""

        # 补充 system prompt
        if self._prompt_builder:
            messages = await self._inject_system_prompt(messages, spec)

        # 流式 LLM 调用
        async for raw_event in self._stream_llm(messages, spec):
            # TextModeParser 逐事件解析
            async for parsed in parser.feed(raw_event):
                kind = parsed["type"]
                if kind == "content":
                    accumulated += parsed["text"]
                    yield {"type": "message_delta", "content": parsed["text"]}
                elif kind == "thinking":
                    thinking += parsed["text"]
                    yield {"type": "thinking", "content": parsed["text"]}
                elif kind == "tool_call":
                    tool_calls.append(parsed)

        # flush
        for parsed in parser.flush():
            if parsed["type"] == "content":
                accumulated += parsed["text"]

        # 最终结果
        yield StepResult.ok(ReasonResponse(
            raw_content=accumulated,
            tool_calls=tool_calls,
            thinking=thinking,
        ))

    async def _stream_llm(self, messages, spec):
        """流式 LLM 调用 — 包装 runner_v2._stream_llm 逻辑"""
        ...

    async def _inject_system_prompt(self, messages, spec):
        """补充 system prompt — 包装 runner_v2._build_system_prompt"""
        ...
```

#### tool_actor.py — ToolActor(StreamingHandler)

```python
class ToolActor(StreamingHandler):
    """Chat ACT: 工具调度 + confirmation + microcompact。

    有状态：microcompact 在 spec._compacted_results 上产生副作用。
    双输出：compacted content → messages，original result → SSE events。
    流式：逐 tool yield TOOL_CALL_START / END / ERROR events。

    构造时依赖：tool_executor
    运行时依赖：从 ChatSpec 取 tool_registry, session_id, microcompact 配置
    """
    def __init__(self, tool_executor):
        self._executor = tool_executor

    async def stream(self, response, spec, ctx):
        from llmwikify.apps.chat.agent import events
        from llmwikify.apps.chat.agent.microcompact import microcompact_serialize

        messages_to_inject = []
        next_tool_calls = []
        tools_used = []
        compacted_count = 0

        for tc in response.tool_calls:
            tool_name = tc.get("name") or tc.get("tool", "")
            args = self._parse_args(tc)
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:8]}"

            if not tool_name:
                yield {"type": events.TOOL_CALL_ERROR, "tool": "", "error": "empty name"}
                continue

            yield {"type": events.TOOL_CALL_START, "tool": tool_name, "call_id": call_id}

            try:
                result = await self._execute_tool(tool_name, args, spec, ctx)
            except Exception as exc:
                yield {"type": events.TOOL_CALL_ERROR, "tool": tool_name, "error": str(exc)}
                continue

            # Confirmation check
            if isinstance(result, dict) and result.get("status") == "confirmation_required":
                yield StepResult(
                    output=ActResult(needs_confirmation=True, tool_name=tool_name),
                )
                return

            # microcompact — 双输出处理
            if self._should_compact(tool_name, spec):
                content, was_compacted, saved = microcompact_serialize(
                    result, tool_name, call_id, spec,
                )
                if was_compacted:
                    compacted_count += 1
                    yield {"type": events.COMPACTED, "tool": tool_name, "chars_saved": saved}
            else:
                content = json.dumps(result, ensure_ascii=False, default=str)

            # compacted content → messages
            messages_to_inject.append({
                "role": "tool", "name": tool_name,
                "content": content, "tool_call_id": call_id,
            })
            # original result → SSE event
            yield {"type": events.TOOL_CALL_END, "tool": tool_name, "result": result}
            tools_used.append(tool_name)

        yield StepResult.ok(ActResult(
            success=True,
            tool_calls_for_next_round=next_tool_calls,
            messages_to_inject=messages_to_inject,
        ))

    def _should_compact(self, tool_name, spec):
        return (getattr(spec, "microcompact", False)
                and tool_name in getattr(spec, "microcompact_compactable_tools", set()))

    def _parse_args(self, tc): ...
    async def _execute_tool(self, name, args, spec, ctx): ...
```

### 5. 无状态 Pipelines（pipelines/）

#### codegen.py

```python
class CodegenReasoner(Pipeline):
    """Codegen REASON: LLMCallStep(sync) + ExtractCodeStep → ReasonResponse"""
    def __init__(self, llm_client=None):
        from llmwikify.reproduction.codegen.llm_code import build_llm_client
        client = llm_client or build_llm_client()
        super().__init__(LLMCallStep(client), ExtractCodeStep())

    async def handle(self, input, spec, ctx):
        pipeline_result = await super().handle(input, spec, ctx)
        if not pipeline_result.success:
            return StepResult.ok(ReasonResponse(error=pipeline_result.error, is_valid=False))
        return StepResult.ok(ReasonResponse(code=pipeline_result.output, is_valid=True))

class CodeActor(StepHandler):
    """Codegen ACT: ValidateAndExecuteStep + BuildFeedbackStep"""
    def __init__(self):
        self._executor = ValidateAndExecuteStep()
        self._feedback = BuildFeedbackStep()

    async def handle(self, response, spec, ctx):
        if response.code is None:
            feedback = await self._feedback.handle(
                CodeExecResult(success=False, error="no code", error_kind="extract_failed"),
                spec, ctx,
            )
            return StepResult.ok(ActResult(
                success=False, error="no code", error_kind="extract_failed",
                messages_to_inject=[feedback.output] if feedback.output else [],
            ))

        exec_result = await self._executor.handle(response.code, spec, ctx)
        code_result = exec_result.output  # CodeExecResult

        if code_result.success:
            return StepResult.ok(ActResult(
                success=True, output=code_result.series, code=code_result.code,
            ))

        feedback = await self._feedback.handle(code_result, spec, ctx)
        return StepResult.ok(ActResult(
            success=False, error=code_result.error, error_kind=code_result.error_kind,
            code=code_result.code,
            messages_to_inject=[feedback.output] if feedback.output else [],
        ))
```

### 6. UnifiedAgentLoop（loop.py）

```python
class UnifiedAgentLoop(AgentRunner[BaseSpec, UnifiedResult]):
    """统一状态机。

    PRECHECK → [REASON → DECIDE① → ACT → DECIDE② → OBSERVE → DECIDE③] → FINALIZE

    REASON 和 ACT 可以是 StepHandler 或 StreamingHandler：
    - StepHandler: await handler.handle(input, spec, ctx) → StepResult
    - StreamingHandler: async for event in handler.stream(input, spec, ctx) → yield events + StepResult

    DECIDE 只用 StepHandler（简单判断，不需要流式）。
    """

    def __init__(
        self,
        reasoner: StepHandler | StreamingHandler,
        actor: StepHandler | StreamingHandler,
        deciders: dict[str, StepHandler],
        hook: UnifiedHook | None = None,
        precheck: Callable | None = None,
        finalize: Callable | None = None,
    ):
        self._reasoner = reasoner
        self._actor = actor
        self._deciders = deciders
        self._hook = hook or UnifiedHook()
        self._precheck = precheck
        self._finalize = finalize

    async def run_stream(self, spec: BaseSpec) -> AsyncIterator[dict]:
        ctx = UnifiedContext(spec=spec)

        try:
            for iteration in range(spec.max_iterations):
                ctx.iteration = iteration

                # ── PRECHECK ──
                if self._precheck and self._precheck(ctx):
                    yield {"type": "phase", "phase": "timeout"}
                    break

                await _maybe_await(self._hook.before_iteration(ctx))

                # ── REASON ──
                await _maybe_await(self._hook.on_reason_start(ctx))
                response = None

                if isinstance(self._reasoner, StreamingHandler):
                    async for event in self._reasoner.stream(ctx.messages, spec, ctx):
                        if isinstance(event, StepResult):
                            if not event.success:
                                ctx.error = event.error
                                yield {"type": "error", "message": event.error}
                                break
                            response = event.output
                        else:
                            yield event  # 透传流式 events
                    if ctx.error:
                        break
                else:
                    result = await self._reasoner.handle(ctx.messages, spec, ctx)
                    for ev in result.events:
                        yield ev
                    if not result.success:
                        ctx.error = result.error
                        yield {"type": "error", "message": result.error}
                        break
                    response = result.output

                if response is None:
                    yield {"type": "error", "message": "Reasoner returned no response"}
                    break

                await _maybe_await(self._hook.on_reason_end(ctx, response))

                # ── DECIDE after REASON ──
                if "after_reason" in self._deciders:
                    decide_result = await self._deciders["after_reason"].handle(response, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                # ── ACT ──
                await _maybe_await(self._hook.on_act_start(ctx))
                result = None

                if isinstance(self._actor, StreamingHandler):
                    async for event in self._actor.stream(response, spec, ctx):
                        if isinstance(event, StepResult):
                            if not event.success:
                                ctx.error = event.error
                                yield {"type": "error", "message": event.error}
                                break
                            result = event.output
                        else:
                            yield event  # 透传流式 events (TOOL_CALL_START/END 等)
                    if ctx.error:
                        break
                else:
                    act_result = await self._actor.handle(response, spec, ctx)
                    for ev in act_result.events:
                        yield ev
                    if not act_result.success:
                        ctx.error = act_result.error
                        yield {"type": "error", "message": act_result.error}
                        break
                    result = act_result.output

                if result is None:
                    yield {"type": "error", "message": "Actor returned no result"}
                    break

                await _maybe_await(self._hook.on_act_end(ctx, result))

                if result.needs_confirmation:
                    ctx.stop_reason = "confirmation_required"
                    yield {"type": "confirmation_required"}
                    break

                # ── DECIDE after ACT ──
                if "after_act" in self._deciders:
                    decide_result = await self._deciders["after_act"].handle(result, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                # ── OBSERVE ──
                for msg in result.messages_to_inject:
                    ctx.messages.append(msg)
                ctx.steps.append({"iteration": iteration, "result": result})
                ctx.tools_used.extend(getattr(result, "tools_used", []))
                await _maybe_await(self._hook.on_observe(ctx))

                # ── DECIDE after OBSERVE ──
                if "after_observe" in self._deciders:
                    decide_result = await self._deciders["after_observe"].handle(result, spec, ctx)
                    stop, reason = decide_result.output
                    if stop:
                        ctx.stop_reason = reason
                        break

                await _maybe_await(self._hook.after_iteration(ctx))

        except Exception as exc:
            ctx.error = str(exc)
            ctx.stop_reason = "error"
            await _maybe_await(self._hook.on_error(ctx, exc))
            yield {"type": "error", "message": str(exc)}

        # ── FINALIZE ──
        final_content = ctx.final_content
        if self._finalize:
            final_content = self._finalize(ctx)
        final_content = self._hook.finalize(ctx, final_content)

        yield {
            "type": "done",
            "content": final_content or "",
            "stop_reason": ctx.stop_reason or "completed",
            "error": ctx.error,
            "iterations": ctx.iteration + 1,
            "elapsed_sec": ctx.elapsed_sec,
        }

    async def run_to_completion(self, spec: BaseSpec) -> UnifiedResult:
        """drain run_stream，构建 UnifiedResult。"""
        result = UnifiedResult()
        async for event in self.run_stream(spec):
            if event.get("type") == "done":
                result.final_content = event.get("content")
                result.stop_reason = event.get("stop_reason", "completed")
                result.error = event.get("error")
                result.iterations = event.get("iterations", 0)
                result.elapsed_sec = event.get("elapsed_sec", 0)
            elif event.get("type") == "error":
                result.error = event.get("message")
        return result

    def execution_context(self) -> AgentExecutionContext:
        """返回执行上下文（SubagentManager 用）。"""
        return AgentExecutionContext(
            chat_service=getattr(self._reasoner, "_chat_service", None),
            tool_executor=getattr(self._actor, "_executor", None),
            config={},
        )
```

### 7. 注册表（registry.py）

```python
@dataclass
class AgentModeConfig:
    """一个 mode 的完整配置。"""
    name: str
    reasoner: StepHandler | StreamingHandler | Callable  # 实例或工厂函数
    actor: StepHandler | StreamingHandler | Callable
    deciders: dict[str, StepHandler] = field(default_factory=dict)
    spec_cls: type = BaseSpec
    precheck: Callable | None = None
    finalize: Callable | None = None
    hook_factory: Callable | None = None

_MODE_REGISTRY: dict[str, AgentModeConfig] = {}

def register_mode(config: AgentModeConfig) -> None:
    _MODE_REGISTRY[config.name] = config

def create_agent_loop(name: str, **kwargs) -> UnifiedAgentLoop:
    """工厂 — 保证策略组合合法。"""
    config = _MODE_REGISTRY.get(name)
    if config is None:
        raise ValueError(f"Unknown mode: {name!r}. Available: {list(_MODE_REGISTRY.keys())}")

    reasoner = config.reasoner(**kwargs) if callable(config.reasoner) else config.reasoner
    actor = config.actor(**kwargs) if callable(config.actor) else config.actor
    hook = config.hook_factory(**kwargs) if config.hook_factory else None

    return UnifiedAgentLoop(
        reasoner=reasoner,
        actor=actor,
        deciders=config.deciders,
        hook=hook,
        precheck=config.precheck,
        finalize=config.finalize,
    )

# ─── 预注册内置模式 ─────────────────────────────────────

def _chat_precheck(ctx):
    timeout = ctx.spec.timeout_seconds
    if timeout and ctx.elapsed_sec > timeout:
        return True
    pred = ctx.spec.goal_active_predicate
    if pred is not None:
        try:
            if not pred():
                ctx.stop_reason = "goal_abandoned"
                return True
        except Exception:
            pass
    return False

def _chat_finalize(ctx):
    return ctx.final_content

register_mode(AgentModeConfig(
    name="chat",
    spec_cls=ChatSpec,
    reasoner=lambda **kw: ChatReasoner(kw["chat_service"], kw.get("prompt_builder")),
    actor=lambda **kw: ToolActor(kw["tool_executor"]),
    deciders={"after_reason": CheckEmptyStep("tool_calls", "no_tool_calls")},
    hook_factory=lambda **kw: AgentHookAdapter(kw.get("hook")),
    precheck=_chat_precheck,
    finalize=_chat_finalize,
))

register_mode(AgentModeConfig(
    name="codegen",
    spec_cls=CodegenSpec,
    reasoner=lambda **kw: CodegenReasoner(kw.get("llm_client")),
    actor=CodeActor(),
    deciders={"after_act": CheckSuccessStep()},
))
```

### 8. Hook 适配器（hook_adapter.py）

```python
class AgentHookAdapter(UnifiedHook):
    """AgentHook 13 点 → UnifiedHook 完整映射。"""

    def __init__(self, hook: Any):
        self._hook = hook or NoOpHook()

    def wants_streaming(self) -> bool:
        return self._hook.wants_streaming()

    def before_iteration(self, ctx):
        self._hook.before_iteration(self._to_hook_ctx(ctx))

    def on_reason_start(self, ctx):
        pass  # AgentHook 没有直接对应

    def on_reason_end(self, ctx, response):
        self._hook.on_stream_end(self._to_hook_ctx(ctx), resuming=False)

    def on_stream(self, ctx, delta):
        self._hook.on_stream(self._to_hook_ctx(ctx), delta)

    def emit_reasoning(self, ctx, content):
        self._hook.emit_reasoning(self._to_hook_ctx(ctx), content)

    def emit_reasoning_end(self, ctx):
        self._hook.emit_reasoning_end(self._to_hook_ctx(ctx))

    def on_act_start(self, ctx):
        self._hook.before_execute_tools(self._to_hook_ctx(ctx))

    def on_act_end(self, ctx, result):
        pass  # after_tool_executed 由 ToolActor 内部调用

    def after_tool_executed(self, ctx, tool_call, result):
        self._hook.after_tool_executed(self._to_hook_ctx(ctx), tool_call, result)

    def on_tool_error(self, ctx, tool_call, error):
        self._hook.on_tool_error(self._to_hook_ctx(ctx), tool_call, error)

    def on_confirmation(self, ctx, tool_call):
        self._hook.on_confirmation(self._to_hook_ctx(ctx), tool_call)

    def on_observe(self, ctx):
        pass  # AgentHook 没有直接对应

    def on_error(self, ctx, error):
        self._hook.on_error(self._to_hook_ctx(ctx), error)

    def finalize(self, ctx, content):
        return self._hook.finalize_content(self._to_hook_ctx(ctx), content)

    def after_iteration(self, ctx):
        self._hook.after_iteration(self._to_hook_ctx(ctx))

    def _to_hook_ctx(self, ctx: UnifiedContext) -> AgentHookContext:
        """UnifiedContext → AgentHookContext 映射（17 字段）。"""
        return AgentHookContext(
            iteration=ctx.iteration,
            messages=ctx.messages,
            response=None,
            usage={},
            tool_calls=[],
            tool_results=[],
            tool_events=[],
            streamed_content=False,
            streamed_reasoning=False,
            final_content=ctx.final_content,
            stop_reason=ctx.stop_reason,
            error=ctx.error,
            observations=[],
            cancelled=False,
            paused=False,
            compacted_count=ctx.compacted_count,
            chars_saved=0,
        )
```

### 9. 事件常量（events.py）

```python
"""统一事件常量 — 合并 chat + research，re-export 兼容。

chat events（原有 16 个）+ research events（6 个）统一定义。
research_runner.py 通过 re-export 保持旧 import 路径不变。
"""

# ── Chat events（原有）──────────────────────────────────
SESSION_CREATED = "session_created"
SESSION_INIT = "session_init"
USER_MESSAGE = "user_message"
MESSAGE_DELTA = "message_delta"
THINKING = "thinking"
TOOL_CALL_START = "tool_call_start"
TOOL_CALL_END = "tool_call_end"
TOOL_CALL_ERROR = "tool_call_error"
CONFIRMATION_REQUIRED = "confirmation_required"
COMPACTED = "compacted"
COMMAND_DONE = "command_done"
RESEARCH_RUN_STARTED = "research_run_started"
DONE = "done"
ERROR = "error"
SAVE_WARNING = "save_warning"
PHASE = "phase"

# ── Research events（合并）──────────────────────────────
REASONING = "reasoning"                # 原 EVENT_REASONING
ACTION_ERROR = "action_error"          # 原 EVENT_ACTION_ERROR
OBSERVATION_ERROR = "observation_error" # 原 EVENT_OBSERVATION_ERROR
ROUND_COMPLETE = "round_complete"      # 原 EVENT_ROUND_COMPLETE
TIMEOUT = "timeout"                    # 原 EVENT_TIMEOUT
```

```python
# research_runner.py — re-export（旧代码不改 import 路径）
from llmwikify.apps.chat.agent.unified.events import (
    REASONING as EVENT_REASONING,
    ACTION_ERROR as EVENT_ACTION_ERROR,
    OBSERVATION_ERROR as EVENT_OBSERVATION_ERROR,
    ROUND_COMPLETE as EVENT_ROUND_COMPLETE,
    PHASE as EVENT_PHASE,
    TIMEOUT as EVENT_TIMEOUT,
)
```

---

## 状态机对比

### 原始（三套独立）

```
Chat:     PRECHECK → REASON → ACT → OBSERVE → FINALIZE
Codegen:  REASON → ACT → OBSERVE → DECIDE
Research: PRECHECK → REASON → ACT → OBSERVE → PERSIST
```

### 统一后

```
PRECHECK → [REASON → DECIDE① → ACT → DECIDE② → OBSERVE → DECIDE③] → FINALIZE

DECIDE① = after_reason（Chat 用：无 tool_calls → stop）
DECIDE② = after_act（Codegen 用：success → stop）
DECIDE③ = after_observe（Research 用：quality gate → stop）
```

---

## 新增组件示例

### 最简（~10 行）— 无状态 mode

```python
VALIDATOR = AgentModeConfig(
    name="validator",
    reasoner=Pipeline(ReadCodeStep(), ExtractCodeStep()),
    actor=ValidateAndExecuteStep(),
    deciders={"after_act": CheckFieldStep("success")},
)
register_mode(VALIDATOR)
```

### 中等（~30 行）— 自定义 Step

```python
@step(name="read_code", input_type=str)
async def read_code(input, spec, ctx):
    from pathlib import Path
    return StepResult.ok(Path(input).read_text())

VALIDATOR = AgentModeConfig(
    name="validator",
    reasoner=Pipeline(read_code, ExtractCodeStep()),
    actor=Pipeline(
        ValidateAndExecuteStep(),
        MapStep(lambda r: ActResult(success=r.success, output=r.series)),
    ),
    deciders={"after_act": CheckFieldStep("success")},
)
register_mode(VALIDATOR)
```

### 复杂（~80 行）— 有状态 mode

```python
class ResearchActor(StreamingHandler):
    """有状态的 Research ACT — 需要 StreamingHandler"""
    async def stream(self, response, spec, ctx):
        action = response.action
        if action == "gather":
            results = await self._gather(spec)
            yield {"type": "event", "action": "gather", "results": results}
        elif action == "analyze":
            analysis = await self._analyze(spec)
            yield {"type": "event", "action": "analyze", "analysis": analysis}
        yield StepResult.ok(ActResult(success=True))

RESEARCH = AgentModeConfig(
    name="research",
    reasoner=Pipeline(LLMCallStep(...), ExtractJSONStep(), WrapStep(ReasonResponse, ...)),
    actor=ResearchActor(),
    deciders={"after_observe": CheckFieldStep("phase", "done")},
)
register_mode(RESEARCH)
```

---

## 预置 Steps 清单

| Step | 类型 | 输入 | 输出 | 用途 |
|---|---|---|---|---|
| `LLMCallStep` | StepHandler | messages | raw text | LLM 调用（同步） |
| `ExtractCodeStep` | StepHandler | text | code str | 提取 Python 代码 |
| `ExtractJSONStep` | StepHandler | text | dict | 提取 JSON |
| `ValidateSyntaxStep` | StepHandler | code | code | 语法检查 |
| `ValidateSafetyStep` | StepHandler | code | code | 安全检查 |
| `ExecuteCodeStep` | StepHandler | code | CodeExecResult | 执行代码 |
| `ValidateAndExecuteStep` | Pipeline | code | CodeExecResult | 完整验证+执行 |
| `BuildFeedbackStep` | StepHandler | CodeExecResult | message dict | 错误 feedback |
| `TruncateStep` | StepHandler | text | text | 截断文本 |
| `CheckFieldStep` | StepHandler | Any | (bool, str) | 字段检查 |
| `CheckEmptyStep` | StepHandler | Any | (bool, str) | 空检查 |
| `CheckToolCallsStep` | StepHandler | ReasonResponse | (bool, str) | tool_calls 空检查 |
| `CheckSuccessStep` | StepHandler | ActResult | (bool, str) | success 检查 |
| `MapStep` | StepHandler | Any | Any | 转换 output |
| `WrapStep` | StepHandler | Any | cls 实例 | 包装为指定类型 |

**共 15 个 StepHandler + 1 个 Pipeline（ValidateAndExecuteStep）。**

ChatReasoner 和 ToolActor 是 StreamingHandler，不在预置 Steps 里（它们有状态，不能用 StepHandler）。

---

## 影响面评估

### react_engine.py（Codegen）— 影响最小

| 类型 | 文件数 | 说明 |
|---|---|---|
| 生产代码 | 2 | `llm_code.py`, `workflow.py`（改 import 路径） |
| 脚本 | 3 | `run_101_alphas.py`, `test_one_factor_llm_code.py`, `demo_react_self_repair.py` |
| 测试 | 6 | ~500 行（改 import + 断言适配） |
| 风险 | 🟢 低 | |

### runner_v2.py（Chat）— 影响最大

| 类型 | 文件数 | 说明 |
|---|---|---|
| 生产代码 | 2 | `orchestrator.py`, `subagent_manager.py` |
| 测试 | 12 | **11,400+ 行**（保留不动，runner_v2 改为 delegate） |
| 风险 | 🟡 中 | 保留 ChatRunnerV2 作为兼容层 |

### research_runner.py（Research）— 影响中等

| 类型 | 文件数 | 说明 |
|---|---|---|
| 生产代码 | 3 | `research_skill.py`, `engine.py`, `research_bridge.py` |
| 测试 | 1 | ~100 行 |
| 风险 | 🟡 中 | 最后迁移，re-export 保持兼容 |

---

## 迁移路径

| Phase | 内容 | 新建 | 改 | 删 | 验证 |
|---|---|---|---|---|---|
| 1 | 核心 + 数据结构 | `core.py` + `spec.py` (~200 行) | 0 | 0 | py_compile |
| 2 | 预置 Steps | `steps/` 5 文件 (~300 行) | 0 | 0 | py_compile |
| 3 | Loop + 注册表 + Hook + events | `loop.py` + `registry.py` + `hook_adapter.py` + `events.py` (~250 行) | 0 | 0 | py_compile |
| 4 | Codegen 策略 | `pipelines/codegen.py` (~70 行) | 0 | 0 | py_compile |
| 5 | Codegen 迁移 | 0 | `run_101_alphas.py` + `llm_code.py` + `workflow.py` + 6 测试 (~70 行) | 0 | 101 alpha 对比 |
| 6 | Chat 策略 | `handlers/chat_reasoner.py` + `handlers/tool_actor.py` (~200 行) | 0 | 0 | py_compile |
| 7 | Chat 迁移 | 0 | `runner_v2.py` (~50 行 delegate + 兼容层) | 0 | 617+ 测试全过 |
| 8 | 清理 | 0 | 0 | ~1,800 行 | 全量测试 |

**总计新建**: ~1,070 行
**总计改动**: ~120 行
**总计删除**: ~1,800 行（Phase 8，验证后）

---

## 设计决策记录

| # | 决策 | 原因 |
|---|---|---|
| 1 | 两种 handler：StepHandler + StreamingHandler | 无状态步骤用 StepHandler（Pipeline 组合），有状态流式用 StreamingHandler（TextModeParser / microcompact） |
| 2 | Pipeline 组合，不用继承 | Steps 可跨模式复用，新增 mode 只需组合 |
| 3 | Spec 用继承不用 God Object | type safety，构造时编译器检查必填字段 |
| 4 | 工厂函数 + 注册表 | 保证策略组合合法，新增 mode 自动注册 |
| 5 | StreamingHandler 内部 yield events | 流式逻辑封装在 handler 内，loop 只透传 |
| 6 | Actor 内部处理 observe | messages_to_inject 消除 loop 层的消息格式依赖 |
| 7 | DECIDE 三阶段检查点 | Chat/Codegen/Research 在不同阶段判断停止 |
| 8 | UnifiedHook + AgentHookAdapter 13 点完整映射 | 统一 hook 接口，AgentHook 通过适配器接入 |
| 9 | 预置 15 Steps | 覆盖 80% 常见需求，新 mode 只组合不写新代码 |
| 10 | runner_v2.py 改为 delegate 不删除 | 保留 11,400 行测试不动，Phase 8 统一清理 |
| 11 | events.py 合并 + re-export 兼容 | 统一定义，旧 import 路径不变 |
| 12 | microcompact 保留在 ToolActor 内部 | 双输出不适合 StepHandler，StreamingHandler 自然处理 |
| 13 | TextModeParser 保留在 ChatReasoner 内部 | 状态机不适合 StepHandler，StreamingHandler 天然有状态 |
