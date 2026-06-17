# M1 Research: nanobot providers/base.py Vendor Feasibility

> Date: 2026-06-17
> nanobot tag: v0.2.1 (`f309982 chore(release): update version to 0.2.1`)
> Source path: `/tmp/nanobot/nanobot/providers/`

---

## 1. nanobot v0.2.1 `providers/` 目录结构

| 文件 | LOC | 角色 |
|---|---|---|
| `base.py` | **843** | `LLMProvider` ABC + `LLMResponse`/`ToolCallRequest` 数据类 + 重试机 |
| `factory.py` | **244** | `make_provider(config)` — 从 `Config` 派发 provider |
| `registry.py` | **533** | `PROVIDERS` 元组 (30+ ProviderSpec) + `find_by_name()` |
| `__init__.py` | 45 | 懒加载 6 个 provider 类 |
| `openai_compat_provider.py` | **1267+** | OpenAI 兼容实现 (重试/sanitize/Responses API) |
| `anthropic_provider.py` | (未读) | Anthropic 原生 SDK |
| `azure_openai_provider.py` | (未读) | Azure OpenAI |
| `bedrock_provider.py` | (未读) | AWS Bedrock |
| `openai_codex_provider.py` | (未读) | ChatGPT OAuth |
| `github_copilot_provider.py` | (未读) | GitHub Copilot OAuth |
| `fallback_provider.py` | (未读) | Fallback chain wrapper |
| `image_generation.py` | (未读) | 图像生成 |
| `transcription.py` | (未读) | Whisper 转录 |
| `openai_responses/` | (目录) | Responses API 解析 |

**总计可见 ~2900+ LOC** (不含未读文件)。

---

## 2. nanobot `LLMProvider` ABC 公开接口

### 抽象方法 (2 个)
```python
class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        reasoning_effort: str | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    def get_default_model(self) -> str: ...
```

### 数据类 (2 个)
- `ToolCallRequest`: `id, name, arguments, extra_content, provider_specific_fields, function_provider_specific_fields`
- `LLMResponse`: `content, tool_calls, finish_reason, usage, retry_after, reasoning_content, thinking_blocks, error_status_code, error_kind, error_type, error_code, error_retry_after_s, error_should_retry`
- `GenerationSettings`: `temperature, max_tokens, reasoning_effort`

### 关键类属性
- `supports_progress_deltas = False`

### 重试机 (~500 LOC)
- `_run_with_retry()` — 核心调度
- `chat_with_retry()` / `chat_stream_with_retry()` — 包装
- `_safe_chat()` / `_safe_chat_stream()` — 异常转 LLMResponse
- `_is_transient_error()` / `_is_transient_response()` — 错误分类
- `_is_retryable_429_response()` — 429 精细分类 (含 billing vs rate_limit)
- `_extract_retry_after()` (4 种 pattern) / `_extract_retry_after_from_headers()` / `_extract_retry_after_from_response()`
- `_sleep_with_heartbeat()` — 重试等待 + 心跳回调
- `_NON_RETRYABLE_429_ERROR_TOKENS` / `_RETRYABLE_429_ERROR_TOKENS` — 错误 token 表
- `is_arrearage_response()` — 402/余额不足检测

### 消息清洗 (~80 LOC)
- `_sanitize_empty_content()` — 空 content 修复
- `_enforce_role_alternation()` — 同 role 合并 / trailing assistant 移除 / 合成 user 消息
- `_strip_image_content()` / `_strip_image_content_inplace()` — 图片占位
- `_sanitize_request_messages()` — 字段白名单
- `_tool_cache_marker_indices()` — 缓存标记位置

### 外部依赖 (vendor 必带)
```python
from loguru import logger                  # 日志
from nanobot.utils.helpers import image_placeholder_text  # 跨模块依赖
```

---

## 3. llmwikify apps/chat/providers/ 目录结构 (对比)

| 文件 | LOC | 角色 |
|---|---|---|
| `base.py` | **64** | `LLMProvider` Protocol + `BaseLLMProvider` (2 个 helper) |
| `registry.py` | **79** | 装饰器注册 + `get_provider/list_providers/create_llm` |
| `__init__.py` | 15 | 重导出 |
| `minimax.py` | **94** | MiniMaxProvider (OpenAI-compat + reasoning_split) |
| `xiaomi.py` | **71** | XiaomiProvider (OpenAI-compat + api-key auth) |

**总计 ~323 LOC**. **与 nanobot 6+ 文件、2900+ LOC 完全不在一个量级**.

### llmwikify `LLMProvider` Protocol 公开接口 (6 个 abstractmethod)
```python
@runtime_checkable
class LLMProvider(Protocol):
    def from_config(self, config: dict) -> "StreamableLLMClient": ...
    def validate_config(self, config: dict) -> list[str]: ...
    def default_model(self) -> str: ...
    def supported_models(self) -> list[str]: ...
    def default_base_url(self) -> str: ...
    def provider_name(self) -> str: ...
```

### llmwikify `BaseLLMProvider` 共享方法 (2 个)
- `_resolve_api_key(config)` — `env:VAR_NAME` 语法支持
- `_resolve_field(config, field, default)` — `LLM_<FIELD>` 环境变量覆盖

---

## 4. 关键问题回答 (4 个)

### Q1: nanobot `LLMProvider` 与 llmwikify 现有 6 个 provider 接口是否兼容?

**答: 否 — 形状完全不同, 不能直接 vendor.**

| 维度 | nanobot | llmwikify |
|---|---|---|
| 类型 | `ABC` (继承 + super) | `Protocol` (结构化子类型) |
| 抽象方法数 | 2 (`chat`, `get_default_model`) | 6 (`from_config`, `validate_config`, ...) |
| 返回值 | `LLMResponse` (dataclass) | `StreamableLLMClient` (类实例, 在 `foundation/llm/streamable.py`) |
| 入参 | `messages: list[dict]` + `tools` + 配置 | `config: dict` (整个配置) |
| 流式 | `chat_stream(messages, ...)` (async, callback 风格) | `StreamableLLMClient.stream()` (独立客户端 API) |
| 重试 | 内置 (`_run_with_retry`) | 外置 (`streamable.py` 中 `RetryConfig` + `_compute_backoff`) |
| 注册方式 | `ProviderSpec` dataclass + factory 派发 | 装饰器 + `PROVIDERS: dict` |
| 思考控制 | `reasoning_effort` (semantic) + wire format 映射 | `reasoning_split: bool` (per-provider) |
| 工具调用 | `ToolCallRequest` dataclass | 由 `StreamableLLMClient` 解析 |

**vendor nanobot `LLMProvider` ABC 必须二选一**:
- (a) 迁移所有 llmwikify provider 改为 nanobot 形状 (改 2 文件, 影响 ~30 测试, 风险高)
- (b) 写适配层让 nanobot provider 适配 llmwikify Protocol (适配层代码可能 > vendor 的代码, 价值为负)

### Q2: nanobot abstractmethod 有多少? llmwikify 哪些已实现, 哪些缺失?

**答: 2 个 abstractmethod (`chat`, `get_default_model`). llmwikify 0 个已实现 (因为抽象层形状不同).**

llmwikify 6 个抽象方法 (`from_config/validate_config/default_model/supported_models/default_base_url/provider_name`) 在 nanobot 抽象层里**完全不存在**. 反之, nanobot 的 `chat()` 在 llmwikify 中**对应的是 `StreamableLLMClient` 的方法**, 不在 Provider 接口里.

**vendor 不产生任何"复用"**. 必须重写.

### Q3: 是否有 nanobot 内部依赖必须一起 vendor?

**答: 是. 必须同时 vendor 的至少 4 个文件:**

| 必需 | 文件 | LOC | 用途 |
|---|---|---|---|
| ✅ | `providers/base.py` | 843 | `LLMProvider` ABC + 数据类 + 重试 |
| ✅ | `providers/openai_compat_provider.py` | 1267+ | 唯一 OpenAI-compat 实现 (含 MiniMax/xiaomi_mimo) |
| ✅ | `utils/helpers.py` (跨模块) | (估 200+) | `image_placeholder_text()` |
| ✅ | `config/schema.py` (跨模块) | (估 500+) | `Config`, `ModelPresetConfig` (factory.py 用) |
| ⚠️ | `providers/openai_responses/` | (估 500+) | Responses API 解析 (optional) |

**`loguru` + `json_repair` 是 transitive deps** (openai_compat_provider.py 用了).

**vendor 总成本: 估 3000+ LOC + 2 个新依赖**.

**对应收益: 替换 llmwikify 323 LOC**.

**净值: +2700 LOC, -2 deps 简化**.

### Q4: 现有测试能否直接复用?

**答: 否. 必须重写或大幅调整.**

- llmwikify provider 测试 (估 5-10 个) 测 `LLMProvider` Protocol 形状 (e.g. `provider_name()`, `default_model()`)
- vendor nanobot 后, 测试需要测 `chat()` async + `LLMResponse` 形状
- llmwikify 的 `StreamableLLMClient` 测试 (估 15+ 个) 完全不适用 (那是另一层)
- 测试代码估 200-400 LOC 需要重写

---

## 5. nanobot 已有 MiniMax 支持 (重要发现)

`registry.py:365-373`:
```python
ProviderSpec(
    name="minimax",
    keywords=("minimax",),
    env_key="MINIMAX_API_KEY",
    display_name="MiniMax",
    backend="openai_compat",
    default_api_base="https://api.minimax.io/v1",   # 注: 与 llmwikify 域名不同
    thinking_style="reasoning_split",
),
```

**注意**: nanobot 用 `api.minimax.io`, llmwikify 用 `api.minimaxi.com`. **域名不一致**, vendor 后需要本地 patch 或环境变量覆盖.

`openai_compat_provider.py:73-77`:
```python
_THINKING_STYLE_MAP: dict[str, Any] = {
    "thinking_type": lambda on: {"thinking": {"type": "enabled" if on else "disabled"}},
    "enable_thinking": lambda on: {"enable_thinking": on},
    "reasoning_split": lambda on: {"reasoning_split": on},  # 与 llmwikify 一致!
}
```

`reasoning_split` 模式与 llmwikify MiniMaxProvider 默认一致. **思考控制方式可平滑迁移**.

`xiaomi_mimo` 在 nanobot 也已存在 (line 405-413), 用 `thinking_style="thinking_type"`. 与 llmwikify 当前用 `reasoning_split=True` **不一致**.

---

## 6. 风险清单 (vendor 路径)

| 风险 | 严重度 | 说明 |
|---|---|---|
| LOC 净增 | 🟡 中 | vendor ~3000 LOC, 仅替换 323 LOC |
| loguru 依赖 | 🟡 中 | llmwikify 当前无此 dep, 引入需评估 |
| LLMResponse 迁移 | 🔴 高 | 改抽象层形状 → 影响所有 provider caller (~30 测试) |
| 域名不一致 | 🟡 中 | nanobot `api.minimax.io` vs llmwikify `api.minimaxi.com` |
| xiaomi_mimo thinking | 🟡 中 | nanobot `thinking_type` vs llmwikify `reasoning_split` |
| 重试双实现 | 🟢 低 | 两套 retry 可共存 (nanobot base + llmwikify streamable) |
| 测试重写 | 🟡 中 | 估 200-400 LOC 重写 |
| 版本同步 | 🔴 高 | nanobot 升级可能破坏 vendor 代码 |

---

## 7. 不 vendor 的替代方案

### 方案 A: 只借模式 (idea borrowing), 不 vendor 代码

从 nanobot base.py / openai_compat_provider 借鉴以下**模式**到 `streamable.py`:

1. **429 精细分类** — `_is_retryable_429_response()` 移植到 `streamable.py:_is_retryable_429()` (~80 LOC)
   - billing token: `insufficient_quota`, `quota_exceeded`, `payment_required`
   - rate_limit token: `rate_limit_exceeded`, `too_many_requests`
   - llmwikify 当前只做 HTTP 状态码判断, 不区分这两类
2. **arrearage 检测** — `is_arrearage_response()` 移植 (~40 LOC)
3. **thinking_style map** — `_THINKING_STYLE_MAP` 移植到 `streamable.py` (~30 LOC)
4. **role alternation 强化** — `_enforce_role_alternation()` 中"trailing assistant → 合成 user"逻辑 (~20 LOC)

**总增量**: 估 170 LOC 新代码, **0 vendor LOC**, **0 新依赖**.

### 方案 B: 数据类 vendor (只搬 dataclass)

只 vendor 3 个 dataclass (~50 LOC):
- `ToolCallRequest`
- `LLMResponse`
- `GenerationSettings`

不带 ABC, 不带 retry, 不带 loguru.

**风险**: 调用点需要从 dict 改为 dataclass (破坏性变更).
**收益**: 数据形状统一 (但 llmwikify 当前已用 dict+流式 chunk, 没必要换).

### 方案 C: 跳过 M1, 直接进 M6

按用户原计划 (Option B): M6 agent loop 是主痛点. M1 vendor 价值低, 不应阻塞 M6.

---

## 8. 结论 + 推荐

**结论**: M1 vendor **强烈不推荐**.

| 维度 | vendor | 借模式 | 跳 M1 |
|---|---|---|---|
| LOC 净增 | **+2700** | +170 | 0 |
| 新依赖 | loguru + json_repair | 0 | 0 |
| 测试改动 | 200-400 LOC | 50 LOC | 0 |
| 风险 | 🔴 高 | 🟢 低 | 无 |
| 阻塞 M6 | 是 (2-3 天 vendor) | 是 (1 天) | **否** |
| M6 收益 | 间接 | 间接 | **直接** |

**推荐**: **跳过 M1, 直接进 M6** (Option B with sub-option C in original plan).

**理由**:
1. llmwikify 已有更成熟的 streaming 实现 (`streamable.py` 1238 LOC vs nanobot `OpenAICompatProvider` 1267 LOC, 相当但代码更新)
2. vendor 净增 2700+ LOC, 引入 loguru dep, 价值为负
3. 抽象层形状不兼容, vendor 后还要适配或迁移 (~30 测试受影响)
4. 用户已表态 "主要问题就在 agent loop 上" (M6 是主痛)
5. 借模式 (方案 A) 可在 M6 实施时顺手做, 不需要单独的 M1 阶段

**建议保留 M1 决策文档作为 future 选型参考**, 若未来需要 OpenAI Responses API 支持 (现 streamable.py 不支持), 可重新评估 vendor `openai_responses/` 部分 (~500 LOC).
