# 合并 `wiki_search` 与 `wiki_search_cross`

> **日期**: 2026-11-16 · **状态**: 方案待拍板（**未实施**）
> **起因**: 上一轮接线后，多 wiki 模式下 `wiki_search`（无 `wiki_id` 时跨全部）与
> `wiki_search_cross` **功能重叠**，LLM 侧要猜该用哪个。
> **前置**: [docs/diagnostics/mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md)、
> [docs/designs/multi-wiki-mcp-reconnect.md](multi-wiki-mcp-reconnect.md)

---

## 1. 现状：三个搜索工具的真相对照

| 面 | 工具 | 签名 | 作用域 | `backend` | `limit` 语义 | 返回 |
|---|---|---|---|---|---|---|
| MCP 单 wiki | `wiki_search` | `(query, limit=10, backend="fts5")` | 当前 wiki | ✅ | **总条数** | 裸 list |
| MCP 多 wiki | `wiki_search` | `(query, limit=10, wiki_id=None, backend="fts5")` | `wiki_id` 指定；缺省 → **全部** | 仅指定分支 | **per wiki** | 裸 list |
| MCP 多 wiki | `wiki_search_cross` | `(query, limit=10, wiki_ids=None)` | `wiki_ids` 指定；缺省 → 全部 | ❌ | **per wiki** | `{results, total_results, searched_wikis}` |
| skill | `search` | `(query, limit, backend)` | 当前 wiki | ✅ | 总条数 | `{result: [...]}` |
| skill | `wiki_search` | `(query, limit, wiki_id)` | `wiki_id` 指定；缺省 → 全部 | ❌ | per wiki | `{result: [...]}` |
| skill | `wiki_search_cross` | `(query, limit, wiki_ids)` | `wiki_ids` 指定；缺省 → 全部 | ❌ | per wiki | `{results, total_results, searched_wikis}` |
| REST | `GET /api/search/cross` | `(q, limit=10, wikis=None, backend="fts5")` | `wikis` 指定；缺省 → 全部（**按 token claim 过滤**） | ⚠️ **收了但没传** | per wiki | `{results, total_results, searched_wikis}` |

### 1.1 重叠点

多 wiki 模式下 `wiki_search(q)` 与 `wiki_search_cross(q)` **调用的是同一个
`registry.cross_wiki_search(query, None, limit)`**，只是返回包装不同。

### 1.2 合并必须处理的三处语义差异

| # | 差异 | 现状 | 合并后的处理 |
|---|---|---|---|
| **①** | `limit` 语义两套 | 单 wiki = 总条数上限；cross = **per wiki**（N 个 wiki → 最多 N×limit 条） | 统一为**全局总条数上限** |
| **②** | `backend` | 单 wiki 支持；cross 固定 fts5；**REST 收了 `backend` 却没传给 registry**（已有 bug） | 全链路透传 |
| **③** | 返回结构 | 单 wiki 裸 list；cross 结构化 dict | 统一（见 D6） |

### 1.3 一个顺带发现

`registry.cross_wiki_search` 对**未知 `wiki_id` 是静默跳过**（`continue`），
不报错。合并后若只传了不存在的 id，调用方会拿到空结果而不知原因。

---

## 2. 决策点

| # | 决策 | 候选 | 倾向 | 理由 |
|---|---|---|---|---|
| **D1** | 合并范围 | ① 只 MCP 工具 ② MCP 工具 + skill action ③ 再加 REST 路由 | **②** | REST `/api/search/cross` 是 HTTP 面、已有鉴权（`_filter_by_claim`）、形态已定；改动它会破坏 HTTP 客户端。**但顺带修它的 `backend` 未透传 bug**（纯 bug 修复，语义不变） |
| **D2** | 保留哪个名字 | `wiki_search` / `wiki_search_cross` | **`wiki_search`** | 更通用、已被 skill `search` action 与多份文档引用；`wiki_search_cross` 的能力用参数表达更自然 |
| **D3** | 多 wiki 合并后签名 | — | **`wiki_search(query, limit=10, wiki_ids=None, backend="fts5")`** | 一个参数覆盖"搜一个 / 搜多个 / 搜全部" |
| **D4** | `wiki_ids=None` 的含义 | ① 当前 default wiki ② 全部 wiki | **① 当前 default** | 跨模式一致（单 wiki 模式搜的就是当前 wiki）。全部用 `wiki_ids="*"` —— **`"*"` 已是本项目既有的通配约定**（授权表 `wiki_id='*'`，见 multiuser-auth-design Q3） |
| **D5** | `wiki_id` 参数 | ① 保留两个参数 ② 并入 `wiki_ids` | **② 并入** | 单个 id 写成 `"a"`；两个参数会让 LLM 纠结填哪个 |
| **D6** | 返回结构 | ① MCP 裸 list ② 全结构化 dict | **① MCP 裸 list / skill `{"results", "total_results"}`** | 裸 list 与单 wiki 一致、LLM 消费成本最低；跨 wiki 的归属信息已在每条结果的 `wiki_id` / `wiki_name` 里 |
| **D7** | 单 wiki 模式 | ① 保持 20 工具不变 ② 也加 `wiki_ids` | **① 不变** | 单 wiki 只有一个 wiki，`wiki_ids` 无意义；且保持 schema 零变化是上一轮 B3 的既定约束 |
| **D8** | `limit` 统一 | ① 全局上限 ② 维持 per wiki | **① 全局上限** | LLM 传 `limit=10` 的直觉是"给我 10 条"，不是"每个 wiki 10 条" |
| **D9** | 未知 `wiki_id` | ① 维持静默跳过 ② 返回 error | **② 返回 error** | 合并后 `wiki_ids` 成为唯一入口，静默失败会让人误以为"没搜到内容" |

> **D4 是唯一的语义破坏性变更**（多 wiki 下 `wiki_search(q)` 从"跨全部"变成"搜当前 default"）。
> 旧行为用 `wiki_ids="*"` 即可恢复。

---

## 3. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `kernel/multi_wiki/registry.py` | `cross_wiki_search(query, wiki_ids, limit)` **加 `backend="fts5"`** 并透传给本地 `wiki.search(...)`；远程 wiki 不支持 backend（忽略） |
| 2 | `interfaces/server/http/wiki/search_routes.py` | 把已收集的 `backend` 传给 `registry.cross_wiki_search`（**修 bug**，REST 语义不变） |
| 3 | `interfaces/mcp/tools.py`（`register_multi_wiki_tools`） | **删** `wiki_search_cross`；`wiki_search` 改为 `(query, limit=10, wiki_ids=None, backend="fts5")`：<br>· `wiki_ids=None` → 当前 default wiki<br>· `wiki_ids="*"` → 全部<br>· `wiki_ids="a,b"` → 指定多个<br>· 结果截断到 `limit`（全局上限）<br>· 未知 id → 返回 error |
| 4 | `apps/chat/skills/wiki_query_skill.py` | **删** `wiki_search_cross` action 与 `_wiki_search_cross` handler；`wiki_search` action 吸收 `wiki_ids` + `backend`（`_wiki_search_by_id` 重写为 `_wiki_search`）；单 wiki 的 `search` action 不变 |
| 5 | `README.md` / `docs/MCP_SETUP.md` / 核实文档 | 工具表：多 wiki **26 → 25**；删 `wiki_search_cross` 行；`wiki_search` 描述更新（`wiki_ids` / `backend`） |
| 6 | 测试 | 改 `tests/test_apps_chat_skills_wiki_query.py:144`（断言 action 名）；改 `tests/scenarios/test_03_multi_wiki.py:27`（troubleshooting 文案）；新增合并行为测试（见 §5） |

**工具数变化**：单 wiki **20 不变**；多 wiki **26 → 25**。

---

## 4. Breaking 面

| 变更 | 影响 | 缓解 |
|---|---|---|
| `wiki_search_cross` 移除（MCP + skill） | 写死该工具名的客户端失效 | LLM 客户端按 schema 自适应；人类客户端需改用 `wiki_search` |
| `wiki_search` 的 `wiki_id` → `wiki_ids` | 同上 | 单 id 写成 `"a"` |
| 多 wiki `wiki_search(q)`：跨全部 → 当前 default | 结果集变小 | `wiki_ids="*"` 恢复旧行为 |
| cross 的 `limit`：per wiki → 全局 | 结果条数变少 | 更符合 LLM 预期 |
| `registry.cross_wiki_search` 加 `backend` 参数 | **向后兼容**（默认 fts5） | — |

---

## 5. 验收标准

| # | 断言 |
|---|---|
| **V1** | 单 wiki：**20** 工具；`wiki_search` schema 仍 `(query, limit, backend)`，**无 `wiki_ids`** |
| **V2** | 多 wiki：**25** 工具；`wiki_search_cross` **不存在** |
| **V3** | 多 wiki `wiki_search(q)` → 只搜当前 default wiki |
| **V4** | 多 wiki `wiki_search(q, wiki_ids="*")` → 搜全部 wiki |
| **V5** | 多 wiki `wiki_search(q, wiki_ids="a,b")` → 只搜 a、b |
| **V6** | `wiki_ids="a,nosuch"` → 返回 error（不静默） |
| **V7** | `limit` 是**全局**上限：3 个 wiki 各命中 5 条 + `limit=5` → 结果 **≤ 5** |
| **V8** | `backend="qmd"` 透传到本地 wiki（远程 wiki 忽略并正常返回） |
| **V9** | skill：`wiki_query.wiki_search` 支持 `wiki_ids` / `backend`；`wiki_search_cross` action **不存在**；`search`（单 wiki）不变 |
| **V10** | REST `GET /api/search/cross?backend=qmd` 现在**真的生效**（bug 修复） |
| **V11** | 四项门禁：ruff / mypy 415 文件 0 错 / 架构 0 violation / pytest 全过 |

---

## 6. 风险

| 风险 | 缓解 |
|---|---|
| 外部 MCP 客户端写死了 `wiki_search_cross` | breaking 已列 §4；工具表与文档同步标注 |
| `limit` 全局化使跨 wiki 结果变少 | 这是**修正**而非退化；`wiki_ids="*"` + 大 limit 可覆盖 |
| `backend="qmd"` 在多 wiki 下只有本地 wiki 生效 | QMD 目前是可选加速路径（`index.search` 有 fts5 回落），不影响正确性 |
| 远程 wiki 不支持 `backend` | 已在工具 docstring 注明 |

---

## 7. 交付节奏（doc-first）

1. 本方案 → **拍板后** commit（已写）
2. 实现 §3 的 1–4 → **commit**
3. 验证 §5 → **commit**
4. 文档同步 §3 的 5 → **commit**
5. `push`

---

*关联: [mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md) ·
[multi-wiki-mcp-reconnect.md](multi-wiki-mcp-reconnect.md) · `docs/MCP_SETUP.md`*
