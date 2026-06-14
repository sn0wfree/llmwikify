# LLM Access Layer（LAL）— 一体化设计规范

> 仓库级 LLM 配置与调用栈治理规范。当前版本：v1.0（设计稿，待 PR 1 实施）
>
> 关联文档：[`llm-inventory.md`](../llm-inventory.md) · [`llm-access-layer-migration.md`](./llm-access-layer-migration.md)

---

## 0. 背景与动机

仓库当前存在 3 条并行的 LLM 调用栈，配置真相分散在 4+ 个地方，并有 5+ 处静默 fallback 到 `openai/gpt-4o`：

| 调用栈 | 入口 | 解析 provider 方式 | 默认值 |
|---|---|---|---|
| `LLMClient`（同步） | `foundation.llm_client.LLMClient` | `from_config` 直接读 `llm.*` | `provider=openai, model=gpt-4o` |
| `StreamableLLMClient` | `foundation.llm.streamable.StreamableLLMClient` | `from_config` 读 `llm.*` | `provider=openai, model=gpt-4o` |
| Provider Registry | `apps.chat.providers.*` | `provider.from_config(llm_cfg)` | 各 provider 内置 |

加上：
- subagent 进程**没有**从父进程继承 LLM 配置的通道
- workflow YAML `actor.model` 硬编码 `sonnet/opus`，runtime 还要靠 `inherit` 关键字
- `inherit` 解析逻辑是「读不到 actor.model 就用 None → LLMClient 默认值」
- 业务代码多处 `getattr(model, "model", "gpt-4o")` 兜底
- `LLMSettings.tsx EMPTY_CONFIG` 默认 `minimax/MiniMax-M3`

**结果**：开发者无法回答「Chat 现在到底用哪个模型？」——8 个调用点都可能有不同行为。

LAL 的目标是把上述问题一次性收敛。

---

## 1. 五大硬约束（C1–C5）

### C1 单一解析入口（Single Resolver）
仓库里**只能有 1 个**函数负责把「环境变量 / wiki 配置文件 / UI 设置 / 旧 alias」解析为统一的运行时契约：

- `llmwikify.foundation.llm.resolver.resolve_chat_llm(config=None) -> LLMSpec`

任何其它解析路径（`LLMClient.from_config` / `StreamableLLMClient.from_config` / `provider.*.from_config`）必须**委派**到此函数；不允许自行读 `llm.*`、自行写默认值。

### C2 单一 Client 抽象（Single Client）
全仓 LLM 客户端**只剩一个实现**：`StreamableLLMClient`（OpenAI 兼容 + 流式）。
- 旧 `LLMClient` 降级为 shim，内部委派到 `StreamableLLMClient`
- 业务调用入口收敛为两个方法：
  - `complete(messages, **gen) -> str`（同步）
  - `stream(messages, **gen) -> Iterator[str]`（流式）
- 旧 `chat(messages, json_mode=...)`、`achat(...)` 等兼容方法由 shim 转发

### C3 配置可传递到所有执行单元（Propagatable Config）
subagent / kernel engine / workflow actor / agent service 等**任何**执行单元都**不**自行解析 LLM 配置。它们只能接收一个**已解析的、不可变的 `LLMSpec`**。
- `SubagentRequest` 新增 `llm: LLMSpec`
- `actor.model` 字段语义：**覆盖**而非**指定**
  - 缺省 → 用 `LLMSpec.model`
  - 写具体字符串 → 校验通过后覆盖
  - 写 `sonnet` / `opus` / `haiku` 等 provider-specific alias → 校验失败必须 fail-fast
- 移除 `actor.model="inherit"` 关键字（业界无此概念，简化语义）

### C4 workflow DSL 强校验（Strict DSL）
- workflow YAML 的 `actor.model` 字段：
  - 缺省 / 写具体 model name 允许
  - 写其它字符串 → runtime 启动时校验是否在 `provider.supported_models` 内
  - 校验失败 → workflow 启动直接 fail，**不进入任何 phase**
- actor prompt frontmatter **禁止**写 `model:` 行（runtime 忽略，但保留也无影响；本规范不动 actor prompt）
- 移除所有 hardcoded `sonnet` / `opus` / `haiku`

### C5 失败语义统一（Uniform Failure）
- 4 类错误类型，每类带 `action` 字段供前端识别
- 默认行为：**never silently fallback to `openai/gpt-4o`**
- 任何缺失配置 → 抛 `LLMNotConfiguredError` + `action="go-to-llm-settings"`

---

## 2. 配置优先级与合并规则

| 优先级 | 来源 | 解析时机 | 说明 |
|---|---|---|---|
| P0 | 环境变量 `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_PROVIDER` | resolver 启动 | 用于容器/CI 覆盖 |
| P1 | wiki 配置 `llm.*` 字段 | resolver 启动 | 用户在 `LLMSettings` 保存的 |
| P2 | provider 内置默认值 | provider 注册时 | 仅作为「字段缺失时的占位」，**不是兜底** |
| P3 | resolver 旧 id alias | resolver 阶段 | `minimax` → `minimax` 自动映射 |

**合并规则**：
- env 优先于 config（env 显式胜出）
- 同一字段若 P0/P1 都缺失 → 抛 `LLMNotConfiguredError`，**不**用 P2 默认值
- P2 默认值**仅**用于「字段缺失但已显式禁用 LLM」场景下的「UI 占位」，不参与运行时
- alias 映射只对 `provider` 字段生效，其它字段不动

---

## 3. 核心数据类型：`LLMSpec`

```python
@dataclass(frozen=True)
class LLMSpec:
    provider: str              # 已 alias 解析后的 provider id
    base_url: str
    api_key: str               # 已 env 展开（env:VAR → 实际值）
    model: str
    context_window: int | None
    timeout: float
    reasoning_split: bool
    auth_scheme: str           # "bearer" | "api-key"
    extra_headers: dict[str, str]
    source: str                # "ui" | "env" | "config" | "merged"
```

- `frozen=True` 保证下游不可修改
- `source` 字段强制填充，便于观测
- 序列化：`dataclass(frozen=True)`，不暴露 setter
- 位于 `src/llmwikify/foundation/llm/spec.py`

**`LLMSpec` 是 LAL 的「真理源」**：配置源 → resolver → `LLMSpec` → 所有执行单元。

---

## 4. 4 类错误类型

所有错误继承 `LLMError`，均带 `action` 字段供前端识别。

| 错误类 | 触发条件 | `action` 字段 | 前端行为 |
|---|---|---|---|
| `LLMNotConfiguredError` | `enabled=False` / `api_key` 缺失 / `provider` 缺失 | `"go-to-llm-settings"` | 自动跳转 `/llm-settings` |
| `LLMModelNotSupportedError` | `model` 不在 `provider.supported_models` | `"select-supported-model"` | toast + 显示可用 model 列表 |
| `LLMSpecMismatchError` | subagent `actor.model` 与 `LLMSpec.model` 冲突且校验失败 | `"fix-workflow-yaml"` | workflow run 状态 `failed`，timeline 显示 |
| `SubagentLLMError` | subagent 进程内 LLM 调用异常 | `"retry-or-check-provider"` | phase 状态 `failed`，error.output 落盘 |

错误对象结构：
```python
class LLMError(Exception):
    def __init__(self, message: str, action: str, path: str | None = None):
        super().__init__(message)
        self.action = action
        self.path = path  # e.g. "/llm-settings"
```

**前端处理逻辑**（伪代码）：
```python
# ChatOrchestrator
try:
    response = streamable_client.complete(messages)
except LLMError as e:
    yield ChatEvent.error_with_action(
        message=str(e),
        action=e.action,
        path=e.path
    )
    # 前端识别 action 后自动跳转或显示强引导
```

---

## 5. 数据流（4 条主路径）

### 5.1 路径 1：Chat 主链路

```
用户消息
  → ChatOrchestrator
      → resolver.resolve_chat_llm(wiki.config) → LLMSpec
      → StreamableLLMClient(llm_spec).complete(messages)
      → ChatEvent 流式返回
```

**关键点**：
- `agent_service` / `orchestrator` / `context_manager` **不**直接读 `llm.*`
- 它们只接收 `LLMSpec`（由 `resolver` 在启动时解析一次）
- 移除所有 `gpt-4o` / `gpt-4` fallback（PR 4）

### 5.2 路径 2：Subagent（workflow 编排）

```
ChatOrchestrator
  → spawn subagent:
      SubagentRequest(
        actor, actor_prompt, actor_tools, actor_permission_mode,
        inputs, budget, session_id, worktree_path,
        llm: LLMSpec  ← 父进程解析好的完整 LLM 契约
      )
  → subagent process:
      LlmClientDriver.complete(messages, model=actor.model)
        → 若 actor.model 缺省：用 llm.model
        → 若 actor.model 写具体字符串：校验 → 覆盖 llm.model
        → 构造 StreamableLLMClient(llm_spec_with_override)
        → 调用 LLM
```

**关键点**：
- subagent 进程**不**读 env，**不**读 wiki config
- `actor.model` 是「覆盖」而非「指定」
- 校验失败 → `LLMSpecMismatchError`，phase 状态 `failed`

### 5.3 路径 3：Workflow DSL 校验

```
workflow.yaml 加载
  → WorkflowSpec 解析
  → resolver 解析 LLMSpec
  → 对每个 actor.model 校验：
      缺省 → 用 LLMSpec.model
      字符串 → 在 provider.supported_models 内才允许
  → 校验失败 → WorkflowValidationError，workflow 启动失败
  → 校验通过 → 进入运行时
```

**关键点**：
- 启动前 fail-fast，**不**进入任何 phase
- 灰度开关 `LLM_ALLOW_ALIAS_MODEL=true` 可临时放行

### 5.4 路径 4：旧 Kernel / Engine 兼容

```
kernel.wiki.engines.analyzer
  → LLMClient.from_config(wiki.config)  # shim
      → resolver.resolve_chat_llm(wiki.config) → LLMSpec
      → StreamableLLMClient(llm_spec)
  → 调用 LLM
```

**关键点**：
- 旧 `LLMClient` 保留为 shim，委派到 `StreamableLLMClient`
- 旧 kernel / engine 走同一 resolver

---

## 6. 调用栈收敛图

```
┌────────────────────────────────────────────────────────────┐
│  配置源：env / wiki config / UI settings / 旧 id alias     │
└────────────────────────────────────────────────────────────┘
                        ↓ 解析
        ┌──────────────────────────────┐
        │  resolver.resolve_chat_llm   │  ← 唯一解析入口
        │  返回 LLMSpec（frozen）        │
        └──────────────────────────────┘
                        │
        ┌───────────────┼───────────────────────┐
        ↓               ↓                       ↓
  Chat 主链路      Provider Registry       Subagent Driver
  (agent_service,  (providers/*.py:        (subagent_worker.
   orchestrator,    from_config)            LlmClientDriver)
   context_manager)                          │
        │               │                       │
        └───────────────┴───────────────────────┘
                        ↓
        ┌──────────────────────────────┐
        │  StreamableLLMClient          │  ← 唯一 client 实现
        │  - complete(messages) -> str  │
        │  - stream(messages) -> iter   │
        └──────────────────────────────┘
                        ↓
                 HTTP 调用 LLM Provider
```

---

## 7. provider id 改名

| 字段 | 旧值 | 新值 |
|---|---|---|
| provider id | `minimax` | `minimax` |
| default base_url | `https://api.minimaxi.com/v1` | 不变 |
| default model | `MiniMax-M3` | `minimax-M3` |
| provider 文件 | `providers/minimax.py` | `providers/minimax.py` |
| 类名 | `MiniMaxProvider` | `MiniMaxProvider` |

**为什么改名**：
- 与 host 域名 `minimaxi.com` 视觉对齐
- 全小写，与「model 即字符串」语义一致
- 切断「看到 `minimax` 就以为是别家模型」的心智陷阱

**兼容策略**：resolver 阶段 alias 映射 `minimax` → `minimax`，老 wiki 配置无需手动改。

**UI 展示**：
- `LLMSettings.tsx` 的 `PROVIDERS` 数组第一项改为 `minimax`
- `MODEL_OPTIONS.minimax` / `BASE_URL_DEFAULTS.minimax` 键名同步
- `EMPTY_CONFIG.provider` 改为 `minimax`
- 显示标签（`label`）改为「MiniMax」

---

## 8. 灰度开关清单

| 开关 | 作用域 | 默认值 | 行为 |
|---|---|---|---|
| `LLM_USE_RESOLVER` | PR 1 | `true` | `false` 时旧 `from_config` 走原路径 |
| `LLM_SUBAGENT_INHERIT` | PR 2 | `true` | `false` 时 subagent 读 env + warning |
| `LLM_ALLOW_ALIAS_MODEL` | PR 3 | `false` | `true` 时放行 `sonnet/opus/haiku` alias |
| `LLM_LEGACY_FALLBACK` | PR 4 | `false` | `true` 时保留 `gpt-4o` 兜底（仅 PR 4 验证期） |

**回退策略**：
- PR 1 出问题 → `LLM_USE_RESOLVER=false`，立即回退
- PR 2 出问题 → `LLM_SUBAGENT_INHERIT=false`，subagent 回退到 env 读取
- PR 3 出问题 → `LLM_ALLOW_ALIAS_MODEL=true`，放行旧 alias
- PR 4 出问题 → `LLM_LEGACY_FALLBACK=true`，保留兜底

PR 4 验证通过后**删除** `LLM_LEGACY_FALLBACK` 开关（不留后门）。

---

## 9. 4 个 PR 的范围

### PR 1：Stage 1（LAL 骨架）— 完全不破坏
- 新增 `foundation/llm/spec.py`：`LLMSpec` dataclass
- 新增 `foundation/llm/resolver.py`：`resolve_chat_llm` + alias 表
- `StreamableLLMClient` 加 `complete(messages) -> str` 同步方法
- `LLMClient.from_config` 委派到 resolver（**保留** `gpt-4o` 默认值，PR 4 再删）
- `StreamableLLMClient.from_config` 委派到 resolver
- `provider.*.from_config` 委派到 resolver
- 灰度开关 `LLM_USE_RESOLVER`
- 测试：resolver 优先级 / alias 映射

### PR 2：Stage 2（subagent 继承）— 完全不破坏
- `SubagentRequest` 增 `llm: LLMSpec` 字段
- `LlmClientDriver.complete` 重写：基于 `llm` 构造 client
- `actor.model` 校验：只有当前 provider supported 时才覆盖
- `ChatOrchestrator` spawn subagent 时注入 `LLMSpec`
- 灰度开关 `LLM_SUBAGENT_INHERIT`（`false` 时读 env + warning）
- 测试：subagent 继承

### PR 3：Stage 3（workflow 治理）— 小破坏
- `autoresearch-compound.yaml`：删 `model: sonnet/opus` 行（直接删字段）
- `llmwikify-research.yaml`：删 `model: sonnet/opus` 行
- actor prompt frontmatter **不动**（runtime 忽略，无影响）
- `WorkflowSpec` validator 加 `actor.model` 校验
- 灰度开关 `LLM_ALLOW_ALIAS_MODEL`
- 测试：workflow 校验

### PR 4：Stage 4（失败语义 + 观测）— 大破坏
- 新增 4 类错误：`LLMNotConfiguredError` / `LLMModelNotSupportedError` / `LLMSpecMismatchError` / `SubagentLLMError`，带 `action` 字段
- `LLMClient.__init__` 默认 `provider=None` → 未配置抛 `LLMNotConfiguredError`
- `foundation.config.DEFAULT_CONFIG["llm"]`：所有字段设 `None` / `enabled=False`
- 删除所有 `gpt-4o` fallback（`service.py:668,764,940` / `context_manager.py:294-297` / `orchestrator.py:623` / `LLMClient.__init__` / `StreamableLLMClient.__init__`）
- token 估算**整个保留**（`token_estimator.py` / `token_budget.py` / `context_windows.py` 不动）
- `LLMSettings.tsx` `EMPTY_CONFIG` 改「未配置」状态
- provider id `minimax` → `minimax` 改名 + resolver alias
- 灰度开关 `LLM_LEGACY_FALLBACK`（验证期保留，PR 合并稳定后删）
- 测试：错误类型 / UI 状态 / provider alias

---

## 10. 验证步骤

每个 PR 完成后：
1. 跑全量单测：`pytest tests/ -q`
2. 跑 lint：`ruff check src/ tests/`
3. 跑前端 build：`cd ui/webui && npx vite build`
4. 手动 smoke：启动后端 → 配 LLM → 触发 `/study 研究：xxx` → 检查 `ResearchRunCard` timeline

---

## 11. 风险与缓解

| 风险 | 可能性 | 影响 | 缓解 |
|---|---|---|---|
| resolver bug 导致全仓 LLM 不可用 | 中 | 高 | 保留 `LLMClient` shim 兼容旧调用；Stage 1 完成后做 smoke test |
| subagent 注入 `LLMSpec` 失败 | 中 | 中 | Stage 2 完成后做端到端测试；失败时回退到「subagent 读 env + warning」 |
| workflow YAML 校验过严挡住旧 workflow | 高 | 低 | 提供 `LLM_ALLOW_ALIAS_MODEL=true` 临时放行 |
| provider id 改名 `minimax` 破坏老配置 | 中 | 中 | resolver alias 映射自动迁移 |
| 测试覆盖不足 | 中 | 中 | 强制要求 PR 4 包含测试矩阵 |

---

## 12. 相关文档

- [`llm-inventory.md`](../llm-inventory.md)：LLM 调用点盘点（迁移前必读）
- [`llm-access-layer-migration.md`](./llm-access-layer-migration.md)：旧调用点迁移指南
- 调研对照：LiteLLM / LangChain / Pydantic AI / OpenAI SDK / Vercel AI SDK / AutoGen
