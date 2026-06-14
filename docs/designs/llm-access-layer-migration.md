# LAL 迁移指南（Migration Guide）

> 本文档面向**维护者**，讲解如何把旧代码切换到 LAL 规范。
>
> 关联文档：[`llm-access-layer.md`](./llm-access-layer.md) · [`llm-inventory.md`](../llm-inventory.md)

---

## 0. 迁移原则

- **渐进迁移**：4 个 PR 逐步落地，**不**一次性大爆炸
- **灰度可控**：每个 PR 带 env 开关，出问题立即回退
- **测试先行**：每个 PR 自带测试矩阵
- **观测友好**：`LLMSpec.source` 字段记录配置来源

---

## 1. 错误对照表

### 1.1 旧行为 vs 新行为

| 旧行为 | 新行为 | PR |
|---|---|---|
| `LLMClient()` 无参数 → `provider=openai, model=gpt-4o` | `LLMClient()` 无参数 → 抛 `LLMNotConfiguredError` | PR 4 |
| `gpt-4o` token 兜底 | 拿不到时用 `unknown` + warning log | PR 4 |
| `actor.model="sonnet"` → runtime 默念「也许用 sonnet」 | 校验失败 → `LLMSpecMismatchError` | PR 3 |
| `actor.model="inherit"` → 解析为「父 client 的 model」 | 关键字删除，缺省 = 用 `LLMSpec.model` | PR 2/3 |
| `provider: minimax` 老配置 | resolver alias 映射，**无需改** | PR 4 |
| `LLMClient.from_config` 自己读 `llm.*` | 委派到 `resolver.resolve_chat_llm` | PR 1 |
| subagent 进程 `LLMClient()` 默认值 | subagent 进程用 `SubagentRequest.llm` 注入 | PR 2 |

### 1.2 错误类型映射

| 触发条件 | 旧抛什么 | 新抛什么 | `action` |
|---|---|---|---|
| LLM 未配置 | `ValueError("LLM API key not configured")` | `LLMNotConfiguredError` | `"go-to-llm-settings"` |
| model 不支持 | `ValueError("Model 'xxx' not supported")` | `LLMModelNotSupportedError` | `"select-supported-model"` |
| actor.model 校验失败 | （无校验，悄悄 fallback） | `LLMSpecMismatchError` | `"fix-workflow-yaml"` |
| subagent LLM 错 | `RuntimeError` | `SubagentLLMError` | `"retry-or-check-provider"` |

### 1.3 前端处理示例

```typescript
// 旧：仅 toast
if (error.message.includes('API key')) {
  toast.error('LLM 未配置');
}

// 新：识别 action 自动跳转
if (error.action === 'go-to-llm-settings') {
  toast.error(error.message);
  router.push(error.path || '/llm-settings');
}
```

---

## 2. 旧调用点切换

### 2.1 LLMClient 构造

**旧**：
```python
from llmwikify.foundation.llm_client import LLMClient

client = LLMClient()  # 默认 openai/gpt-4o
client = LLMClient.from_config(config)  # 自己读 llm.*
```

**新**：
```python
from llmwikify.foundation.llm.resolver import resolve_chat_llm
from llmwikify.foundation.llm.streamable import StreamableLLMClient

llm_spec = resolve_chat_llm(config)  # 唯一解析入口
client = StreamableLLMClient.from_spec(llm_spec)  # 唯一 client
response = client.complete(messages)
```

### 2.2 provider 注册

**旧**：
```python
class MyProvider(BaseLLMProvider):
    def from_config(self, config: dict) -> StreamableLLMClient:
        api_key = self._resolve_api_key(config)
        base_url = self._resolve_field(config, "base_url", self.default_base_url())
        model = self._resolve_field(config, "model", self.default_model())
        return StreamableLLMClient(
            provider=self.provider_name(),
            base_url=base_url,
            api_key=api_key,
            model=model,
            ...
        )
```

**新**：
```python
class MyProvider(BaseLLMProvider):
    def from_config(self, config: dict) -> StreamableLLMClient:
        from llmwikify.foundation.llm.resolver import resolve_chat_llm
        llm_spec = resolve_chat_llm(config)  # 委派 resolver
        return StreamableLLMClient.from_spec(llm_spec)
```

### 2.3 token 估算

**旧**：
```python
from llmwikify.foundation.llm.token_estimator import count_tokens

model_name = getattr(llm_client, "model", "gpt-4o")
tokens = count_messages(messages, model_name)
```

**新**（PR 4）：
```python
from llmwikify.foundation.llm.token_estimator import count_tokens

# 从 LLMSpec 取真实 model name
model_name = llm_spec.model  # 可能为 None
if model_name is None:
    logger.warning("LLM not configured, using conservative token estimate")
    model_name = "unknown"
tokens = count_messages(messages, model_name)
```

### 2.4 workflow actor.model

**旧**：
```yaml
actors:
  clarifier:
    model: sonnet
  planner:
    model: opus
  # 或
    model: inherit
```

**新**（PR 3）：
```yaml
actors:
  clarifier:
    # 缺省 = 用 LLMSpec.model
  planner:
    # 缺省 = 用 LLMSpec.model
  # 或显式覆盖
  synthesizer:
    model: minimax-M3  # 必须在校验白名单内
```

### 2.5 subagent 注入 LLMSpec

**旧**（PR 2 前）：
```python
request = SubagentRequest(
    actor_name=actor.name,
    actor_prompt_text=prompt_text,
    actor_model=actor.model,
    actor_tools=actor.tools,
    inputs=inputs,
    ...
)
# subagent 进程内：
client = LLMClient()  # 默认 openai/gpt-4o
```

**新**（PR 2 后）：
```python
# 父进程
request = SubagentRequest(
    actor_name=actor.name,
    actor_prompt_text=prompt_text,
    actor_model=actor.model,  # 覆盖语义
    actor_tools=actor.tools,
    inputs=inputs,
    llm=llm_spec,  # ← 新增：父进程解析好的 LLMSpec
    ...
)

# subagent 进程内
llm_spec = request.llm
if request.actor_model:  # 覆盖
    llm_spec = dataclasses.replace(llm_spec, model=request.actor_model)
client = StreamableLLMClient.from_spec(llm_spec)
```

---

## 3. provider id 映射

### 3.1 旧 → 新

| 旧 id | 新 id | 旧 model | 新 model |
|---|---|---|---|
| `minimax` | `minimax` | `MiniMax-M3` | `minimax-M3` |

### 3.2 alias 映射表（resolver 内部）

```python
PROVIDER_ALIASES = {
    "minimax": "minimax",  # 旧 id → 新 id
}
```

### 3.3 兼容性

- 老 wiki 配置 `provider: minimax` → resolver 自动 alias → `provider: minimax`
- **无需手动改**
- 启动时打 info log：「provider 'minimax' aliased to 'minimax'」

### 3.4 UI 默认值

**旧**：
```typescript
const EMPTY_CONFIG: LLMConfig = {
  provider: 'minimax',
  model: 'MiniMax-M3',
  base_url: 'https://api.minimaxi.com/v1',
  api_key: '',
};
```

**新**（PR 4）：
```typescript
const EMPTY_CONFIG: LLMConfig = {
  provider: 'minimax',  // 改名
  model: '',            // 空 = 未配置
  base_url: '',
  api_key: '',
};
```

加载时若 `model === ''` → 显示「未配置」状态，提示用户前往 `/llm-settings`。

---

## 4. workflow YAML 修改（PR 3）

### 4.1 autoresearch-compound.yaml

**旧**（10 个 actor.model 行）：
```yaml
actors:
  clarifier:
    prompt_file: actor_prompts/autoresearch-clarifier.md
    model: sonnet       # ← 删
    tools: [Read, Grep, Glob]
  planner:
    prompt_file: actor_prompts/autoresearch-planner.md
    model: opus         # ← 删
    tools: [Read, Grep, Glob]
  ...
```

**新**（10 个 actor.model 行全部删除）：
```yaml
actors:
  clarifier:
    prompt_file: actor_prompts/autoresearch-clarifier.md
    # model 缺省 = 用 LLMSpec.model
    tools: [Read, Grep, Glob]
  planner:
    prompt_file: actor_prompts/autoresearch-planner.md
    # model 缺省 = 用 LLMSpec.model
    tools: [Read, Grep, Glob]
  ...
```

### 4.2 llmwikify-research.yaml

同上，4 个 actor.model 行全部删除。

### 4.3 灰度开关

```bash
# 默认严格：workflow 启动失败
export LLM_ALLOW_ALIAS_MODEL=true  # 临时放行 sonnet/opus/haiku alias
```

---

## 5. 灰度开关使用

### 5.1 4 个 env 开关

| 开关 | 默认 | 作用域 | 出问题时回退 |
|---|---|---|---|
| `LLM_USE_RESOLVER` | `true` | PR 1：resolver vs 旧 from_config | `LLM_USE_RESOLVER=false` |
| `LLM_SUBAGENT_INHERIT` | `true` | PR 2：subagent 注入 vs env 读取 | `LLM_SUBAGENT_INHERIT=false` |
| `LLM_ALLOW_ALIAS_MODEL` | `false` | PR 3：alias 校验 | `LLM_ALLOW_ALIAS_MODEL=true` |
| `LLM_LEGACY_FALLBACK` | `false` | PR 4：gpt-4o 兜底 | `LLM_LEGACY_FALLBACK=true` |

### 5.2 回退示例

**场景 1**：PR 1 后发现 resolver 解析有问题
```bash
export LLM_USE_RESOLVER=false
# 旧 from_config 走原路径，立即生效，无需重启代码
```

**场景 2**：PR 3 后 workflow 启动失败率高
```bash
export LLM_ALLOW_ALIAS_MODEL=true
# 放行 sonnet/opus/haiku alias
```

**场景 3**：PR 4 后生产报错
```bash
export LLM_LEGACY_FALLBACK=true
# 保留 gpt-4o 兜底
```

### 5.3 验证期后清理

- PR 1 验证 1-2 周稳定后：移除 `LLM_USE_RESOLVER` 开关
- PR 2 验证 1-2 周稳定后：移除 `LLM_SUBAGENT_INHERIT` 开关
- PR 3 验证 1-2 周稳定后：移除 `LLM_ALLOW_ALIAS_MODEL` 开关
- PR 4 验证 1-2 周稳定后：移除 `LLM_LEGACY_FALLBACK` 开关

**最终目标**：所有开关删除，LAL 强制生效。

---

## 6. 测试迁移

### 6.1 旧测试写法

```python
def test_llm_client():
    client = LLMClient()  # 默念 openai/gpt-4o
    assert client.model == "gpt-4o"
```

**问题**：依赖默认值，PR 4 后会抛 `LLMNotConfiguredError`。

### 6.2 新测试写法

```python
def test_llm_client():
    with pytest.raises(LLMNotConfiguredError) as exc_info:
        LLMClient()  # PR 4 后默认抛错
    assert exc_info.value.action == "go-to-llm-settings"
```

### 6.3 测试 helper

建议在 `tests/conftest.py` 加：

```python
@pytest.fixture
def llm_spec():
    """Standard LLMSpec for tests."""
    from llmwikify.foundation.llm.spec import LLMSpec
    return LLMSpec(
        provider="minimax",
        base_url="https://api.minimaxi.com/v1",
        api_key="test-key",
        model="minimax-M3",
        context_window=128000,
        timeout=120,
        reasoning_split=True,
        auth_scheme="bearer",
        extra_headers={},
        source="test",
    )
```

---

## 7. 常见问题

### Q1：PR 1 后业务代码还能用 `LLMClient` 吗？
**A**：能。`LLMClient` 降级为 shim，内部委派到 `StreamableLLMClient`。**但**默认值保留 `gpt-4o`（PR 4 才删）。

### Q2：PR 2 后 subagent 进程拿不到 LLM 配置怎么办？
**A**：检查 `ChatOrchestrator` 是否正确注入 `LLMSpec` 到 `SubagentRequest`。临时回退：`LLM_SUBAGENT_INHERIT=false` 让 subagent 读 env。

### Q3：PR 3 后 workflow 启动失败？
**A**：检查 `actor.model` 是否在 `provider.supported_models` 内。临时放行：`LLM_ALLOW_ALIAS_MODEL=true`。

### Q4：PR 4 后 LLM 未配置抛错，业务怎么降级？
**A**：Chat 主链路捕获 `LLMNotConfiguredError`，前端识别 `action="go-to-llm-settings"` 自动跳转。

### Q5：老 wiki 配置 `provider: minimax` 还能用吗？
**A**：能。resolver alias 映射，**无需改**。启动时打 info log 提醒。

### Q6：删了 `gpt-4o` 兜底，token 估算会不会失效？
**A**：不会。`token_estimator.py` / `token_budget.py` / `context_windows.py` **整个保留**。业务代码改用 `llm_spec.model` 拿真实 model name，拿不到时用 `"unknown"` + warning log。

### Q7：LLMSpec 是 frozen 的，下游能改吗？
**A**：不能。要修改必须用 `dataclasses.replace(llm_spec, model=new_model)` 创建新实例。

---

## 8. 回滚策略

每个 PR 独立可回滚：

| PR | 回滚方式 | 数据损失 |
|---|---|---|
| PR 1 | `LLM_USE_RESOLVER=false` | 无 |
| PR 2 | `LLM_SUBAGENT_INHERIT=false` | 无 |
| PR 3 | `LLM_ALLOW_ALIAS_MODEL=true` | 无 |
| PR 4 | `LLM_LEGACY_FALLBACK=true` | 无 |

**最坏情况**：4 个 PR 全部回滚，业务回到 LAL 之前状态。

---

## 9. 相关文档

- [`llm-access-layer.md`](./llm-access-layer.md)：LAL 规范
- [`llm-inventory.md`](../llm-inventory.md)：LLM 调用点盘点
