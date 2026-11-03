# Phase 4 / 方案 A：mypy 豁免递减（第一层：foundation）

日期: 2026-11-03 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 背景

架构评审发现 `pyproject.toml` 里 `tool.mypy.overrides` 有 **138 个模块** 挂了
`ignore_errors = true`。这些豁免让 mypy 在 CI 里形同虚设——基线跑出来只有
42 个错误，且全部集中在**豁免名单之外**的模块上。

## 先纠正方案本身

评审里写的"逐步去掉豁免"听起来是重活，实测不是：

| 假设 | 实测 |
|------|------|
| 138 个豁免模块都藏着类型错误 | foundation 的 14 个豁免模块**自身 0 错误** |
| 需要逐个模块修 138 遍 | 14 个 foundation 豁免全是**无效豁免**，直接删即可 |

根因：mypy 的 `overrides[].module` 是**精确匹配**，`llmwikify.foundation.llm`
只豁免 `foundation/llm/__init__.py`，**不含** `base.py` / `client.py` / `streamable.py`
等子模块。换句话说，**豁免名单比作者以为的小得多**，而作者以为被豁免的
子模块其实一直裸奔在 mypy 视野里。

所以 foundation 的 14 条豁免删掉后，真实错误只有两类：

1. **第三方缺 stub**（yaml / tiktoken / trafilatura / markitdown / youtube_transcript_api）
   → 归入 `ignore_missing_imports`，不是 `ignore_errors`
2. **foundation 自身的真实类型错误** → 逐个修

## 改动

### 1. 豁免名单：-14

`pyproject.toml` 的 `ignore_errors` 名单删除全部 14 条 foundation 条目
（`auth._jwt` / `auth.db` / `auth.prompt` / `callback.composite` / `config` /
`db` / `extractors.youtube` / `llm` / `llm.client` / `llm.resolver` /
`llm.streamable` / `llm_client` / `migration` / `prompts.prompt_registry`）。

**豁免名单 138 → 124**。

### 2. 第三方 stub → `ignore_missing_imports`

新增 `yaml` / `tiktoken` / `trafilatura` / `markitdown` / `youtube_transcript_api`
到既有第二个 override。它们都是**可选 extras 里的第三方库**，本身没有类型
stub；这是"库没有类型信息"，不是"我们的代码有类型错误"，两者不该混为一谈。

### 3. 真实类型错误修复（12 个文件）

| 文件 | 问题 | 处理 |
|------|------|------|
| `llm/base.py` | `on_exceed` 传 `str` 给 `Literal`；`payload` 推断成 `dict[str,str]`；`resp.json()` 返回 Any | `payload` 显式 `dict[str, Any]`；content 走 `str()` |
| `llm/token_budget.py` | — | **新增** `normalize_on_exceed()`：把用户侧的 `str` 归一化成 `Literal["warn","raise"]`，`base.py` 与 `streamable.py` 共用 |
| `llm/streamable.py` | 同 `on_exceed`；两个生成器缺返回标注；`meta.get()` 返回 Any | 复用 `normalize_on_exceed`；补 `Iterator` / `AsyncIterator` 标注 |
| `llm/resolver.py` | `_load_providers()` 是 `dict[str, Any]`，`.get()` 链返回 Any | 显式 `dict(...)` / `str(...)` 收敛 |
| `llm/client.py` | `json.loads()` 返回 Any | `isinstance` 校验后 `dict()` |
| `llm/__init__.py` | `__getattr__` 缺返回标注 | 补 `-> Any` |
| `callback/composite.py` | **13 个 override 冲突**：基类声明 sync（`-> None`），`CompositeHook` 用 async 覆写 | 基类改 `_HookRet = Awaitable[None] \| None`（见下） |
| `db.py` | `**self._pragmas` 展开成 `dict[str, object]` 传给 `connect`；`@contextmanager` 返回标注错；`_connections` key 类型错 | 拆成 5 个实例属性显式传参；`-> Iterator[sqlite3.Connection]`；key 改 `tuple[str, ConnectionProfile]` |
| `config.py` | `DEFAULT_CONFIG` 无标注 → 推断出 `dict[str, object]`，多处"object not indexable" | 加 `: dict[str, Any]`；连带删掉 2 个多余 `# type: ignore` |
| `auth/_jwt.py` | `from_dict(data: dict[str, object])` 里 `int(data["exp"])` 不匹配 overload | 放宽为 `dict[str, Any]` |
| `auth/db.py` | `create()` 声明返回 `ApiKey`，实际返回 `ApiKey \| None` | 插入后显式判空抛错 |
| `auth/prompt.py` | `input_fn` / `out` 无标注 → `disallow_untyped_defs` 报错 | 补 `Callable[[], str]` / `TextIO` |
| `extractors/youtube.py` | `_fetch_transcript` 缺返回标注；转录返回 Any | 补 `list[dict[str, Any]]` + `list()` 包装 |
| `migration.py` | `json.loads()` 返回 Any | `isinstance` 校验后 `dict()` |

### `AgentHook` 基类签名的关键修正

`foundation/callback/composite.py` 是**豁免里最有价值的一个**，它暴露的是
真实的接口设计问题，而不是笔误：

- 基类 `AgentHook` 的 13 个 hook 方法声明为 sync（`-> None`）
- `CompositeHook` 覆写成 `async def`（返回 `Coroutine`）
- 调用方统一用 `maybe_await(...)` 适配两者

也就是说**运行时契约本来就是"sync/async 都接受"**，只是基类签名没表达出来。
基类改为 `-> Awaitable[None] | None` 后：sync 实现返回 `None`（联合合法），
async 实现返回 `Coroutine`（`Awaitable` 子类型，合法），LSP 冲突消失。

这也顺带修掉了 `apps/chat/agent/chat_plan.py` 里 2 个
`"before_iteration" does not return a value` 错误——那是同一个根因的外部表现。

## 验证

```
mypy src/llmwikify/foundation     →  0 errors   （改动前 8 errors）
mypy src/llmwikify（CI 同款命令）   →  26 errors  （改动前 34 errors）
```

**减少 8 个错误，零新增。** 剩下的 26 个全在 `apps/` / `kernel/` / `interfaces/`
层，属于下一批（那些模块目前仍在豁免名单内或同样未被豁免），不在本次范围。

> 对照口径说明：CI 用的是 `mypy src/llmwikify`（路径模式），不是
> `mypy -p llmwikify`（包模式）。两者文件集合一致，错误数相同（42）。

测试：

```
pytest tests/test_foundation_*.py tests/test_prompt_registry.py \
       tests/test_batch0_db_profile.py tests/test_batch0_llm_contract.py
    →  384 passed, 10 skipped
ruff check src/llmwikify/foundation/  →  All checks passed
```

## 行为影响评估

所有改动都是**类型层面**的，实际行为变化仅两处，都刻意保持向后兼容：

1. `normalize_on_exceed()`：`"truncate"` 映射到 `"warn"`（不是 `"raise"`），
   与 `TokenBudgetChecker` 原有的 `if self.on_exceed == "raise"` 判断一致
2. `auth/db.py` 的 `create()`：插入后查不到行时抛 `RuntimeError`（原为
   静默返回 `None`，但返回类型声明是 `ApiKey`，本来就矛盾）

## 下一步

- **下一批**：`kernel/` 层（relation.py 8 个、knowledge_gaps.py 2 个）
  与 `apps/chat/agent/`（chat_plan.py 6 个、state_trace.py 2 个等），
  共 26 个错误。这批模块大多**不在**豁免名单里，是一直裸露的真实债务。
- **豁免名单继续清**：`apps/` / `interfaces/` 剩余 124 条。
  按同样方法先量化再决定，避免盲目开工。
- **棘轮守卫**：给 `check_architecture.py` 加一条检查——豁免名单条目只能变短，
  且列出的模块必须真的存在（当前 mypy 已报 `unused section`，
  说明有 3 条指向已删除的 `unified/` 模块）。
