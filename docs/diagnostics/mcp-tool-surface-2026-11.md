# MCP 工具面核实 — 重复定义是否死代码

> **日期**: 2026-11-16
> **起因**: 总览文档同步时，我判断 `interfaces/mcp/tools.py` 里 `wiki_status` / `wiki_search`
> 各定义两次、后定义的覆盖先定义的、构成**不可达死代码**，并把它列为待清理的技术债。
> 用户指示"该清理的技术债清理"后，逐条复核 → **该判断不成立**。本文记录复核过程与真实结论。
> **结论**: 代码侧**无需修改**；真正的债是**文档表述**（26 是两条注册路径的名字并集，
> 没有任何一个运行中的服务器暴露 26 个工具）。

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

| 模式 | 工具数 | 名单 |
|---|---|---|
| 单 wiki（`MCPAdapter(wiki)`） | **20** | wiki_init / wiki_ingest / wiki_write_page / wiki_read_page / wiki_search / wiki_lint / wiki_analyze_source / wiki_references / wiki_status / wiki_log / wiki_recommend / wiki_build_index / wiki_read_schema / wiki_update_schema / wiki_synthesize / wiki_sink_status / wiki_suggest_synthesis / wiki_knowledge_gaps / wiki_graph_analyze / wiki_graph |
| 多 wiki（`MCPAdapter(registry)`） | **8** | wiki_list / wiki_switch / wiki_register / wiki_unregister / wiki_status / wiki_search / wiki_search_cross / wiki_scan |

同名工具在两条路径下的**语义不同**，是有意设计：

| 工具 | 单 wiki 模式 | 多 wiki 模式 |
|---|---|---|
| `wiki_status` | `wiki.status()` | `registry.get_wiki_status(wiki_id)`，`wiki_id` 可选（缺省 = default wiki） |
| `wiki_search` | `wiki.search(query, limit, backend=...)`，**支持 `backend` 参数**（fts5 / qmd） | 指定 `wiki_id` → 该 wiki；缺省 → `registry.cross_wiki_search(...)`；**无 `backend` 参数** |

### 1.5 顺带核实 FastMCP 去重行为

同一 `FastMCP` 实例上重复注册同名工具时，FastMCP 按名去重（后者覆盖前者，
并打印 `Component already exists` 警告）。**本项目不会触发这条路径**，
因为两条注册路径互斥（见 1.2）。

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

### 3.2 修正口径

统一表述为：

> 单 wiki 模式 **20** 个工具；多 wiki 模式 **8** 个；两模式名字并集 **26** 个。
> **没有任何一个运行中的服务器暴露 26 个。**

具体改动：

| 文件 | 改动 |
|---|---|
| `README.md` | 标题与说明行标注 20/8；工具表**补齐到 26 行**（逐条对齐 `tools.py` 的 docstring） |
| `docs/MCP_SETUP.md` | 头部加模式表；`Available Tools` 章节说明改为"并集 26"；多 wiki 章节标注 6 个专属 + 2 个同名不同语义 |
| `docs/llmwikify-功能全景与缺口清单.md` | §2 换成正确解释（20 + 8 − 2 同名 = 26 并集，if/else 互斥） |

工具**名单**与**数量**（26 并集口径）不变 —— 改的只是"available when server runs"的措辞。

---

## 4. 待决项（产品决策，本轮不动）

| # | 项 | 现状 | 决策点 |
|---|---|---|---|
| **D1** | 多 wiki 模式 `wiki_search` 缺省走 `registry.cross_wiki_search`，与独立工具 `wiki_search_cross` **语义重叠** | `wiki_search` 返回裸结果列表；`wiki_search_cross` 返回 `{results, total_results, searched_wikis}` 且支持 `wiki_ids` 过滤 | 是否让 `wiki_search` 在多 wiki 模式下**只搜 default wiki**（与单 wiki 模式对齐），把跨 wiki 明确交给 `wiki_search_cross`？这会改变默认行为，**需你拍板** |
| **D2** | 多 wiki 模式 `wiki_search` **无 `backend` 参数**（qmd 语义后端不可选） | 单 wiki 模式有 | 是否补齐多 wiki 的 `backend` 透传？属能力扩展，非债 |
| **D3** | 单 wiki 模式 `wiki_search` 无 `wiki_id` 参数 | 设计如此 | 无需动 |

---

## 5. 复现

```bash
# 工具数（单 wiki / 多 wiki）
python -c "
import asyncio, tempfile, pathlib
from llmwikify.kernel import Wiki
from llmwikify.interfaces.mcp.adapter import MCPAdapter
from llmwikify.kernel.multi_wiki.registry import WikiRegistry
tmp = pathlib.Path(tempfile.mkdtemp()); w = Wiki(tmp); w.init()
print('single:', len(asyncio.run(MCPAdapter(w)._mcp.list_tools())))
reg = WikiRegistry({}); reg.register_wiki('w1', 'w1', tmp, is_default=True)
print('multi :', len(asyncio.run(MCPAdapter(reg)._mcp.list_tools())))
w.close()
"

# AST 扫描：每个注册函数体内是否有未装饰 / 未调用的局部 def
# 见 §1.3 的扫描口径
```

---

*核实于 2026-11-16 · 相关文档：`README.md` · `docs/MCP_SETUP.md` · `docs/llmwikify-功能全景与缺口清单.md`*
