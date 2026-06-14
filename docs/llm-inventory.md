# LLM 调用点盘点（LLM Inventory）

> 本文档盘点仓库内**所有**与 LLM 相关的调用点，作为 LAL 迁移的基线。
>
> 盘点时间：2026-06-14
>
> 关联文档：[`llm-access-layer.md`](./designs/llm-access-layer.md) · [`llm-access-layer-migration.md`](./designs/llm-access-layer-migration.md)

---

## 1. 盘点范围

| 类别 | 描述 | 是否需要 LAL 治理 |
|---|---|---|
| LLM client 实现 | 同步/流式 HTTP client | ✅ |
| `from_config` 入口 | 从 config 构造 client 的函数 | ✅ |
| 硬编码默认值 | `model=...` / `provider=...` 默认值 | ✅ |
| 静默 fallback | `getattr(..., "gpt-4o")` 等兜底 | ✅ |
| workflow actor.model | YAML 里硬编码的 `sonnet/opus` | ✅ |
| provider 注册 | 各 provider 文件的 `from_config` | ✅ |
| token 估算 | `count_tokens` / `TokenBudgetChecker` | ❌ 整个保留 |
| 测试 / 文档 | 提到模型名的地方 | 部分 |

---

## 2. LLM Client 实现

| 文件 | 类 | 角色 | LAL 处置 |
|---|---|---|---|
| `src/llmwikify/foundation/llm_client.py` | `LLMClient` | 同步 OpenAI 兼容 | 降级为 shim（PR 1） |
| `src/llmwikify/foundation/llm/streamable.py` | `StreamableLLMClient` | 流式 OpenAI 兼容 | 唯一 client 实现（PR 1） |

**现状**：
- 2 个 client 并存，行为不一致
- 旧 `LLMClient` 默认 `provider=openai, model=gpt-4o`
- 业务代码混用两者

**LAL 处置**：
- PR 1：`StreamableLLMClient` 加 `complete(messages) -> str` 同步方法
- PR 1：`LLMClient` 全部委派到 `StreamableLLMClient`（保留 `gpt-4o` 默认，PR 4 再删）

---

## 3. `from_config` 入口

| 文件 | 行号 | 类/函数 | 职责 |
|---|---|---|---|
| `src/llmwikify/foundation/llm_client.py` | 58-88 | `LLMClient.from_config` | 同步 client 构造 |
| `src/llmwikify/foundation/llm/streamable.py` | 190-210 | `StreamableLLMClient.from_config` | 流式 client 构造 |
| `src/llmwikify/apps/chat/providers/base.py` | 22 | `BaseLLMProvider.from_config` | provider 基类 |
| `src/llmwikify/apps/chat/providers/minimax.py` | 34-54 | `MiniMaxProvider.from_config` | minimax provider |
| `src/llmwikify/apps/chat/providers/xiaomi.py` | 31-50 | `XiaomiProvider.from_config` | xiaomi provider |
| `src/llmwikify/apps/chat/providers/registry.py` | 52 | `provider.from_config(llm_cfg)` | provider registry 入口 |

**现状**：
- 6 个 `from_config` 实现，各自读 `llm.*`、各自写默认值
- 默认值不一致：`openai/gpt-4o` / `minimax/MiniMax-M3` / `xiaomi/mimo-v2.5-pro` 等

**LAL 处置**：
- PR 1：全部 6 个 `from_config` 委派到 `resolver.resolve_chat_llm`
- PR 1：resolver 内做 alias 映射 `minimax` → `minimax`

---

## 4. 硬编码默认值

### 4.1 实际发出 HTTP 请求的调用点

| 文件 | 行号 | 字段 | 默认值 | 影响 |
|---|---|---|---|---|
| `src/llmwikify/foundation/llm_client.py` | 24 | `provider` | `"openai"` | 无 api_key 时抛错 |
| `src/llmwikify/foundation/llm_client.py` | 27 | `model` | `"gpt-4o"` | 无 api_key 时抛错 |
| `src/llmwikify/foundation/llm/streamable.py` | 150-153 | `provider/model` | `"openai"` / `"gpt-4o"` | 同上 |
| `src/llmwikify/foundation/llm/streamable.py` | 183 | `_default_base_url` | `"https://api.openai.com"` | 无 api_key 时抛错 |
| `src/llmwikify/foundation/llm_client.py` | 51 | `_default_base_url` | `"https://api.openai.com"` | 同上 |
| `src/llmwikify/foundation/config.py` | 33-36 | `provider/model/base_url` | `"openai"` / `"gpt-4"` / `"http://localhost:11434"` | 全局默认 |

### 4.2 仅做 token 估算的调用点（PR 4 不动）

| 文件 | 行号 | 字段 | 默认值 | 说明 |
|---|---|---|---|---|
| `src/llmwikify/foundation/llm/token_budget.py` | 40 | `model` | `"gpt-4o"` | token 预算 |
| `src/llmwikify/foundation/llm/token_budget.py` | 59 | `model` | `"gpt-4o"` | test fixture |
| `src/llmwikify/foundation/llm/token_estimator.py` | 33 | `model` | `"gpt-4o"` | token 估算 |
| `src/llmwikify/foundation/llm/token_estimator.py` | 48 | `model` | `"gpt-4o"` | token 估算 |
| `src/llmwikify/foundation/llm/context_windows.py` | 17-33 | 多 model | gpt-4o / claude-3-* / deepseek-coder | 查表 |

### 4.3 业务代码静默 fallback

| 文件 | 行号 | 代码 | 影响 |
|---|---|---|---|
| `src/llmwikify/apps/chat/agent/service.py` | 668 | `getattr(model, "model", "gpt-4o") if model else "gpt-4o"` | token 估算 |
| `src/llmwikify/apps/chat/agent/service.py` | 764 | 同上 | token 估算 |
| `src/llmwikify/apps/chat/agent/service.py` | 940 | `getattr(self.llm_client, "model", "gpt-4o")` | token 估算 |
| `src/llmwikify/apps/chat/agent/context_manager.py` | 294-297 | `getattr(self._llm_client, "model", "gpt-4o")` | token 估算 |
| `src/llmwikify/apps/chat/agent/orchestrator.py` | 623 | `model_name = "gpt-4o"` | token 估算 |

**LAL 处置**：
- PR 4：删除 §4.1 所有硬编码默认值；缺失 → 抛 `LLMNotConfiguredError`
- PR 4：删除 §4.3 所有 `getattr(..., "gpt-4o")` fallback；缺失 → 用 `unknown` + warning log
- §4.2 token 估算**整个保留**

---

## 5. workflow actor.model 硬编码

| 文件 | 行号 | actor | 硬编码值 | LAL 处置 |
|---|---|---|---|---|
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 30 | clarifier | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 34 | planner | `model: opus` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 38 | evidence_extractor | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 43 | finding_extractor | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 47 | wiki_proposer | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml` | 51 | synthesizer | `model: opus` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml` | 23 | planner | `model: opus` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml` | 27 | researcher | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml` | 32 | verifier | `model: sonnet` | PR 3 删字段 |
| `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml` | 36 | synthesizer | `model: opus` | PR 3 删字段 |

**actor prompt frontmatter**（runtime 忽略，无影响，PR 3 不动）：
- `actor_prompts/autoresearch-clarifier.md:4` — `model: sonnet`
- `actor_prompts/autoresearch-planner.md:4` — `model: opus`
- `actor_prompts/autoresearch-evidence-extractor.md:4` — `model: sonnet`
- `actor_prompts/autoresearch-finding-extractor.md:4` — `model: sonnet`
- `actor_prompts/autoresearch-wiki-proposer.md:4` — `model: sonnet`
- `actor_prompts/autoresearch-synthesizer.md:4` — `model: opus`
- `actor_prompts/wikify-research-planner.md:4` — `model: opus`
- `actor_prompts/wikify-phase-researcher.md:4` — `model: sonnet`
- `actor_prompts/wikify-adversarial-verifier.md:4` — `model: sonnet`
- `actor_prompts/wikify-synthesizer.md:4` — `model: opus`

**LAL 处置**：
- PR 3：删 10 个 `model:` 行（直接删字段）
- PR 3：actor prompt frontmatter **不动**（runtime 忽略，无影响）
- PR 3：WorkflowSpec validator 加 `actor.model` 校验

---

## 6. provider 注册

| 文件 | provider id | default_model | base_url | 备注 |
|---|---|---|---|---|
| `src/llmwikify/apps/chat/providers/minimax.py` | `minimax` | `MiniMax-M3` | `https://api.minimaxi.com/v1` | 需改名 |
| `src/llmwikify/apps/chat/providers/xiaomi.py` | `xiaomi` | `mimo-v2.5-pro` | `https://token-plan-cn.xiaomimimo.com/v1` | OK |
| `src/llmwikify/apps/chat/providers/base.py` | （基类） | — | — | OK |
| `src/llmwikify/apps/chat/providers/registry.py` | — | — | — | OK |
| `src/llmwikify/foundation/llm/streamable.py` | `minimax` / `xiaomi` / `openai` / `ollama` / `lmstudio` | — | — | 内置 base_url 表 |

**UI 引用**（`ui/webui/src/components/agent/LLMSettings.tsx`）：
- L11: `PROVIDERS` 第一项 `minimax`
- L19-28: `MODEL_OPTIONS.minimax`
- L45-51: `MODEL_OPTIONS.xiaomi`
- L55: `BASE_URL_DEFAULTS.minimax`
- L65: `EMPTY_CONFIG.provider='minimax'`
- L66: `EMPTY_CONFIG.base_url='https://api.minimaxi.com/v1'`
- L67: `EMPTY_CONFIG.model='MiniMax-M3'`

**LAL 处置**：
- PR 4：provider id `minimax` → `minimax`
- PR 4：default model `MiniMax-M3` → `minimax-M3`
- PR 4：文件 `providers/minimax.py` → `providers/minimax.py`
- PR 4：UI 同步改名

---

## 7. Subagent 配置传递

| 文件 | 行号 | 字段 | 现状 | LAL 处置 |
|---|---|---|---|---|
| `src/llmwikify/apps/chat/skills/workflows/subagent_runner.py` | 62-90 | `SubagentRequest` | 无 `llm` 字段 | PR 2 增字段 |
| `src/llmwikify/apps/chat/skills/workflows/subagent_worker.py` | 172-200 | `LlmClientDriver` | 自行 `LLMClient()` | PR 2 改为基于 `llm` 构造 |
| `src/llmwikify/apps/chat/skills/workflows/dag.py` | 57 | `ActorModel` 类型 | `Literal["opus", "sonnet", "haiku", "inherit"] \| str` | PR 2 移除 `"inherit"` |

**LAL 处置**：
- PR 2：`SubagentRequest` 增 `llm: LLMSpec` 字段
- PR 2：`LlmClientDriver` 改为基于 `llm` 构造 client
- PR 2：`actor.model` 校验：只有当前 provider supported 时才覆盖
- PR 2：移除 `ActorModel` 类型里的 `"inherit"`

---

## 8. 总结：LAL 治理清单

| 类别 | 数量 | 涉及 PR |
|---|---|---|
| 删 `gpt-4o` 兜底 | 5 处 | PR 4 |
| 删硬编码默认值 | 6 处 | PR 4 |
| 删 workflow `model:` 行 | 10 处 | PR 3 |
| 委派到 resolver | 6 个 `from_config` | PR 1 |
| subagent 注入 `LLMSpec` | 3 处 | PR 2 |
| provider id 改名 | 1 个 + 5 处 UI 引用 | PR 4 |
| 移除 `inherit` 关键字 | 1 处类型 + 10 处 YAML | PR 2 + PR 3 |
| token 估算**保留** | 5 处 | 不动 |

---

## 9. 验证 checklist（PR 完成后逐项打勾）

- [ ] `grep -rn 'gpt-4o' src/llmwikify/` 无业务代码命中（PR 4）
- [ ] `grep -rn '"openai"' src/llmwikify/` 无默认值命中（PR 4）
- [ ] `grep -rn 'sonnet\|opus\|haiku' src/llmwikify/apps/chat/skills/workflows/builtins/*.yaml` 无命中（PR 3）
- [ ] `grep -rn 'from_config' src/llmwikify/foundation/llm*` 全部委派到 resolver（PR 1）
- [ ] `grep -rn 'SubagentRequest(' src/llmwikify/` 全部带 `llm=...`（PR 2）
- [ ] `grep -rn 'minimax' src/llmwikify/apps/chat/providers/` 无命中（PR 4）

---

## 10. 相关文档

- [`llm-access-layer.md`](./designs/llm-access-layer.md)：LAL 规范
- [`llm-access-layer-migration.md`](./designs/llm-access-layer-migration.md)：迁移指南
