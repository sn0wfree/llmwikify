# 性能 / 内存瓶颈实测 · 2026-11-06

> 数据源：真实 wiki `CKbase-test-2026-10-22`（**1438 页 / 9.4 MB**，与
> `lint-performance-2026-10-23.md` 同一份数据）
> 方法：复制到临时目录（不碰原数据）→ `cProfile` + `tracemalloc` 逐操作测量
> 复现：会话 scratch `profile_wiki.py`

## 1. 总表

| 操作 | wall | 峰值内存 | 主因 |
|---|---:|---:|---|
| **`build_index(auto_export=False)`** | **489.4 s** | **115.5 MB** | jieba 分词 ≈97% |
| **`lint(mode=check, force=True)` 冷** | **117.9 s** | 22.9 MB | `missing_cross_refs` 108.8 s（92%） |
| `graph_analyze(force=True)` | 48.7 s | 76.6 MB | networkx greedy modularity 33.7 s |
| `search(...)` 首次 | 15.3 s | 48.6 MB | jieba 词典 `marshal.load` 14.8 s（**一次性**） |
| `search(...)` 第 2/3 次 | **0.03 s** | — | 稳态正常 |
| `lint` 热（缓存命中） | 1.6–2.5 s | 1.0 MB | 指纹缓存生效 ✓ |
| `fix_wikilinks(dry_run=True)` | 1.0 s | 2.6 MB | O(N²) 已修 ✓（历史 143.4 s） |

**内存不是瓶颈**：峰值 115.5 MB，常驻大头是 jieba 词典约 48 MB（一次性）。
瓶颈全在 CPU。

## 2. 瓶颈 #1 — `build_index` 489 s（最大）

分解（cProfile cumulative）：

```
page_io.build_index                          489.4 s
├─ jieba_dict_gen.generate_user_dict         310.4 s  (63%)
│   └─ generate_fast_dict                    301.2 s
│       └─ jieba.cut  ×8,462,862            392.6 s*  (__cut_DAG 286.5 s)
└─ index.build_index_from_files              165.5 s  (34%)
    └─ jieba.analyse.extract_tags ×1,439     163.5 s
```
\* 含与上层重叠的计时。

**两个根因：**

1. **`generate_user_dict` 无任何缓存**（`jieba_dict_gen.py` 只有文件 `exists()`
   检查，无 mtime / 内容指纹跳过）。`page_io.build_index()` **无条件**调用它
   （`page_io.py:225`）→ 每次重建索引都全库重新分词 310 s。
2. **`extract_tags` 每页跑一次 TF-IDF**（1439 次 × 113 ms）。

**SQLite / IO 不是问题**：`upsert_page` ×1440 仅 160 s，且已被历史优化
（批量 commit）覆盖；真正吃时间的是分词。

**影响面**：`build_index` 被 CLI `build-index`、MCP `wiki_build_index`、
skill action、`WikiRegistry.reload_wiki()` 调用 —— agent 调一次
`wiki_build_index` 会阻塞 **8 分钟**。

## 3. 瓶颈 #2 — `lint` 冷 118 s

```
analyzer.lint                                117.9 s
├─ _run_all_rules                            113.6 s
│   └─ lint.run_all                          113.6 s
│       └─ missing_cross_refs.detect_all     108.8 s  (92%)
│           self time 51.2 s
│           set.update  ×5,195,578   24.9 s
│           dict.get   ×5,257,215   17.7 s
│           str.join   ×2,684,518   11.2 s
```

`missing_cross_refs.py:148-159` 的 P1 倒排索引**确实实现了**，但外层仍是
**每页 n-gram 滑窗**（`for n in 1..MAX_TITLE_WORDS` × `for i in words-n`）：

- 复杂度是 **O(总词数 × MAX_TITLE_WORDS)**，不是 O(页²)
- 1438 页 / 9.4 MB 正文 → 520 万次 set.update + 526 万次 dict.get

`lint-performance-2026-10-23.md` 的目标「150 s → 秒级」**未达成**（实测 108 s）。
缓存（P2）是有效的：二次调用 1.6 s。

## 4. 瓶颈 #3 — `graph_analyze` 48.7 s

```
graph.analyze                                 48.7 s
└─ _analyze_communities                       38.3 s
    └─ export.detect_communities              38.2 s
        └─ networkx greedy_modularity_communities  33.7 s
```

1438 节点对 networkx 的纯 Python 贪心模块度算法就是 34 s；峰值内存 76.6 MB
是 networkx 图对象。`force=True` 下每次全算。

## 5. 内存

| 场景 | 峰值 | 说明 |
|---|---:|---|
| `build_index` | 115.5 MB | 分词中间结构 + 批量写 |
| `graph_analyze` | 76.6 MB | networkx 图 |
| `search` 首次 | 48.6 MB | **jieba 词典常驻**（之后不释放） |
| `lint` 冷 | 22.9 MB | 正文 dict + 倒排索引 |
| `lint` 热 | 1.0 MB | 缓存命中 |

**结论：内存无压力**，1 GB 进程绰绰有余。唯一常驻成本是 jieba 词典 ~48 MB。

## 6. 已修好的（对照历史文档）

| 项 | 历史 | 现测 | 状态 |
|---|---:|---:|---|
| `fix_wikilinks` 全树 rglob | 143.4 s | 1.0 s | ✅ stem 索引 |
| `upsert_page` 每页 commit | 37.0 s → 11.2 s | 含在 165 s 内 | ✅ 批量 commit |
| `lint` 二次调用 | 全量 | 1.6 s | ✅ 指纹缓存 |
| `missing_cross_ref` | 150 s → 目标秒级 | **108 s** | ❌ **未达成** |

## 7. 优化建议（按 ROI）

| # | 改动 | 预期 | 风险 |
|---|---|---|---|
| 1 | `generate_user_dict` 加内容指纹缓存（wiki 内容 hash + mtime，未变则跳过） | build_index **489 → ~180 s** | 低 |
| 2 | `extract_tags` 结果随 `upsert_page` 落库复用，或改异步/可选 | 再 → **~20 s**（累计 24×） | 中 |
| 3 | `missing_cross_refs` 去掉 n-gram 滑窗，改为倒排索引直接查（候选词已在 index 中） | lint 冷 **118 → 目标 <5 s** | 中（需保语义） |
| 4 | `graph_analyze` 换 Louvain（`networkx.community.louvain_communities`）或加结果缓存 | 49 → ~5 s | 低 |
| 5 | jieba 词典预热（进程启动后台 `initialize()`），或 `search` 首调前显式 warmup | 首次 15 s → ~0 | 低 |

**优先级**：1、3 是纯收益且直接对应两个最大数字；2 收益最大但动写路径；
4、5 是体验优化。

## 8. 复现

```bash
python <scratch>/profile_wiki.py    # cProfile + tracemalloc，6 个操作
# 输入：C:\Users\1\Documents\CKbase-test-2026-10-22\CKbase（1438 页）
# 输出：profile_out.txt
```
