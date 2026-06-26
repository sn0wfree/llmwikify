# Unified Agent Loop 设计文档

> 日期：2026-06-26
> 状态：设计完成，待实施
> 作者：基于 llmwikify 团队讨论

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
3. **状态机对比分析**：Chat 5步（PRECHECK→REASON→ACT→OBSERVE→FINALIZE）vs Codegen 4步（REASON→ACT→OBSERVE→DECIDE）vs Research 5步（PRECHECK→REASON→ACT→OBSERVE→PERSIST）
4. **统一架构设计**：策略模式（Reasoner / Actor / Decider）+ 统一循环
5. **设计评审**：修 God Object / 流式 / OBSERVE / DECIDE / Hook 问题
6. **StepHandler 抽象**：统一接口 + Pipeline 组合 + 预置 Steps + 注册表

---

## 设计目标

1. **一套循环**：`UnifiedAgentLoop` 替代三套独立循环
2. **自由组合**：Reasoner + Actor + Decider 可任意拼装
3. **流式支持**：Chat 的 LLM streaming 不降级
4. **向后兼容**：旧代码改为 delegate，测试不动
5. **易于扩展**：新增 mode 最简 ~10 行

---

## 架构

### 核心抽象

```
StepHandler（原子操作：输入 → StepResult）
  → Pipeline（串行组合：output → input）
    → AgentModeConfig（声明式：reasoner + actor + deciders）
      → UnifiedAgentLoop（编排循环）
        → register_mode()（注册表）
          → create_agent_loop("chat")（工厂）
```

### 目录结构

```
src/llmwikify/apps/chat/agent/unified/
├── __init__.py
├── core.py              # StepHandler + StepResult + Pipeline + UnifiedContext
├── spec.py              # BaseSpec / ChatSpec / CodegenSpec / ReasonResponse / ActResult / UnifiedResult
├── loop.py              # UnifiedAgentLoop
├── registry.py          # AgentModeConfig + register_mode + create_agent_loop
├── hook_adapter.py      # AgentHookAdapter（AgentHook 13 点 → UnifiedHook）
│
├── steps/               # 预置 Steps（16 个，开箱即用）
│   ├── __init__.py
│   ├── llm.py           # LLMCallStep + ExtractJSONStep
│   ├── code.py          # ExtractCodeStep + ValidateSyntaxStep + ValidateSafetyStep
│   │                    # + ExecuteCodeStep + ValidateAndExecuteStep + CodeExecResult
│   ├── tool.py          # ParseToolCallsStep
│   ├── feedback.py      # BuildFeedbackStep + TruncateStep
│   ├── checks.py        # CheckFieldStep + CheckEmptyStep + CheckToolCallsStep + CheckSuccessStep
│   └── transforms.py    # MapStep + WrapStep
│
├── pipelines/           # 预定义 Pipeline 组合
│   ├── __init__.py
│   ├── chat.py          # ChatReasoner + ToolActor
│   └── codegen.py       # CodegenReasoner + CodeActor
│
└── events.py            # 统一事件常量（合并 chat + research events）
```

---

## 详细设计

### 1. 核心抽象（core.py）

#### StepResult — 统一的步骤输出

```python
@dataclass
class StepResult:
    """StepHandler 的输出。所有角色统一格式。"""
    output: Any = None                # 该步骤的产出（类型由具体 step 决定）
    events: list[dict] = field(default_factory=list)  # 透传给 SSE 流
    success: bool = True
    error: str | None = None

    @staticmethod
    def ok(output=None, events=None): ...
    @staticmethod
    def fail(error, events=None): ...
```

#### StepHandler — 统一的状态转换接口

```python
class StepHandler(ABC):
    """原子步骤 — 所有策略的统一接口。

    一个接口，三个角色：
    - Reasoner.handle(messages, ...) → StepResult(output=ReasonResponse)
    - Actor.handle(response, ...)   → StepResult(output=ActResult)
    - Decider.handle(result, ...)   → StepResult(output=(bool, str))

    共享组件也是 StepHandler：
    - LLMCallStep.handle(messages, ...)    → StepResult(output=str)
    - ExtractCodeStep.handle(text, ...)    → StepResult(output=str|None)
    """
    @abstractmethod
    async def handle(self, input: Any, spec: Any, ctx: Any) -> StepResult:
        ...
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

#### UnifiedContext — Loop 内部状态

```python
@dataclass
class UnifiedContext:
    spec: BaseSpec
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
        self.messages = list(self.spec.messages)
        self.start_time = time.monotonic()
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
    microcompact: bool = True
    hook: Any | None = None
    goal_active_predicate: Callable[[], bool] | None = None

@dataclass
class CodegenSpec(BaseSpec):
    df: Any = None                    # pl.DataFrame
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
```

### 3. 预置 Steps（steps/）

#### llm.py

```python
class LLMCallStep(StepHandler):
    """LLM 调用（支持 streaming/sync）。

    输入: messages (list[dict])
    输出: raw response text (str) 或 stream events (list)
    构造时依赖: llm_client
    运行时依赖: 从 spec 取 temperature
    """
    def __init__(self, llm_client, streaming=False, max_retries=3): ...

class ExtractJSONStep(StepHandler):
    """从 LLM 响应提取 JSON。

    输入: text (str)
    输出: dict
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
    """执行 compute_factor 代码。输入: code + spec.df → 输出: pl.Series"""

class ValidateAndExecuteStep(Pipeline):
    """代码验证+执行流水线。输入: code → 输出: CodeExecResult"""
    def __init__(self):
        super().__init__(ValidateSyntaxStep(), ValidateSafetyStep(), ExecuteCodeStep())
```

#### checks.py

```python
class CheckFieldStep(StepHandler):
    """通用字段检查 — Decider 基础组件。

    用法：
        CheckFieldStep(field="success", equals=True)
        # input.success == True → (True, "success")
    """
    def __init__(self, field: str, equals: Any = True, stop_reason: str = ""): ...

class CheckEmptyStep(StepHandler):
    """检查列表/字段是否为空。"""
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

### 4. UnifiedAgentLoop（loop.py）

```python
class UnifiedAgentLoop(AgentRunner[BaseSpec, UnifiedResult]):
    """统一状态机。

    PRECHECK → [REASON → DECIDE → ACT → DECIDE → OBSERVE → DECIDE] → FINALIZE

    每个 phase 都是 StepHandler。
    每个 phase 的 StepResult.events 透传给 SSE 流。
    DECIDE 有三个检查点：after_reason / after_act / after_observe。
    """

    def __init__(
        self,
        reasoner: StepHandler,
        actor: StepHandler,
        deciders: dict[str, StepHandler],  # {"after_reason": ..., "after_act": ..., "after_observe": ...}
        hook: UnifiedHook | None = None,
        precheck: Callable | None = None,
        finalize: Callable | None = None,
    ): ...

    async def run_stream(self, spec: BaseSpec) -> AsyncIterator[dict]:
        ctx = UnifiedContext(spec=spec)
        for iteration in range(spec.max_iterations):
            # PRECHECK
            if self._precheck and self._precheck(ctx): break

            # REASON
            reason_result = await self._reasoner.handle(ctx.messages, spec, ctx)
            for ev in reason_result.events: yield ev
            if not reason_result.success: break
            response = reason_result.output

            # DECIDE after REASON
            if "after_reason" in self._deciders:
                stop, reason = (await self._deciders["after_reason"].handle(response, spec, ctx)).output
                if stop: break

            # ACT
            act_result = await self._actor.handle(response, spec, ctx)
            for ev in act_result.events: yield ev
            if not act_result.success: break
            result = act_result.output

            # DECIDE after ACT
            if "after_act" in self._deciders:
                stop, reason = (await self._deciders["after_act"].handle(result, spec, ctx)).output
                if stop: break

            # OBSERVE — Actor 已处理，只注入 messages_to_inject
            for msg in result.messages_to_inject:
                ctx.messages.append(msg)

            # DECIDE after OBSERVE
            if "after_observe" in self._deciders:
                stop, reason = (await self._deciders["after_observe"].handle(result, spec, ctx)).output
                if stop: break

        # FINALIZE
        yield {"type": "done", ...}
```

### 5. 注册表（registry.py）

```python
@dataclass
class AgentModeConfig:
    """一个 mode 的完整配置。"""
    name: str
    reasoner: StepHandler | Callable   # 实例或工厂函数
    actor: StepHandler | Callable
    deciders: dict[str, StepHandler] = field(default_factory=dict)
    spec_cls: type = BaseSpec
    precheck: Callable | None = None
    finalize: Callable | None = None
    hook_factory: Callable | None = None

_MODE_REGISTRY: dict[str, AgentModeConfig] = {}

def register_mode(config: AgentModeConfig) -> None:
    _MODE_REGISTRY[config.name] = config

def create_agent_loop(name: str, **kwargs) -> UnifiedAgentLoop:
    config = _MODE_REGISTRY[name]
    reasoner = config.reasoner(**kwargs) if callable(config.reasoner) else config.reasoner
    actor = config.actor(**kwargs) if callable(config.actor) else config.actor
    return UnifiedAgentLoop(reasoner=reasoner, actor=actor, deciders=config.deciders, ...)

# 预注册内置模式
register_mode(AgentModeConfig(
    name="chat",
    reasoner=lambda **kw: ChatReasoner(kw["chat_service"], kw.get("prompt_builder")),
    actor=lambda **kw: ToolActor(kw["tool_executor"]),
    deciders={"after_reason": CheckEmptyStep("tool_calls", "no_tool_calls")},
    hook_factory=lambda **kw: AgentHookAdapter(kw.get("hook")),
    precheck=chat_precheck,
    finalize=chat_finalize,
))

register_mode(AgentModeConfig(
    name="codegen",
    reasoner=lambda **kw: CodegenReasoner(kw.get("llm_client")),
    actor=CodeActor(),
    deciders={"after_act": CheckFieldStep("success")},
))
```

### 6. Pipeline 组合（pipelines/）

#### chat.py

```python
class ChatReasoner(StepHandler):
    """Chat REASON: LLMCallStep(streaming) + ParseToolCallsStep"""
    def __init__(self, chat_service, prompt_builder=None):
        self._llm = LLMCallStep(chat_service, streaming=True)
        self._parser = ParseToolCallsStep()

    async def handle(self, input, spec, ctx):
        messages = input
        llm_result = await self._llm.handle(messages, spec, ctx)
        if not llm_result.success: return llm_result
        return await self._parser.handle(llm_result.output, spec, ctx)

class ToolActor(StepHandler):
    """Chat ACT: 工具调度 + confirmation + microcompact"""
    def __init__(self, tool_executor): ...
```

#### codegen.py

```python
class CodegenReasoner(Pipeline):
    """Codegen REASON: LLMCallStep(sync) + ExtractCodeStep → ReasonResponse"""
    def __init__(self, llm_client=None):
        client = llm_client or build_llm_client()
        super().__init__(LLMCallStep(client, streaming=False), ExtractCodeStep())

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

    async def handle(self, input, spec, ctx):
        response = input
        if response.code is None:
            feedback = await self._feedback.handle(CodeExecResult(success=False, error="no code", error_kind="extract_failed"), spec, ctx)
            return StepResult.ok(ActResult(success=False, error="no code", error_kind="extract_failed", messages_to_inject=[feedback.output]))
        exec_result = await self._executor.handle(response.code, spec, ctx)
        code_result = exec_result.output
        if code_result.success:
            return StepResult.ok(ActResult(success=True, output=code_result.series, code=code_result.code))
        feedback = await self._feedback.handle(code_result, spec, ctx)
        return StepResult.ok(ActResult(success=False, error=code_result.error, error_kind=code_result.error_kind, code=code_result.code, messages_to_inject=[feedback.output]))
```

### 7. Hook 适配器（hook_adapter.py）

```python
class AgentHookAdapter(UnifiedHook):
    """AgentHook 13 点 → UnifiedHook 适配。"""
    def __init__(self, hook: AgentHook): ...
    def before_iteration(self, ctx): self._hook.before_iteration(self._to_hook_ctx(ctx))
    def on_reason_end(self, ctx, result): self._hook.on_stream_end(self._to_hook_ctx(ctx), resuming=False)
    def on_act_start(self, ctx): self._hook.before_execute_tools(self._to_hook_ctx(ctx))
    def on_error(self, ctx, error): self._hook.on_error(self._to_hook_ctx(ctx), error)
    def finalize(self, ctx, content): return self._hook.finalize_content(self._to_hook_ctx(ctx), content)
    def after_iteration(self, ctx): self._hook.after_iteration(self._to_hook_ctx(ctx))
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

### 最简（~10 行）

```python
VALIDATOR = AgentModeConfig(
    name="validator",
    reasoner=Pipeline(ReadCodeStep(), ExtractCodeStep()),
    actor=ValidateAndExecuteStep(),
    deciders={"after_act": CheckFieldStep("success")},
)
register_mode(VALIDATOR)
```

### 中等（~30 行）

```python
@step(name="read_code", input_type=str)
async def read_code(input, spec, ctx):
    from pathlib import Path
    return StepResult.ok(Path(input).read_text())

VALIDATOR = AgentModeConfig(
    name="validator",
    reasoner=Pipeline(read_code, ExtractCodeStep()),
    actor=Pipeline(ValidateAndExecuteStep(), MapStep(lambda r: ActResult(success=r.success, output=r.series))),
    deciders={"after_act": CheckFieldStep("success")},
)
register_mode(VALIDATOR)
```

### 复杂（~80 行）

```python
class ResearchActor(StepHandler):
    async def handle(self, response, spec, ctx):
        action = response.action
        if action == "gather": ...
        elif action == "analyze": ...
        return StepResult.ok(ActResult(...))

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

| Step | 输入 | 输出 | 用途 |
|---|---|---|---|
| `LLMCallStep` | messages | raw text / stream | LLM 调用 |
| `ExtractCodeStep` | text | code str | 提取 Python 代码 |
| `ExtractJSONStep` | text | dict | 提取 JSON |
| `ParseToolCallsStep` | stream events | ReasonResponse | 解析 tool_calls |
| `ValidateSyntaxStep` | code | code | 语法检查 |
| `ValidateSafetyStep` | code | code | 安全检查 |
| `ExecuteCodeStep` | code + df | pl.Series | 执行代码 |
| `ValidateAndExecuteStep` | code | CodeExecResult | 完整验证+执行 |
| `BuildFeedbackStep` | CodeExecResult | message dict | 错误 feedback |
| `TruncateStep` | text | text | 截断文本 |
| `CheckFieldStep` | Any | (bool, str) | 字段检查 |
| `CheckEmptyStep` | Any | (bool, str) | 空检查 |
| `CheckToolCallsStep` | ReasonResponse | (bool, str) | tool_calls 空检查 |
| `CheckSuccessStep` | ActResult | (bool, str) | success 检查 |
| `MapStep` | Any | Any | 转换 output |
| `WrapStep` | Any | cls 实例 | 包装为指定类型 |

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
| 风险 | 🟡 中 | 最后迁移 |

---

## 迁移路径

| Phase | 内容 | 新建 | 改 | 删 | 验证 |
|---|---|---|---|---|---|
| 1 | 核心 + 数据结构 | `core.py` + `spec.py` (~200 行) | 0 | 0 | py_compile |
| 2 | 预置 Steps | `steps/` 6 文件 (~350 行) | 0 | 0 | py_compile |
| 3 | Loop + 注册表 + Hook | `loop.py` + `registry.py` + `hook_adapter.py` + `events.py` (~200 行) | 0 | 0 | py_compile |
| 4 | Codegen 策略 | `pipelines/codegen.py` (~70 行) | 0 | 0 | py_compile |
| 5 | Codegen 迁移 | 0 | `run_101_alphas.py` + `llm_code.py` + `workflow.py` + 6 测试 (~70 行) | 0 | 101 alpha 对比 |
| 6 | Chat 策略 | `pipelines/chat.py` (~160 行) | 0 | 0 | py_compile |
| 7 | Chat 迁移 | 0 | `runner_v2.py` (~30 行 delegate) | 0 | 617+ 测试全过 |
| 8 | 清理 | 0 | 0 | ~1,800 行 | 全量测试 |

**总计新建**: ~1,050 行
**总计改动**: ~100 行
**总计删除**: ~1,800 行（Phase 8，验证后）

---

## 设计决策记录

| # | 决策 | 原因 |
|---|---|---|
| 1 | 一个 StepHandler 接口，不用三个独立 ABC | 三者结构相同（输入→执行→输出），差异只在"执行什么" |
| 2 | Pipeline 组合，不用继承 | Steps 可跨模式复用，新增 mode 只需组合 |
| 3 | Spec 用继承不用 God Object | type safety，构造时编译器检查必填字段 |
| 4 | 工厂函数 + 注册表 | 保证策略组合合法，新增 mode 自动注册 |
| 5 | Reasoner 内部 yield events | 流式逻辑封装在 Reasoner 内，loop 只透传 |
| 6 | Actor 内部处理 observe | messages_to_inject 消除 loop 层的消息格式依赖 |
| 7 | DECIDE 三阶段检查点 | Chat/Codegen/Research 在不同阶段判断停止 |
| 8 | UnifiedHook + AgentHookAdapter | 统一 hook 接口，AgentHook 13 点通过适配器接入 |
| 9 | 预置 16 Steps | 覆盖 80% 常见需求，新 mode 只组合不写新代码 |
| 10 | runner_v2.py 改为 delegate 不删除 | 保留 11,400 行测试不动，Phase 8 统一清理 |
