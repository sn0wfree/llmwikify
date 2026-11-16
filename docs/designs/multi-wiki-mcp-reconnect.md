# 多 wiki MCP / Skill 能力接线（方案 B）

> **日期**: 2026-11-16 · **状态**: ✅ **已实现**（commit `bc316bb8`）
> **前置**: [docs/diagnostics/mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md) §4
> **拍板**: 用户选 **方案 B**（A 接线 + 动态解析）
> **设计依据**: v0.31「MCP 工具集 20 → 26」（`docs/KNOWN_ISSUES.md:30`）、
> `wiki_query_skill` 28-action 设计（`wiki_query_skill.py:1,487`）

### 实现结果（V1–V8 全过）

| 验收 | 结果 |
|---|---|
| V1 单 wiki 路径 | **20 工具**，`wiki_search` schema 仍是 `(query, limit, backend)`，**无 `wiki_id`** |
| V2 多 wiki `WikiServer` | **26 工具**（含 6 个 registry 专属），启动**无** `Component already exists` 警告 |
| V3/V4 `wiki_switch` | 调用后 `default_wiki_id` 更新，**不重启**核心工具读到新 wiki |
| V5 skill 层 | `wiki_list` / `wiki_switch` / `wiki_search_cross` 全部 `status=ok`，不再报 `wiki_registry not configured` |
| V7 四项门禁 | ruff 干净 · mypy 415 文件 0 错 · `check_architecture.py` 0 violation · **pytest 5201 passed** |

### 实现中偏离本方案的两处

| # | 方案原文 | 实际 | 理由 |
|---|---|---|---|
| **B4** | 默认 wiki 解析失败 → **返回 JSON 错误** | **改为 `raise`**（`RuntimeError` / `KeyError` / `ValueError`） | ① 本文件返回 JSON 的模式是**用户输入错误**（如 bad `wiki_id`），而"没有 default wiki / default 是 remote"是**服务端配置错误**；② 26 个核心工具都要加 `if isinstance(t, dict)` 判断，40 行样板违反简洁优先；③ FastMCP 会把异常转成结构化 tool error 交给客户端。**单 wiki 路径不受影响**（`registry is None` 时直接返回 `wiki`）。 |
| **B3 附带** | 未涉及 | `core.py` 增加 `_multi_wiki` 标志：**只有显式传入 `WikiRegistry` 才给 26 工具**，`WikiServer(single_wiki)` 仍给 20 | 否则单 wiki 部署会因"内部也建 registry"而变成 26 工具，违背"单 wiki 20 / 多 wiki 26" |

### 另一处实现细节

`FastMCP.remove_tool()` 在 fastmcp 3.2 起被弃用（改用 `local_provider.remove_tool`），
而 `pyproject.toml` 的约束是 `fastmcp>=3.0,<3.3` —— 所以 `MCPAdapter._remove_tool()`
优先走 `local_provider`，没有则回落到 `remove_tool()`，两种版本都无警告。

---

---

## 1. 背景

多 wiki 能力在三层断掉，是 v0.31 **"写好了但没接上"的半成品**：

| 断点 | 现状 |
|---|---|
| ① MCP 注册 | `register_multi_wiki_tools` 的 8 个工具**生产零可达**（5 个 `MCPAdapter(` 调用点全传 `Wiki`） |
| ② Skill 注入 | `wiki_query` 28 个 action 中 8 个恒返回 `wiki_registry not configured` |
| ③ `wiki_switch` | MCP 版与 skill 版**都是 no-op**（没调 `set_default_wiki`） |

**方案 B 的目标**：把三层接上，并让核心工具**动态解析当前 default wiki**，
使 `wiki_switch` 之后核心工具真正跟随切换（方案 A 做不到这一点）。

---

## 2. 决策点

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| **B1** | 注册顺序与同名冲突 | **先注册核心 20 → `remove_tool` 移除 `wiki_status`/`wiki_search` → 再注册 multi-wiki 8** | 单 wiki 路径 schema **零变化**；避免 FastMCP `Component already exists` 警告 |
| **B2** | 核心工具如何拿 wiki | **`register_wiki_tools(..., registry=None)`**：`registry` 为 `None` 走原闭包（单 wiki 完全不变）；否则每次调用 `registry.get_wiki(wiki_id or default)` | 单 wiki 路径零回归；多 wiki 路径跟随 `wiki_switch` |
| **B3** | `wiki_id` 参数是否给单 wiki 暴露 | **不暴露** —— 单 wiki 路径签名与今天完全一致 | 避免单 wiki 客户端看到会报错的参数 |
| **B4** | default wiki 解析失败 | 返回 **JSON 错误**（`{"error": ...}`），**不抛异常** | default 是 REMOTE 时 `registry.get_wiki()` 会抛 `ValueError`；MCP 工具应返回结构化错误 |
| **B5** | 多 wiki 版 `wiki_search` 是否补 `backend` | **补** | 否则覆盖核心版后 **qmd 语义后端入口丢失**（能力倒退） |
| **B6** | `wiki_search` 缺省是否改"只搜 default"（原 D1） | **不改** —— 保持 `cross_wiki_search` | 属产品行为变更，超出接线范围；已在核实文档 §4.4 记录重叠 |
| **B7** | research 引擎路径 | **不做** —— 记为已知限制 | `ResearchEngine.__init__(wiki, db, llm_client, config)` 无 registry，注入需改构造签名与所有调用点；且研究引擎是"对单 wiki 研究"，非跨 wiki 管理 |

---

## 3. 实现规格

### 3.1 `interfaces/mcp/tools.py` — `register_wiki_tools` 支持动态解析

```python
def register_wiki_tools(
    mcp: FastMCP,
    wiki: Wiki | None = None,
    *,
    registry: Any | None = None,
) -> None:
```

内部新增闭包 `_target(wiki_id: str | None = None) -> Wiki | dict`：

| `registry` | `wiki_id` | 行为 |
|---|---|---|
| `None` | 忽略 | 返回 `wiki`（与今天完全一致） |
| 给定 | `None` | `registry.get_wiki(registry.get_default_wiki_id())` — **每次调用重新解析** |
| 给定 | 指定 | `registry.get_wiki(wiki_id)` |
| 给定 | 解析失败（未设 default / remote / 未注册） | 返回 `{"error": ...}` dict |

`register_wiki_tools` 函数体内 **26 处 `wiki.` 属性访问**改为经 `_target()` 解析。
`wiki_status` / `wiki_search` 两个核心版在多 wiki 模式下会被 3.2 移除，
但**仍按同一规则实现**（保证注册顺序万一调整也不会出错）。

### 3.2 `interfaces/mcp/adapter.py` — registry 分支接线

```python
if self.registry:
    register_wiki_tools(self._mcp, self.wiki, registry=self.registry)
    for name in ("wiki_status", "wiki_search"):   # 交给 multi-wiki 版（带 wiki_id）
        self._mcp.remove_tool(name)
    register_multi_wiki_tools(self._mcp, self.registry)
elif self.wiki:
    register_wiki_tools(self._mcp, self.wiki)
```

结果：**单 wiki 20 个（签名不变）/ 多 wiki 26 个（20 核心 − 2 同名 + 8 multi-wiki）**。

### 3.3 `wiki_switch` 真切换（两处）

| 位置 | 改动 |
|---|---|
| `interfaces/mcp/tools.py` `wiki_switch` | 加 `registry.set_default_wiki(wiki_id)` |
| `apps/chat/skills/wiki_query_skill.py` `_wiki_switch` | 同上 |

失败路径（wiki 不存在）保持现有 `KeyError` → JSON error。

### 3.4 多 wiki 版 `wiki_search` 补 `backend`

`register_multi_wiki_tools` 的 `wiki_search(query, limit=10, wiki_id=None)` →
`wiki_search(query, limit=10, wiki_id=None, backend="fts5")`。

**已确认**（`registry.py:414-419`）：`cross_wiki_search(query, wiki_ids, limit)`
**不接受 `backend`**，所以：

- `wiki_id` 分支 → `registry.get_wiki(wiki_id).search(query, limit, backend=backend)`（透传）
- 缺省（跨 wiki）分支 → `registry.cross_wiki_search(query, None, limit)`，**忽略 `backend`**
  （docstring 注明 "backend only applies to the single-wiki branch"）

### 3.5 `apps/chat/skills/tool_adapter.py` — 注入 registry

两处构造 `config` 的地方（`_execute_direct` L179、`_execute_confirmed` L240）加：

```python
if self.wiki_service is not None and getattr(self.wiki_service, "wiki_registry", None):
    config["wiki_registry"] = self.wiki_service.wiki_registry
```

`WikiService.wiki_registry` 已确认是 `WikiRegistry`
（`apps/wiki/service.py:54`，由 `interfaces/server/http/routes.py:251` 注入）。

### 3.6 明确不改

- `register_multi_wiki_tools` 的 6 个专属工具实现（除 3.3 / 3.4）
- `wiki_search` 缺省跨 wiki 行为（B6）
- `ResearchEngine` 路径（B7）
- 单 wiki 路径的任何签名或行为

---

## 4. 验收标准

| # | 断言 | 判据 |
|---|---|---|
| **V1** | 单 wiki 路径零回归 | `MCPAdapter(wiki)` → **20** 个工具；`wiki_search` 签名仍为 `(query, limit, backend)`，**无 `wiki_id`** |
| **V2** | 多 wiki 路径 26 工具 | `WikiServer(WikiRegistry)` → **26** 个；含 `wiki_list` `wiki_switch` `wiki_register` `wiki_unregister` `wiki_search_cross` `wiki_scan` |
| **V3** | `wiki_switch` 真切换 | 调用 `wiki_switch(wiki_id="b")` 后 `registry.get_default_wiki_id() == "b"`；且核心工具（如 `wiki_read_page`）读到的是 **b** 的内容 |
| **V4** | 核心工具动态解析 | 同上，切换后**不重启**即跟随 |
| **V5** | skill 层复活 | `wiki_query` 的 `wiki_list` / `wiki_switch` / `wiki_search_cross` / `wiki_search` 在注入 registry 后 **不再返回 `wiki_registry not configured`** |
| **V6** | 无注册警告 | 多 wiki 启动不打印 `Component already exists` |
| **V7** | 四项门禁 | `ruff check` / `mypy src/` / `check_architecture.py` / `pytest` 全过 |
| **V8** | 现有 MCP 集成测试 | `tests/test_mcp_integration.py` 全过（它走单 wiki 路径，覆盖 V1） |

---

## 5. 风险

| 风险 | 缓解 |
|---|---|
| 26 处 `wiki.` 替换出错 | 单 wiki 路径 `registry=None` 直接返回原 `wiki`，行为与今天**逐字节一致**；靠 V1 + V8 兜底 |
| `remove_tool` 在多 wiki 模式移除后，若有客户端缓存了旧 schema | 工具在启动时一次性注册，客户端连接时拉取，不受影响 |
| `registry.get_wiki()` 对 REMOTE default 抛异常 | `_target()` 统一捕获并返回 JSON 错误（B4） |
| 多 wiki 启动日志噪音 | B1 用 `remove_tool` 规避（V6） |

---

## 6. 交付节奏（doc-first）

1. 本方案文档 → **commit**
2. 实现（3.1–3.5）→ **commit**
3. 验证（V1–V8）→ 若有调整 → **commit**
4. 同步文档（`MCP_SETUP.md` / `README.md` / 核实文档 §5 标记方案 B 已落地）→ **commit**
5. `push`

---

*关联: [mcp-tool-surface-2026-11.md](../diagnostics/mcp-tool-surface-2026-11.md) ·
`docs/KNOWN_ISSUES.md` · `docs/MCP_SETUP.md` · `docs/designs/v0.32-skill-restructure.md`*
