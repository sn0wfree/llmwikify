# Phase 2 / 方案 3 — 抽取 apps/knowledge/，解开 chat↔research 循环

日期: 2026-11-02 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 问题

架构评审 P0-04：`apps.chat` ↔ `apps.research` 包级循环依赖。

先实测依赖方向——**它是不对称的**：

| 方向 | 边数 | 性质 |
|------|------|------|
| research → chat | **21 个 chat 模块** | 合法方向：research 管线建在 chat agent 机制上 |
| chat → research | **4 类真边** | 成环的那一边 |

chat 侧真正需要 research 的只有 4 样东西：

| chat 侧使用者 | 需要的 research 模块 |
|----------------|---------------------|
| `chat/gatherer.py`、`chat/skills/actions/web_search_action.py`、`chat/skills/pipelines/gather_skill.py`、`chat/skills/workflows/subagent_worker.py` | `research.web_search.WebSearch` |
| `chat/config.py`、`chat/task_manager.py`、`chat/harness/quality_gate.py` | `research.base.*` |
| `chat/db/_facade.py`、`chat/db/research_delegate.py`、`apps/db.py` | `research.db.ResearchDatabase` |
| `chat/research_agent.py` | `research.engine.ResearchEngine` |

其余 `chat → apps.research` 的边（12 个模块）都是**单向的 backward-compat
re-export shim**（`chat/research_engine/*`、`chat/{actions,engine,report}.py`），
不构成环。

## 方案

新建 `apps/knowledge/` —— 位于两者之下的共享基座：

```
apps/chat ─────┐
               ├──► apps/knowledge ──► foundation / kernel
apps/research ─┘
```

| 新位置 | 内容 | 原位置 |
|--------|------|--------|
| `apps/knowledge/web_search.py` | 327 LOC，零 llmwikify 依赖 | `apps/research/web_search.py` |
| `apps/knowledge/base.py` | 482 LOC，零 llmwikify 依赖 | `apps/research/base.py` |
| `apps/knowledge/db.py` | 948 LOC，只依赖 `apps.db_base` | `apps/research/db.py` |
| `apps/knowledge/config_defaults.yaml` | research 默认值 | `apps/research/config_defaults.yaml` |
| `apps/research/agent.py` | ResearchAgent（研究专属） | `apps/chat/research_agent.py` |

三个候选模块都**不依赖 chat**（实测确认），所以可以安全下沉。

### 向后兼容

旧路径全部保留，且是**同一模块对象**（仓库既有的 `sys.modules` 别名范式，
见 `apps/chat/engine.py`）：

```python
# apps/research/web_search.py
import sys as _sys
from llmwikify.apps.knowledge import web_search as _canonical
_sys.modules[__name__] = _canonical
```

这不是可选的讲究——测试里有 20 多处
`patch("llmwikify.apps.research.web_search.WebSearch")`。若 shim 只是
属性拷贝而非同一模块，patch 会**静默失效**（打不到真正被调用的类）。

`apps/chat/research_agent.py` 同样变成指向 `apps/research/agent.py` 的 shim。

## 途中踩到的坑

**模块搬家必须带走它的数据文件。** `apps/knowledge/base.py` 里
`_load_research_defaults()` 按 `Path(__file__).parent / "config_defaults.yaml"`
读 YAML。文件没跟着搬 → 返回 `{}` → research 默认值**全部消失** →
`merge_six_step_config()` 返回一个连 `search_provider` 都没有的 dict
→ 4 个测试变红。已把 YAML 一起搬走，并加了回归测试。

## 机器可证

`scripts/check_architecture.py` 新增**同层包规则**（层规则看不到层内循环）：

```python
SIBLING_RULES = (
    ("chat", "research", frozenset({...13 个 back-compat shim...})),
    ("knowledge", "chat", frozenset()),
    ("knowledge", "research", frozenset()),
)
```

- `chat → research`：只允许 13 个文档化的 shim
- `knowledge → chat` / `knowledge → research`：一律禁止
- `research → chat`：**合法**（研究管线建在 chat agent 机制上），不检查

违规时退出码 1 并指明 `apps.X → apps.Y`。

## 回归网

`tests/test_apps_knowledge_package.py`（14 项）：

1. `apps.knowledge` 导出 6 个共享名
2. `apps/knowledge/**` 不 import chat / research
3. 三个 shim 与 canonical 是**同一模块对象**（参数化 3 项）
4. shim 在 `sys.modules` 里注册为 canonical（参数化 3 项）
5. `apps.research` / `apps.chat` 的公开面不变
6. `ResearchAgent` 搬家后两路径同一
7. **research 默认值 YAML 必须找得到**（搬家踩坑的回归网）
8. YAML 必须声明为 package data
9. YAML 必须在模块旁边

`tests/test_check_architecture.py` 新增 6 项：规则能抓到 chat→research、
knowledge→chat、允许 research→chat、允许走 knowledge、允许白名单 shim、
当前仓库零违规。

## 文档同步

- `ARCHITECTURE.md` — 结构图加 `apps/knowledge/`，新增「Inside apps/」小节
- `AGENTS.md` — 架构分层段加同层包规则与新的 shim 清单

## 验证

```
python scripts/check_architecture.py
  → ✅ 0 architecture violations across 4 layers
  → ✅ 0 sibling-package violations inside apps
人工注入一条 chat→research 违规 → 正确报出并 exit 1
全量 pytest → 58 failed / 5273+ passed（基线 59 failed）
  → 新增失败 0，消失 1（flaky）
ruff check → clean
```
