# llmwikify Issues 跟踪

> 生成日期: 2026-05-30 | 分支: main | 版本: 0231936

---

## 一、总览表

### 🔴 P0 — 高优先级（影响功能正确性）

| 编号 | 系统 | 功能 | 位置 | 现状 | 问题 | 建议 | 复杂度 | 状态 |
|------|------|------|------|------|------|------|--------|------|
| DR-2 | Deep Research | Gather | `gatherer.py:364-373` | 失败直接标记 "failed"，永不重试 | 网络抖动导致永久丢失搜索方向 | 在下一轮 ReAct 中自动重试失败 sub-query | 低 | 待处理 |
| DR-4 | Deep Research | Review | `engine.py:626-629` | LLM 异常时创建 `{"approved":False,"score":0}` | LLM 调用失败 ≠ 报告质量差，浪费 revise 轮次 | 异常时跳过 review，标记 "review_skipped" | 低 | 待处理 |
| IN-1 | Ingest | Analyze | `analyze_source.yaml:11`, `wiki_mixin_llm.py:22-24`, `wiki_mixin_source_analysis.py:116` | `max_content_chars=8000`，长文档只分析前 1/5 | PDF/长文核心信息在后半部分，分析不完整 | 调大阈值 + heading-aware 截取 | 低~中 | 待处理 |
| IN-2 | Ingest | Confirm | `agent/tools.py:263` | `requires_confirmation="posthoc"` 执行后才记录 | 与 `wiki_write_page` 的 pre 模式不一致，误操作无法回滚 | 改为 `requires_confirmation="pre"` | 低 | 待处理 |

### 🟡 P1 — 中优先级（影响性能/体验）

| 编号 | 系统 | 功能 | 位置 | 现状 | 问题 | 建议 | 复杂度 | 状态 |
|------|------|------|------|------|------|------|--------|------|
| DR-1 | Deep Research | Gather | `gatherer.py:55-57` | 50% 任务完成 + 15s grace 后取消剩余 | 慢但有价值的源（PDF/arxiv）被过早取消 | 提高阈值到 70-80% 或按质量判断 | 低 | 待处理 |
| DR-3 | Deep Research | Report | `report.py:89-103` | 报告生成是阻塞式 LLM 调用（120s） | 用户在最耗时阶段看不到进度 | 支持 report LLM 流式输出 | 中 | 待处理 |
| DR-5 | Deep Research | DB | `db.py:347` | 每个 source 完整内容（最大 500K chars）存 SQLite | DB 膨胀，查询变慢，resume 加载慢 | 大内容存文件系统，DB 只存 metadata | 中 | 待处理 |
| DR-6 | Deep Research | Engine | `engine.py:392-403` | `_check_control_signals()` 每轮都读 DB | 不必要 I/O | 每 N 轮检查或用 asyncio.Event | 低 | 待处理 |
| DR-7 | Deep Research | Frontend | `api.ts:318-355` | 流断开后用户必须手动 resume | 网络不稳定体验差 | exponential backoff 自动重连 | 中 | 待处理 |
| DR-8 | Deep Research | Frontend | `ResearchPanel.tsx:563-564` | `readerRef` 存了 reader 但没接 cancel | 导航离开后 fetch 继续运行 | unmount 时 abort 流 | 低 | 待处理 |
| DR-9 | Deep Research | Frontend | `ResearchDetail.tsx:43-63` | 用一次性 REST 加载，不用 SSE | 查看运行中 session 数据过时 | running 状态也建立 SSE 连接 | 中 | 待处理 |
| IN-3 | Ingest | Pipeline | `wiki_mixin_llm.py:15-79` vs `agent/tools.py:258-271` | CLI 硬编码 2 步链，Agent 自行决策 | 同一源不同路径产生不同质量页面 | 统一分析流程或加强 ingest_instructions 约束 | 中 | 待处理 |
| IN-4 | Ingest | Cache | `wiki_mixin_source_analysis.py:46-72` | 缓存在 wiki 页面 HTML 注释中 | 页面编辑时缓存丢失 | 缓存存 SQLite 或独立文件 | 中 | 待处理 |
| IN-6 | Ingest | Generate | `generate_wiki_ops.yaml`, `wiki_mixin_llm.py:48-68` | 一次 LLM 调用生成所有页面内容 | 源复杂时输出截断或省略页面 | 先生成操作列表再逐操作填充 | 中 | 待处理 |
| IN-7 | Ingest | CLI/Agent | `commands.py:165-206`, `tools.py:258-271` | CLI 阻塞无进度，Agent 无后续反馈 | 用户看不到进度 | CLI 添加进度条；Agent 返回操作列表确认 | 中 | 待处理 |

### 🟢 P2 — 低优先级（代码质量/可维护性）

| 编号 | 系统 | 功能 | 位置 | 现状 | 问题 | 建议 | 复杂度 | 状态 |
|------|------|------|------|------|------|------|--------|------|
| DR-10 | Deep Research | Engine | `engine.py` 全文 | 所有 action/reasoning/observation 在一个类（930 行） | 可维护性差 | 拆分为 Reasoner/ActionDispatcher/Observer | 高 | 待处理 |
| DR-11 | Deep Research | Frontend | `ResearchPanel.tsx:632-755` | 120+ 行 switch 处理 16 种事件 | 可维护性差 | strategy pattern 或 reducer 拆分 | 中 | 待处理 |
| DR-12 | Deep Research | Frontend | 多处（loadSessions, handlePause, handleDelete） | catch 后 silent | 用户不知道操作是否成功 | console.warn 或 toast 提示 | 低 | 待处理 |
| DR-13 | Deep Research | Observability | `engine.py` 全文 | 无 token 用量/耗时/成本追踪 | 无法分析优化 | 添加 metrics 收集 | 中 | 待处理 |
| DR-14 | Deep Research | Engine | `engine.py` 各 action handler | Phase 分散赋值，无集中验证 | 状态机隐式 | 定义显式状态转移表 | 中 | 待处理 |
| IN-5 | Ingest | Transaction | `wiki_mixin_relation.py:86-121` | 逐页写入，无原子性 | 中途失败导致部分页面丢失 | 写入前快照 + 失败回滚 | 高 | 待处理 |
| IN-8 | Ingest | Relation | `relation_engine.py:102-141` | `add_relation()` 精确匹配去重 | 不同表述产生重复关系 | 语义去重（LLM 或 embedding） | 中 | 待处理 |
| IN-9 | Ingest | Index | `core/index.py:77-111` | 每次 `write_page()` 重建 FTS5 条目 | 批量 ingest 性能瓶颈 | 延迟索引更新，最后一次性重建 | 中 | 待处理 |
| IN-10 | Ingest | Architecture | `core/wiki.py:29-60` | 13 个 mixin 组合，职责分散 | 跨 mixin 调用链路长 | 合并功能相近的 mixin | 高 | 待处理 |
| IN-11 | Ingest | Observability | 全局 | 无提取/分析/建页耗时追踪 | 无法分析优化 | 添加 metrics 收集 | 低 | 待处理 |
| IN-12 | Ingest | Index | `wiki_mixin_page_io.py:83,276-423` | 每次写入重建整个 index.md | 大 wiki 时耗时增加 | 增量更新或延迟重建 | 中 | 待处理 |

---

## 二、Token 预算检查系统（新功能设计）

### 设计决策

| 决策点 | 结论 | 理由 |
|--------|------|------|
| Token 估算 | tiktoken + fallback | 精确且快速，无依赖时自动降级到字符比估算 |
| 日志方案 | 标准 logging + extra= | 与项目 104 处 logging 一致，零新依赖 |
| 中间件行为 | 只检查+日志，不截断 | 截断由调用方/其他功能负责 |
| 超限处理 | 可配置：`"warn"` 或 `"raise"` | 默认 warn（日志+返回状态），可选 raise（抛异常） |
| Context window 获取 | config → provider API → 模型名推断 → 映射表 → 默认 | 多级 fallback |
| `get_model_info()` | 正式加入 `LLMProvider` protocol | 结构化获取模型参数 |
| LLM 自询问 | 仅 debug 模式可选 | 不可靠，仅作校验 |

### 文件结构

```
src/llmwikify/llm/
├── __init__.py              # 公开 API
├── token_estimator.py       # Token 估算 (tiktoken + fallback)
├── token_budget.py          # 预算检查器 (检查+日志，不截断)
└── context_windows.py       # 模型上下文窗口数据库 + 解析逻辑

src/llmwikify/agent/backend/providers/
├── base.py                  # 修改: 添加 get_model_info() protocol
├── minimax.py               # 修改: 实现 get_model_info()
├── xiaomi.py                # 修改: 实现 get_model_info()
└── registry.py              # 修改: 添加 get_model_info() 工具函数

src/llmwikify/llm_client.py          # 修改: 集成 TokenBudgetChecker
src/llmwikify/agent/backend/adapters.py  # 修改: 集成 TokenBudgetChecker

pyproject.toml               # 修改: 添加 llm 依赖组
```

### 模块 1: `context_windows.py`

模型上下文窗口数据库 + 多级 fallback 解析。

**内置映射表**（来源: LiteLLM `model_prices_and_context_window.json`）:

```python
CONTEXT_WINDOWS = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-haiku": 200_000,
    "llama3": 8_192,
    "llama3.1": 131_072,
    "llama3.2": 131_072,
    "qwen2.5": 131_072,
    "deepseek-coder": 16_384,
    "mistral": 32_768,
    "phi3": 131_072,
    "MiniMax-M2.7": 1_000_000,
    "MiniMax-M2.5": 1_000_000,
    "default": 32_768,
}
```

**解析链**:

```
resolve_context_window(model, config_override, base_url, api_key, llm_client, debug)
  │
  ├─ config_override? → 返回配置值
  │
  ├─ base_url + api_key? → 调 /v1/models/{model}
  │   └─ 返回 context_length? → 返回探测值
  │
  ├─ 模型名推断 (如 "llama3-8k" → 8192)? → 返回推断值
  │
  ├─ model 在映射表中? → 返回映射值
  │
  ├─ debug=True + llm_client? → 问 LLM (返回 unverified 标记)
  │
  └─ 返回默认值 32768
```

**Provider API 探测**:

```python
def probe_provider_api(model, base_url, api_key) -> int | None:
    """调用 /v1/models/{model} 探测 context window"""
    # vLLM 返回 max_model_len
    # 其他 provider 可能返回 context_length / max_context_length
```

**LLM 自询问**（仅 debug 模式）:

```python
def ask_llm_context_window(llm_client) -> int | None:
    """问 LLM "你的上下文窗口多大?" — 仅 debug 模式使用"""
    # 发送 prompt: "What is your maximum context window size in tokens? Reply with ONLY a number."
    # 从回复中提取数字
```

### 模块 2: `token_estimator.py`

Token 估算器，优先 tiktoken，fallback 到字符比估算。

```python
def count_tokens(text: str, model: str = "gpt-4o") -> int:
    """计算文本的 token 数"""
    enc = _get_tiktoken_encoding(model)  # 带缓存
    if enc is not None:
        return len(enc.encode(text))
    return max(1, len(text) // 3)  # fallback: 1 token ≈ 3 chars

def count_messages(messages: list[dict], model: str = "gpt-4o") -> int:
    """估算 messages 总 token 数 (含 message overhead)"""
    # 每条 message +4 tokens overhead
```

### 模块 3: `token_budget.py`

Token 预算检查器 — 只检查和日志，不截断。

**核心类**:

```python
@dataclass
class TokenUsage:
    timestamp: float
    model: str
    prompt_name: str
    estimated_tokens: int
    context_window: int
    exceeds_window: bool       # ← 调用方通过此字段判断是否超限
    message_count: int
    largest_message_tokens: int

@dataclass
class TokenBudgetConfig:
    model: str = "gpt-4o"
    context_window: int | None = None        # None = 自动解析
    reserve_output_tokens: int = 4096         # 为输出预留
    on_exceed: Literal["warn", "raise"] = "warn"
    base_url: str | None = None
    api_key: str | None = None

class TokenBudgetChecker:
    def check(self, messages, prompt_name="unknown") -> TokenUsage:
        """检查 token 预算，返回使用记录"""
        # 1. 用 tiktoken 精确计算 tokens
        # 2. 对比 context_window - reserve_output
        # 3. 超限时:
        #    - "warn": WARNING 日志 + 返回 exceeds_window=True
        #    - "raise": WARNING 日志 + 抛 TokenBudgetExceeded 异常
        # 4. 记录到 _usage_log
        # 5. 返回 TokenUsage (warn 模式下永远返回)

    def get_stats(self) -> dict:
        """获取累计使用统计"""
```

**超限行为**:

| `on_exceed` | 日志 | 异常 | 返回值 |
|-------------|------|------|--------|
| `"warn"` | ✅ WARNING | ❌ 不抛 | `TokenUsage(exceeds_window=True)` |
| `"raise"` | ✅ WARNING | ✅ 抛异常 | 超限时不返回（异常） |

**调用方使用模式**:

```python
usage = checker.check(messages, prompt_name="analyze_source")
if usage.exceeds_window:
    # warn 模式: 永远能拿到状态，调用方自行决定
    # raise 模式: 不会到达这里（已抛异常）
    ...
```

### 模块 4: `LLMProvider` protocol 修改

`base.py` 新增 `get_model_info()` 方法：

```python
class LLMProvider(Protocol):
    ...
    def get_model_info(
        self, model: str, base_url: str, api_key: str
    ) -> dict[str, Any] | None:
        """获取模型参数 (context_window, max_output_tokens 等)"""
        ...

class BaseLLMProvider:
    def get_model_info(self, model, base_url, api_key) -> dict | None:
        """默认实现: 调用 /v1/models/{model}"""
        # 检查 context_length / max_model_len / max_context_length
        # 检查 max_output_tokens / max_tokens
```

### 模块 5: 装饰器 + LLM Client 集成

**装饰器** (`llm/budget_decorator.py`):

```python
def check_token_budget(checker_getter) -> Callable:
    """装饰器：在 LLM 调用前自动检查 token 预算
    
    从 kwargs 中提取 _prompt_name（用于日志标注），检查预算后移除。
    支持普通函数、生成器、异步生成器。
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            prompt_name = kwargs.pop("_prompt_name", func.__name__)
            messages = kwargs.get("messages", [])
            if messages:
                checker = checker_getter(args[0]) if args else checker_getter()
                checker.check(messages, prompt_name=prompt_name)
            result = func(*args, **kwargs)
            # 生成器/异步生成器透传
            if hasattr(result, '__next__'):
                return (lambda: (yield from result))()
            if hasattr(result, '__aiter__'):
                return (lambda: (async for item in result: yield item))()
            return result
        return wrapper
    return decorator
```

**LLMClient 集成**:

```python
class LLMClient:
    def __init__(self, ..., context_window=None, budget_on_exceed="warn"):
        self._budget_checker = TokenBudgetChecker(...)
    
    @check_token_budget(lambda self: self._budget_checker)
    def chat(self, messages, json_mode=False, **generation_params): ...
    
    @check_token_budget(lambda self: self._budget_checker)
    def chat_json(self, messages, **generation_params): ...
```

**StreamableLLMClient 集成**:

```python
class StreamableLLMClient:
    @check_token_budget(lambda self: self._budget_checker)
    def chat(self, messages, json_mode=False, **generation_params): ...
    
    @check_token_budget(lambda self: self._budget_checker)
    def chat_with_tools(self, messages, tools=None, **generation_params): ...
    
    @check_token_budget(lambda self: self._budget_checker)
    def stream_chat(self, messages, tools=None, **generation_params): ...
    
    @check_token_budget(lambda self: self._budget_checker)
    async def astream_chat(self, messages, tools=None, **generation_params): ...
    
    @check_token_budget(lambda self: self._budget_checker)
    async def achat(self, messages, json_mode=False, **generation_params): ...
```

**调用方使用**:

```python
# 只需在 generation_params 中传入 _prompt_name
analysis = client.chat_json(
    messages,
    _prompt_name="analyze_source",   # ← 装饰器提取并消费
    temperature=0.1,
    max_tokens=4096,
)
```

### 配置方式

```json
{
  "llm": {
    "enabled": true,
    "model": "gpt-4o",
    "context_window": 128000,
    "budget_on_exceed": "warn"
  }
}
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `context_window` | 自动解析 | 手动覆盖模型上下文窗口 |
| `budget_on_exceed` | `"warn"` | `"warn"`=日志+返回状态, `"raise"`=抛异常 |

### 结构化日志输出（标准 logging + extra=）

**正常情况**:

```json
{
  "message": "token_budget.ok: 15234/123904 tokens (12.3%) for 'analyze_source'",
  "model": "gpt-4o",
  "prompt_name": "analyze_source",
  "estimated_tokens": 15234,
  "context_window": 128000,
  "budget": 123904,
  "exceeds_window": false,
  "message_count": 3,
  "largest_message_tokens": 12500,
  "pct": 12.3
}
```

**超限情况**:

```json
{
  "message": "token_budget.exceeded: 45000/4096 tokens (1098.4%) for 'analyze_source'",
  "model": "gpt-4",
  "prompt_name": "analyze_source",
  "estimated_tokens": 45000,
  "context_window": 8192,
  "budget": 4096,
  "exceeds_window": true,
  "pct": 1098.4
}
```

### 依赖变更

```toml
# pyproject.toml
[project.optional-dependencies]
llm = [
    "tiktoken>=0.7.0",
]
agent = [
    ...existing...,
    "llmwikify[llm]",
]
```

### 实施步骤

| 步骤 | 内容 | 文件 | 复杂度 |
|------|------|------|--------|
| 1 | 新建 `src/llmwikify/llm/` 模块 | `__init__.py`, `context_windows.py`, `token_estimator.py`, `token_budget.py`, `budget_decorator.py` | 低 |
| 2 | 修改 `LLMProvider` protocol | `providers/base.py` | 低 |
| 3 | 实现 provider `get_model_info()` | `providers/minimax.py`, `providers/xiaomi.py` | 低 |
| 4 | `LLMClient` 集成装饰器 | `llm_client.py` | 低 |
| 5 | `StreamableLLMClient` 集成装饰器 | `adapters.py` | 低 |
| 6 | 配置系统添加 `context_window`/`budget_on_exceed` | `config.py` | 低 |
| 7 | 更新 `pyproject.toml` | 添加 `llm` 依赖组 | 低 |
| 8 | 调用方注入 `_prompt_name` | `wiki_mixin_llm.py`, `engine.py`, `review.py`, `report.py` | 低 |
| 9 | 编写单元测试 | `tests/test_token_budget.py` | 中 |

### 与 Ingest 分层保护的关系

```
Layer 0: TokenBudgetChecker (通用，所有 LLM 调用)
  ↓ tiktoken 精确计算
  ↓ 超限时 warn/raise (可配置)
  ↓ structlog 结构化日志
  ↓ 返回 TokenUsage，调用方自行决定如何处理

Layer 1-4: Ingest 专用截断 (后续迭代，在 Layer 0 之上)
  ↓ ingest_source 返回截断
  ↓ wiki_schema 摘要注入
  ↓ current_index 截断
  ↓ content 动态截取
```

---

## 三、附录：LLM 调用点审计

14 个调用点中，仅 4 个有截断保护。TokenBudgetChecker 提供全局安全网：

| # | 调用点 | 位置 | 有截断 |
|---|--------|------|--------|
| 1 | `_call_llm_with_retry()` | `wiki_mixin_llm.py:98` | ✅ (caller 截断) |
| 2 | `_llm_generate_synthesize_answer()` | `wiki_mixin_llm.py:218` | ❌ |
| 3 | `analyze_source()` | `wiki_mixin_source_analysis.py:123` | 部分 |
| 4 | `_llm_generate_investigations()` | `wiki_analyzer.py:543` | ❌ |
| 5 | `_llm_detect_gaps()` | `wiki_analyzer.py:638` | ❌ |
| 6 | `_llm_reason()` | `engine.py:367` | N/A (状态摘要) |
| 7 | `_plan_sub_queries()` | `engine.py:751` | 部分 |
| 8 | `_plan_for_gaps()` | `engine.py:835` | ❌ |
| 9 | `ResearchReviewer.review()` | `review.py:47` | ❌ |
| 10 | `ResearchRevisor.revise()` | `review.py:120` | ❌ |
| 11 | `ReportGenerator.generate()` | `report.py:98` | ✅ |
| 12 | `AgentService.chat()` | `service.py:341` | ✅ |
| 13 | `approve_confirmation_and_continue()` | `service.py:525` | ✅ |
| 14 | `_analyze_one()` (indirect) | `analyzer.py:89` | 部分 |
