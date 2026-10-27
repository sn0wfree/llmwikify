# 代码复用优化方案（graphify + AST 实测）

> **日期**: 2026-10-27 · **基线 commit**: `89684cc3` (v0.41-dev)
> **性质**: 文档先行，方案待评审，**尚未改任何代码**
> **工具**: graphify 0.9.96 (`extract . --code-only`，纯 AST 无 LLM 成本) + 自写 AST 归一化克隆检测

---

## 1. 工具与数据来源

```
graphify 0.9.96  extract . --code-only
  → 19312 nodes · 40747 edges · 696 communities
  → Deduplicated 44 nodes (30 exact, 14 fuzzy)
另加自写 AST 归一化克隆检测（结构哈希，去名字/字面量/位置）
```

graphify 报告位置：`graphify-out/GRAPH_REPORT.md`、`graphify-out/graph.json`（**不入仓**）。

---

## 2. 先纠正一处外部结论

其他 agent 检查 main 时给出的 CLI 结论与实测不符，先校准，避免按错数据做设计。

| 说法 | 实测 | 判定 |
|------|------|------|
| CLI `setup_parser`「472 行浪费 = 全部克隆浪费的 49%」 | 33 命令共 **655 行**，其中 4 行样板 × 33 = **119 行（18%）**；**536 行是真正的参数定义**（业务载荷） | **高估约 4×** |
| 「CLI 命令几乎逐字重复」 | 两两相似度**均值 0.47**；528 对中仅 **12 对 ≥ 0.80** | 不成立 |

**结论**：CLI 的问题不是「克隆」，而是**样板未抽**（119 行）。这决定了 R2 的做法——
**只抽 4 行 helper，绝不做生成器**。

---

## 3. 实测复用现状

### 3.1 精确克隆浪费（AST 结构哈希，全 src）

**总计 644 行**

| 文件 | 浪费行 | 内容 |
|------|------:|------|
| `apps/chat/db/research_delegate.py` | **179** | 与 `_facade.py` 的 8 组方法逐字相同 |
| `foundation/auth/db.py` | 56 | `UserRepository._init_schema` 38 行 ≈ `ApiKeyRepository._init_schema` 35 行 |
| `apps/chat/db/wiki_delegate.py` | 49 | 与 `_facade.py` 5 组方法逐字相同 |
| `kernel/wiki/mixins/core/utility.py` | 30 | `_build_merge_notice` 与 `storage/backend.py` 相同 |
| `apps/chat/skills/workflows/skill.py` | 29 | `_format_run_not_found` 与 `autoresearch_compound_skill.py` 相同 |
| `kernel/agent/loop.py` | 22 | `execution_context` 与 `chat/agent/runner_v2.py` 相同 |
| `apps/research/report.py` + `chat/harness/review.py` + `chat/clarifier.py` | 44 | 3 组 `__init__` 样板 |

### 3.2 转发层（graphify god-node + AST 统计）

| 层 | 文件 | 总行 | 纯转发 | 真实现 |
|----|------|-----:|-------:|-------:|
| ChatDatabase | `apps/chat/db/_facade.py` | 740 | **64 方法 / 271 行** | 12 方法 / 261 行 |
| ResearchDelegate | `apps/chat/db/research_delegate.py` | 318 | **28 方法 / 137 行** | 6 / 85 |
| WikiDelegate | `apps/chat/db/wiki_delegate.py` | 150 | **17 方法 / 69 行** | 2 / 9 |
| ResearchDatabase | `apps/research/db.py` | 1039 | 0 | 37 / 932 |
| WikiDatabase | `apps/wiki/db.py` | 431 | 2 / 10 | 19 / 340 |

**转发合计 487 行**。三层共用同一 `.llmwiki_agent.db`；
`ResearchDelegate` 的 docstring 已自带 `DEPRECATED`。

调用面（AST 全量）：`apps/chat/session.py`、`chat/engine_helpers.py`、
`chat/memory/__init__.py`、`apps/agent/tools/__init__.py`、`apps/research/routes.py`
—— 均只认 facade 的**方法名**，不认中间层。

### 3.3 结构性问题

**import 环 ×5**，同一条根：

```
kernel/wiki/mixins/analysis/status.py:5   from llmwikify import __version__
                                            ↓
llmwikify/__init__.py:30                   from .kernel import Wiki, WikiIndex
```

`kernel` 反向依赖包根 → 违反本项目「kernel 不依赖 apps/interfaces」的方向约定。

**god-node（出度）**：`Wiki` 434 · `SkillContext` 327 · `ChatRunnerV2` 167 ·
`ChatDatabase` 166 · `SkillResult` 160 · `SkillRegistry` 136 · `PromptRegistry` 131

**模块扇入**：`apps/chat/skills/base.py` **654**（基类，正常）·
`kernel/agent/_core_types.py` 129 · `interfaces/cli/_base.py` 107 ·
`interfaces/cli/_output.py` 88 · `foundation/auth/db.py` 82

---

## 4. 优化项（按 收益/风险 排序）

### 🔴 R1 — 删掉 `ResearchDelegate` / `WikiDelegate` 中间层（结构性）

| 项 | 内容 |
|----|------|
| **问题** | `ChatDatabase → ResearchDelegate → ResearchDatabase` 三层转发，方法体逐字相同；中间层 docstring 已标 DEPRECATED |
| **做法** | `ChatDatabase` 直接持 `ResearchDatabase` / `WikiDatabase` 实例，facade 方法改为 `return self._research.create_research_session(...)`（保留一层）；删 `research_delegate.py`(318) + `wiki_delegate.py`(150) |
| **收益** | **删 468 行**（两文件）；转发 487 → 约 240 行 |
| **必须保住** | ① `ResearchDatabase(foreign_keys=False)` 语义（research 表不启用 FK）② `ChatDatabase` 侧 `PRAGMA foreign_keys = ON` ③ 同一 `.llmwiki_agent.db` 路径 |
| **风险** | 中。外部只调 facade 方法名 → 理论上零外部改动；但 `AutoResearchDatabase` 别名、`get_autoresearch_db_path` 兼容别名要留 |
| **验证** | `test_apps_chat_db.py` / `test_apps_db.py` / `test_research_save.py` / `test_apps_chat_db_research_run_id.py` 全绿；删层前后 facade 方法数一致 |
| **建议** | 独立 PR、独立 commit；先 `ResearchDelegate`（179 行克隆主体），`WikiDelegate` 次之 |

> ⚠️ 不要「抽公共函数」——那是**再加一层**。正确解法是**删中间层**。

### 🟠 R2 — CLI `setup_parser` 抽 4 行 helper（不是生成器） ✅ 已完成

```python
# interfaces/cli/_base.py
def add_subparser(subparsers, name, help, **kwargs) -> argparse.ArgumentParser:
    """Validate ``subparsers`` and register a parser for one command."""
    if not isinstance(subparsers, _SubParsersAction):
        raise TypeError("setup_parser requires an argparse subparsers action")
    return subparsers.add_parser(name, help=help, **kwargs)


class CommandBase(Command):
    """Base class for CLI command implementations."""

    def _sub(self, subparsers) -> argparse.ArgumentParser:
        return add_subparser(subparsers, self.name, self.help)
```

33 个命令的 `setup_parser` 从 6 行样板改为 1 行 `p = self._sub(subparsers)`。

| 项 | 内容 |
|----|------|
| **收益** | **净减 97 行**（136 增 / 233 删）；错误文案唯一化 |
| **不做** | T4「脚手架生成器」——YAGNI，33 命令不构成模板化前提 |
| **设计要点** | `Command` **保持为纯结构化 Protocol**（不加 `_sub`）——否则鸭子类型命令 `isinstance(cmd, Command)` 会失效（`test_cli_framework.py::test_command_protocol_is_runtime_checkable`）。helper 放在 `CommandBase` mixin 上 |
| **风险** | 低。`test_cli_framework.py` / `test_cli_registry_dispatch.py` / `test_cli_comprehensive.py` / `test_cli_integration.py` 兜底 |
| **实测** | CLI 套件 107 passed，0 新增失败；全量 4754 passed / 66 failed（failed −2） |

### 🟠 R3 — `foundation/auth/db.py` 两个 `_init_schema` 合并

`UserRepository._init_schema`(38) 与 `ApiKeyRepository._init_schema`(35) 结构约 90% 相同。

| 项 | 内容 |
|----|------|
| **做法 A** | 抽 `_base_schema(conn)` 建公共表，各自差异部分保留 |
| **做法 B** | `ApiKeyRepository` 继承 `UserRepository` 的 schema 初始化 |
| **收益** | **减约 35 行**；消除「加字段要改两处」的维护陷阱 |
| **风险** | 低-中。需确认两表索引/约束无耦合 |

### 🟡 R4 — 三处小重复合并

| 重复 | 位置 | 行数 | 建议 |
|------|------|-----:|------|
| `_build_merge_notice` | `kernel/storage/backend.py:437` + `kernel/wiki/mixins/core/utility.py:236` | 19×2 | 后者改调前者（backend 已被 wiki 依赖） |
| `_format_run_not_found` | `apps/chat/skills/autoresearch_compound_skill.py:28` + `apps/chat/skills/workflows/skill.py:43` | 29×2 | 提到 `apps/chat/skills/errors.py`（已有同族模块） |
| `execution_context` | `apps/chat/agent/runner_v2.py:192` + `kernel/agent/loop.py:292` | 22×2 | runner_v2 是 kernel 的薄封装，可直接委托 |
| `__init__` 样板 ×4 | clarifier / harness.review / research.report / retry_managers | 11×4 | 视语义是否真同，**不同则不强抽** |

**合计约 90 行**，风险低。

### 🟡 R5 — 修 `kernel → llmwikify` 的 import 环

```
kernel/wiki/mixins/analysis/status.py:5   from llmwikify import __version__
```

| 做法 | 说明 |
|------|------|
| **A（推荐）** | `__version__` 下沉到叶子模块（如 `foundation/version.py`），包根 `__init__.py` 再 re-export；`status.py` 改从 `foundation` 取 |
| B | `status.py` 改用 `importlib.metadata.version("llmwikify")`（运行期开销，无导入环） |

**收益**：消除 5 条 import 环，修复「kernel 依赖包根」的方向违规。**风险低，收益明确**。

### ⚪ R6 — 观察项（本次不动）

| 项 | 数据 | 判断 |
|----|------|------|
| `apps/chat/skills/base.py` 扇入 654 | 基类 | **不动** |
| `Wiki` 434 / `SkillContext` 327 | 组合根 / 数据类 | **不动**（高扇入是设计意图，非重复） |
| `ChatDatabase` 64 个转发方法 | R1 后仍剩 | API 面可收窄再议 |
| `apps/chat/agent/runner_v2.py` 1061 行 | 大文件 | 属**拆分**议题，非复用议题，另议 |

---

## 5. 建议执行顺序

```
批次 1（低风险，立即做）      收益 ~120 行，1~2 小时
  R2  CLI _sub helper
  R4  三处小重复合并
  R5  __version__ 下沉，修 import 环

批次 2（中风险，独立 PR）     收益 ~470 行
  R1  删 ResearchDelegate（先）→ 删 WikiDelegate（次）
  R3  auth/db 两 schema 合并

不动：R6 全部观察项
```

---

## 6. 不建议做的

| 提案 | 不做的理由 |
|------|-----------|
| T4 CLI 脚手架生成器 | 实测相似度均值 0.47，33 命令不满足模板化前提；抽象收益 < 维护成本 |
| T5 通用行级正则扫描器 | B1 实际只是 **1 处 compile 位置错误**，抽象反而增加耦合 |
| 「抽公共函数」处理 DB 三层 | 那是**再加一层**，正确解法是删中间层 |
| 重构 `Wiki` / `SkillContext` 等 god-node | 它们是**组合根与数据类**，高扇入是设计意图 |

---

## 7. 待拍板事项

1. **R1 范围**：先只删 `ResearchDelegate`（179 行克隆主体、风险可控），
   还是连 `WikiDelegate` 一起？
2. **R1 兼容策略**：`AutoResearchDatabase` / `get_autoresearch_db_path`
   这类别名保留还是同批删除？
3. **R3 做法**：抽 `_base_schema()` 公共建表，还是
   `ApiKeyRepository` 继承 `UserRepository`？
4. **执行位置**：全部在 `v0.41-dev` 上做，还是 R1 单独切
   `refactor/db-delegate` 分支？

---

## 附：与 B1 的关系

B1（lint 矛盾检测正则提出循环外 + 系词预筛，已完成于 `83158568`）属**性能**议题，
与本方案**不重叠**：B1 只需把 1 处 compile 移出循环，不需要通用扫描器。
差分守卫见 `tests/test_lint_contradiction_parity.py`。
