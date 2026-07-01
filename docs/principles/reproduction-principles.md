# 研报复现功能 — 开发原则

> 版本: v1.1
> 日期: 2026-06-12
> 适用范围: `src/llmwikify/reproduction/` 全模块
> 配套文档: `docs/plan/reproduction-realignment.md`

---

## 0. 原则的元规则（先说清楚这些原则本身怎么用）

### 0.1 原则 vs 规范 vs 决策

- **原则（本文）**：高层抽象，提供决策框架，不直接给代码
- **规范**（`docs/plan/reproduction-spec.md`）：命名、frontmatter schema、枚举值的具体定义
- **决策**（重整文档 §3-7）：本次重整的具体选择

修改原则需要先讨论；违反原则需要在 PR 描述中显式说明理由。

### 0.2 强制 vs 引导

每条原则标注**强度**：
- 🔒 **强制**：CI/Code Review 必须拒绝违反的 PR
- ⚠️ **强引导**：允许豁免但需文档化理由
- 💡 **建议**：最佳实践，违反不强制

### 0.3 演进

原则不是一成不变的。修改需在 PR 描述中说明：触发场景、新旧对比、影响面。每条原则有 `Last reviewed` 日期。

### 0.4 阅读路径

- 5 分钟扫读：只看每条原则开头的**陈述**和**反例 / 正例**
- 30 分钟理解：加上"规则"和"验收"
- 1 小时沉淀：加上"业内参考"
- 写代码时查表：附录 C 的 checklist

---

## 1. P1 · 路径唯一权威 🔒

> 原则：**所有 Wiki 路径的读与写都必须通过 `reproduction/paths.py` 内的常量和 helper 函数。**

### 1.1 规则

- 写 Wiki：`paper.py` `factor.py` `strategy.py` `reproduction.py` 任何写 `*.md` 的地方
- 读 Wiki：`extract_factors.py` `extract_strategy_config` `list_factors` 等所有 glob 调用
- API 响应：所有返回 `wiki_page` 字段的路径
- 测试 fixture / 文档示例例外，但要写明来源

### 1.2 反模式

```python
# ❌ 硬编码路径字符串
wiki.write_page("wiki/factor/foo.md", ...)
md_path = wiki.wiki_dir / "factors" / f"{slug}.md"
```

### 1.3 正模式

```python
# ✅ 通过 paths module
from llmwikify.reproduction.paths import WIKI_DIR_FACTOR, page_path

wiki.write_page(str(page_path(wiki, WIKI_DIR_FACTOR, slug)), ...)
md_path = page_path(wiki, WIKI_DIR_FACTOR, slug)
```

### 1.4 验收

- `grep -rn "wiki/\(factor\|strategy\|trading\|codegen\|backtest\|optimization\|factor-backtest\|sources\)" src/llmwikify/reproduction/ | grep -v paths.py` 命中 0 处业务代码
- CI 加 lint：禁止 `reproduction/` 外部使用 `pathlib.Path("wiki/...")`

### 1.5 业内参考

> **The Twelve-Factor App §III. Config**
> "Store config in the environment. ... A litmus test for whether an app has all config correctly factored out of the code is whether the codebase could be made open source at any moment, without compromising any credentials."
> — Adam Wiggins, 2017

> **Spring Boot / Externalized Configuration**
> "Configuration should be externalized so the same code can run in different environments."
> — Spring Boot Reference Documentation

> **Google Engineering Practices / Pinned Dependencies**
> "You depend on it, so you should specify it explicitly. ... Pin your dependencies to specific versions."

我们把这些思想延伸到"路径"——路径也是配置，必须外部化、单点。

---

## 2. P2 · Schema 优先 🔒

> 原则：**所有 Wiki 页面必须能用 Pydantic 模型 round-trip 解析。**

### 2.1 规则

- 4 类页面（Source / Factor / Strategy / BacktestResult）各自有 Pydantic 模型
- 写入：构建 Pydantic 实例 → `render_page(model, body)` 序列化为 md
- 读取：`parse_page(content) -> Model`
- 枚举（`factor_class` / `signal_type` / `status` 等）在 `contracts.py` 内集中定义
- spec 文档**从 `contracts.py` 自动生成**（避免人工维护漂移）

### 2.2 反模式

```python
# ❌ 字符串拼接 frontmatter
frontmatter = f"""---
title: {title}
type: Factor
factor_class: {factor_class}
"""
```

### 2.3 正模式

```python
# ✅ Pydantic 序列化
from llmwikify.reproduction.contracts import FactorPage, render_page

page = FactorPage(
    title=title,
    factor_class=factor_class,
    factor_params=factor_params,
    ...
)
md_path.write_text(render_page(page, body=body_md))
```

### 2.4 验收

- `tests/reproduction/test_contracts.py` 包含每个 Page 类的 round-trip 测试
- 所有 Wiki 写入点用 `render_page(model, body)`
- 所有 Wiki 读取点用 `parse_page(content) -> Model`
- 枚举字符串字面量只在 `contracts.py` 出现

### 2.5 业内参考

> **Protocol Buffers / gRPC design philosophy**
> "Define your data first, then generate the code from the schema."
> — Google Protobuf docs

> **Apache Avro: Schema-First Serialization**
> "Avro relies on schemas. When Avro data is read, the schema used when writing it is always present."
> — Apache Avro Specification

> **OpenAPI Specification**
> "The OpenAPI Specification (OAS) defines a standard, language-agnostic interface description for HTTP APIs."

> **The Pragmatic Programmer / "Don't Live with Broken Windows"**
> 类比：坏的 frontmatter 是 broken window，没人修只会越来越多。Pydantic 守住就是不让 broken window 出现。

---

## 3. P3 · 不变量强制 🔒

> 原则：**跨模块的数据关系必须有 test 守门，发现 invariant 违反立即报错。**

### 3.1 规则

跨模块数据关系一旦确立，必须有对应的 invariant test。invariant 写在 `tests/reproduction/test_invariants.py`。

### 3.2 必须守住的不变量

**FactorBacktestResult**：
```python
assert r.total_rebalances >= r.valid_rebalances
assert len(r.n_stocks_per_date) == r.total_rebalances
assert len(r.ic_series) == r.valid_rebalances
assert len(r.group_metrics) in (0, n_groups)
assert len(r.longshort_curve) <= r.total_rebalances + 1
```

**BacktestResult**：
```python
assert len(r.equity_curve) >= 2
assert abs(r.final_cash - r.equity_curve[-1].value) / r.final_cash < 0.01
for ym in r.monthly_returns:
    assert start_date <= date(int(ym[:4]), int(ym[5:]), 1) <= end_date
```

**Reproduction 状态机**：
```
合法：pending → extracting → data.fetching → backtesting → analyzing → done
合法：* → error
非法：done → extracting 等
```

**Wiki 引用**：
```python
for ref in strategy_page.factor_refs:
    assert (wiki.wiki_dir / "factor" / f"{ref}.md").exists()
```

### 3.3 触发时机

| 触发 | 行为 |
|---|---|
| 单元测试 | `test_invariants.py` 集中检查 |
| 集成测试 | 每个子系统端到端测试末调用 `assert_*_invariants(result)` |
| 调试 hook | 开发模式下 API 响应返回前自动检查，违反记 warning |
| CI | 必须通过，否则 PR 拒绝 |

### 3.4 与 P2 的分工

- P2 = 单数据 shape 合法（字段名/类型/必填）
- P3 = 多数据 shape 关系合法（长度/区间/存在性）

### 3.5 业内参考

> **Bertrand Meyer / Design by Contract (1986)**
> "An invariant is a property of the system that holds throughout execution. ... In DbC, the relationship between a class and its clients is viewed as a formal agreement, expressing each party's rights and obligations."
> — Object-Oriented Software Construction, Bertrand Meyer

> **PostgreSQL / CHECK constraints**
> "Check constraints specify that the value in a certain column must satisfy a Boolean (truth-value) expression."

> **Martin Fowler / "Refactoring" — "Replace Magic Number with Symbolic Constant"**
> 不变量就是被命名的 magic。把它命名、写下来、守住。

> **HashiCorp Terraform / Sentinel**
> "Sentinel is a policy as code framework that allows you to enforce invariants."
> — HashiCorp Sentinel Docs

> **CERN ROOT / Consistency Checks**
> 大型科学软件（CERN 用的 ROOT / Facebook TAO / 各类金融交易系统）的常见模式：每个模块出口都跑 invariant check，违反即 panic。

---

## 4. P4 · 端到端提交 🔒

> 原则：**一个 PR 必须走完一个子系统的"用户点击 → 后端处理 → Wiki 写入 → UI 显示"端到端流程。**

### 4.1 端到端 PR 的最小标准

| 检查项 | 说明 |
|---|---|
| 后端代码 | 端到端能跑通（手动 + 集成测试） |
| 前端代码 | UI 上能看到后端产物变化（截图） |
| Wiki 产物 | 实际写入的 md 文件 diff 展示在 PR 中 |
| 测试 | 端到端 happy path + 1 个边界 case |
| 截图 | UI 截图（前后对比） |
| 文档 | 重整文档 v0.5.0 Stage 列表的 checkbox 打钩 |

### 4.2 反例（不允许的 PR 模式）

```
PR #1: "feat(factor): add group_metrics field"  (后端)
PR #2: "feat(factor): add metrics to UI"  (前端)
PR #3: "test: add group metrics invariant"  (测试)
```
3 个 PR，每个只动一层，UI 端到端跑不通。

### 4.3 正例

```
PR #1: "feat(factor-stage2): cross-section group_metrics 端到端"
  - 后端：FactorBacktestResult.group_metrics 字段 + 算法
  - 前端：GroupMetricsTable.tsx + FactorPanel 集成
  - 测试：test_factor_backtest_cross_section + test_invariants
  - 截图：FactorPanel Quantile tab 显示 G1-G5 明细表
  - 文档：v0.5.0 Stage 2 checkbox 勾上
```

### 4.4 例外

- 紧急 bug fix：可不端到端，但需要 follow-up PR
- 重构（无功能变化）：可不端到端，但不破坏现有功能
- 文档/注释/PR template：明显豁免

### 4.5 业内参考

> **Jez Humble & David Farley / Continuous Delivery (2010)**
> "The deployment pipeline is the set of validations that a change has to pass before it can be deployed to production. ... Every change should be deployable. If a change is not deployable, then the team should make it deployable as soon as possible."

> **Eric Ries / The Lean Startup (2011) — "Minimum Viable Product"**
> 每个 PR 是一个 MVP：必须能演示价值。

> **Martin Fowler / "Test Pyramid" (2012)**
> "End-to-end tests are there as a second line of test defense. ... If you get a failure in a high level test, not just do you have a bug in your functional code, you also have a missing or incorrect unit test."

> **GitHub Flow**
> "Anything in the main branch is deployable. ... When you create a branch, you're creating an environment for your work."

> **Accelerate / Nicole Forsgren et al. (2018)**
> "Trunk-based development is correlated with high performance."

P4 本质是：**trunk-based development 的强约束**。每个 PR 必须可部署 = 端到端跑通。

---

## 5. P5 · 算法单一实现 ⚠️

> 原则：**任何算法只允许一处实现。新增/替换时删除旧实现，禁止保留多版本并存。**

### 5.1 规则

- IC / Group / LongShort 只允许一处（QuantNodes 优先）
- 自实现 vs 库函数：取其一，禁用 `if-else` 双路径
- 单元测试只测当前活实现

### 5.2 反模式

```python
# ❌ 双路径并存
if use_quantnodes:
    return quantnodes_group_analyzer(...)
else:
    return my_own_group_analyzer(...)
```

### 5.3 正模式

```python
# ✅ 单一实现
from QuantNodes.research.factor_test.nodes import GroupAnalyzerNode
return GroupAnalyzerNode(...).execute(...)
```

### 5.4 例外

- 实验性新实现可在独立 feature branch，**禁止合并到 main 包含旧实现**
- 性能 critical path 的内联优化：注释清楚为什么不能调用高层

### 5.5 验收

- `grep -rn "TODO.*legacy\|TODO.*old\|TODO.*replace" src/llmwikify/reproduction/` 命中 0
- 同一逻辑没有两个不同名字的函数

### 5.6 业内参考

> **Robert C. Martin / Clean Code (2008) — "Don't Repeat Yourself"**
> "Duplication may be the root of all evil in software. ... The duplication represents an opportunity for abstraction. ... If you find yourself writing similar code in two places, you're making a mistake."

> **Martin Fowler / Refactoring — "Inline Function" / "Replace Inline Code with Function Call"**
> 当逻辑被分散到多处，要么抽取到一处（正模式），要么内联消除重复（也正模式）。**不要并排保留**。

> **Go Proverbs — "A little copying is better than a little dependency."**
> "If you have a 5-line function that's used in three places, don't extract it into a library yet. Copy it. The cost of the wrong abstraction is higher than the cost of the duplication."
> — Rob Pike, Gopherfest SV 2015

我们的 P5 是反方向的：**已经有了"那一份"，禁止再加一份**。Go proverb 处理的是"从无到有"时克制，我们处理的是"从有到多"时克制。

> **The C++ Core Guidelines / "Don't repeat yourself"**
> "If you have duplicated code, extract it into a function. If you have multiple implementations of the same algorithm, delete all but one."

---

## 6. P6 · 路径兼容窗口 = 0 ⚠️

> 原则：**要么立刻迁移到唯一路径，要么读时拒绝。不留隐性 race（两边都接受但行为不同）。**

### 6.1 规则

- 重整开始时，一次性把 `wiki/trading/` → `wiki/strategy/` 和 `wiki/factors/` → `wiki/factor/` 迁移
- 不提供「读时兼容、写时统一」的中间态
- 迁移脚本必须 idempotent，重复运行结果相同

### 6.2 反模式（不允许）

```python
# ❌ 读时 fallback
def read_factor(wiki, slug):
    for subdir in ("factors", "factor"):
        path = wiki.wiki_dir / subdir / f"{slug}.md"
        if path.exists():
            return parse(path)
    return None
```

### 6.3 正模式

```python
# ✅ 单一权威
def read_factor(wiki, slug):
    path = page_path(wiki, WIKI_DIR_FACTOR, slug)
    if not path.exists():
        raise FileNotFoundError(...)
    return FactorPage.model_validate(parse_frontmatter(path))
```

### 6.4 验收

- 迁移后 `wiki/trading/` `wiki/factors/` 目录为空或被删
- 任何"读时 fallback"代码被删除
- 路径常量在 `paths.py` 单点定义

### 6.5 业内参考

> **Kevlin Henney / "Comments Are a Code Smell" / "Delete Dead Code"**
> "Dead code is not a historical artifact. Dead code is a risk. ... Every line of dead code is a line that someone might be tempted to 'fix' without realizing it's dead. Or worse, a line that someone will rely on, only to find it doesn't work."
> — Kevlin Henney, NDC London 2014

> **Google SRE Book / "Just Culture"**
> 兼容窗口让 post-mortem 无法定位 root cause — 因为"是新的还是旧的问题"无法判断。

> **Rust Editions**
> Rust 2018 → 2021 → 2024 每个 edition 删除旧 API，**不无限向后兼容**。迁移工具有，但兼容窗口有限。

> **Python __future__ imports**
> 同样的设计：用 `from __future__ import x` 一次性完成迁移，迁移后删除。

---

## 7. P7 · 兜底可降级 💡

> 原则：**关键路径失败时给出明确降级，而非崩溃或静默错。**

### 7.1 规则

- LLM 失败 → 返回 minimal offline 提取 + 警告
- QuantNodes 不可用 → 临时回退自实现 + 日志
- iFinD 不可用 → 用本地 parquet cache + 标记 stale
- ClickHouse 不可用 → 静默回退 AKShare + 降级警告

### 7.2 兜底契约

```python
def fetch_paper_extraction(paper_id, llm_client) -> ExtractionResult:
    """Always returns ExtractionResult, never raises.
    
    result.status in {success, llm_failed_offline_fallback, llm_disabled}
    result.warnings: list[str]  # 降级原因
    """
```

### 7.3 反模式

```python
# ❌ 静默失败
try:
    return llm_client.extract(...)
except Exception:
    return {}  # 默默返回空，后续 404 用户看不懂
```

### 7.4 正模式

```python
# ✅ 显式降级
try:
    return ExtractionResult(status="success", data=llm_client.extract(...))
except LLMUnavailable:
    return ExtractionResult(
        status="llm_failed_offline_fallback",
        data=offline_extract_from_title(...),
        warnings=["LLM unavailable, used offline extraction"],
    )
```

### 7.5 验收

- 每个有外部依赖的函数都有 try/except + 降级路径
- 降级时输出明确的 `status` + `warnings` 字段
- 日志中降级事件可被 grep 到

### 7.6 业内参考

> **Google SRE Book / Chapter 22 — Addressing Reliability**
> "When a dependency fails, return a degraded but useful response, not a 5xx error. ... The key insight is that reliability is not the same as availability: a system can be highly available by quickly returning 'no' or 'try again later' rather than by always saying 'yes'."

> **Michael Nygard / "Release It!" (2007) — Circuit Breaker Pattern**
> "Wrap a protected call in a circuit breaker object that monitors for failures. ... When failures reach a certain threshold, the breaker trips, and all further calls to the breaker return with an error, without the protected call being made at all."

> **Charity Majors / "Observability is for the 99th percentile" (2019)**
> "Fallback is not failure. Fallback is reliability. ... The best teams in the world have aggressive fallback strategies and very clear warnings when they're in degraded mode."

> **The Twelve-Factor App / IX. Disposability**
> "Maximize robustness with fast startup and graceful shutdown. ... The process should be robust against sudden death."

> **Progressive Enhancement (Web standards)**
> "Build the core experience first, then enhance. If JavaScript fails, the core still works."

---

## 8. P8 · Wiki 即文档 ⚠️

> 原则：**所有产物落 Wiki 而非额外文件 / 数据库 / 临时结构，让任何信息都能被 grep 到。**

### 8.1 规则

- Wiki page = 一等公民
- 不创建 side-by-side 的 `factor_classifier.json` 或 `reproduction.db` 单独存派生数据
- Session DB 存：执行状态、event log、artifact 路径
- Session DB 不存：计算结果、metrics、equity curve（这些落 Wiki）

### 8.2 验收

- `find . -name "*.json" -not -path "./node_modules/*" -not -path "./.git/*" -not -path "./wiki/*"` 命中极少（仅 package-lock 等）
- 任何 metrics 都能通过 `wiki/factor-backtest/{slug}.md` 看到

### 8.3 业内参考

> **Donald Knuth / "Literate Programming" (1984)**
> "Instead of imagining that our main task is to instruct a computer what to do, let us concentrate rather on explaining to human beings what we want a computer to do."

> **Docs as Code (Various)**
> "Documentation should live in the same repository as the code, written in the same format, reviewed with the same process, and versioned with the same tooling."

> **Jupyter Notebooks (Project Jupyter)**
> Notebooks are simultaneously:
> 1. Code that runs
> 2. Output that documents execution
> 3. Markdown that explains intent
> We adopt the same idea for Wiki pages.

> **GitHub README.md culture**
> "Markdown is the lingua franca of the modern developer."

---

## 9. P9 · Spec 与代码同源 💡

> 原则：**枚举值在 `contracts.py` 定义，spec 文档自动生成，避免人工维护漂移。**

### 9.1 规则

- `factor_class` / `signal_type` / `strategy_class` / `status` 等枚举只在 `contracts.py` 出现
- spec 文档生成脚本：`python -m llmwikify.reproduction.specgen > docs/plan/reproduction-spec.md`
- CI 检查 spec 文档和 contracts.py 一致
- PR 修改枚举值时，spec 必须同步

### 9.2 工具

```python
# specgen.py
from llmwikify.reproduction.contracts import (
    FactorClass, SignalType, StrategyClass, Status,
)

def render_enum(enum_cls) -> str:
    lines = [f"### `{enum_cls.__name__}`", ""]
    for member in enum_cls:
        lines.append(f"- `{member.value}` — {member.__doc__ or ''}")
    return "\n".join(lines)
```

### 9.3 业内参考

> **Single Source of Truth (Wikipedia summary)**
> "The single source of truth (SSOT) is the practice of structuring information models and associated data schemas such that every data element is stored exactly once. ... SSOT is often associated with the concept of data normalization."

> **Protocol Buffers / Generated Code**
> "Protobuf compiler generates data access classes, function stubs for RPC, etc. from the schema."

> **CUE / JSON Schema with codegen**
> "CUE is a data validation language. It is designed for describing data and validating it. ... CUE generates code from schemas."

> **Terraform / HCL**
> "HCL is a structural configuration language. ... Configuration is expressed declaratively, then generated to a plan, then applied."

---

## 10. P10 · 测试即 Invariant ⚠️

> 原则：**bug 暴露后第一件事是写 regression test，第二件事才是修。**

### 10.1 规则

- 每个修复 bug 的 PR 必须在描述中回答：哪个 invariant 失败？为什么 invariant test 没守住？
- 如果 invariant 缺失，PR 必须**先添加 invariant test（红），再修复（绿）**
- 严禁只修代码不补测试

### 10.2 流程

```
1. 复现 bug（手动或 e2e）
2. 写一个失败的测试，断言 invariant（红）
3. 修复代码（绿）
4. 把 invariant test 沉淀到 test_invariants.py
5. 提交：fix + test 必须同 PR
```

### 10.3 反模式

```python
# ❌ "我先修，测试以后补"  → 永远不补
def fix_bug():
    code.patch()
    return "fixed"  # 忘了写 test
```

### 10.4 业内参考

> **Kent Beck / Test-Driven Development by Example (2002)**
> "Never write a line of functional code without a broken test. ... The flow is: Red → Green → Refactor."

> **Charity Majors / "Bugs are stories" (2018)**
> "Every bug is a story about your system. The post-mortem isn't a punishment; it's an opportunity to learn. ... The test you write after the fact is the moral of the story."

> **Martin Fowler / TestPyramid (2012)**
> "I always argue that high-level tests are there as a second line of test defense. If you get a failure in a high level test, not just do you have a bug in your functional code, you also have a missing or incorrect unit test. Thus I advise that before fixing a bug exposed by a high level test, you should replicate the bug with a unit test. Then the unit test ensures the bug stays dead."

> **Hillel Wayne / The Bug Lawyer**
> "Bug reports are like legal cases — they specify behavior. A regression test is the 'judgment' that locks in the correct behavior."

> **Property-Based Testing (Hypothesis / QuickCheck)**
> John Hughes: "Don't write tests — generate them. ... Define properties, let the framework find the inputs that break them."

---

## 11. 附录 A：业界原则全景表

| 原则 | 出处 | 与本项目原则对应 | 借鉴点 |
|---|---|---|---|
| **Don't Repeat Yourself (DRY)** | Clean Code / Fowler | P5 算法单一 | 同一逻辑不重复实现 |
| **Single Source of Truth (SSOT)** | DB / API 设计 | P1 / P9 | 唯一权威来源 |
| **Design by Contract (DbC)** | Bertrand Meyer | P3 | pre/post-condition / invariant |
| **Schema First** | Protobuf / Avro | P2 | 类型系统守住接口 |
| **Continuous Delivery** | Jez Humble | P4 | 部署单元 = 价值单元 |
| **Twelve-Factor App** | Heroku | P7 / P8 | 配置与代码分离 |
| **You Build It, You Run It** | Amazon | P7 | 责任到人 |
| **Test-Driven Development** | Kent Beck | P10 | Red-Green-Refactor |
| **Literate Programming** | Knuth | P8 | 代码即叙事 |
| **Property-Based Testing** | Haskell QuickCheck | P3 | 自动生成边界 case |
| **Circuit Breaker** | Nygard | P7 | 熔断 + 降级 |
| **Progressive Enhancement** | Web standards | P7 | 核心先可用 |
| **A Little Copying > Little Dependency** | Go Proverbs | P5 反向 | 克制的复用 |
| **Pinned Dependencies** | Google Eng | P1 | 避免漂移 |
| **Externalized Configuration** | Spring | P1 | 配置独立 |
| **Consistency Checks** | CERN / Facebook TAO | P3 | 大型系统 invariant |
| **Fallback is not Failure** | Charity Majors | P7 | 降级是责任 |
| **Markdown is Lingua Franca** | GitHub | P8 | 人类可读 |
| **Code as Spec** | Protocol Buffers | P9 | schema-first |
| **Test Pyramid** | Mike Cohn / Fowler | P4 / P10 | e2e 触发 unit test |
| **Always Be Shipping** | GitHub Flow | P4 | 频繁合并 |
| **Trunk-Based Development** | Accelerate | P4 | 高性能团队 |
| **Phoenix Server** | Netflix | P6 隐喻 | 重生胜于腐烂 |
| **Just Culture** | Google SRE / Sidney Dekker | P3 / P6 | 不指责，定位根因 |

---

## 12. 附录 B：原则与重整文档的对应

| 原则 | 解决重整文档 §3 的哪个根因 |
|---|---|
| P1 路径唯一 | A 双轨制、B 路径硬编码 |
| P2 Schema 优先 | D 配置与实现不同步、§3.2 路径不一致 |
| P3 不变量强制 | E 反馈环缺失、§3.1 数字错位 |
| P4 端到端提交 | §3 整体、避免 5 轮迭代重现 |
| P5 算法单一 | C 责任链不明、IC/Group 三处实现 |
| P6 兼容窗口=0 | A 双轨制 |
| P7 兜底可降级 | §3.1 P0 断链（Paper 永远为空、router 404） |
| P8 Wiki 即文档 | §4.1 端到端产物沉淀 |
| P9 spec 同源 | §3.2 spec 与代码脱节、§2.6 枚举对照表 |
| P10 测试即 invariant | §3.1 反馈环缺失 |

---

## 13. 附录 C：原则 checklist（新 PR 提交前自查）

复制到 PR 模板：

```markdown
## 端到端验证
- [ ] 后端代码改动已手测跑通
- [ ] 前端 UI 截图 / 录屏
- [ ] Wiki 产物 diff 已附上
- [ ] pytest 通过
- [ ] 文档 checkbox 已勾

## 原则符合性
- [ ] P1 路径唯一：无 `wiki/...` 字符串字面量
- [ ] P2 Schema 优先：所有写入用 `render_page(model)`
- [ ] P3 不变量：新加的字段有 invariant test
- [ ] P4 端到端：UI 截图 / 后端 trace 齐全
- [ ] P5 算法单一：未引入第二份实现
- [ ] P6 兼容窗口：未留「读时 fallback」
- [ ] P7 兜底：失败路径返回降级 + warnings
- [ ] P8 Wiki 即文档：无 side-by-side 派生文件
- [ ] P9 spec 同源：枚举值改动同步 contracts.py
- [ ] P10 测试即 invariant：bug 修复伴随 invariant test
```

---

## 14. 附录 D：日常工作中的实践指南

### 14.1 写新功能时

```
1. 先看 P1-P3 决定：新功能落哪个 Wiki 目录、字段 schema 是什么、哪些 invariant 必须守
2. 实现前先写 P3 的 invariant test
3. 实现：paths.py + contracts.py + Pydantic round-trip
4. 验证：UI 截图 + 端到端测试
5. 自查 P10 checklist
```

### 14.2 修 bug 时

```
1. 复现 bug（手动或现有 e2e）
2. 写 regression test（P10 红）
3. 修代码
4. 思考：bug 暴露了什么 invariant 缺失？补充到 test_invariants.py
5. 提交：fix + test + invariant 补全必须同 PR
```

### 14.3 重构时

```
1. 评估影响面（grep 引用、改动文件、spec）
2. 写入 P6 兼容窗口判断：能否一次迁移？
3. 准备 P2 Pydantic 迁移
4. 一次提交（哪怕大）— 不要跨 PR 留中间态
```

### 14.4 评审他人 PR 时

```
1. 跑 P10 checklist 5 项强制
2. 跑 P3 不变量（如果新字段没补 invariant test，拒绝）
3. 跑 P4 端到端（缺 UI 截图拒绝）
4. 跑 P1 路径（grep 一下）
5. 不要评论行级细节（那是 PR 的工作流）
```

---

## 15. 附录 E：反例库（**不要**这样写）

| 反例 | 来自哪里 | 原因 | 状态 |
|---|---|---|---|
| `if use_quantnodes: ... else: ...` 双路径 | factor_backtest.py 现状 | 违反 P5 | 待修 (Stage 2) |
| `for subdir in ("trading", "strategy"): ...` 读时 fallback | ~~extract.py 现状~~ extract_strategy.py:112 | 违反 P6 | ✅ 已修 (G+Y Stage 0) |
| `try: ... except: return {}` 静默失败 | paper.py 现状 | 违反 P7 | 待修 (Stage 5) |
| `factor_metrics = json.load("side.json")` 派生数据 | 不存在但潜在 | 违反 P8 | 守门中 |
| spec 写 `factor_class: momentum` 与代码 `factor_class: Momentum` 大小写不一致 | spec 现状 | 违反 P9 | 待修 |
| "我先修，测试以后补" | 协作中常见 | 违反 P10 | 流程约束 |
| `wiki/factor/` 和 `wiki/factors/` 都能写 | ~~现状~~ 迁移脚本 `migrate_wiki_factors_to_factor.py` | 违反 P1 | ✅ 已修 (G+Y Stage 0) |
| 一周后才补的 invariant test | `tests/reproduction/test_invariants.py` (20 测试) | 违反 P3 | ✅ 已修 (G+Y Stage 0) |

---

## 16. 版本与变更

| 版本 | 日期 | 变更 |
|---|---|---|
| v1.1 | 2026-06-12 | 添加 13-15 章节（应用指南、反例库、业内参考详化） |
| v1.0 | 2026-06-12 | 合并 P1-P10，附录 A 业界参考 |
| 内部 draft | 2026-06-12 | 初次拆分 P1-P4 为单独文件 |
