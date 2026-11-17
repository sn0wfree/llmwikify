# 合并 `wiki_search` 与 `wiki_search_cross`（v2 · 保留兼容 + deprecated）

> **日期**: 2026-11-16 · **状态**: ✅ **已实现**（commit `3c6aabfb`）
> **v2 变更**: 用户定方向 —— **不删工具、不改老调用形态**，靠**默认参数保持原始功能** +
> **deprecated 提示**引导新调用；**底层合并为一个实现**。
> **前置**: [docs/diagnostics/mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md)、
> [docs/designs/multi-wiki-mcp-reconnect.md](multi-wiki-mcp-reconnect.md)

### 实现结果

| 验收 | 结果 |
|---|---|
| V1 | 单 wiki **20** 工具；`wiki_search` schema 仍 `(query, limit, backend)`，**无 `wiki_ids`** |
| V2/V3 | 多 wiki **26** 工具（数量不变）；`wiki_search_cross` 仍在，带 `annotations.deprecated=true` + `tags={"deprecated"}` + ⚠️ description |
| V4 | 兼容矩阵全绿：`wiki_search(q)` / `wiki_search(q, 20, "a")` / `wiki_search(q, wiki_id="a")` / `wiki_search_cross(q)` / `wiki_search_cross(q, 20, "a,b")` 全部与旧行为一致（除 limit 语义） |
| V5–V7 | `wiki_ids` 作用域正确；`wiki_id` 优先于 `wiki_ids`；全未知 → error |
| V8 | `limit` 为**全局上限**（两个工具都是） |
| V9 | `backend` 透传到本地 `Wiki.search` |
| V10/V11 | `wiki_search_cross` 返回 `{results, total_results, searched_wikis}`（未变）；`wiki_search` 返回裸 list |
| V12 | skill 层同构：`wiki_search` 支持 `wiki_ids`/`backend`；`wiki_search_cross` description 标 Deprecated |
| V13 | REST `GET /api/search/cross?backend=qmd` 现在真的生效（bug 修复） |
| V14 | ruff 干净 · mypy 416 文件 0 错 · 架构 0 violation · **pytest 5226 passed** |
| V15 | 17 个单元测试覆盖 `kernel/multi_wiki/search.py` 的全部分支（fake registry） |

### 实现中超出方案的两处改进

**① 单 wiki 分支的结果也补上了 `wiki_id` / `wiki_name`。**

方案里只说"多 wiki 场景补"，但实现时发现：合并后的 `wiki_search` 在只搜一个 wiki 时
（`wiki_ids="a"` 或 `wiki_id="a"`）走的是单 wiki 分支，其结果原本**不带来源标记**，
而跨 wiki 分支带 —— 同一个工具返回两种形状，LLM 会困惑。
现在两条分支统一都带 `wiki_id` / `wiki_name`（老调用 `wiki_search(q, wiki_id="a")`
的结果从"无标记"变成"有标记"，属**增强**，不破坏）。

**② 共享实现提到 kernel 层，可直接单元测试。**

初版实现里搜索逻辑写了两份 —— MCP 侧是 `register_multi_wiki_tools` 内的**闭包**，
skill 侧是**模块级函数**（同名不同处，逻辑相同）。闭包无法 import，也就无法单元测试。
现已提取为 `src/llmwikify/kernel/multi_wiki/search.py`：

```python
resolve_scope(registry, *, wiki_ids=None, wiki_id=None) -> list[str]
search_wikis(registry, query, limit=10, *, wiki_ids=None, wiki_id=None, backend="fts5")
    -> tuple[results, searched_wiki_ids]
```

MCP（`interfaces/`）与 skill（`apps/`）都改为调用它 —— 这才是真正的"**一份实现**"，
而且现在可以用 fake registry 做纯单元测试。

新增测试：
- `tests/test_kernel_multi_wiki_search.py` —— **17 个单元测试**（fake registry，不起服务）：
  作用域解析 6 项 + 单 wiki 分支 4 项 + 多 wiki 分支 3 项
- `tests/test_kernel_multi_wiki_cross_search.py` —— **9 个单元测试**（stub registry）：
  backend 透传 / 按 score 排序 / 未知 id 跳过 / 单 wiki 失败不中断 / 远程分支 / limit 语义
- `tests/test_mcp_search_tool_merge.py` —— 8 个端到端验收（真实 server）

---

## 1. 方向

| | v1（初稿） | **v2（本稿，用户定调）** |
|---|---|---|
| `wiki_search_cross` | 删除 | **保留**，降级为 deprecated 薄壳 |
| 老调用形态 | 破坏（`wiki_id`→`wiki_ids`） | **完全不变**（参数名、位置、必填性全保留） |
| 底层 | 两个独立实现 | **一份实现**，两个入口都转调 |
| 统一手段 | 删工具 | **默认参数 + deprecated 标注** |
| 工具数 | 26 → 25 | **26 不变** |

**"统一"落在三处**：① 底层一份搜索实现；② 作用域表达统一为 `wiki_ids`
（`None`/`"*"` = 全部，`"a,b"` = 指定）；③ `backend` / `limit` 两个工具一致。
**"不破坏"落在两处**：① 工具名与参数全部保留；② deprecated 薄壳保持原返回结构。

---

## 2. 现状对照

| 面 | 工具 | 签名 | 作用域（无参时） | `backend` | `limit` | 返回 |
|---|---|---|---|---|---|---|
| MCP 单 wiki | `wiki_search` | `(query, limit=10, backend="fts5")` | 当前 wiki | ✅ | 总条数 | 裸 list |
| MCP 多 wiki | `wiki_search` | `(query, limit=10, wiki_id=None, backend="fts5")` | **全部** | 仅指定分支 | per wiki | 裸 list |
| MCP 多 wiki | `wiki_search_cross` | `(query, limit=10, wiki_ids=None)` | **全部** | ❌ | per wiki | `{results, total_results, searched_wikis}` |
| skill | `search` / `wiki_search` / `wiki_search_cross` | 同上三套 | | | | |
| REST | `GET /api/search/cross` | `(q, limit, wikis, backend)` | 全部（按 claim 过滤） | ⚠️ **收了没传（bug）** | per wiki | 结构化 |

**重叠事实**：多 wiki 下 `wiki_search(q)` 与 `wiki_search_cross(q)` 调的是**同一个**
`registry.cross_wiki_search(query, None, limit)`。

---

## 3. 决策点

| # | 决策 | 候选 | 倾向 | 理由 |
|---|---|---|---|---|
| **D1** | 合并范围 | ① 只 MCP ② MCP + skill ③ 加 REST | **②** | REST 是 HTTP 面、已有鉴权、形态已定；改它会破坏 HTTP 客户端。**但顺带修它的 `backend` 未透传 bug** |
| **D10** | 是否删 `wiki_search_cross` | 删 / 保留 | **保留（deprecated 薄壳）** | 用户定调：不破坏老用户 |
| **D11** | deprecated 怎么标 | ① 只写 description ② MCP 标准 `annotations.deprecated` ③ 两者都做 | **③** | 实测 fastmcp 3.2.4 的 `@mcp.tool(annotations={"deprecated": True}, tags={"deprecated"})` **能传到客户端**（`list_tools()` 里 `annotations.deprecated=true`）。description 里再加 ⚠️ 文案让 LLM 读懂。**skill 层无 `deprecated` 字段，只能靠 description** |
| **D12** | `wiki_id` 与 `wiki_ids` 共存 | ① 只留 `wiki_ids` ② 共存 | **② 共存**，`wiki_id` 优先、`wiki_ids` 推荐 | `wiki_id` 删了会破老调用。**新参数追加在参数表末尾**，位置参数顺序不动（`wiki_search(q, 20, "a")` 仍命中 `wiki_id`） |
| **D13** | deprecated 工具的返回结构 | ① 跟随新工具 ② 保持原样 | **② 保持 `{results, total_results, searched_wikis}`** | 老客户端在读 `resp["results"]`，改了就读不到 |
| **D14** | 新工具的返回结构 | 裸 list / 结构化 | **裸 list** | 与单 wiki 一致、LLM 消费成本最低；跨 wiki 归属在每条结果的 `wiki_id` / `wiki_name` 里 |
| **D15** | `limit` 语义 | ① 全局上限 ② 维持 per wiki | **① 全局上限** | `limit=10` 的直觉是"给我 10 条"。**这是唯一的行为变化**（cross 的结果条数会变少） |
| **D16** | 未知 wiki id | ① 静默跳过 ② 报错 | **① 跳过，但"全部未知"时返回 error** | 能区分"配置写错"与"确实没内容"；部分未知仍返回已搜到的结果 |
| **D7** | 单 wiki 模式 | 保持 20 工具不变 | **不变** | 沿用上轮 B3 约束；单 wiki 无 `wiki_ids` 语义 |

---

## 4. 对外形态（实施后的样子）

### 4.1 MCP · 多 wiki

```python
@mcp.tool
def wiki_search(
    query: str,
    limit: int = 10,
    wiki_id: str | None = None,      # ⚠️ Deprecated — 用 wiki_ids
    backend: str = "fts5",
    wiki_ids: str | None = None,     # ✅ 推荐：None/"*" = 全部，"a,b" = 指定
) -> str:
    """Search wiki pages.

    Scope:
      - wiki_ids omitted / None / "*"  → all registered wikis
      - wiki_ids="a"                   → wiki a only
      - wiki_ids="a,b"                 → wikis a and b
      - wiki_id="a"                    → deprecated alias for wiki_ids="a"
    """


@mcp.tool(annotations={"deprecated": True}, tags={"deprecated"})
def wiki_search_cross(
    query: str,
    limit: int = 10,
    wiki_ids: str | None = None,
) -> str:
    """⚠️ Deprecated — use `wiki_search(wiki_ids=...)` instead.

    Kept for backward compatibility; behaves identically to
    wiki_search with the same wiki_ids.
    """
```

**兼容性核对**

| 老调用 | 新行为 | 破坏? |
|---|---|---|
| `wiki_search(q)` | 全部 wiki（与旧一致） | ✅ 无 |
| `wiki_search(q, 20)` | 同上 | ✅ 无 |
| `wiki_search(q, 20, "a")` | `wiki_id="a"` → 只搜 a（位置参数顺序未动） | ✅ 无 |
| `wiki_search(q, wiki_id="a")` | 只搜 a | ✅ 无 |
| `wiki_search(q, wiki_ids="a,b")` | 搜 a、b（**新能力**） | ✅ 无 |
| `wiki_search_cross(q)` | 全部 wiki，返回结构不变 | ✅ 无 |
| `wiki_search_cross(q, 20, "a,b")` | 搜 a、b，返回结构不变 | ✅ 无 |

### 4.2 skill · 同构

| action | 变更 |
|---|---|
| `search` | 不变（单 wiki） |
| `wiki_search` | 加 `wiki_ids` + `backend`；保留 `wiki_id`（description 标注 deprecated） |
| `wiki_search_cross` | 签名不变，description 加 ⚠️ Deprecated 说明 |

### 4.3 REST

`GET /api/search/cross` **签名与语义不变**，仅把已收集的 `backend` 真正传给 registry（**修 bug**）。

---

## 5. 底层：一份实现

落在 **`src/llmwikify/kernel/multi_wiki/search.py`**（L2，apps 与 interfaces 都能依赖）：

```python
def resolve_scope(
    registry: Any, *, wiki_ids: str | None = None, wiki_id: str | None = None
) -> list[str]:
    """Wiki ids to hit; raises ValueError when none of them exist."""


def search_wikis(
    registry: Any,
    query: str,
    limit: int = 10,
    *,
    wiki_ids: str | None = None,
    wiki_id: str | None = None,
    backend: str = "fts5",
) -> tuple[list[dict[str, Any]], list[str]]:
    """(results, searched_wiki_ids); raises ValueError on bad scope."""
```

- 作用域解析：`wiki_id` 优先 → `wiki_ids` → 全部。
- 全部 / 多个 → `registry.cross_wiki_search(query, ids, limit, backend=backend)`；
  单个 → `registry.get_wiki(wid).search(query, limit, backend=backend)`（远程 wiki 走 client，忽略 backend）。
- 结果**截断到 `limit`**（全局上限，取代原来的 per-wiki 语义）。
- 未知 id 跳过；**全部未知** → 抛 `ValueError`（MCP 层转 `{"error": ...}`，skill 层转 `SkillResult.fail`）。
- 两条分支的结果都带 `wiki_id` / `wiki_name`。

`registry.cross_wiki_search` 需加 `backend` 参数并透传给本地 `wiki.search(...)`。
**REST 顺带把这个参数用上**（原本收了不传）。

---

## 6. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `kernel/multi_wiki/registry.py` | `cross_wiki_search` 加 `backend="fts5"` 并透传给本地 wiki |
| 1b | **`kernel/multi_wiki/search.py`（新增）** | **共享实现 `resolve_scope` / `search_wikis`**（见上面改进 ②） |
| 2 | `interfaces/server/http/wiki/search_routes.py` | 把 `backend` 传给 registry（**修 bug**，REST 语义不变） |
| 3 | `interfaces/mcp/tools.py`（`register_multi_wiki_tools`） | `wiki_search` 加 `wiki_ids`（追加末尾）+ `wiki_id` 标 deprecated；`wiki_search_cross` 改为薄壳转调 + `annotations.deprecated` + `tags={"deprecated"}` + ⚠️ description；两者返回结构按 D13/D14 |
| 4 | `apps/chat/skills/wiki_query_skill.py` | 同构：`wiki_search` 加 `wiki_ids` + `backend`；`wiki_search_cross` description 标 deprecated |
| 5 | `README.md` / `docs/MCP_SETUP.md` / 核实文档 | `wiki_search` 描述补 `wiki_ids`；`wiki_search_cross` 标 deprecated；**工具数仍 26** |
| 6 | 测试 | `tests/test_kernel_multi_wiki_search.py`（17 单元）+ `tests/test_kernel_multi_wiki_cross_search.py`（9 单元）+ `tests/test_mcp_search_tool_merge.py`（8 端到端） |

---

## 7. Breaking 面

| 变更 | 影响 | 判定 |
|---|---|---|
| `wiki_search_cross` 标 deprecated | 仅提示，行为不变 | **非破坏** |
| `wiki_search` 新增 `wiki_ids`（末尾） | 位置参数顺序未动 | **非破坏** |
| `wiki_search` 的 `wiki_id` 保留 | 老调用照旧 | **非破坏** |
| deprecated 工具返回结构保持原样 | 老客户端照旧读 `resp["results"]` | **非破坏** |
| **cross 的 `limit`：per wiki → 全局** | 结果条数变少 | ⚠️ **唯一的行为变化**（D15） |
| REST `backend` 现在生效 | 之前被静默忽略 | ⚠️ 行为修正（bug fix） |

---

## 8. 验收标准

| # | 断言 |
|---|---|
| **V1** | 单 wiki：**20** 工具；`wiki_search` schema 仍 `(query, limit, backend)`，无 `wiki_ids` |
| **V2** | 多 wiki：**26** 工具（数量不变）；`wiki_search_cross` **仍存在** |
| **V3** | `wiki_search_cross` 带 `annotations.deprecated == true` + `tags` 含 `deprecated` |
| **V4** | **兼容矩阵全绿**：`wiki_search(q)` / `wiki_search(q, 20, "a")` / `wiki_search(q, wiki_id="a")` / `wiki_search_cross(q)` / `wiki_search_cross(q, 20, "a,b")` 结果与旧行为一致（除 limit 语义） |
| **V5** | `wiki_search(q, wiki_ids="a,b")` → 只搜 a、b |
| **V6** | `wiki_search(q, wiki_ids="*")` → 全部 |
| **V7** | `wiki_search(q, wiki_id="a", wiki_ids="b")` → `wiki_id` 优先，搜 a |
| **V8** | `limit` 全局：3 wiki 各命中 5 条 + `limit=5` → 结果 ≤ 5 |
| **V9** | `backend="qmd"` 透传到本地 wiki；远程 wiki 忽略且正常返回 |
| **V10** | `wiki_search_cross` 返回 `{results, total_results, searched_wikis}`（结构未变） |
| **V11** | `wiki_search` 返回裸 list |
| **V12** | skill：`wiki_query.wiki_search` 支持 `wiki_ids`/`backend`；`wiki_search_cross` description 含 Deprecated |
| **V13** | REST `GET /api/search/cross?backend=qmd` 真的生效 |
| **V14** | 四项门禁：ruff / mypy 416 文件 0 错 / 架构 0 violation / pytest 全过（**5226 passed**） |
| **V15** | **单元测试**：`kernel/multi_wiki/search.py` 的作用域解析与单/多/远程分支各有覆盖（fake registry，不起服务）—— `tests/test_kernel_multi_wiki_search.py` 17 项 |

---

## 9. 风险

| 风险 | 缓解 |
|---|---|
| LLM 仍可能选到 deprecated 工具 | description ⚠️ + `annotations.deprecated` 双标注；`wiki_search` 的 description 明确写"推荐用法" |
| 两个工具并存 → 长期双维护 | 底层只有一份实现；deprecated 工具是 3 行的薄壳 |
| `limit` 语义变化让老用户结果变少 | D15 需拍板；如需绝对兼容可让 deprecated 薄壳保留 per-wiki（底层加一个 flag） |
| `wiki_id` + `wiki_ids` 双参数让 LLM 困惑 | description 明确 `wiki_id` 已废弃、`wiki_ids` 为推荐；实现里 `wiki_id` 优先且兼容 |
| QMD 未就绪 | `index.search` 有 fts5 回落，不影响正确性 |

---

## 10. 交付节奏（doc-first）

1. 本方案 → **拍板后** commit（已写）
2. 实现 §6 的 1–4 → **commit**
3. 验证 §8 → **commit**
4. 文档同步 §6 的 5 → **commit**
5. `push`

---

*关联: [mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md) ·
[multi-wiki-mcp-reconnect.md](multi-wiki-mcp-reconnect.md) · `docs/MCP_SETUP.md`*
