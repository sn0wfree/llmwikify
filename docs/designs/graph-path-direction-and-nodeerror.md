# graph-query path：方向参数 + 节点不存在的崩溃修复

日期: 2026-11-03 · 分支: `feat/auto-doc-ingest`

## 背景

排查 graph 相关问题时确认了两处缺陷（另有两处是「能力缺失」与「语义瑕疵」，
不在本次范围，见文末）。

## 缺陷 1：`get_path` 只捕获 `NetworkXNoPath`，节点不存在时崩溃

`kernel/wiki/engines/relation.py:573` 只捕获 `nx.NetworkXNoPath`。而
`nx.shortest_path(G, source, target)` 在**源或目标不在图中**时抛的是
`nx.NodeNotFound`——未捕获，直接冒泡到 CLI 崩溃。

实测：

```
get_path("concepts/DoesNotExist", "concepts/Beta")
  → NodeNotFound: Source concepts/DoesNotExist is not in G
```

函数签名返回 `dict | None`（`None` 表示「无路径」），崩溃显然违背契约。

## 缺陷 2：`path` 有向求解，反向查不到

`_build_networkx_graph()` 返回 `MultiDiGraph`，`nx.shortest_path` 默认沿边
方向求解。实测（A→B→C 两条边）：

```
path(A → C): ['concepts/Alpha', 'concepts/Beta', 'concepts/Gamma']   ✓
path(C → A): None                                                    ← 反向查不到
neighbors(C, both): 1 条                                             ← 双向能查到
```

CLI 的 `path` 子命令（`graph_query.py:50`）没有方向参数，而 `neighbors`
子命令有（`direction: in|out|both`）。用户想问「C 到 A 通不通」时只能换
用 `neighbors`，拿到的还不是路径。

## 方案

### `get_path` 加 `direction` 参数

```python
def get_path(self, source, target, max_length=5, direction="out") -> dict | None:
```

| 值 | 语义 | 实现 |
|----|------|------|
| `"out"`（默认） | 沿边方向（现状） | `shortest_path(G, source, target)` |
| `"both"` | 无向求解 | `G.to_undirected()` 后求解 |

默认 `"out"` 保持现有调用方行为不变。

**边明细要能反向匹配**：无向图里找到的路径 `C→B→A` 对应的边是
`A→B`、`B→C`。原 SQL `WHERE source=? AND target=?` 按路径顺序查会查不到，
改为双向匹配，并让 `edges` 的 `source`/`target` 反映**真实边方向**（不是
路径顺序），这样打印出来的箭头是准确的。

### 捕获 `NodeNotFound`

`except (nx.NetworkXNoPath, nx.NodeNotFound): return None`——与「无路径」
同语义（图里没有这个节点，自然也没有路径），且不改变返回类型。

### CLI

`graph-query path <A> <B> [--direction out|both]`，默认 `out`。
`--direction` 是全局选项，`neighbors` / `stats` / `context` 忽略它。

## 修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kernel/wiki/engines/relation.py` | edit | `get_path` 加 `direction`；捕获 `NodeNotFound`；边明细双向匹配 |
| `interfaces/cli/commands/graph_query.py` | edit | `path` 加 `--direction` |
| `tests/test_graph_path.py` | NEW | 方向语义 + 崩溃修复测试 |

## 测试用例

| # | 场景 | 期望 |
|---|------|------|
| 1 | 节点不存在 | 返回 `None`，不抛异常 |
| 2 | 正向有向路径 | 返回路径（与改动前一致） |
| 3 | 反向 + `direction="out"` | 返回 `None` |
| 4 | 反向 + `direction="both"` | 返回路径 |
| 5 | `both` 模式的边明细 | `source`/`target` 是真实边方向，与 `get_neighbors` 一致 |
| 6 | 默认参数 | 与改动前行为一致（`direction` 缺省 = `"out"`） |
| 7 | `max_length` 仍然生效 | 超长路径返回 `None` |

## 未处理（本次不做）

- **缺 `graph write` 子命令**：关系写入目前只有 `ingest --self-create`、
  `enrich` 与 agent tool 三条路（均汇到 `wiki.write_relations()`）。
  补一个 CLI 子命令属于新功能，需单独设计（参数、去重策略、审计日志）。
- **`add_relations` 返回值语义**：返回的是「处理成功的条数」而非「新增
  条数」（重复边也计入）。数据正确性不受影响，但调用方容易误读。
