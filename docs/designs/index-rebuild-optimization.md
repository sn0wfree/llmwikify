# index.md 全量重建优化（L1）

日期: 2026-11-03 · 分支: `feat/auto-doc-ingest`
上游: [`docs/designs/auto-doc-enrichment.md`](auto-doc-enrichment.md)（Track C 的已知限制 #4）

## 背景

`wiki.write_page()` 末尾调用 `_update_index_file()`，而后者**全量重建**
`wiki/index.md`：

```
遍历全部页
  ├─ 每页重新读文件 + 正则提取 summary   ← 内容没变也重算
  ├─ 每页 1 次 SQL 取 word_count
  ├─ 每页 1 次 SQL 取 inbound links（拉全部行再 len()）
  ├─ 每页 1 次 SQL 取 outbound links（拉全部行再 len()）
  └─ 每页 1 次 stat 判断 sink 文件是否存在
```

实测（`write_page` 总耗时里 99.6% 在这里）：

| 页数 | 单次 write_page | 其中 index 重建 |
|------|----------------|----------------|
| 400 | 360 ms | 359 ms |
| 1400 | ~1141 ms | ~1140 ms |

批量场景的浪费是**乘性**的：Track C 补 5 个链 = 5 次 `write_page` =
**5 次全量重建** = 400 页 2235 ms、1400 页 5.7 s。

## 实测收益

优化后（`mypy`/`ruff` 全绿，index.md 内容与逐页旧算法**逐字一致**）：

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 单次重建（1400 页，冷缓存） | 1141 ms | 766 ms | 1.5x |
| 单次重建（1400 页，缓存命中） | 1141 ms | **250 ms** | **4.6x** |
| 批量补 5 个链（400 页，走真实 write_page） | 2235 ms | **875 ms** | **2.6x** |
| 改 1 页后重建（1400 页） | 1141 ms | 250 ms | 4.6x |

热重建之所以快：批量改 5 个页时只有第 1 次需要重算全部摘要，之后 4 次
只有被改动的那个页摘要失效。

## 根因

三层，前两层可解：

| 层 | 问题 | 性质 |
|----|------|------|
| **L1** | 每次重建都重算**没变**的东西：summary 每页重读重提取；每页 4 次 SQL 换成 4 次全表查询 | 可解，本次做 |
| **L2** | 批量写页时**重复重建**：N 次写 = N 次全量重建 | 可解，需新 API，留待与 v0.41-dev 合并后 |
| **L3** | `index.md` 是分组结构化文本（按页面类型分组 + 统计），增量更新困难 | 约束，非缺陷 |

## 已有零件被浪费

`WikiIndex.count_inbound_for_pages()`（`kernel/storage/index.py:470`）**已经存在**，
一次查询统计多页的 inbound 数量。但 `_update_index_file` 用的是
`get_inbound_links()` —— 把全部行拉进内存再 `len()`。

outbound 缺一个对称的批量接口，本次补上。

## 方案（L1）

### 1. 批量查询

| 项 | 现状 | 改为 |
|----|------|------|
| word_count | 每页 1 次 `SELECT ... WHERE page_name = ?` | 1 次全表 `SELECT page_name, word_count FROM pages` |
| inbound | 每页 1 次 `get_inbound_links()`（拉全部行） | 1 次全表 `GROUP BY target_page` |
| outbound | 每页 1 次 `get_outbound_links()`（拉全部行） | 1 次全表 `GROUP BY source_page` |

三个查询都**不带参数**：页数与 wiki 同阶，全表聚合一次比逐页查快，且不受
SQLite 变量上限影响（`IN (...)` 形式在超大 wiki 上会撞上限——现代 SQLite
是 32766 个变量，虽比旧版的 999 宽裕得多，但仍是个隐患）。

已有的 `count_inbound_for_pages()` 用的是 `IN (...)`，本次**不动它**
（`analyzer.py:94` 在用），只新增无参数的全表版本。

### 2. summary 缓存

`_extract_page_summary()` 是最贵的单项（1400 页约 390 ms：读文件 + 正则）。
但**页面内容没变，summary 就没变**。

缓存放在 Wiki 实例上，键为页面名，值为 `(mtime, size, summary)`；
命中条件是 mtime 与 size 都相同。批量补链只改 1 个页 → 其余 1399 页
全部命中缓存。

缓存大小：1400 页 × 约 100 B ≈ 140 KB。

### 3. 明确不做的部分

- **sink 批量**：`_update_index_file` 每页调 `query_sink.get_info_for_page()`
  （每页一次 `Path.exists()`，400 页 50 ms，占 12%）。要批量化需改
  `query_sink.py`，而该文件与 v0.41-dev 有 80 行差异（path_codec），
  收益不足以换取冲突面。
- **L2 批量写页 API**：`_update_index_file` 还有 4 个调用点
  （`query.py:81/91/293`、`analyzer.py:551`），延迟 index 更新会改变
  「写完立刻读 index.md」的可观测行为，批量 API 只能给明确安全的调用方用。
  留待与 v0.41-dev 合并后一起做。

## 修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kernel/storage/index.py` | edit | 新增三个**无参数**全表查询：`count_inbound_all()` / `count_outbound_all()` / `word_counts_all()` |
| `kernel/wiki/mixins/io/page_io.py` | edit | `_update_index_file` 改批量查询 + summary 缓存（新增 `_cached_page_summary`） |
| `tests/test_index_rebuild_perf.py` | NEW | 性能护栏 + 缓存正确性 + 与逐页算法等价性（6 项） |
| `docs/designs/index-rebuild-optimization.md` | NEW | 本文档 |

## 正确性考量

| 风险 | 处理 |
|------|------|
| 内容变了但 mtime+size 相同 → 摘要陈旧 | 极罕见（需同尺寸改写且时间戳未变）；`index.md` 只是目录页摘要，不参与检索 |
| 缓存跨 wiki 串味 | 缓存是**实例级**（`self.__dict__`），不挂在类上 |
| 缓存无限增长 | 页数 = 缓存条目数，与 wiki 规模同阶；无淘汰策略（页面被删时条目残留，量级可忽略） |
| 全表聚合的内存占用 | 返回的字典大小与页数同阶（1400 页约 100 KB），与现有逐页结果集同量级 |

## 与 v0.41-dev 的冲突面

| 文件 | main / v0.41-dev | 差异 | 影响 |
|------|-----------------|------|------|
| `kernel/storage/index.py` | 665 / 667 行 | 10 行（全为 encoding 修复） | 新增方法**零冲突** |
| `kernel/wiki/mixins/io/page_io.py` | 489 / 503 行 | 111 行（path_codec + logical name） | `_update_index_file` 内部会冲突，但区域明确 |
| `kernel/storage/query_sink.py` | 810 / 820 行 | 80 行 | 本次**不改**它 |

## 测试用例

| # | 场景 | 期望 |
|---|------|------|
| 1 | 600 页重建（冷/热） | 冷 < 2s、热 < 1s，且热 ≤ 冷 |
| 2 | 批量查询与逐页查询一致 | inbound / outbound / word_count 数值相同 |
| 3 | 批量查询无参数 | 签名只有 `self`（不受 SQLite 变量上限影响） |
| 4 | 改一个页面后重建 | 该页摘要更新，其余页摘要不变 |
| 5 | 摘要缓存不跨实例串味 | 两个 wiki 实例各自独立 |
| 6 | index.md 与逐页旧算法等价 | 逐字一致（除时间戳） |
| 7 | 既有 index 相关测试 | 不回归 |

## 验证

```bash
ruff check src/llmwikify/ tests/
mypy src/llmwikify/kernel/wiki/mixins/io/page_io.py src/llmwikify/kernel/storage/index.py
pytest tests/test_index_rebuild_perf.py tests/test_v029_index_enhancement.py \
       tests/test_sink_flow.py tests/test_wiki_analyzer.py
python scripts/check_architecture.py
```
