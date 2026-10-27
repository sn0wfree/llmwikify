# llmwikify 代码库梳理（graphify + AST 独立复核）

> **日期**: 2026-10-27 · **基线 commit**: `dea463f1`（R2 已落地）/ HEAD `5398f6d3`
> **性质**: 对 `docs/designs/code-reuse-optimization.md` 的**独立复核** + 文档未覆盖的新发现
> **工具**: graphify 0.9.96（`extract . --code-only`，纯 AST 无 LLM 成本）+ 自写 AST 归一化克隆检测（`scripts/clone_survey.py`）
> **状态**: 文档先行，**未改任何 `src/` 代码**
>
> ⚠️ 复核期间 R2 由另一会话提交为 `dea463f1`（含原方案文档同步更新）。
> 本文所有 `src/` 实测均针对该 commit 的树，与提交内容一致。

---

## 1. 结论摘要

原方案的方向判断是对的（删中间层而不是加抽象、R2 只抽 helper 不做生成器），
但**有 3 处必须修订才可执行**，另有 **7 项文档未覆盖的发现**。

**必须修订（否则按原方案做会踩坑）**

| # | 原方案 | 问题 | 修订 |
|---|--------|------|------|
| **A** | R5 只改 `kernel/wiki/mixins/analysis/status.py:5` | **`kernel/wiki/mixins/core/utility.py:59` 是第二处 `from llmwikify import __version__`**，同样构成 kernel→包根的环。只改 status.py，kernel 的方向违规依然存在 | R5 范围扩到两处 |
| **B** | R3 做法 B：「`ApiKeyRepository` 继承 `UserRepository`」 | 两个 `_init_schema` **逐字相同**（不是「90% 相似」），没有「各自差异部分」可保留；且 `ApiKeyRepository` 继承 `UserRepository` 是错误的 is-a 关系 | R3 改为抽模块级 `_create_auth_schema(conn)` |
| **C** | R1 验证清单（4 个测试文件） | **漏了 2 个会真正坏掉的文件**：`tests/test_apps_chat_db_research_delegate.py`（5.3 KB）、`tests/test_apps_chat_db_wiki_delegate.py`（8.2 KB） | 补进验证清单 |

**数据修正**

| 项 | 原方案 | 本次实测 | 说明 |
|----|--------|----------|------|
| 精确克隆浪费（docstring 口径） | 644 行 | **902 行 / 70 组** | 口径不同，不可直接比 |
| 精确克隆浪费（**payload 口径**） | 未区分 | **402 行 / 70 组** | ⭐ **这才是可回收的真实代码量** |
| 转发层合计 | 487 行（3 个 DB 层，方法体口径） | **834 行（全 src，函数全行口径）** | 口径 + 范围都不同：原方案只数 3 个 DB 层，本文扫全 src |
| import 环 | 5 条，同一条根 | ✅ **属实** | graphify 5 条文件级环同根；另有 6 个**模块级 SCC** 环，原方案未提 |
| 层违规 | 未提 | **0**（AST + grep 双确认） | `scripts/check_architecture.py` 通过 ⚠️ 当时的 AST 那一路是假阴性，见 N1b；现已修复并双路复验 |
| god-node 榜首 | `Wiki` 434 | **`_make_spec()` 597 / `_make_full_runner()` 436** | 前两名是**测试 helper**，原方案静默剔除但未标注口径 |

**新发现（P0/P1）**

- **N1（P0）**：`scripts/check_architecture.py` 在 Windows 控制台 **崩溃**，即使 0 违规也 `exit 1` → CI 误报失败（§4.1）
- **N2（P1）**：R1 真正的风险不是「外部改动」，而是 **lazy → eager** 的建表时机变化（§4.2）
- **N3（P1）**：R4 的 `__init__` 样板是 **3 处不是 4 处**，`retry_managers` 不构成第 4 处（§3.4）
- **N4（P2）**：`foundation/auth/db.py` 两份 schema 各自跑一遍相同的「Phase 2.5 migration」检测（§4.3）

---

## 2. 代码库结构地图

### 2.1 规模与分层

`src/llmwikify/` 共 **407 个 .py 文件 / 79,635 行**（含空行）。

| 层 | 文件 | 行数 | 占比 | 主要子包 |
|----|-----:|-----:|-----:|----------|
| `apps/` | 201 | 44,858 | 56% | `chat` 33,652 · `research` 5,490 · `agent` 4,052 · `wiki` 919 |
| `kernel/` | 77 | 14,599 | 18% | `wiki` 6,744 · `storage` 2,518 · `agent` 1,569 · `graph` 1,417 |
| `interfaces/` | 75 | 11,740 | 15% | `cli` 6,590 · `server` 4,387 · `mcp` 645 |
| `foundation/` | 51 | 8,331 | 10% | `llm` 3,551 · `auth` 1,274 · `extractors` 803 |

> 口径：行数含空行（`(Get-Content f).Count`）。这与原方案 §3.2 的
> `_facade.py` 740 / `research_delegate.py` 318 / `wiki_delegate.py` 150 **完全吻合**，
> 可确认原方案的文件行数统计无误。

依赖方向（AGENTS.md §架构分层）**实测 0 违规** —— AST 扫描与 `scripts/check_architecture.py`
（grep 口径）双向确认。`kernel → apps` / `foundation → kernel` 等反向依赖均不存在。

全仓最大文件（`src/` 内）：

| 行数 | 文件 |
|-----:|------|
| 1,073 | `apps/agent/tools/__init__.py` |
| 1,060 | `apps/chat/agent/runner_v2.py` |
| 1,042 | `apps/research/actions.py` |
| 1,039 | `apps/research/db.py` |
| 1,016 | `apps/chat/agent/orchestrator.py` |

### 2.2 热点节点（god-node，graphify 出度）

| # | 节点 | 出度 | 性质 |
|---|------|-----:|------|
| 1 | `_make_spec()` | 597 | **测试 helper**（`tests/test_apps_chat_agent_runner_v2.py`） |
| 2 | `_make_full_runner()` | 436 | **测试 helper**（同上） |
| 3 | `Wiki` | 434 | 组合根（mixin 聚合 13 个） |
| 4 | `SkillContext` | 327 | 数据类 |
| 5 | `ChatRunnerV2` | 167 | 薄封装 |
| 6 | `ChatDatabase` | 166 | 门面（7 个 repo） |
| 7 | `SkillResult` | 160 | 数据类 |
| 8 | `SkillRegistry` / `PromptRegistry` | 136 / 131 | 注册表 |

> **口径提示**：graphify 把 `tests/` 一并纳入图，前两名全是测试 fixture。
> 原方案直接以 `Wiki`(434) 开头，等于**静默剔除了测试节点**却未标注 —— 读者会误以为
> `Wiki` 是最高扇入点。**建议在任何引用该列表的地方注明「已排除 tests/」**。
>
> 排除测试后，前 8 名与原方案一致，且**全部是组合根 / 数据类 / 注册表**，
> 印证了原方案 §R6「高扇入是设计意图，非重复」的判断 —— 该判断成立。

### 2.3 模块扇入（AST 模块级，import 该模块的模块数）

| 扇入 | 模块 | 说明 |
|-----:|------|------|
| 40 | `apps.chat.skills.base` | Skill 基类（正常） |
| 34 | `interfaces.cli._base` | CLI 框架（R2 后上升） |
| 20 | `interfaces.cli._output` | CLI 输出helper |
| 14 | `kernel` / `apps.research` | 包级 `__init__` 聚合 |
| 13 | `kernel.wiki.protocols` | Wiki 协议 |
| 11 | `kernel.multi_wiki.registry`, `foundation.utils`, `foundation.llm.streamable` | |
| 10 | `foundation.config`, `apps.chat.skills.registry`, `kernel.storage.backend`, … | |

### 2.4 转发层全景（AST 判定：函数体为单条 `return self._x.y(...)`）

全 src 共 **834 行**纯转发。原方案只覆盖了 3 个 DB 层（487 行），完整分布：

| 文件 | 文件行 | 函数行合计 | 纯转发行 | 转发方法 | 真实方法 |
|------|-------:|-----------:|--------:|--------:|--------:|
| `apps/chat/db/_facade.py` | 740 | 539 | **375** | 70 | 7 |
| `apps/chat/db/research_delegate.py` | 318 | 222 | **213** | 32 | 2 |
| `apps/chat/db/wiki_delegate.py` | 150 | 78 | **69** | 17 | 2 |
| `apps/chat/agent/agent_service.py` | 744 | 668 | 52 | 19 | 23 |
| `apps/chat/session.py` | — | 80 | 25 | 2 | 11 |
| `apps/wiki/db.py` | — | 350 | 17 | 3 | 18 |
| `apps/chat/agent/orchestrator.py` | 1,016 | 875 | 14 | 7 | 31 |
| 其余 15 个文件 | — | — | 69 | — | — |

> **两种口径**：*文件行* 含空行与 import；*函数行合计* 是所有函数体跨度之和
> （不含模块级代码）。两者都列出，避免与原方案的数字混淆。
>
> 原方案按「方法体行数」计 DB 三层 = 487 行；本文按「函数全行」计 = **657 行**。
> **两个 delegate 文件是全 src 最集中的转发点** —— 这点原方案与本文一致。

---

## 3. 对 `code-reuse-optimization.md` 的逐条复核

### 3.1 R1 — 删 `ResearchDelegate` / `WikiDelegate`

**结论：方向正确，但风险描述与验证清单需修订。**

✅ **核实通过**
- 两个文件确为纯转发层：全部方法体为单行 `return self._research.<method>(...)` / `self._wiki.<method>(...)`，无逻辑无 schema。
- 两者 docstring 均自带 `DEPRECATED` 标记。
- `ResearchDelegate` 27 个方法 + `WikiDelegate` 17 个方法 = 44 个，与门面上的转发方法数一致。

🔧 **修订 1：R1 的风险被高估 —— delegate 在门面之外零生产调用方**

全仓扫描 `ResearchDelegate` / `WikiDelegate` 的引用点，**只有 3 处**：

| 位置 | 用途 |
|------|------|
| `apps/chat/db/_facade.py:69,71,130,131` | import + 实例化 |
| `apps/chat/db/__init__.py:33,35,46,48` | re-export（`__all__`） |
| `tests/test_apps_chat_db_research_delegate.py` / `test_apps_chat_db_wiki_delegate.py` | 专门测这两个类的测试 |

> delegate docstring 写的「kept for back-compat with **91** / **32** production callers」
> 指的是**门面方法**（`create_research_session` 等）的调用方，**不是 delegate 类的实例化方**。
> 这个措辞会让人误以为删除 delegate 会波及 91 个调用点 —— 实际不会。**建议同时修正 docstring。**

🔧 **修订 2：验证清单漏了 2 个会真正坏掉的文件**

原方案列了 `test_apps_chat_db.py` / `test_apps_db.py` / `test_research_save.py` /
`test_apps_chat_db_research_run_id.py` —— 这 4 个都**不覆盖**被删的两个类。
真正需要处理的是：

- `tests/test_apps_chat_db_research_delegate.py`（5.3 KB）
- `tests/test_apps_chat_db_wiki_delegate.py`（8.2 KB）

处置二选一：① 随实现删除（改测门面等价路径）；② 改写为直接测 `ResearchDatabase` / `WikiDatabase`。

🔧 **修订 3：真正要保住的是「惰性」，不是「FK 语义」**

原方案「必须保住」列了 3 条，实测后优先级应调整：

| 原「必须保住」 | 实测结论 |
|----------------|----------|
| ① `ResearchDatabase(foreign_keys=False)` | ✅ 真实且重要 —— `ResearchDatabase.__init__` 自己覆写了 `BaseDatabase.__init__` 并用 `foreign_keys=False` 建连。只要门面**直接实例化 `ResearchDatabase`** 就自动保留；**不要绕过它的 `__init__`** |
| ② 门面侧 `PRAGMA foreign_keys = ON` | ⚠️ **已冗余** —— `foundation/db.py:60-61` 在 `connect()` 时就执行了 `PRAGMA foreign_keys = ON`（默认 `foreign_keys=True`）。`_facade.py:225` 那句在事务内、且 FK 本已开启，保留不保留都不影响行为 |
| ③ 同一 `.llmwiki_agent.db` 路径 | ✅ 真实 —— 三层共用 `get_app_db_path(data_dir)` → `data_dir/.llmwiki_agent.db` |

**真正的隐藏风险（原方案完全没提）**：

```
ResearchDelegate._research   ← @property，惰性构造 ResearchDatabase
WikiDelegate._wiki           ← @property，惰性构造 WikiDatabase
AutoResearchDatabase.__init__ ← 急切构造 ResearchDatabase + WikiDatabase
```

- 现在 `ChatDatabase.__init__` → `ResearchDelegate(data_dir)`，**建表发生在首次调用研究方法时**。
- 若 R1 改成门面 `__init__` 里直接 `new ResearchDatabase(data_dir)`，**建表时机从「首次调用」变成「构造时」**。
- 副作用：`get_app_db_path()` 里的旧库自动改名（`autoresearch.db` → `.llmwiki_agent.db`）也会提前触发。

👉 **正确做法：门面内部保留 lazy 语义** —— 把 delegate 的 `@property` 惯用法直接搬到门面
（`self._research` 改为惰性 property），而不是在 `__init__` 里直接实例化。
这样删掉的是「中间层类」，**不是「惰性」**。

顺带：`AutoResearchDatabase.__init__`（`_facade.py:734-740`）里那两行急切构造，
在 R1 完成后会变成「ChatDatabase 已经持有同样的实例」的重复 —— 可一并简化，
但**它当前被 `apps/research/` 4 个生产模块 + 5 个测试文件使用，必须保留这个类**。

### 3.2 R2 — CLI `setup_parser` 抽 helper

**结论：✅ 已完成并提交（`dea463f1`），实现优于原方案。**

commit `dea463f1`：**35 files changed, +154 / −242**（其中 `src/` 34 files，+136 / −233）。
实测状态：

- ✅ 33 个命令**全部**继承 `CommandBase`，无残留 inline `isinstance(subparsers, ...)` 守卫
- ✅ 31 处走 `self._sub(subparsers)`；2 处直接 `add_subparser(...)`（`serve.py` 需 `aliases=["mcp"]`，`auth.py` 走函数式 setup）
- ✅ `ruff check src/llmwikify/interfaces/cli/` → All checks passed
- ✅ `pytest tests/test_cli_registry_dispatch.py tests/test_cli_framework.py` → **43 passed**（本次复跑）

> **实现优于原方案**：原方案提议把 `_sub` 加在 `Command` 上。但 `Command` 是
> `@runtime_checkable Protocol`，给它加具体方法会破坏「鸭子类型命令仍然合法」的语义
> （`test_cli_framework.py::test_command_protocol_is_runtime_checkable` 就是这条约束的守卫）。
> 实际实现改为 **`CommandBase(Command)` + 模块级 `add_subparser()`**：
> 协议保持纯结构化，同时用 `**kwargs` 容纳 `aliases` —— 正确解法。
>
> 原方案文档已在 `dea463f1` 中同步记录了这一点（「`Command` 保持为纯结构化 Protocol」），
> **与本文独立得出的结论一致**。

### 3.3 R3 — `foundation/auth/db.py` 两个 `_init_schema` 合并

**结论：比原方案描述的更简单，原方案的做法 B 方向错误。**

实测：两个方法**逐字相同**（AST 结构哈希一致，38 行 vs 35 行物理行），
**且都同时创建 `users` + `api_keys` 两张表**：

```
UserRepository._init_schema   (db.py:128)  ─┐
                                            ├─ 同样的 PRAGMA table_info(users) 检测
ApiKeyRepository._init_schema (db.py:325)  ─┘   同样的 DROP/CREATE users + api_keys
```

所以：
- 原方案「做法 A：抽 `_base_schema(conn)` 建公共表，各自差异部分保留」——
  **不存在差异部分**，抽出来就是完整的单一函数。
- 原方案「做法 B：`ApiKeyRepository` 继承 `UserRepository`」——
  **方向错误**：`ApiKeyRepository` 不是 `UserRepository`，继承会建立错误的 is-a 关系，
  且 `UserRepository` 还带 `exists()` / `count()` / `get_by_email()` 等用户域方法。

👉 **建议做法**：抽模块级 `_create_auth_schema(conn)`，两个 repository 各自调用。
净减约 **35 行**，且顺带消除「两份 Phase 2.5 迁移逻辑各跑一次」（见 §4.3 N4）。

### 3.4 R4 — 三处小重复合并

| 重复 | 原方案 | 实测结论 |
|------|--------|----------|
| `_build_merge_notice` | `kernel/storage/backend.py:437` + `kernel/wiki/mixins/core/utility.py:236`，19×2 | ✅ 属实。**方向已验证安全**：`kernel/wiki/mixins/core/utility.py:11` 本就 `from llmwikify.kernel.storage.backend import is_path_excluded`，且 `kernel/storage/backend.py` **不反向** import `kernel/wiki`。<br>⚠️ 补一点：`_build_merge_notice` 是**下划线私有名**，跨模块 import 私有名是 smell。建议在 `kernel/storage/backend.py` 里改名为公开的 `build_merge_notice`，wiki 侧调公开名 |
| `_format_run_not_found` | `autoresearch_compound_skill.py:28` + `workflows/skill.py:43`，29×2 | ✅ 属实（AST 哈希一致）。提到 `apps/chat/skills/errors.py` 的建议合理 |
| `execution_context` | `kernel/agent/loop.py:292` + `chat/agent/runner_v2.py:192`，22×2 | ✅ 属实，但**它不是最大的那一组** —— 见 N5 |
| `__init__` 样板 ×4 | clarifier / harness.review / research.report / retry_managers | 🔧 **是 3 处不是 4 处**：`clarifier.py:27` / `harness/review.py:23` / `research/report.py:25` 各 11 行，AST 哈希一致；**`retry_managers` 不构成第 4 处**。原方案的「4 处」应为笔误 |

### 3.5 R5 — 修 `kernel → llmwikify` 的 import 环

**结论：根因判断正确，但范围漏了一半 —— 这是本文档最需要修订的一条。**

✅ **核实通过**：graphify 报出 **5 条文件级 import 环，全部同根**：

```
llmwikify/__init__.py → kernel/… → kernel/wiki/wiki.py → kernel/wiki/mixins/analysis/status.py → llmwikify/__init__.py
```

根因即 `status.py:5` 的 `from llmwikify import __version__`。原方案「同一条根」**表述准确**。

🔧 **修订：kernel 有两处包根 import，不是一处**

```
kernel/wiki/mixins/analysis/status.py:5     from llmwikify import __version__
kernel/wiki/mixins/core/utility.py:59        from llmwikify import __version__   ← 原方案漏掉
```

第二处**同样构成环**，实测链路：

```
kernel/wiki/mixins/core/utility.py:59
  → llmwikify/__init__.py:30   (from .kernel import Wiki, WikiIndex)
  → kernel/__init__.py:39      (from .wiki import ... Wiki)
  → kernel/wiki/wiki.py:20     (from .mixins.core.utility import WikiUtilityMixin)
  → kernel/wiki/mixins/core/utility.py:59   ← 闭环
```

👉 **只改 `status.py` 不会消除 kernel 的方向违规**，`utility.py` 仍在环里。
R5 范围必须扩到两处。

补充：全仓 `from llmwikify import ...` 共 **5 处**，另 3 处在 `interfaces/`
（`cli/commands/doctor_cmd.py:297`、`cli/commands/serve.py:316`、`server/core.py:16`）——
`interfaces` 可以向下依赖，**方向合法**，但同样会经包根形成环。
是否一并处理属可选，不影响分层合规性。

原方案做法 A（`__version__` 下沉到 `foundation/version.py`，包根再 re-export）
方向正确且能同时解决两处 —— **下沉到 `foundation` 后，`kernel` 取值不再经过包根，环即断**。

#### 补充：还有 6 个**模块级 SCC 环**，与包根无关

graphify 只报了 5 条「同根」的文件级环。用 AST 导入图做 Tarjan SCC，
另外查出 **6 个模块级强连通分量**（原方案未提）：

| 环 | 模块 |
|----|------|
| 2 | `foundation.config` ↔ `foundation.utils` |
| 2 | `kernel.storage.backend` ↔ `kernel.storage.index` |
| 7 | `foundation.extractors.{base, jina, markitdown_extractor, pdf, text, web, youtube}` |
| 5 | `apps.research.{engine, gates, observer, reasoner, resume}` |
| 2 | `apps.chat.skills.workflows.subagent_runner` ↔ `subagent_worker` |
| 2 | `kernel.wiki.engines.analyzer` ↔ `kernel.wiki.wiki` |

这 6 个环**与包根 import 无关**，R5 修完不会消除它们。它们多为**函数内延迟 import**
（避免顶层环）造成的表面闭环，未必是设计缺陷 —— 但 `foundation.extractors` 的 7 模块环
与 `apps.research` 的 5 模块环规模偏大，值得单列一个观察项。

> ⚠️ 这 6 个环**不违反分层规则**（分层检查实测 0 违规），与 R5 解决的问题不同类别。
> 建议**不并入 R5**，避免批次 1 的「低风险」承诺被稀释。

### 3.6 R6 — 观察项

原方案的判断全部成立，补充一条：

- `apps/chat/agent/runner_v2.py` 实测 **1,060 行**（原方案写 1,061 行 —— 差 1 行，**实质一致**），
  是 `src/` 内**第 2 大**的文件（仅次于 `apps/agent/tools/__init__.py` 1,073 行）。
  原方案「属**拆分**议题，非复用议题」的归类成立。补一条：`apps/research/actions.py`（1,042）
  与 `apps/research/db.py`（1,039）同样在千行量级，拆分议题的范围比原方案列的更广。

---

## 4. 文档未覆盖的新发现

### N1（P0）`scripts/check_architecture.py` 在 Windows 控制台崩溃

```powershell
> python scripts/check_architecture.py
UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'
exit=1
```

脚本用 ✅ / ❌ emoji 打印结果（`check_architecture.py:120,128`）。
在 GBK 控制台（Windows 默认）下 **0 违规也会 exit 1** → **CI 会误报架构违规失败**。

> 规避：`$env:PYTHONIOENCODING='utf-8'` 后正常输出 `✅ 0 architecture violations` 且 `exit=0`。

修复（2 行）：

```python
# scripts/check_architecture.py —— main() 开头
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass
```

或把 emoji 换成 ASCII（`OK` / `FAIL`）。**建议连同 R 批次一起修** —— 它是分层守卫，
守卫本身挂掉比分层违规更危险。

> ✅ **N1 已修复并有回归网**（2026-10-27）：`scripts/check_architecture.py` 的 `main()` 开头
> 现在对 `stdout`/`stderr` 强制 `reconfigure(encoding="utf-8", errors="replace")`。
> 回归测试 `tests/test_check_architecture.py::test_script_survives_non_utf8_console`
> 用 `PYTHONIOENCODING=ascii` / `gbk` 起子进程，断言 **exit 0 且 stderr 无 `UnicodeEncodeError`**。
> 变异验证：去掉该 guard 后同一条命令 → `exit 1` + `UnicodeEncodeError`（守卫有牙齿）。

### N1b（P1）`scripts/clone_survey.py` 的层违规检测一直是**假阴性**（2026-10-27 补测时发现）

`detect_layer_violations()` 里写的是 `layer_of_module("llmwikify." + mod)`，
但 `module_name()` 返回的**已经是** `llmwikify.kernel.x` 这样的全限定名 ——
再拼一次前缀会得到 `llmwikify.llmwikify.kernel.x`，
`layer_of_module()` 的 `parts[1] in LAYERS` 判断必然落空 → `layer is None` → **每个文件都被 `continue` 跳过**。

| | 修复前 | 修复后 |
|---|---|---|
| `detect_layer_violations(kernel → apps)` | `[]`（漏报） | 正确检出 |
| `detect_root_deps()` 的层标签 | 恒为 `"?"` | `kernel` / `interfaces` 等真实层 |

**对本文结论的影响**：§2 的「层违规 0」结论**不变且仍成立** ——
因为 `scripts/check_architecture.py`（独立实现，不走这条路径）本来就报 0。
但当时「AST + grep 双确认」里的 **AST 那一路是空转的**，结论实为单点确认。
现在两路都真跑起来了，结果一致：**0 违规**。

> 这条发现本身就是「先写单元测试」的价值：495 行、零测试的分析工具，
> 藏着一个让核心检测项**恒为真**的 bug。回归网见
> `tests/test_clone_survey.py::test_detect_layer_violations_flags_kernel_to_apps`。

### N2（P1）R1 的真正风险是 lazy → eager

详见 §3.1 修订 3。摘要：门面直接 `new ResearchDatabase(...)` 会把建表时机
从「首次调用研究方法」提前到「构造 ChatDatabase 时」，并提前触发旧库改名迁移。
**门面内改用惰性 property 即可零行为变更地删掉中间层。**

### N3（P1）R4 的 `__init__` 样板是 3 处不是 4 处

`retry_managers` 不构成第 4 处克隆组。详见 §3.4。

### N4（P2）两份 Phase 2.5 迁移逻辑各跑一遍

`foundation/auth/db.py` 的两个 `_init_schema` 各自执行同一段
「`PRAGMA table_info(users)` → 检出 `password_hash` → DROP 两表 → 重建」。
只要 `UserRepository` 和 `ApiKeyRepository` 都被实例化，这段检测**跑两遍**。
R3 合并后天然消除。

### N5（P2）按 **payload 口径**的真实重复排名（文档未覆盖）

> ⚠️ 本条**修正了本文早期版本的一个误判**。AST 结构哈希会把
> 「长 docstring + `raise NotImplementedError`」和「长 docstring + `...`」
> 这类**抽象桩**算成克隆组 —— 但它们的代码载荷只有 2~5 行，**没有复用价值**。
> 引入 *payload*（剔除签名与 docstring 后的实际代码行数）后，
> 真实重复的排名与「docstring 口径」**完全不同**。

全 src 真实重复 **402 行**（payload 口径），Top 8：

| # | 位置 | payload/份 | 浪费 | 判断 |
|---|------|----------:|-----:|------|
| 1 | `foundation/auth/db.py` `UserRepository._init_schema` ×2 | 37 | **37** | ✅ 即 R3，**最高优先级** |
| 2 | `apps/research/db.py:431` `get_sub_queries` + `:509` `get_sources` | 18 | **18** | 🆕 **文档未提** —— 同样的「JSON 字段解码 + row 展开」模式 |
| 3 | `apps/chat/skills/` `_format_run_not_found` ×2 | 17 | **17** | ✅ 即 R4 |
| 4 | `kernel/storage/backend.py` `_build_merge_notice` ×2 | 17 | **17** | ✅ 即 R4 |
| 5 | `apps/chat/skills/crud/` `_get_memory` / `_get_manager` / `_get_scheduler` / `_get_manager` / `_get_editor` | 4 | **16** | 🆕 5 个 CRUD skill 各写一遍「取依赖」样板 |
| 6 | `apps/chat/skills/actions/web_search_action.py` `_search_youtube` + `_search_news` | 14 | **14** | 🆕 文档未提 |
| 7 | `apps/agent/tools/__init__.py:823` `WikiToolRegistry.list_tools` + `skill_adapter.py:99` `SkillToolAdapter.list_tools` | 12 | **12** | 🆕 文档未提 |
| 8 | `apps/chat/memory/consolidation_store.py` `list_by_session` + `list_since` | 11 | **11** | 🆕 文档未提 |

**另外 3 处值得一并处理**：

- `foundation/config.py:325` `get_mcp_config` + `:346` `get_search_config` —— 10 行，配置加载器同构
- `foundation/auth/db.py:92` `UserRepository._ensure_dir` + `:312` `ApiKeyRepository._ensure_dir` —— 8 行，**与 R3 同文件，合并时顺手带掉**
- `apps/chat/bus/queue.py:194` `_get_default_lock` + `apps/chat/channels/websocket.py:224` 同名同构 —— 6 行

**被 payload 口径排除的「伪重复」**（避免后续 agent 重复踩坑）：

| 组 | docstring 口径 | payload 口径 | 真相 |
|----|---------------:|------------:|------|
| `agent_runner.execution_context` + `ChatDBBase._init_schema` + `BaseDatabase._init_db` | 42 行 | **10 行** | 三个**抽象桩**，载荷只有 `raise NotImplementedError` —— 无复用价值 |
| `protocols.py` 4 组 Protocol 方法 | 45 行 | **≈0** | 全是 `...` 协议桩 —— 无复用价值 |
| `clarifier` / `review` / `report` 的 `__init__` ×3 | 22 行 | **10 行** | 真实但很小（各 5 行赋值） |
| `_facade` ↔ `research_delegate` 的 `save_source` 等 | 21 行/组 | 9~10 行/组 | ✅ **真实**，但这些正是 R1 要删的层 |

> **这解释了原方案与本文的 644 vs 902 差异**：两者口径不同，
> 且原方案未区分「文档行」与「代码行」。**payload 口径的 402 行才是可回收的真实代码。**

### N6（P2）`interfaces/cli/_app.py` 的 `WikiCLI` 是 23 个 5 行转发方法

`WikiCLI` 的 23 个方法结构完全一致（`return run_xxx(self.wiki, args)`），
共 115 行。**但这不是克隆浪费** —— 每个方法调用的是**不同的**命令函数
（`run_init` / `run_ingest` / `run_search` …），是典型的**表驱动 dispatch** 候选。

> 我的 AST 检测器第一版把它误判为 23 份克隆（因为被调函数名在源码里是裸 `Name`，
> 被归一化成了同一个符号）。修正归一化口径（保留被调用符号名）后该组消失。
> **记录在此以防他人复现时踩同一个坑** —— 口径见 §6。

### N7（P3）`apps/chat/memory/` 三 store 的 CRUD 同构

`consolidation_store.py` / `facts_store.py` / `chat_session_repo.py` 的
`delete`（3 份，payload 5 行/份 → 10 行浪费）与 `list_*` 同构。
payload 口径下收益不大（仅 10 行），**优先级应低于 N5 的 1~8 项**。

---

## 5. 修订后的执行建议

```
批次 0（先做，独立于一切重构）  收益 0 行，但修掉一个「会误报的守卫」
  N1  scripts/check_architecture.py 修 GBK 崩溃

批次 1（低风险）               收益 ~86 行
  R2  CLI helper                ← ✅ 已完成（dea463f1）
  R4  三处小重复合并            ← 注意：_build_merge_notice 建议改公开名
  R5  __version__ 下沉           ← 【修订】范围含 utility.py:59，不止 status.py:5

批次 2（中风险，独立 PR）      收益 ~470 行
  R1  删 ResearchDelegate → 删 WikiDelegate
      ← 【修订】保留惰性语义 + 补 2 个 delegate 测试文件 + 修正 docstring
  R3  auth/db 抽 _create_auth_schema(conn)
      ← 【修订】不用继承，用模块级函数
      ← 顺手带掉 _ensure_dir ×2（N5 附项）
```

**新增可选批次**（原方案外，按 payload 口径排序）

```
批次 3（可选，需先评估语义是否真同）  收益 ~85 行（payload 口径）
  N5-2  research/db.py  get_sub_queries / get_sources      18 行
  N5-5  skills/crud/  5 份 _get_* 依赖获取样板              16 行
  N5-6  skills/actions/web_search_action  _search_youtube/news  14 行
  N5-7  WikiToolRegistry.list_tools ↔ SkillToolAdapter.list_tools  12 行
  N5-8  memory/consolidation_store  list_by_session / list_since  11 行
  附    foundation/config.py  get_mcp_config / get_search_config  10 行
```

**仍不建议做**（沿用原方案判断，复核后维持）

| 提案 | 判断 |
|------|------|
| CLI 脚手架生成器 | ✅ 维持不做 —— 33 命令参数差异大，相似度均值 0.47 |
| DB 三层「抽公共函数」 | ✅ 维持不做 —— 那是再加一层，正确解法是删中间层 |
| 重构 `Wiki` / `SkillContext` god-node | ✅ 维持不做 —— 组合根与数据类，高扇入是设计意图 |
| `kernel/agent/loop.py` ↔ `runner_v2.py` 的 `execution_context` | ⚠️ **降级到不做** —— payload 口径下仅 8~10 行 |
| `agent_runner.execution_context` / `ChatDBBase._init_schema` / `BaseDatabase._init_db` | ⚠️ **新增「不做」** —— 是抽象桩（载荷仅 `raise NotImplementedError`），docstring 口径的 42 行是假象 |
| `apps/chat/agent/protocols.py` 的 4 组 Protocol 方法 | ⚠️ **新增「不做」** —— 全是 `...` 协议桩，零复用价值 |

---

## 6. 附录 A：复核方法与口径

### 工具

```powershell
graphify extract . --code-only          # 纯 AST，无 LLM 成本
graphify cluster-only . --no-label --no-viz
graphify god-nodes --top 20
python scripts/clone_survey.py          # 本次自写，已入库
python scripts/check_architecture.py     # 分层守卫
```

### 克隆检测口径（关键，避免复现踩坑）

结构哈希 = 归一化 AST 的 SHA1。归一化规则：

| 节点 | 处理 | 理由 |
|------|------|------|
| 局部变量名 / 参数名 | → `V` / `a` | 名字不是结构 |
| 字面量 | → 类型名（`"str"` / `"int"`） | 值不是结构 |
| **被调用符号名** | **保留** | `run_init(...)` 与 `run_ingest(...)` 是不同 API，抹平会**制造假克隆**（见 N6） |
| 属性接收者 | → `V` | 只抹对象，不抹方法名 |
| 类名 / 函数名 / 装饰器 | → `C` / `f` / 去掉 | |
| 文档字符串 | → `"str"` | |

> 第一版未保留被调用符号名，把 `interfaces/cli/_app.py` 的 23 个方法误判为
> 23 份克隆（110 行「浪费」）。修正后该组消失。**这就是口径必须写下来的原因。**
>
> 第二版补上了 **payload 口径**（剔除签名与 docstring），
> 把「抽象桩」从重复名单里剔出去 —— 真实重复从 902 行收敛到 **402 行**。

### 与原方案的统计口径差异

| 指标 | 本文 | 原方案 |
|------|------|--------|
| 文件行数 | 含空行（`(Get-Content f).Count`） | 同口径 ✅ |
| 克隆：docstring 口径 | 函数全跨度（签名 + docstring + 代码） | 未说明 |
| 克隆：**payload 口径** ⭐ | 剔除签名与 docstring 后的实际代码行数 | 未区分 |
| 转发行 | 函数**全行**（含签名 + docstring） | 方法**体行数** |
| 层违规 | AST 导入图 | — |

故两者数字不可直接比较；本文的数值用于**排序与定位**，不用于替换原方案的历史记录。

> ⚠️ **两个必须写进口径的坑**：
>
> 1. **PowerShell 的 `Get-Content f | Measure-Object -Line` 不统计空行** ——
>    会把 `runner_v2.py` 报成 970 行（真值 1,060）、`_facade.py` 报成 618（真值 740）。
>    本报告所有行数均用 `(Get-Content f).Count`。
> 2. **AST 结构哈希必须区分 docstring 口径与 payload 口径** ——
>    否则「长 docstring + `raise NotImplementedError`」和「长 docstring + `...`」
>    这类抽象桩会被算成大额克隆浪费。**本文同时给出两个口径**，
>    以 payload 口径（402 行）作为行动依据。

### 6.1 附录 B：本次新增工具 `scripts/clone_survey.py`

可复现本报告 §3.1 / §4 的全部 AST 指标（克隆浪费 **双口径** / 转发层 / import 环 /
层违规 / 包根导入 / 模块扇入）。纯标准库，无新增依赖，`ruff` 通过。

```powershell
python scripts/clone_survey.py                 # 文本报告
python scripts/clone_survey.py out.json         # 附带 JSON（便于二次分析）
```

输出字段：`clone_waste_total`（docstring 口径）/ `clone_payload_waste_total`（payload 口径，
**行动依据**）/ `forwarders` / `cycles` / `layer_violations` / `root_deps` / `fan_in_top`。

**回归网**：`tests/test_clone_survey.py`（26 个用例）覆盖归一化器、结构哈希、
克隆/转发/环/层违规/包根导入/扇入 六类检测器。
没有它的时候，工具里藏着一个让 `layer_violations` **恒为 `[]`** 的 bug（N1b）——
正是这个工具被写进方案文档当作证据来源的前提。

---

## 7. 与既有文档的关系

- 本文**不替代** `docs/designs/code-reuse-optimization.md` —— 原方案是**方案**，本文是**复核**。
- 本文所有「修订」项建议**回写进原方案**后再执行。
- R2 已由 `dea463f1` 落地，原方案文档同步标记 ✅；本文 §3.2 对该实现的复核**结论一致**。
- B1（lint 矛盾检测性能议题）与本方案不重叠的结论**维持不变**。
- 本次**未改任何 `src/` 代码**；新增 `scripts/clone_survey.py`（纯只读分析工具，ruff 通过）。
