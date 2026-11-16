# MCP 工具面核实 — 重复定义与多 wiki 能力断链

> **日期**: 2026-11-16
> **起因 1**: 总览文档同步时，我判断 `interfaces/mcp/tools.py` 里 `wiki_status` / `wiki_search`
> 各定义两次、后定义的覆盖先定义的、构成**不可达死代码**，并把它列为待清理的技术债。
> 用户指示"该清理的技术债清理"后，逐条复核 → **该判断不成立**（§1–§3）。
>
> **起因 2**: 复核过程中追问"多 wiki 模式下 18 个核心工具不注册，是设计还是遗漏"，
> 三层逐层实测 → **是遗漏，且断在三处**（§4）。
>
> **结论**:
> - §1–§3：重复定义**不是死代码**；真债是文档表述（26 是两条注册函数的名字并集）→ 已修。
> - §4–§5：多 wiki 的 MCP / skill 能力是 v0.31 **"写好了但没接上"的半成品**，
>   MCP 8 个工具生产零可达、skill 8 个 action 恒失败、`wiki_switch` 是 no-op。
>   **代码侧确实有债**，修复方案见 §5，**待拍板**。

---

## 1. 复核方法与证据

### 1.1 函数边界

`src/llmwikify/interfaces/mcp/tools.py` 有**两个顶层注册函数**，各自独立作用域：

| 注册函数 | 行范围 | 工具数 |
|---|---|---|
| `register_wiki_tools(mcp, wiki)` | L14–265 | **20** |
| `register_multi_wiki_tools(mcp, registry)` | L267–461 | **8** |

`wiki_status` / `wiki_search` 确实各出现在两个函数里，但**分属不同作用域**，
Python 不存在"后定义覆盖先定义"的问题。

### 1.2 注册是互斥的

`src/llmwikify/interfaces/mcp/adapter.py:54-57`：

```python
if self.registry:
    register_multi_wiki_tools(self._mcp, self.registry)
elif self.wiki:
    register_wiki_tools(self._mcp, self.wiki)
```

**if/else 二选一** —— 一个 FastMCP 实例上只会执行其中一条路径。

### 1.3 AST 扫描：无未调用定义

对 `tools.py` 做 AST 扫描（每个注册函数体内的局部 `def`）：

```
register_wiki_tools:       defines=20 decorated=20
register_multi_wiki_tools: defines=8  decorated=8
```

20 + 8 个定义**全部带 `@mcp.tool` 装饰器**，全部是对外暴露的工具，
**没有任何"定义了但从不调用"的局部函数**。

### 1.4 运行时实测

用真实 `Wiki` / `WikiRegistry` 实例注册后 `await mcp.list_tools()`：

| 构造方式 | 工具数 | 名单 |
|---|---|---|
| `MCPAdapter(wiki)` | **20** | wiki_init / wiki_ingest / wiki_write_page / wiki_read_page / wiki_search / wiki_lint / wiki_analyze_source / wiki_references / wiki_status / wiki_log / wiki_recommend / wiki_build_index / wiki_read_schema / wiki_update_schema / wiki_synthesize / wiki_sink_status / wiki_suggest_synthesis / wiki_knowledge_gaps / wiki_graph_analyze / wiki_graph |
| `MCPAdapter(registry)` | **8** | wiki_list / wiki_switch / wiki_register / wiki_unregister / wiki_status / wiki_search / wiki_search_cross / wiki_scan |

> ⚠️ **第二行在生产中不可达** —— 全仓 5 个 `MCPAdapter(` 调用点全部传 `Wiki`
> （含多 wiki 部署走的 `core.py:164`，它把 registry 解析成 default wiki 再传入）。
> 详见 §4.2 断点 1。所以**实际运行的服务器一律是 20 个**。

同名工具在两条路径下的**语义不同**：

| 工具 | 单 wiki 路径（生产实际走的） | 多 wiki 路径（生产不可达） |
|---|---|---|
| `wiki_status` | `wiki.status()` | `registry.get_wiki_status(wiki_id)`，`wiki_id` 可选（缺省 = default wiki） |
| `wiki_search` | `wiki.search(query, limit, backend=...)`，**支持 `backend` 参数**（fts5 / qmd） | 指定 `wiki_id` → 该 wiki；缺省 → `registry.cross_wiki_search(...)`；**无 `backend` 参数** |

### 1.5 顺带核实 FastMCP 去重行为

同一 `FastMCP` 实例上重复注册同名工具时，FastMCP 按名去重（后者覆盖前者，
并打印 `Component already exists` 警告）。当前 if/else 互斥所以**不触发**；
但若按 §5 方案 A"两个注册函数都调"，**会触发** —— 需把 multi-wiki 那组
**后注册**以覆盖同名的两个核心版，恰好得到 26 个唯一名字。

---

## 2. 我上一条判断错在哪

| 我当时的说法 | 实际 |
|---|---|
| "同一函数作用域**各定义两次**" | 错 —— 分属 `register_wiki_tools` / `register_multi_wiki_tools` 两个独立作用域 |
| "Python 层后者覆盖前者" | 错 —— 跨函数作用域不覆盖 |
| "FastMCP 注册时也按名去重" | 事实成立，但**本项目不会触发**（if/else 互斥） |
| "对外实际 26" | 错 —— 26 是两条路径的**名字并集**（20 + 8 − 2 同名），**没有任何服务器暴露 26** |
| "前两个定义是**不可达死代码**" | 错 —— 两份定义都在各自路径上**实际生效** |

该错误结论已被写进 `README.md` 与 `docs/llmwikify-功能全景与缺口清单.md`（commit `17456c94`），
本次一并修正。

---

## 3. 真正的债：文档表述

### 3.1 问题

| 位置 | 原文 | 问题 |
|---|---|---|
| `README.md` | "26 `wiki_*` tools available when server runs with `--transport stdio` or HTTP" | 暗示单个服务器暴露 26 个；实际是 20 或 8 |
| `README.md` | `## MCP Server (26 Tools)` | 同上（该表本身按"维护与查询 / 多 wiki 管理"分组，实际已隐含两种模式） |
| `README.md` | MCP 工具表 | **只列了 16 个工具**，标题却写 26 —— 漏 10 个：`wiki_log` `wiki_recommend` `wiki_analyze_source` `wiki_suggest_synthesis` `wiki_knowledge_gaps` `wiki_build_index` `wiki_read_schema` `wiki_update_schema` `wiki_sink_status` `wiki_unregister` |
| `docs/MCP_SETUP.md` | "暴露 **26 个 wiki 工具**" / "Current: 26 tools (v0.38.0)" / "📋 Available Tools (26 Total)" | 同上；且"数字 = 实际注册到 FastMCP 的工具数"这句**本身就是错的** |
| `docs/llmwikify-功能全景与缺口清单.md` | §2 README 对照表 | 我在 commit `17456c94` 里写进了**错误解释**（"FastMCP 按名去重 → 对外实际 26"） |

### 3.2 修正口径（已按 §4 进一步修订）

统一表述为：

> `register_wiki_tools` 注册 **20** 个；`register_multi_wiki_tools` 注册 **8** 个；
> 两函数工具名并集 **26** 个。
>
> **但生产中只有单 wiki 路径可达** —— 所以无论单 wiki 还是多 wiki 部署，
> 服务器实际都只暴露 **20** 个；6 个多 wiki 专属工具**从未被注册**。
> **没有任何一个运行中的服务器暴露 26 或 8 个。**

具体改动：

| 文件 | 改动 |
|---|---|
| `README.md` | 标题与说明行标注 20/8；工具表**补齐到 26 行**（逐条对齐 `tools.py` 的 docstring） |
| `docs/MCP_SETUP.md` | 头部加模式表；`Available Tools` 章节说明改为"并集 26"；多 wiki 章节标注 6 个专属 + 2 个同名不同语义 |
| `docs/llmwikify-功能全景与缺口清单.md` | §2 换成正确解释（20 + 8 − 2 同名 = 26 并集，if/else 互斥） |

工具**名单**与**数量**（26 并集口径）不变 —— 改的只是"available when server runs"的措辞。

> ⚠️ 本轮早些时候 commit `4e9f73c1` 写的"多 wiki 模式 8 个"**在生产中不成立**，
> 是按"手动 `MCPAdapter(registry)`"得出的，而该构造方式**全仓无调用点**（见 §4）。

---

## 4. 多 wiki 能力核实 — 三层断链（原 D3 复核）

> **结论**：多 wiki 的 MCP / skill 能力是 v0.31 **"写好了但没接上"的半成品**。
> 代码在、设计文档写 28、但没有任何调用点把它挂上。**不是设计选择，是遗漏。**

### 4.1 设计意图（有文档与代码佐证）

| 出处 | 说法 |
|---|---|
| `wiki_query_skill.py:1,8,487` | "28-action aggregator"、"28 actions map 1:1 to the 28 MCP `@mcp.tool` definitions" |
| `docs/designs/v0.32-skill-restructure.md:691` | "`interfaces/mcp/tools.py` 完整 28 个 tool（20 wiki + 8 multi-wiki）" |
| `docs/KNOWN_ISSUES.md:30` | "MCP 工具集 20 → 26 — 增 6 个 multi-wiki 工具 + 2 个 scoped 变体"（v0.31） |
| `docs/MCP_SETUP.md` | Available Tools 按"Wiki 核心 20 + Multi-Wiki 6"两组列出 = 26 |

设计意图是**一个服务器暴露 20 核心 + 8 multi-wiki（26 唯一名字）**。

### 4.2 实际断在三处

#### 断点 1 · MCP：`register_multi_wiki_tools` 零可达

`MCPAdapter.__init__` 的 `adapter.py:54-57` 是 if/else：

```python
if self.registry:
    register_multi_wiki_tools(self._mcp, self.registry)   # 8 个
elif self.wiki:
    register_wiki_tools(self._mcp, self.wiki)             # 20 个
```

**全仓 `MCPAdapter(` 共 5 处调用，全部传 `Wiki`，无一传 registry**：

| 调用点 | 传入 |
|---|---|
| `interfaces/cli/commands/serve.py:383` | `wiki`（单 wiki 模式的 Wiki 实例） |
| `interfaces/mcp/server.py:29` | `wiki: Wiki` |
| `interfaces/mcp/server.py:43` | `wiki: Wiki` |
| `interfaces/server/core.py:164` | `self.wiki` = `self.registry.get_default_wiki()` |

`core.py:164` 是**多 wiki 部署的唯一路径**：`WikiServer(registry)` 内部
把 registry 解析成 default `Wiki` 再交给 `MCPAdapter`，于是走 `elif` 分支 → 20 个工具。

**运行时实测**（`WikiServer(WikiRegistry)` → `list_tools()`）：

```
multi-wiki WikiServer exposes 20 tools
multi-wiki-only tools present: []
multi-wiki-only tools MISSING: ['wiki_list', 'wiki_register', 'wiki_scan',
                                'wiki_search_cross', 'wiki_switch', 'wiki_unregister']
```

→ **多 wiki 部署下，MCP 客户端无法列出/切换/注册 wiki，也无法跨 wiki 搜索。**

#### 断点 2 · Skill：8 个 multi-wiki action 恒失败

`wiki_query_skill._registry()`（L82-87）从 `ctx.config["wiki_registry"]` 取注册表。
但 `tool_adapter.py:179` 与 `:240` 构造 config 时只放：

```python
config = {"wiki_id": self.wiki_id} if self.wiki_id else {}
config["subagent_manager"] = ...        # 可选
config["child_tool_registry"] = ...     # 可选
```

**全仓无任何 `config["wiki_registry"]` 写入点**（`grep '"wiki_registry"'` 只命中读取处）。

运行时实测（用 `tool_adapter` 实际会传的 config 形状）：

```
wiki_list          -> {'status': 'error', 'error': 'wiki_registry not configured'}
wiki_switch        -> {'status': 'error', 'error': 'wiki_registry not configured'}
wiki_search_cross  -> {'status': 'error', 'error': 'wiki_registry not configured'}
wiki_search        -> {'status': 'error', 'error': 'wiki_registry not configured'}
```

`wiki_query` 共 28 个 action，其中 8 个（`wiki_list` `wiki_switch` `wiki_register`
`wiki_unregister` `wiki_search` `wiki_status` `wiki_search_cross` `wiki_scan`）
**恒返回错误** —— LLM 会反复尝试并拿到同一句错误。

#### 断点 3 · `wiki_switch` 是 no-op

MCP 版（`tools.py:289-306`）与 skill 版（`wiki_query_skill.py:322-338`）**完全一致**：

```python
instance = registry.get_wiki_instance(wiki_id)
return {"message": f"Switched to wiki: {instance.name}", "wiki": instance.to_dict()}
```

**只返回 instance 信息，没有调用 `registry.set_default_wiki(wiki_id)`。**
返回的 `"Switched to wiki: ..."` 是**假成功**。

`set_default_wiki` 全仓只有 2 个调用点，都不在多 wiki 能力面上：

| 调用点 | 场景 |
|---|---|
| `interfaces/server/core.py:110` | 服务启动时设置初始 default |
| `interfaces/server/http/wiki/registry_routes.py:117` | `PUT /api/wikis/{id}` 且 body 带 `is_default` |

**REST/WebUI 不受影响** —— 它们有完整的 GET/POST/PUT/DELETE + reload/health/scan，
且 PUT 路径能真正切换 default。多 wiki 能力**只在 MCP / skill 两条路上断掉**。

### 4.3 影响面

| 使用方 | 影响 |
|---|---|
| 外部 MCP 客户端（Claude Desktop / Cursor / opencode）在多 wiki 部署 | 只能操作 default wiki；无法列/切/注册 wiki，无法跨 wiki 搜索 |
| Chat agent（skill 路径） | `wiki_query` 的 8 个 multi-wiki action 恒失败 |
| REST / WebUI | **不受影响** |
| 单 wiki 部署 | **不受影响**（本就只需要 20 个核心工具） |

### 4.4 原 D1 / D2 复核：前提不成立

| 原判断 | 复核结论 |
|---|---|
| **D1** 多 wiki `wiki_search` 与 `wiki_search_cross` 语义重叠 | **生产中不成立** —— 多 wiki 版 `wiki_search`（带 `wiki_id`）不可达；生产实际暴露的是单 wiki 版 |
| **D2** 多 wiki `wiki_search` 缺 `backend` 参数 | **不成立** —— 生产走单 wiki 版，**有** `backend`（`fts5`/`qmd`） |
| **D3** 多 wiki 模式 18 个核心工具不注册 | **反了** —— 多 wiki 部署暴露的是 20 个核心工具（绑 default wiki）；**缺的是 6 个多 wiki 专属工具** |

skill 层其实把两套都实现了（不同 action 名）：

| skill action | handler | 类型 |
|---|---|---|
| `search` / `status` | `_search` / `_status` | 单 wiki 核心 |
| `wiki_search` / `wiki_status` | `_wiki_search_by_id` / `_wiki_status_by_id` | 多 wiki（需 registry） |
| `wiki_search_cross` | `_wiki_search_cross` | 跨 wiki（需 registry） |

**skill 层是干净的两套命名**；MCP 层用同名 + if/else 区分，结果只跑了一套。

---

## 5. 修复方案（需拍板）

| 方案 | 内容 | 成本 | 风险 |
|---|---|---|---|
| **A · 最小接线** | ① `core.py:164` / `serve.py:383` 改为把 registry 传下去；② `MCPAdapter` 在 registry 分支**先注册 20 核心、再注册 8 multi-wiki**（同名由后者覆盖 → 恰好 26 唯一名字，对齐 v0.31 设计）；③ `wiki_switch` 补 `set_default_wiki`；④ `tool_adapter` 把 registry 注入 `ctx.config["wiki_registry"]` | 小（4 处） | 中：核心工具仍绑**构造时**的 default wiki，`wiki_switch` 后核心工具不跟随（需方案 B 才根治） |
| **B · A + 动态解析** | 在 A 基础上，核心工具改为每次调用 `registry.get_wiki(registry.get_default_wiki_id())` 解析当前 wiki | 中（改 `register_wiki_tools` 签名/闭包） | 低：但影响单 wiki 路径，需回归测试 |
| **C · 承认现状** | 不动代码；从 `KNOWN_ISSUES` / `MCP_SETUP` / README 删掉 26 工具的说法，明确"多 wiki 能力只承诺给 REST / WebUI / chat" | 极小 | 低：但 v0.31 的设计成果仍是半成品 |

**倾向 A**：skill 层 28 个 action 已写完，只差 config 注入；MCP 的 if/else 只差"两个都注册"。
这是**接线问题，不是设计问题**。A 做完后再评估是否需要 B。

---

## 6. 复现

```bash
# ① 真实多 wiki 服务器暴露多少工具（关键证据）
python -c "
import asyncio, tempfile, pathlib
from llmwikify.interfaces.server.core import WikiServer
from llmwikify.kernel.multi_wiki.registry import WikiRegistry
tmp = pathlib.Path(tempfile.mkdtemp())
reg = WikiRegistry({}); reg.register_wiki('w1','w1',tmp,is_default=True)
s = WikiServer(reg, enable_mcp=True, enable_rest=False, enable_webui=False)
print(len(asyncio.run(s.mcp._mcp.list_tools())))
"

# ② 两条注册函数各自的规模 + 生产调用点
python -c "
import ast, pathlib
t = ast.parse(pathlib.Path('src/llmwikify/interfaces/mcp/tools.py').read_text(encoding='utf-8'))
for fn in [n for n in t.body if isinstance(n, ast.FunctionDef)]:
    print(fn.name, sum(1 for d in fn.body if isinstance(d, ast.FunctionDef) and d.decorator_list))
"
grep -rn 'MCPAdapter(' src/ | wc -l      # 5，且全部传 Wiki

# ③ skill 层 multi-wiki action 是否可用
# 见 §4.2 断点 2 的实测输出：恒为 wiki_registry not configured

# ④ set_default_wiki 调用点（确认 wiki_switch 不切换）
grep -rn 'set_default_wiki' src/         # 只有 core.py:110 与 registry_routes.py:117
```

---

*核实于 2026-11-16 · 相关文档：`README.md` · `docs/MCP_SETUP.md` · `docs/KNOWN_ISSUES.md` ·
`docs/designs/MULTI_WIKI_PLAN.md` · `docs/llmwikify-功能全景与缺口清单.md`*
