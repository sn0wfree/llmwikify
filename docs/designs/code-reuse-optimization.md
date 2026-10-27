# 代码复用优化方案（graphify + AST 实测）

> **日期**: 2026-10-27 · **基线 commit**: `89684cc3` (v0.41-dev)
> **复核 commit**: `dea463f1`（R2 已落地）· 复核文档：`docs/designs/codebase-survey.md`
> **性质**: 文档先行，方案待评审（R2 已完成，其余未动代码）
> **工具**: graphify 0.9.96 (`extract . --code-only`，纯 AST 无 LLM 成本) + 自写 AST 归一化克隆检测（`scripts/clone_survey.py`）

> 📌 **2026-10-27 复核修订**：本方案经 `docs/designs/codebase-survey.md` 独立复核，
> **R1 / R3 / R5 三处已按实测修订**（见各节「复核修订」标注）。
> 复核用的 AST 指标工具已入库：`scripts/clone_survey.py`。

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

> **口径说明**（复核补充）：487 行按「方法体行数」计。
> 若按「函数全行（含签名 + docstring）」计，DB 三层为 **657 行**；
> 全 src 扫描（不只 DB 三层）则为 **834 行**。
> 两种口径不可直接比较 —— 见 `docs/designs/codebase-survey.md` §2.4 的完整分布。

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

> **口径说明**（复核补充）：graphify 把 `tests/` 一并纳入图，
> 实际出度榜首是 **`_make_spec()` 597** 与 **`_make_full_runner()` 436**
> —— 两个都是**测试 fixture helper**。上表已排除测试节点。
> 排除后前 8 名不变，且**全部是组合根 / 数据类 / 注册表**，
> 印证下方 R6「高扇入是设计意图，非重复」的判断。

**模块扇入**：`apps/chat/skills/base.py` **654**（基类，正常）·
`kernel/agent/_core_types.py` 129 · `interfaces/cli/_base.py` 107 ·
`interfaces/cli/_output.py` 88 · `foundation/auth/db.py` 82

---

## 4. 优化项（按 收益/风险 排序）

### 🔴 R1 — 删掉 `ResearchDelegate` / `WikiDelegate` 中间层（结构性）

| 项 | 内容 |
|----|------|
| **问题** | `ChatDatabase → ResearchDelegate → ResearchDatabase` 三层转发，方法体逐字相同；中间层 docstring 已标 DEPRECATED |
| **做法** | `ChatDatabase` 内部保留**惰性**访问（把 delegate 的 `@property` 惯用法搬进门面），facade 方法改为 `return self._research.create_research_session(...)`（保留一层）；删 `research_delegate.py`(318) + `wiki_delegate.py`(150) |
| **收益** | **删 468 行**（两文件）；转发 487 → 约 240 行 |
| **必须保住** | ① `ResearchDatabase(foreign_keys=False)` 语义（research 表不启用 FK）—— ⚠️ **删层本身保不住**，必须叠加「按 profile 建连」的改造（见下方 **批次 0 修订**）② 同一 `.llmwiki_agent.db` 路径 ③ **惰性建表时机**（见下方复核修订） |
| **风险** | **低**（原评「中」偏高）。delegate 在门面之外**零生产调用方**；`AutoResearchDatabase` / `get_autoresearch_db_path` **必须保留**（`apps/research/` 5 个生产模块 + 5 个测试文件在用） |
| **验证** | `test_apps_chat_db.py` / `test_apps_db.py` / `test_research_save.py` / `test_apps_chat_db_research_run_id.py` 全绿；删层前后 facade 方法数一致；**外加 `test_apps_chat_db_research_delegate.py` / `test_apps_chat_db_wiki_delegate.py`**（见下方复核修订） |
| **建议** | 独立 PR、独立 commit；先 `ResearchDelegate`（179 行克隆主体），`WikiDelegate` 次之 |

> ⚠️ 不要「抽公共函数」——那是**再加一层**。正确解法是**删中间层**。

#### 复核修订（2026-10-27）— R1

**① 验证清单漏了 2 个会真正坏掉的文件**

上表所列 4 个测试**都不覆盖**被删的两个类。真正需要处理的是：

- `tests/test_apps_chat_db_research_delegate.py`（5.3 KB）
- `tests/test_apps_chat_db_wiki_delegate.py`（8.2 KB）

处置二选一：① 随实现删除（改测门面等价路径）；② 改写为直接测 `ResearchDatabase` / `WikiDatabase`。

**② 风险等级从「中」降为「低」**

全仓扫描 `ResearchDelegate` / `WikiDelegate` 的引用点，只有 3 处：
`_facade.py`（import + 实例化）、`apps/chat/db/__init__.py`（2 个 re-export）、以及上述 2 个测试文件。

> delegate docstring 写的「kept for back-compat with **91** / **32** production callers」
> 指的是**门面方法**（`create_research_session` 等）的调用方，**不是 delegate 类的实例化方**。
> 这个措辞会让人误以为删除会波及 91 个调用点 —— 实际不会。**建议同时修正 docstring。**

**③ 真正要保住的是「惰性」；「FK 语义」在批次 0 之前根本就没保住**

| 原「必须保住」 | 实测结论 |
|----------------|----------|
| ① `ResearchDatabase(foreign_keys=False)` | ⚠️ **原结论已作废** —— 复核时以为「只要直接实例化 `ResearchDatabase` 就自动保留」，**实测是假的**：`get_connection()` 的单例注册表**只按 path 做 key**，`kwargs` 仅在**首次创建**时生效。`AutoResearchDatabase` 先构造 Chat（默认 `foreign_keys=True`）→ research 显式请求的 `foreign_keys=False` 被**静默丢弃**，research 表实际跑在 FK=**ON** 下，与 `apps/research/db.py` 的 docstring 相反。已由批次 0.1 修复（见下） |
| ② 门面侧 `PRAGMA foreign_keys = ON` | ⚠️ **已冗余** —— `foundation/db.py:60-61` 在 `connect()` 时就执行了 `PRAGMA foreign_keys = ON`（默认 `foreign_keys=True`）。`_facade.py:225` 那句在事务内、且 FK 本已开启，保留不保留都不影响行为 |
| ③ 同一 `.llmwiki_agent.db` 路径 | ✅ 真实 —— 三层共用 `get_app_db_path(data_dir)` → `data_dir/.llmwiki_agent.db` |

#### 批次 0 修订（2026-10-27）— R1 的前置条件：FK profile 化

R1 若在「删中间层」的同时**不处理连接 profile**，会把一个**已经存在的正确性缺陷**原样带进新结构，
甚至更容易被误当成「R1 引入的回归」。因此 R1 的前置条件改为：

1. `get_connection()` 的单例 key 从 `path` 改为 `(path, profile)`；
2. 新增 `ConnectionProfile`（frozen dataclass）+ `PROFILE_DEFAULT` / `PROFILE_RESEARCH`；
3. `ResearchDatabase` 改用 `profile=PROFILE_RESEARCH` → **两条连接、同一文件**。

为什么必须是两条连接：`PRAGMA foreign_keys` 是**连接级**属性，不是文件级。
在同一文件上「切 pragma」不可能同时满足 chat（FK=ON）与 research（FK=OFF）。

> ⚠️ **由此产生的待评审项**：`journal_mode=WAL` 是**文件级**属性 —— research 连接先开 WAL，
> 会让 chat 连接也进入 WAL 模式。当前 `PROFILE_DEFAULT` 与 `PROFILE_RESEARCH` 的 `wal` 字段同值（均为 `True`），
> 故无实际分歧；但若将来两侧要差异化 WAL，**必须走独立文件**，不能靠 profile。

R1 落地时的验收点追加一条：
**research 侧 FK 必须在「Chat 先构造」与「research 先构造」两种顺序下都保持 OFF**
（回归测试见 `tests/test_batch0_db_profile.py::TestResearchDatabaseForeignKeys`）。

**隐藏风险（原方案完全没提）**：

```
ResearchDelegate._research   ← @property，惰性构造 ResearchDatabase
WikiDelegate._wiki           ← @property，惰性构造 WikiDatabase
AutoResearchDatabase.__init__ ← 急切构造 ResearchDatabase + WikiDatabase
```

现在 `ChatDatabase.__init__` → `ResearchDelegate(data_dir)`，**建表发生在首次调用研究方法时**。
若改成门面 `__init__` 里直接 `new ResearchDatabase(data_dir)`，**建表时机从「首次调用」变成「构造时」**；
副作用：`get_app_db_path()` 里的旧库自动改名（`autoresearch.db` → `.llmwiki_agent.db`）也会提前触发。

👉 **正确做法：门面内部保留 lazy 语义** —— 把 delegate 的 `@property` 惯用法直接搬到门面，
而不是在 `__init__` 里直接实例化。这样删掉的是「中间层类」，**不是「惰性」**。

顺带：`AutoResearchDatabase.__init__`（`_facade.py:734-740`）里那两行急切构造，
在 R1 完成后会变成「ChatDatabase 已经持有同样的实例」的重复 —— 可一并简化，
但**它当前被 `apps/research/` 4 个生产模块 + 5 个测试文件使用，这个类必须保留**。

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

`UserRepository._init_schema`(38) 与 `ApiKeyRepository._init_schema`(35) —— **逐字相同**。

| 项 | 内容 |
|----|------|
| **做法** | 抽**模块级** `_create_auth_schema(conn)`，两个 repository 各自调用 |
| **收益** | **减约 35 行**；消除「加字段要改两处」的维护陷阱；顺带消除「Phase 2.5 迁移检测跑两遍」 |
| **风险** | 低。两表索引/约束无耦合（本就由同一段 DDL 创建） |
| **顺带** | 同文件 `UserRepository._ensure_dir`(92) + `ApiKeyRepository._ensure_dir`(312) 同构（8 行）—— 合并时一并处理 |

#### 复核修订（2026-10-27）— R3

**实测：两个方法不是「约 90% 相似」，而是逐字相同，且都同时创建 `users` + `api_keys` 两张表。**

```
UserRepository._init_schema   (db.py:128)  ─┐
                                            ├─ 同样的 PRAGMA table_info(users) 检测
ApiKeyRepository._init_schema (db.py:325)  ─┘   同样的 DROP/CREATE users + api_keys
```

因此原方案的两个候选做法都需要调整：

- ❌ **原做法 A**「抽 `_base_schema(conn)` 建公共表，各自差异部分保留」——
  **不存在差异部分**，抽出来就是完整的单一函数。
- ❌ **原做法 B**「`ApiKeyRepository` 继承 `UserRepository`」——
  **方向错误**：`ApiKeyRepository` 不是 `UserRepository`，
  继承会建立错误的 is-a 关系，且 `UserRepository` 还带
  `exists()` / `count()` / `get_by_email()` 等用户域方法。

👉 **定稿做法**：抽模块级 `_create_auth_schema(conn)`，两个 repository 各自调用。
既不是继承，也不存在「差异部分」要保留。

**额外收益**：`UserRepository._init_schema` 和 `ApiKeyRepository._init_schema`
各自执行同一段「`PRAGMA table_info(users)` → 检出 `password_hash` → DROP 两表 → 重建」，
只要两个 repository 都被实例化，这段检测**跑两遍**。合并后天然消除。

### 🟡 R4 — 三处小重复合并

| 重复 | 位置 | 行数 | 建议 |
|------|------|-----:|------|
| `_build_merge_notice` | `kernel/storage/backend.py:437` + `kernel/wiki/mixins/core/utility.py:236` | 19×2 | 后者改调前者（backend 已被 wiki 依赖）—— 建议同时把私有名改公开 `build_merge_notice`，跨模块 import 下划线私有名是 smell |
| `_format_run_not_found` | `apps/chat/skills/autoresearch_compound_skill.py:28` + `apps/chat/skills/workflows/skill.py:43` | 29×2 | 提到 `apps/chat/skills/errors.py`（已有同族模块） |
| `execution_context` | `apps/chat/agent/runner_v2.py:192` + `kernel/agent/loop.py:292` | 22×2 | runner_v2 是 kernel 的薄封装，可直接委托 —— 复核后**降级**：payload 口径仅 8~10 行 |
| `__init__` 样板 ×3 | clarifier / harness.review / research.report | 11×3 | 视语义是否真同，**不同则不强抽** |

**合计约 90 行**，风险低。

> **复核修订**（2026-10-27）— R4：
> ① `__init__` 样板是 **3 处不是 4 处** —— `retry_managers` 不构成第 4 处克隆组（AST 结构哈希不一致）。
> ② `_build_merge_notice` 的依赖方向**已验证安全**：`kernel/wiki/mixins/core/utility.py:11`
> 本就 `from llmwikify.kernel.storage.backend import is_path_excluded`，
> 且 `kernel/storage/backend.py` **不反向** import `kernel/wiki`。
> ③ 上述「22×2 / 11×3」为 docstring 口径；按 payload 口径实际代码量分别为 8~10 行 / 5 行/份。

### 🟡 R5 — 修 `kernel → llmwikify` 的 import 环

```
kernel/wiki/mixins/analysis/status.py:5     from llmwikify import __version__
kernel/wiki/mixins/core/utility.py:59        from llmwikify import __version__   ← 复核新增
```

| 做法 | 说明 |
|------|------|
| **A（推荐）** | `__version__` 下沉到叶子模块（如 `foundation/version.py`），包根 `__init__.py` 再 re-export；**两处**都改从 `foundation` 取 |
| B | 改用 `importlib.metadata.version("llmwikify")`（运行期开销，无导入环） |

**收益**：消除 5 条 import 环，修复「kernel 依赖包根」的方向违规。**风险低，收益明确**。

#### 复核修订（2026-10-27）— R5

**① kernel 有两处包根 import，不是一处 —— 只改 `status.py` 不足以消除方向违规**

第二处 `kernel/wiki/mixins/core/utility.py:59` **同样构成环**，实测链路：

```
kernel/wiki/mixins/core/utility.py:59
  → llmwikify/__init__.py:30   (from .kernel import Wiki, WikiIndex)
  → kernel/__init__.py:39      (from .wiki import ... Wiki)
  → kernel/wiki/wiki.py:20     (from .mixins.core.utility import WikiUtilityMixin)
  → kernel/wiki/mixins/core/utility.py:59   ← 闭环
```

👉 **R5 范围必须扩到两处。** 做法 A（`__version__` 下沉到 `foundation/version.py`）
能同时解决两处 —— 下沉后 `kernel` 取值不再经过包根，环即断。

**② 「5 条 import 环」表述需要澄清**

graphify 报的确实是 **5 条文件级环，且全部同根**（`llmwikify/__init__.py` ↔
`kernel/wiki/mixins/analysis/status.py`）—— 这部分原方案**表述准确**。

但用 AST 导入图做 Tarjan SCC，另外查出 **6 个模块级强连通分量**，与包根无关：

| 环 | 模块 |
|----|------|
| 2 | `foundation.config` ↔ `foundation.utils` |
| 2 | `kernel.storage.backend` ↔ `kernel.storage.index` |
| 7 | `foundation.extractors.{base, jina, markitdown_extractor, pdf, text, web, youtube}` |
| 5 | `apps.research.{engine, gates, observer, reasoner, resume}` |
| 2 | `apps.chat.skills.workflows.subagent_runner` ↔ `subagent_worker` |
| 2 | `kernel.wiki.engines.analyzer` ↔ `kernel.wiki.wiki` |

这 6 个环**不违反分层规则**（分层检查实测 0 违规），与 R5 解决的问题不同类别，
多为函数内延迟 import 造成的表面闭环。**建议不并入 R5** —— 否则批次 1 的
「低风险」承诺会被稀释。它们属于**观察项**（见 R6）。

**③ 另 3 处包根 import 在 `interfaces/`，方向合法**

全仓 `from llmwikify import ...` 共 5 处，除上述 2 处 kernel 外，还有
`interfaces/cli/commands/doctor_cmd.py:297`、`interfaces/cli/commands/serve.py:316`、
`interfaces/server/core.py:16`。`interfaces` 可以向下依赖，**分层合法**，
但同样会经包根形成环。是否一并处理属可选，不影响分层合规性。

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
批次 0（先做，独立于一切重构）  收益 0 行，但修掉一个「会误报的守卫」
  N1  scripts/check_architecture.py 修 Windows 控制台 GBK 崩溃  ← ✅ 已完成
  0.1 FK profile 化（ConnectionProfile）                        ← ✅ 已完成（批次 0 前提）
  0.2 achat 返回契约统一（as_text）+ 连接生命周期加固              ← ✅ 已完成

批次 1（低风险）               收益 ~86 行
  R2  CLI _sub helper                        ← ✅ 已完成（dea463f1）
  R4  三处小重复合并
  R5  __version__ 下沉，修 import 环          ← 【复核修订】范围含 utility.py:59

批次 2（中风险，独立 PR）      收益 ~470 行
  R1  删 ResearchDelegate（先）→ 删 WikiDelegate（次）
      ← 【复核修订】保留惰性语义 + 补 2 个 delegate 测试文件 + 修正 docstring
      ← 【批次 0 修订】前置条件：FK profile 化已完成（0.1）
  R3  auth/db 两 schema 合并                  ← 【复核修订】抽模块级 _create_auth_schema(conn)

不动：R6 全部观察项
```

> 批次 3（可选，原方案外）见 `docs/designs/codebase-survey.md` §4 N5 ——
> 按 **payload 口径**的真实重复排名（402 行），以及被 payload 口径排除的「伪重复」。

---

## 6. 不建议做的

| 提案 | 不做的理由 |
|------|-----------|
| T4 CLI 脚手架生成器 | 实测相似度均值 0.47，33 命令不满足模板化前提；抽象收益 < 维护成本 |
| T5 通用行级正则扫描器 | B1 实际只是 **1 处 compile 位置错误**，抽象反而增加耦合 |
| 「抽公共函数」处理 DB 三层 | 那是**再加一层**，正确解法是删中间层 |
| 重构 `Wiki` / `SkillContext` 等 god-node | 它们是**组合根与数据类**，高扇入是设计意图 |
| 「合并」抽象桩方法（复核新增） | `apps/chat/agent/protocols.py` 的 4 组 Protocol 方法、`agent_runner.execution_context` / `ChatDBBase._init_schema` / `BaseDatabase._init_db` 三者 —— docstring 口径看似 42~45 行，**实际代码载荷只有 0~5 行**（全是 `...` / `raise NotImplementedError`），无复用价值 |

---

## 7. 待拍板事项

> 复核已解决 2 项（见下方标注），剩余 2 项待拍。

1. **R1 范围**：先只删 `ResearchDelegate`（179 行克隆主体、风险可控），
   还是连 `WikiDelegate` 一起？
   —— 复核后风险评级由「中」降为「低」，两处均可同批删。
2. ~~**R1 兼容策略**：`AutoResearchDatabase` / `get_autoresearch_db_path`
   这类别名保留还是同批删除？~~ —— ✅ **复核已定：必须保留**。
   `AutoResearchDatabase` 是 `ChatDatabase` 的子类，被 `apps/research/` 的
   `db_migrations.py` / `gatherer.py` / `session.py` / `engine.py` / `routes.py`
   5 个生产模块 + 5 个测试文件使用；`get_autoresearch_db_path` 是
   `get_chat_db_path` 的别名，`test_autoresearch.py` 有断言。3. ~~**R3 做法**：抽 `_base_schema()` 公共建表，还是
   `ApiKeyRepository` 继承 `UserRepository`？~~ —— ✅ **复核已定**：
   抽**模块级 `_create_auth_schema(conn)`**。两个 `_init_schema` 逐字相同
   （都建 `users` + `api_keys`），不存在「差异部分」；继承是错误的 is-a 关系。
4. **执行位置**：全部在 `v0.41-dev` 上做，还是 R1 单独切
   `refactor/db-delegate` 分支？

---

## 附：与 B1 的关系

B1（lint 矛盾检测正则提出循环外 + 系词预筛，已完成于 `83158568`）属**性能**议题，
与本方案**不重叠**：B1 只需把 1 处 compile 移出循环，不需要通用扫描器。
差分守卫见 `tests/test_lint_contradiction_parity.py`。
