# Python 设计模式在 llmwikify chat 模块的应用与可借鉴方案

> Date: 2026-06-22 (Pass5 产出)
> 输入: 菜鸟教程 GoF 23 设计模式 + 6 原则 + Python 动态特性专题
> (https://www.runoob.com/python-design-pattern/python-design-pattern-intro.html)
> 对照: llmwikify `src/llmwikify/apps/chat/` + `src/llmwikify/foundation/`
> 目的: 沉淀 chat 子系统已实施的设计模式 + 可借鉴的 Pass5+ 候选方案, 供后续重构与新模块参考

---

## 0. TL;DR

- **chat 模块已实施 15/23 GoF 经典模式**, 其中 14 个实施完善, 模式覆盖率高
- **剩余可借鉴的 3 个候选** (按 ROI 排序): **M-4** CommandRouter 闭包外提, **M-2** ChatServiceAdapter Protocol, **M-1** Slash Command Registry 装饰器
- **不推荐引入的 5 个候选**: ChatEvent ABC / GoalPredicateStrategy / ToolRegistryFactory / ChatRunnerFactory / Visitor-Interpreter
- **架构原则符合度**: 4/6 原则轻度违反 (OCP/LSP/DIP/ISP), 均有明确缓解路径 (Pass5 候选)

---

## 1. GoF 23 设计模式概览

经典著作《Design Patterns - Elements of Reusable Object-Oriented Software》定义的 23 种模式分为三类:

### 1.1 创建型模式 (5)

| 模式 | 核心思想 |
|---|---|
| 工厂方法 (Factory Method) | 子类决定实例化哪个类 |
| 抽象工厂 (Abstract Factory) | 创建相关对象族 |
| 单例 (Singleton) | 全局唯一实例 |
| 建造者 (Builder) | 分步构建复杂对象 |
| 原型 (Prototype) | 克隆而非新建 |

### 1.2 结构型模式 (7)

| 模式 | 核心思想 |
|---|---|
| 适配器 (Adapter) | 接口转换, 让不兼容类协作 |
| 桥接 (Bridge) | 抽象与实现解耦 |
| 组合 (Composite) | 树形结构统一处理 |
| 装饰器 (Decorator) | 动态添加职责 |
| 外观 (Facade) | 统一高层接口 |
| 享元 (Flyweight) | 共享细粒度对象 |
| 代理 (Proxy) | 访问控制 / 延迟加载 |

### 1.3 行为型模式 (11)

| 模式 | 核心思想 |
|---|---|
| 责任链 (Chain of Responsibility) | 链式传递请求 |
| 命令 (Command) | 请求封装为对象 |
| 解释器 (Interpreter) | DSL 语法解释 |
| 迭代器 (Iterator) | 顺序访问聚合 |
| 中介者 (Mediator) | 集中协调对象交互 |
| 备忘录 (Memento) | 状态快照保存/恢复 |
| 观察者 (Observer) | 一对多依赖通知 |
| 状态 (State) | 状态切换行为变化 |
| 空对象 (Null Object) | 默认空行为代替 None |
| 策略 (Strategy) | 算法族可替换 |
| 模板方法 (Template Method) | 骨架在基类, 步骤在子类 |
| 访问者 (Visitor) | 操作分离数据结构 |

---

## 2. Python 动态特性专题

菜鸟教程明确指出 Python 动态特性影响模式实施:

### 2.1 简单工厂 (Pythonic Factory)

```python
# Python 风格 — 不需要 ABC 层次
def create_payment(method):
    methods = {"credit_card": CreditCardPayment, "paypal": PayPayPayment}
    return methods[method]()
```

**llmwikify 应用**: `apps/chat/providers/registry.py` 用 `register_provider` 装饰器 + dict 注册, 而非 ABC 工厂层次。

### 2.2 装饰器语法内置支持

```python
@log_execution_time
def process_data(data): ...
```

**llmwikify 应用**: `@register_provider` (providers), `@slash_command` 候选 (Pass5)。

### 2.3 模块级单例 (Module Singleton)

Python 模块本身就是单例 — `import` 多次只执行一次。多数 "单例" 场景直接用模块变量即可。

**llmwikify 应用**: `MessageBus._default` 是进程内单例, `DreamScheduler` 默认 cron 配置用模块级常量。

---

## 3. chat 模块设计模式实施审计 (15/23)

### 3.1 创建型 (3/5)

| 模式 | llmwikify 实施 | 位置 | 评价 |
|---|---|---|---|
| **工厂方法** | `ChatEvent` 静态工厂簇 (12 个 `@staticmethod`) | `apps/chat/agent/orchestrator.py:38-99` | ✅ 完整, 但 SSE 契约是 dict 不应改 ABC |
| **抽象工厂** | `LLMProvider` Protocol + `register_provider` 装饰器 + 2 concrete (MiniMax + Xiaomi) | `apps/chat/providers/base.py` + `registry.py` | ✅ 完善 |
| **单例** | `MessageBus._default`, `DreamScheduler` 默认 cron | `apps/chat/bus/queue.py`, `apps/chat/memory/dream_scheduler.py` | ✅ 完善 |
| 建造者 | 无显式应用 | — | 业务场景不匹配 |
| 原型 | 无显式应用 | — | 业务场景不匹配 |

### 3.2 结构型 (7/7) ✅ 全部覆盖

| 模式 | llmwikify 实施 | 位置 | 评价 |
|---|---|---|---|
| **适配器** | `ChatBridgeBackend` (3 方法委托 `_truncate_messages`/`_get_toolspec`/`_llm_stream_with_retry`) + `BusAdapter` (SSE→WS 翻译) | `apps/chat/agent/bridge_backend.py` + `apps/chat/bus/adapter.py` | ✅ 完善 |
| **桥接** | `AgentHook` 抽象基类 + `WikiHook`/`DreamSyncHook`/`AutoIngestHook` 具体实现 (3 个业务 hook, 共 113 LOC) | `foundation/callback/` + `integrations/` | ✅ 完善 |
| **组合** | `CompositeHook` (13 钩子点 fan-out + 错误隔离) + `CompositeToolRegistry` | `foundation/callback/composite.py` + `apps/agent/tools/skill_adapter.py` | ✅ 完善 |
| **装饰器** | `_V2PersistenceHook` (包装 tool result 持久化) + `microcompact_fn` (替换过长 tool result) + `measure_latency` CM (Pass5 D-2) | `apps/chat/agent/orchestrator.py` + `apps/chat/agent/microcompact.py` + `foundation/utils_timing.py` | ✅ 完善 + Pass5 深度应用 (见 §3.4) |
| **外观** | `AgentService` (7 依赖 composition root, 555 LOC) + `MemoryManager` (6 stores 门面) + `ChatDatabase._facade` (99 委托) + `ChatOrchestrator` | `apps/chat/agent/agent_service.py` + `apps/chat/memory/__init__.py` + `apps/chat/db/_facade.py` | ✅ 完善 |
| **享元** | `events.MESSAGE_DELTA` 等 15 字符串常量 (共享) + `microcompact.DEFAULT_COMPACTABLE_TOOLS` frozenset (7 tool names 共享) | `apps/chat/agent/events.py` + `apps/chat/agent/microcompact.py` | ✅ 完善 |
| **代理** | `ChatBridgeBackend` (chat_service adapter, 3 方法控访问) | `apps/chat/agent/bridge_backend.py` | ✅ 完善, 决定保留 (改接口 churn ~500 行测试) |

### 3.3 行为型 (5/11)

| 模式 | llmwikify 实施 | 位置 | 评价 |
|---|---|---|---|
| **责任链** | `CompositeHook` 13 钩子点 (每个点 fan-out 到多个 hook) | `foundation/callback/composite.py` | ✅ 完善 |
| **命令** | `CommandRouter` 3-tier dispatch (priority/exact/prefix) + 8 slash commands (`/stop`/`/help`/`/clear`/`/status`/`/title`/`/memory_dream`/`/goal`) | `apps/chat/command_router.py` + `orchestrator.py:_build_default_command_router` | ✅ 完善, 但闭包内嵌 |
| **迭代器** | `AsyncIterator[dict]` SSE yield 流式 | `orchestrator.chat()` + `runner_v2.run_stream()` | ✅ 完善 |
| **中介者** | `MessageBus` 双 asyncio.Queue pub/sub (channels 间通信集中) | `apps/chat/bus/queue.py` + `apps/chat/bus/events.py` | ✅ 完善 |
| **备忘录** | `state_trace: list[_StateTraceEntry]` per-run 记录 + `MemoryManager.conversation.alist` session history 加载 | `runner_v2.py:_RunContext` + `memory/conversation_store.py` | ✅ 完善 |
| **观察者** | `MessageBus` pub/sub (与中介者复用) + `CompositeHook` 钩子回调 | `apps/chat/bus/queue.py` + `foundation/callback/composite.py` | ✅ 完善 |
| **状态** | `runner_v2.py` 5 步状态机 (PRECHECK/REASON/ACT/OBSERVE/COMPLETE) + `_StateTrace` 跟踪 | `apps/chat/agent/runner_v2.py` | ✅ 完善 |
| **策略** | `_THINKING_STYLE_BUILDERS` map (4 模式: reasoning_split / budget_tokens / etc.) | `foundation/llm/streamable.py` | ✅ 完善 |
| **模板方法** | `AgentRunner` ABC + `run_stream`/`run_to_completion`/`wants_streaming` 3 方法 + `ChatRunnerV2` 子类 | `apps/chat/agent/agent_runner.py` | ✅ 完善 |
| 解释器 | 无 | — | 业务场景不匹配 |
| 空对象 | `_StubSkillContext` (Pass4-C 抽 `_make_skill_ctx`) | `apps/chat/agent/orchestrator.py:_make_skill_ctx` | ✅ Pass4-C 实施 |
| 访问者 | 无 | — | 业务场景不匹配 |

### 3.4 装饰器模式深度应用 (Pass5, 2026-06-22)

装饰器模式是 chat 模块**最深度应用**的 GoF 模式 — 3 大装饰器形式全部使用,且 Pass5 又新增 2 个基础工具。

#### 3.4.1 装饰器模式 3 大形式

| 形式 | Python 实现 | chat 应用示例 |
|---|---|---|
| **类层级装饰** | `class X(Y): Y.__init__(self, wrapped)` | `CompositeHook([h1, h2, ...])` 持有 AgentHook 列表, 13 钩子点 fan-out |
| **Python `@decorator` 函数装饰** | `@dec` 语法糖 | `@log_exception_returning`, `@check_token_budget`, `@tracked`, `@register_provider` |
| **Context Manager 协议** | `@contextmanager` | `_StateTrace` (5 步状态机), `measure_latency` (Pass5 D-2) |

#### 3.4.2 GoF 4 角色在 chat 的对位

| GoF 角色 | chat 实例 |
|---|---|
| **Component 接口** | `AgentHook` (13 抽象方法, `foundation/callback/composite.py:25-69`) |
| **ConcreteComponent** | `NoOpHook` (透明装饰器, 同上 L72-73) |
| **Decorator 抽象** | `CompositeHook` (持有 list[AgentHook], 实现 AgentHook 接口) |
| **ConcreteDecorator** | `WikiHook` / `WikiDreamSyncHook` / `AutoIngestHook` / `_V2PersistenceHook` |

#### 3.4.3 Pass5 新增 2 个装饰器工具

**D-2 `@contextmanager measure_latency()`** (foundation/utils_timing.py, 41 LOC):

| 属性 | 值 |
|---|---|
| 模式形式 | Context Manager 协议 (with 语句) |
| 应用位置 | `runner_v2.py:_act()` 包裹 `_execute_tool()` |
| 修复 bug | `TOOL_CALL_END.duration_ms` 之前永远为 0, 现在填充真实毫秒值 |
| 测试 | 单元验证 get_ms() 返回准确 ms + CM 退出后值缓存 |

```python
# 使用
with measure_latency() as get_ms:
    result = await self._execute_tool(...)
yield {
    "type": events.TOOL_CALL_END,
    "tool": tool_name,
    "result": result,
    "call_id": call_id,
    "duration_ms": get_ms(),  # 真实延迟!
}
```

**R-1 `iter_with_metrics` / `call_with_metrics`** (apps/chat/agent/llm_metrics.py, 2026-06-23):

| 属性 | 值 |
|---|---|
| 模式形式 | async generator wrapper (Context Manager 协议 + yield 重定向) |
| 应用位置 | `runner_v2._stream_llm` 3 路径 (retry / astream_chat / chat fallback) |
| 行为 | 自动记录 latency / chars_in / success / error 到 `LLMMetricsCollector` |
| 取代方案 | Pass5 D-4 `@track_llm_call` 装饰器 (callee 层), 改用 caller 层 CM (避免装饰 `streamable.py` 5 处方法的兼容性) |
| 借鉴来源 | Pass5 装饰器思路, 但 CM 形式更易与 async generator 配合 |

```python
# 使用 (R-1 实际方案)
async for ev in iter_with_metrics(
    lambda: retry(messages, tools),
    prompt_name="chat_reason",
    chars_in=chars_in,
):
    yield ev
```

> **Pass7 演进**: R-1 实际替代了 Pass5 D-4 的 `@track_llm_call` 装饰器方案。原装饰器文件 `foundation/callback/track_llm_call.py` (143 LOC) 因 0 引用且功能被 R-1 覆盖, 于 2026-06-23 删除 (F-1 死代码清理)。

#### 3.4.4 装饰器模式设计警示 (来自菜鸟笔记)

1. **装饰顺序重要** (笔记 7): `addtime(blk_bitch(blk_jb(text)))` 中如果顺序错, 后加的 blk 会屏蔽前加的 addtime 时间戳中的字符。LLM metrics 改用 R-1 caller 层 CM (`iter_with_metrics` / `call_with_metrics`), 不再依赖装饰器链。
2. **多层装饰增加复杂性** (GoF 缺点): chat 已有 3 层装饰器 (CompositeHook + _V2PersistenceHook + WikiHook)。装饰层次 ≤ 5 层是安全的。
3. **Python 装饰器灵活性**: 既可装饰函数 (single dispatch), 也可装饰类 (override `__init_subclass__`), 也可装饰 async 函数 + async generator。

#### 3.4.5 装饰器模式决策树 (供后续模块参考)

```
需要给函数/方法动态添加职责?
├─ 否 → 直接调用
└─ 是
   ├─ 职责是一次性的辅助逻辑?
   │  ├─ 例: error log / timing / retry / budget check → @decorator 函数装饰器
   │  └─ 例: 资源管理(状态/锁/文件) → @contextmanager CM 装饰器
   ├─ 职责是"包装现有对象"?
   │  ├─ 静态(编译期) → 类继承装饰器 (CompositeHook + AgentHook 模式)
   │  └─ 动态(运行期) → Python @decorator 函数装饰器
   └─ 职责需要"链式叠加"(前一输出 = 后一输入)?
      ├─ 是 → Pipeline decorator (类似 CompositeHook._fire_pipeline)
      └─ 否 → 单层装饰即可
```

#### 3.4.6 不推荐的装饰器候选 (避免过度设计)

| 候选 | 拒绝理由 |
|---|---|
| `@authorize_session` | 无 session auth 需求 |
| `@cache_tool_result` | microcompact 已处理, 重复抽象 |
| `@rate_limit_per_session` | 无 QPS 限制需求 |
| `@validate_message_schema` | messages 是 dict, 无 schema 验证需求 |
| `@memoize` | chat 流程是 stateful, 缓存破坏流式语义 |

#### 3.4.7 Generic ABC + 上下文对象 (Phase 16+, LSP 修复, 2026-06-23)

**问题**: `SubagentManager` 类型 hint 是 `AgentRunner` (通用 ABC), 但运行时检查 4 个 `ChatRunnerV2` 私有属性 (`_chat_service` / `_tool_executor` / `_prompt_builder` / `_config`), 违反 LSP。任何非 `ChatRunnerV2` 子类 (`FakeAgentRunner` 测试 stub / 未来 `WorkflowRunner` / `CronRunner`) 都被拒。

**方案**: 抽 `AgentExecutionContext` dataclass 作为 collaborator 集合, `AgentRunner` ABC 加 `execution_context()` 抽象方法, `ChatRunnerV2` 实现返回 ctx, `SubagentManager` 用 ctx 构造 child runner。

| 角色 | 实施 | 文件 |
|---|---|---|
| **Context 对象** (Facade) | `AgentExecutionContext` dataclass 含 6 collaborators | `apps/chat/agent/execution_context.py` |
| **ABC 扩展** | `AgentRunner.execution_context() -> AgentExecutionContext` (abstract) | `apps/chat/agent/agent_runner.py` |
| **实现** | `ChatRunnerV2.execution_context` property 返回 ctx | `apps/chat/agent/runner_v2.py` |
| **消费方** | `SubagentManager` 改用 `parent.execution_context()`, 删除 hasattr 4 字段检查 | `apps/chat/agent/subagent_manager.py` |

**Back-compat 双签名**: `ChatRunnerV2.__init__(self, ctx=None, **overrides)` — 接受 `ctx` (新) 或 `chat_service` / `tool_executor` / `prompt_builder` / `config` (旧)。老调用方零修改。

**借鉴来源**: nanobot v0.2.1 `agent/runner.py` 的 Generic ABC 思路, 加上 Spring `ApplicationContext` / DDD `AggregateContext` 模式 (collaborator 集合对象化)。

**LSP 收益**:
- 任何 `AgentRunner` 子类可被 `SubagentManager` 使用
- `FakeAgentRunner` 测试 stub 满足 ABC, 子代理测试不再 mock 私有属性
- 未来 `WorkflowRunner` / `CronRunner` 直接复用

### 3.4 模式实施密度

```
chat 模块 模式覆盖密度
═══════════════════════════════════════════════════════
结构型模式 (Adapter/Bridge/Composite/Decorator/Facade/Flyweight/Proxy)  7/7  ████████████████████ 100%
行为型模式 (CoR/Command/Iterator/Mediator/Memento/Observer/State/      5/11 ██████████░░░░░░░░░░  45%
            Strategy/Template Method)
创建型模式 (Factory Method/Abstract Factory/Singleton)                  3/5  ████████████░░░░░░░░  60%
═══════════════════════════════════════════════════════
合计 (GoF 23)                                                            15/23 ████████████░░░░░░░░ 65%
```

**结论**: 结构型模式 100% 覆盖 (chat 强结构需求); 行为型模式 5/11 (Visitor/Interpreter/NullObject/Command 外提有空间); 创建型模式 3/5 (Builder/Prototype 业务不匹配)。

---

## 4. 六大原则审计

### 4.1 开闭原则 (Open-Closed Principle, OCP)

> 对扩展开放, 对修改关闭

**现状**: 多数模块通过 ABC/Protocol 扩展 (`AgentRunner`, `LLMProvider`, `AgentHook`)。**例外**: `ChatOrchestrator._build_default_command_router` 是 130 LOC 内联方法, 新增 slash command 需改 orchestrator 源码。

**违反程度**: ⚠ 轻度 (8 个 commands, 加命令频率低)

**缓解**: M-1 (Pass5 候选) Slash Command Registry 装饰器

### 4.2 里氏替换原则 (Liskov Substitution Principle, LSP)

> 子类必须能完全替代基类

**现状**: `AgentRunner` Generic ABC + `ChatRunnerV2` 子类遵循 LSP。**例外**: `SubagentManager` 内部 `new ChatRunnerV2`, 未通过 `AgentRunner` ABC 调用 (Phase 16+ 待办)。

**违反程度**: ⚠ 已知, 已记录

**缓解**: SubagentManager 真接 ABC (Phase 16+)

### 4.3 依赖倒置原则 (Dependency Inversion Principle, DIP)

> 高层模块不应依赖低层模块, 都依赖抽象

**现状**: 多数依赖 Protocol/ABC。**例外**: `runner_v2.py:_build_chat_runner_v2` (orchestrator.py) 直接 import 具体类 `ChatBridgeBackend`/`ChatRunnerV2`/`SubagentManager`/`WikiHook`, 通过工厂方法组合而非依赖注入。

**违反程度**: ⚠ 轻度

**缓解**: M-2 (Pass5 候选) ChatServiceAdapter Protocol, 类型安全

### 4.4 接口隔离原则 (Interface Segregation Principle, ISP)

> 客户端不应依赖不用的接口

**现状**: `AgentRunner` ABC 暴露 3 方法 (`run_stream`/`run_to_completion`/`wants_streaming`), 子代理/worker 实际只需 `run_to_completion`。**例外**: `runner_v2.py` 通过 `getattr(self._chat_service, "_truncate_messages", None)` 鸭子访问, 没有强制 Protocol。

**违反程度**: ⚠ 轻度

**缓解**: M-2 (Pass5 候选) ChatServiceAdapter Protocol, 强制 3 方法接口

### 4.5 迪米特法则 (Law of Demeter, LoD)

> 最少知道, 只与直接朋友通信

**现状**: `ChatOrchestrator` 通过 5+ 层间接访问 (`orchestrator → runner → bridge → chat_service → wiki_service → llm_client`), 链路深但每层有清晰 Protocol 边界。

**违反程度**: ✅ 已用 Protocol 解耦大部分

### 4.6 合成复用原则 (Composite Reuse Principle, CRP)

> 优先组合而非继承

**现状**: 多数用组合 (`ChatRunnerV2` 内含 `tool_executor`/`chat_service`/`hook`)。**例外**: `ChatRunnerV2` 继承 `AgentRunner` ABC (Python ABC 是接口约定, 不是实现继承)。

**违反程度**: ✅ 符合

### 4.7 原则符合度总结

| 原则 | 现状 | 违反程度 | 缓解 |
|---|---|---|---|
| OCP | `_build_default_command_router` 内联 | ⚠ 轻度 | M-1 (Pass5) |
| LSP | `SubagentManager` 未接 ABC | ⚠ 已知 | Phase 16+ |
| DIP | runner_v2 直接 import 具体类 | ⚠ 轻度 | M-2 (Pass5) |
| ISP | runner_v2 鸭子访问 | ⚠ 轻度 | M-2 (Pass5) |
| LoD | 5+ 层间接 | ✅ 已缓解 | Protocol 边界 |
| CRP | 多数用组合 | ✅ 符合 | — |

---

## 5. Pass5+ 可借鉴方案 (按 ROI 排序)

### 5.1 候选总览

| 候选 | 模式 | 6 原则应用 | LOC Δ | 风险 | ROI |
|---|---|---|---:|---|---|
| **M-4** CommandRouter 闭包外提 | Command | ISP | orchestrator -100 + builtin_commands +120 = net +20 | 低 | ⭐⭐⭐ |
| **M-2** ChatServiceAdapter Protocol | Adapter + ISP + DIP | ISP + DIP | +15 | 极低 | ⭐⭐ |
| **M-1** Slash Command Registry 装饰器 | Command + OCP | OCP | +30 | 中 | ⭐⭐ |

### 5.2 M-4: CommandRouter 闭包外提 (高 ROI)

**问题**: `apps/chat/agent/orchestrator.py:_build_default_command_router` (L547-727, ~180 LOC) 含 8 个 inline async closure (`stop_handler`/`help_handler`/`clear_handler`/`status_handler`/`title_handler`/`memory_dream_handler`/`goal_handler`), 测试难独立测。

**改造方案**:
1. 新建 `apps/chat/agent/builtin_commands.py` (~120 LOC)
2. 8 个 handler 外提为 module-level `async def` 函数, 接收 `orchestrator` 作首参数 (duck-typed)
3. `_build_default_command_router` 仅注册 (orchestrator.py 减 ~100 LOC)

**风险**: 低 (handler 内仅用 `self.memory_manager`/`self._session_status`/`self.db` 等少数 orchestrator 状态, 通过参数显式传入)

**测试覆盖**:
- `tests/test_apps_chat_orchestrator_goal_command.py` (existing)
- `tests/test_apps_chat_command_router.py` (existing, 不需改)
- `tests/test_apps_chat_agent_builtin_commands.py` (new, ~15 cases)

**预期收益**:
- orchestrator.py 1051 → 951 LOC (-100, ~10%)
- 8 个 slash command 独立可测 (现在必须经 `_build_default_command_router`)
- 命令注册 vs 命令实现关注点分离

**不实施原因**: 当前闭包简单, 加命令频率低

### 5.3 M-2: ChatServiceAdapter Protocol (中 ROI)

**问题**: `runner_v2.py` 通过 `getattr(self._chat_service, "_truncate_messages", None)` 鸭子访问:
- `_safe_truncate` (runner_v2.py L609-620): getattr + try/except + coroutine check
- `_get_tool_specs` (runner_v2.py L622-633): getattr + try/except + coroutine check
- `_llm_stream_with_retry`: 在 bridge_backend 委托 (未鸭子访问)

**改造方案**:
1. 新建 `apps/chat/agent/protocols.py` (~15 LOC)
2. 定义 `ChatServiceAdapter(Protocol)` 强制 3 方法接口
3. `ChatRunnerV2.__init__` type hint 改为 `chat_service: ChatServiceAdapter`
4. `ChatBridgeBackend` 自动满足 Protocol (3 方法已存在)

**风险**: 极低 (Protocol 不影响 runtime, 只在 type checker 报错; duck typing 测试已覆盖)

**测试覆盖**: 现有 `test_apps_chat_agent_runner_v2.py` 100+ stub 类自动满足 Protocol (因 Protocol 是结构化), 不需改

**预期收益**:
- 类型安全 (mypy / pyright 友好)
- IDE 跳转 (从 runner_v2 跳到 ChatBridgeBackend 实现)
- 鸭子访问改显式接口, 违反 LoD 缓解

**ROI 评估**: ⭐⭐ (中, 类型安全收益但当前测试已验证)

### 5.4 M-1: Slash Command Registry 装饰器 (中 ROI)

**问题**: `_build_default_command_router` 是 130 LOC 函数, 8 个命令 hard-code 在 orchestrator 源。新增 slash command 需:
1. 修改 orchestrator.py (违反 OCP)
2. 测试 orchestrator 构造逻辑

**改造方案**:
1. `apps/chat/command_router.py` 新增 `SlashCommandRegistry` 全局 dict
2. 装饰器 `@slash_command("/name", tier="exact")` 自动注册
3. `_build_default_command_router` 改为遍历 `SlashCommandRegistry.all()`

**风险**: 中 (改注册路径, 8 个 inline 闭包需外提为 module-level 函数, 与 M-4 重叠)

**测试覆盖**: 现有 command tests 继续工作, 但 `_build_default_command_router` 测试需更新

**预期收益**:
- 加 slash command 不需改 orchestrator (OCP 符合)
- 命令注册路径统一 (与 `register_provider` 同模式)

**ROI 评估**: ⭐⭐ (中, 实施成本与 M-4 重叠, 收益主要在加命令场景)

---

## 6. 不推荐的 5 个候选 (避免过度设计)

### 6.1 ❌ ChatEvent 抽 EventFactory ABC

**理由**: SSE 契约是 `dict[str, Any]`, 前端按 key 取值 (`event.get("content", "")`)。改为 dataclass 会破坏 SSE 契约 + WebSocket 翻译。`events.py` 常量已是"类型字典键"层面的单一真源, 满足需求。

### 6.2 ❌ GoalPredicateStrategy 抽象

**理由**: 当前只有 1 个策略 (active-only metadata query), 抽象成 Strategy 模式违反 YAGNI。`_goal_active_predicate` closure 简单, 直接 inline 在 orchestrator 可读性更好。

### 6.3 ❌ ToolRegistryFactory 抽独立类

**理由**: `_get_tool_registry` 是 orchestrator 私有方法, 抽到独立工厂类引入新 indirection, 但仍需传 orchestrator 实例 (cache key 依赖 orchestrator 状态)。当前 cache 已 working。

### 6.4 ❌ ChatRunnerFactory Protocol

**理由**: 单一实现 (`ChatRunnerV2`), Protocol 抽象过早。SubagentManager 仍未接 ABC (Phase 16+ 待办), 现阶段改造成本远超收益。

### 6.5 ❌ Visitor / Interpreter 应用

**理由**: 业务场景不匹配。chat 数据结构简单, 无 DSL 需求。

---

## 7. nanobot 借鉴对账 (已实施 12/15 项)

`docs/poc/nanobot-framework.md` 列出的 A1-A6 借鉴方向, **当前 llmwikify 已实施 12 项**:

| 借鉴项 | nanobot 来源 | llmwikify 实施 | 状态 |
|---|---|---|---|
| A2 OpenAI-compat | `api/server.py` (399 LOC) | `apps/api/openai_server.py` (P1-1) | ✅ |
| A1 WebSocket | `channels/websocket.py` (1907 LOC) | `apps/chat/channels/websocket.py` (Phase 14) | ✅ |
| CommandRouter | `command/router.py` (88 LOC) | `apps/chat/command_router.py` (P1-2) | ✅ |
| AgentHook 钩子 | `agent/hook.py` (141 LOC, 9 钩子) | `foundation/callback/composite.py` (13 钩子) | ✅ |
| Microcompact | `_COMPACTABLE_TOOLS` | `apps/chat/agent/microcompact.py` (85 LOC, default ON) | ✅ |
| Consolidator + Dream | `agent/memory.py` (444 + 859) | `apps/chat/memory/consolidator.py` + `dream.py` (Phase 6) | ✅ |
| MessageBus | `bus/queue.py` (103 LOC) | `apps/chat/bus/queue.py` (Phase 13) | ✅ |
| SubagentManager | `agent/subagent.py` (392 LOC) | `apps/chat/agent/subagent_manager.py` (Phase 10-E) | ✅ |
| StateTrace | `observability.StateTraceEntry` | `runner_v2.py:_StateTraceEntry` | ✅ |
| AgentRunner ABC | `agent/runner.py` (~700 LOC) | `apps/chat/agent/agent_runner.py` (Phase 15) | ✅ |
| Goal State | `session/goal_state.py` | `apps/chat/agent/goal_state.py` | ✅ |
| Thinking Style 4 模式 | `providers/base.py` `_THINKING_STYLE_BUILDERS` | `foundation/llm/streamable.py` (M1) | ✅ |
| Anthropic native | `providers/anthropic_provider.py` (~400 LOC) | 未实施 (P2-2 暂缓) | ❌ |
| WebSocket vendor 完整 | channels/websocket 1907 LOC | Phase 14 已简化版, 非完整 vendor | 🟡 |
| bus/session deep 整合 | `session/manager.py` (740 LOC) | 未实施 (P3-3 否决) | ❌ |

**未借鉴 3 项均为高成本 / 低收益**:
- Anthropic native: 业务未提需求
- WebSocket 完整 vendor: 当前简化版足够
- Bus+session deep 整合: 改写成本 > 收益

---

## 8. Pass5+ 执行建议

### 8.1 立即可执行 (Pass5)

| 项 | 改动 | LOC Δ | 测试 |
|---|---|---:|---|
| **M-4** CommandRouter 闭包外提 | 新建 `apps/chat/agent/builtin_commands.py` (~120 LOC) + orchestrator.py -100 LOC | net +20 | orchestrator_goal_command + command_router + memory_consolidator + new builtin_commands tests |

### 8.2 后续 (Pass6+)

| 项 | 时机 | 备注 |
|---|---|---|
| M-2 ChatServiceAdapter Protocol | Pass6 | 类型安全收益中等 |
| M-1 Slash Command Registry 装饰器 | Pass7+ (与 M-4 部分重叠) | OCP 符合收益 |
| Phase 8 microcompact metrics HTTP endpoint | 独立任务 | 不在本范围 |
| Phase 9 memory consolidation + reproduction cross-system query | 独立任务 | 跨域协调者 |
| SubagentManager 真接 AgentRunner ABC | Phase 16+ | LSP 符合 |
| v0.5 CHANGELOG + version bump | Phase 5+6+7+Pass4-C 累计 | release 准备 |

### 8.3 不执行 (过度设计)

- ChatEvent ABC / GoalPredicateStrategy / ToolRegistryFactory / ChatRunnerFactory / Visitor / Interpreter

---

## 9. 模式应用快速参考 (供后续模块借鉴)

新增模块时, 按以下决策树选择模式:

```
需要创建一组相关对象?
  ├─ 是 → Abstract Factory (Protocol + 注册器)
  └─ 否 → 仅创建单一对象
        ├─ 全局唯一 → Singleton (模块级变量)
        └─ 普通 → Factory Method (静态工厂函数)

需要统一高层接口给多个子系统?
  ├─ 是 → Facade
  └─ 否 → 直接调用

需要包装现有对象添加职责?
  ├─ 静态 (编译期) → Decorator (类继承)
  └─ 动态 (运行期) → Decorator (Python 装饰器)

需要控制对象访问?
  ├─ 延迟加载 → Proxy (lazy)
  └─ 接口转换 → Adapter

需要一组算法可互换?
  ├─ 是 → Strategy (dict 注册或 ABC)
  └─ 否 → 直接调用

需要通知多个对象状态变化?
  ├─ 一对多 → Observer
  └─ 集中协调 → Mediator

需要保存/恢复对象状态?
  ├─ 是 → Memento
  └─ 否 → 不需要

需要根据状态改变行为?
  ├─ 是 → State
  └─ 否 → 直接 if/else

需要链式处理请求?
  ├─ 是 → Chain of Responsibility
  └─ 否 → 不需要

需要把请求封装为对象 (含撤销/队列)?
  ├─ 是 → Command
  └─ 否 → 直接调用

需要统一处理树形结构?
  ├─ 是 → Composite
  └─ 否 → 不需要
```

---

## 10. 数据来源

### Python 设计模式

- 菜鸟教程: https://www.runoob.com/python-design-pattern/python-design-pattern-intro.html
- 23 GoF 模式 + 6 原则 (OCP/LSP/DIP/ISP/LoD/CRP)
- Python 动态特性专题 (简单工厂 / 装饰器内置 / 模块单例)

### llmwikify 实施对账

- chat 模块: `src/llmwikify/apps/chat/` (~7000 LOC) + `src/llmwikify/foundation/` (~3000 LOC)
- 测试覆盖: `tests/test_apps_chat_*.py` (~50 文件, ~3000 cases)
- nanobot 借鉴文档: `docs/poc/nanobot-framework.md` (Phase 2 产出, 670 LOC)
- chat vs nanobot 对比: `docs/poc/compare.md` (774 LOC)

### 历次重构 commit

- Phase 5 God Class Split (`da870d9` ~ `793cf1b`): 4 god class → 30 个小文件, 拆 facade/manager
- Pass2 (`115c033`): 消除重复与死代码, 抽 `foundation/utils.py` + `_StubSkillContext` 简版
- Pass3-A (`69fbb7e`): `_state_get` 跨文件共享, research_bridge 简化
- Pass3-B+A2 (`cf18ac3`): SSE events.py 单一真源, runner_v2 + orchestrator 全 events.*
- Pass4-C (`27bc5c8`): `_make_skill_ctx` 工厂 + `_build_chat_runner_v2` 内拆 + `chat_persistence.py` 抽出 + `WSTranslatedType` alias to events
- HEAD: `27bc5c8` (Pass4-C), 837 tests pass

---

## 11. 不在本范围

- ❌ 直接 import 任何设计模式库 (`factory-boy` / `python-patterns` 等) — 违反 stdlib-first 原则
- ❌ 改造 `apps/research/` / `apps/api/` 模块设计模式 — 用户限制仅 chat 模块
- ❌ 写设计模式教程 — 已有菜鸟教程 + GoF 原著
- ❌ 重构 `AgentRunner` ABC 接口 — Phase 15 已稳定
- ❌ 改 AGENTS.md — 规约文件修改需用户明确同意

---

## 12. 后续 Phase (2026 Q3-Q4)

- **Pass5** (本季度): M-4 CommandRouter 闭包外提
- **Pass6** (下季度): M-2 ChatServiceAdapter Protocol + Phase 8 microcompact metrics
- **Pass7+**: M-1 Slash Command Registry 装饰器 + Phase 9 cross-system query
- **Phase 16+**: SubagentManager 真接 AgentRunner ABC (LSP 完整)
- **v0.5 release**: CHANGELOG + version bump (Phase 5+6+7+Pass4-C 累计)