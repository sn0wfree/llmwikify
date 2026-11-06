# unified 循环方案处置计划 · 2026-11-06

> 对应 [feature-completeness-2026-11.md](../diagnostics/feature-completeness-2026-11.md) **C6**
> 与 [code-survey-2026-11.md](../diagnostics/code-survey-2026-11.md) §5.1 / §7-建议2。
> **状态：已标记、暂缓执行**（见 §1 定位约束）。

---

## 1. 定位约束（决定优先级）

**本项目的核心是知识处理（ingest / index / lint / graph / 检索），不是 agent 框架。**
`apps/chat/agent/` 与 `kernel/agent/` 是支撑聊天入口的配套设施，不承载项目主线价值。
因此本项处置**不进入当前批次**，仅完成分析与标记；执行时机等知识处理主线告一段落。

---

## 2. 现状事实

| 项 | 数据 | 来源 |
|---|---|---|
| 死树规模 | 13 文件 / 43582 字节（约 1165 LOC） | `apps/chat/agent/unified/**` 实测 |
| 生产入口 | **0**（导入图 BFS 不可达，入口取 `__main__` + `interfaces.cli\|server\|mcp\|web`） | code-survey §5.1 |
| 测试引用 | 9 个文件：`test_unified_{chat,chat_extra,codegen,codegen_extra,core,loop,loop_extra,registry,steps}.py` | 本轮 grep |
| 生产实际走哪 | `ChatRunnerV2`（`apps/chat/agent/runner_v2.py`，42708 字节），自带 `_reason / _act / _observe / _emit_done`，**不实例化** `UnifiedAgentLoop` | `runner_v2.py:215,437,637,807` |
| 通用框架本体 | `kernel/agent/`（`UnifiedAgentLoop` / `StepHandler` / `Spec` / steps），生产仅消费 `AgentExecutionContext` | `runner_v2.py:202` 等 3 处 |
| 包内自陈 | `registry.py:169,207` `except ImportError: pass  # Phase 6 / Phase 4 未实现时跳过` | 源码 |

历史：通用框架原在此树，后整体迁往 `kernel/agent/`，本树退化为 re-export shim +
mode 注册表（chat mode / codegen mode）。chat 主链路随后固化为 `ChatRunnerV2`，
这层注册表即失去生产调用方（AGENTS.md「backward-compat shim 保留」登记的是
shim 部分，未覆盖 mode 注册表的死链事实）。

---

## 3. 重复证据（本轮实测）

### 3.1 事件常量 — 真子集关系

| | 数量 | 差异 |
|---|---:|---|
| `apps/chat/agent/events.py` | 16 | — |
| `apps/chat/agent/unified/events.py` | 21 | 多 `REASONING` `TIMEOUT` `ROUND_COMPLETE` `ACTION_ERROR` `OBSERVATION_ERROR` |

**生产侧 16 个全部包含于 unified 侧**（`only in main = ∅`）。两份常量是漂移风险点：
改一处忘另一处，ruff/mypy/测试均不报错。

### 3.2 方法级重复 — 同名同职责各写一遍

| 职责 | ChatRunnerV2 | unified handler |
|---|---|---|
| 系统提示构建 | `runner_v2.py:394 _build_system_prompt` | `handlers/chat_reasoner.py:149` |
| 消息截断 | `runner_v2.py:920 _safe_truncate` | `chat_reasoner.py:175` |
| 工具 spec 收集 | `runner_v2.py:928 _get_tool_specs` | `chat_reasoner.py:188` |
| LLM 流式调用 | `runner_v2.py:937 _stream_llm` | `chat_reasoner.py:201` |
| 工具执行 | `runner_v2.py:996 _execute_tool` | `handlers/tool_actor.py:191` |
| microcompact | `runner_v2.py:812 _microcompact_result` | `tool_actor.py:217` |

`unified/handlers/`（`chat_reasoner.py` 9539 B + `tool_actor.py` 8376 B ≈ 18 KB）
是 `ChatRunnerV2` 的**平行重写**：同一套 ReAct 逻辑，一边抽成 handler 类供
`UnifiedAgentLoop` 组合，一边内联在 RunnerV2 循环里。

### 3.3 spec 两套抽象

| | 定义 | 基类 |
|---|---|---|
| 生产 | `apps/chat/agent/spec.py:33 ChatRunSpec` | 独立 dataclass（`ChatRunResult` :76） |
| unified | `apps/chat/agent/unified/spec.py:36 ChatSpec` | `kernel.agent.spec.BaseSpec` |

字段有重叠但归属不同抽象，直接合并需先确定「以谁为契约」。

---

## 4. 设计逻辑与评价

### 4.1 它想解决什么

`UnifiedAgentLoop`（`kernel/agent/loop.py`，301 行）把 ReAct 循环从「一个大函数」
改成**配置驱动的状态机**，骨架即文档（`loop.py:6`）：

```
PRECHECK → [REASON → DECIDE① → ACT → DECIDE② → OBSERVE → DECIDE③] → FINALIZE
```

具体行为全部由构造参数注入：

| 注入点 | 职责 | 已有实现 |
|---|---|---|
| `reasoner` | 怎么思考 | `handlers/chat_reasoner.py ChatReasoner` |
| `actor` | 怎么行动 | `handlers/tool_actor.py ToolActor` / `kernel.agent.CodeActor` |
| `deciders: {位置 → StepHandler}` | 三个检查点各自决定是否停（返回 `(stop, reason)`） | `steps/checks.py CheckEmptyStep` `CheckSuccessStep` |
| `hook` | 16 个生命周期切面 | `hook_adapter.py AgentHookAdapter` → `foundation/callback` |
| `precheck` / `finalize` | 进入前校验、收尾改写 | `registry.py` 按 mode 装配 |

底下只有两个抽象（`kernel/agent/_core_types.py`）：

- **`StepHandler`** — 无状态单次 `handle() → StepResult`，用于 decider 与纯计算
- **`StreamingHandler`** — 有状态多次 yield，**最后一个 yield `StepResult` 当终止信号**，用于流式 reasoner/actor

`StepResult{output, events, success, error}` 把「步骤产出」与「SSE 事件」打包成
一个返回值；`Pipeline` 把 step 串起来（上一个 output 喂下一个，fail-fast）；
`AgentModeConfig` 注册表把整套装配命名成 mode，`create_agent_loop("chat")` 按名取。

对应 GoF：**模板方法（骨架）+ 策略（reasoner/actor/decider 可换）+ 组合（Pipeline）
+ 注册表工厂（mode）**。`ChatRunnerV2` 是同一套流程的内联写法。

### 4.2 可取之处

| # | 设计点 | 价值 |
|---|---|---|
| 1 | 循环骨架 301 行、单一真相 | 迭代上限、cancel/pause、异常兜底、finalize、`done` 事件全集中；`ChatRunnerV2` 里这些散在 42 KB 内联逻辑中 |
| 2 | **decider 显式可插拔** | 「在哪停」变成配置：加一种停止条件 = 加一个 decider，不动循环。RunnerV2 的停止判断散在 `_reason`/`_act` 内部的 if 里 |
| 3 | `StepResult` 统一流式/非流式 | 事件随返回值走，不靠边走边 yield，**可测性好**；`Pipeline` 才能统一组合两种步骤 |
| 4 | `Pipeline` 组合 | codegen 的 `LLM调用 → 提取 → 校验 → 执行` 由配置拼出，无编排代码 |
| 5 | 两种 handler 的分类从需求反推 | docstring 写明 `TextModeParser` 状态机、microcompact 双输出**为何必须**用 `StreamingHandler`——踩过坑留下的分类，非凭空设计 |
| 6 | hook 与 loop 解耦 | 16 切面 + `CompositeHook` fan-out，**已是生产事实**（`foundation/callback` 被 RunnerV2 直接使用） |

### 4.3 局限（为什么没被采用）

| 问题 | 证据 |
|---|---|
| 泛化换来类型失控 | `getattr(spec, ...)` 散布（`loop.py:63,76,80,227`）；chat/codegen 分支靠 `hasattr` 探测 |
| `UnifiedResult` 契约太弱 | `loop.py:279-282` 用 `hasattr(last_act, "code")` / `"output"` 鸭子探测 |
| 角色间隐式耦合 | `loop.py:297-299` `getattr(self._reasoner, "_chat_service")` 抽别的角色私有属性，接口没兜住 |
| 框架先行 + 没接线 | 建好后主链路另写一套 → 平行演化出 §3.2 的 6 组重复 |

**结论**：设计模式可取、抽象成本过高；失败点在「先建框架、后接线」而非设计本身。
故 §5 方向 A 应理解为**吸收零件、砍重复实现**，不是连锅端。

---

## 5. 两个可选方向

| | **A：往生产侧合（保守）** | **B：往框架侧合（彻底）** |
|---|---|---|
| 做法 | 事件常量取超集成一份，两边 re-export；handlers 的 6 组重复方法收敛（删或改为委托 RunnerV2）；unified 仅保留 codegen mode | 把 `ChatRunnerV2` 的 `_reason/_act/_observe/_emit_done` 重构为 `UnifiedAgentLoop` + reasoner/actor/deciders 组合，全仓只剩一套循环 |
| 消除 | 常量漂移、~18 KB 重复实现、双 spec 误读 | 上述全部 + 架构上单一循环概念 |
| 风险 | 低：不碰 chat 主链路时序 | 高：SSE 事件时序、microcompact、timeout、text mode 解析、`_StateTrace` 全在 RunnerV2 内联逻辑里，任一语义丢失即生产事故 |
| 隐含前提 | 无 | 需先证明 `UnifiedAgentLoop` 的 decider/hook 模型能完整承载 RunnerV2 现有语义（含 microcompact 挂载点、`_call_service_method` 反射调用、duration_ms 计时） |
| 工作量 | 1–2 轮，每轮可独立回归 | 大：需完整 SSE 契约测试 + 浏览器实测 |

**codegen mode 单独判断**：`CodegenReasoner` / `generate_factor_code` 生产零引用
（仅 `unified/pipelines` 自引 + 测试），与 `kernel/codegen` 工具链同属「建好未接线」。
若无量化复现需求回归，B 方向也应连同它一起决定去留，而不是默认保留。

---

## 6. 建议

1. **首选 A**，理由：本项目价值在知识处理，第二套循环没有存在理由，那就该收敛到一套；
   A 已能消除全部漂移与重复，且不承担主链路风险。
2. **A 的第一步是事件常量合并**（§3.1）：取 21 个超集为唯一真源，
   `apps/chat/agent/events.py` 改为 re-export；零行为变化，可独立 commit + 回归。
3. **B 暂不启动**。启动前必须回答：为什么要两套循环？若答不出，做 A 收敛即可。
4. 无论 A/B，**先补一个契约测试**锁住当前 `ChatRunnerV2` 的 SSE 事件序列
   （已有 `test_sse_contract_*` 可扩展），否则重构无安全网。

## 7. 分阶段（待授权后执行）

| Phase | 内容 | 风险 | 状态 |
|---|---|---|---|
| 0 | 分析 + 本文档 + 代码/报告标记 | 极低 | ✅ 2026-11-06 |
| 1 | 事件常量合并（超集 + re-export） | 极低 | 待授权 |
| 2 | 6 组方法收敛（先定真源再删平行实现） | 中（触 RunnerV2 内部） | 待授权 |
| 3 | 循环本体二选一（含 codegen mode 去留） | 高 | 需产品决策 |

## 8. 复现

```bash
graphify update .                                   # 图谱（环 / 社区 / god nodes）
# 生产可达性：以 __main__ + interfaces.{cli,server,mcp,web} 为入口做导入图 BFS
rg -n "create_agent_loop|CodegenReasoner" src tests   # unified 的全部引用面
# 事件常量差集
python -c "import re,pathlib; a=set(re.findall(r'^([A-Z_][A-Z0-9_]+)=',pathlib.Path('src/llmwikify/apps/chat/agent/events.py').read_text(encoding='utf-8'),re.M)); b=set(re.findall(r'^([A-Z_][A-Z0-9_]+)=',pathlib.Path('src/llmwikify/apps/chat/agent/unified/events.py').read_text(encoding='utf-8'),re.M)); print(a-b, b-a)"
```
