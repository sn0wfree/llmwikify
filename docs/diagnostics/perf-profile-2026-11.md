# 性能 / 内存瓶颈实测 · 2026-11-06（已修正）

> 数据源：真实 wiki `CKbase-test-2026-10-22`（**1438 页 / 9.4 MB**）
> 方法：复制到临时目录（不碰原数据）→ **纯 `time.perf_counter` wall 计时**
> 复现：会话 scratch `clean_timing.py` / `phase_timing.py` / `equiv_check.py`
>
> **方法论教训**：`cProfile` 与 `tracemalloc` 都会把高频小操作放大数十倍
> （`set.update` / `jieba.initialize` / `marshal.load`）。本文件中凡标注
> 「无 profiler」的数字才是可信的；早期版本里套了 tracemalloc 的
> `wall_timing.py` 结果（search 10.5 s、lint 21.8 s、build_index 158 s）
> **同样作废**，已用不带 profiler 的重测覆盖。

## ⚠️ 修正说明

本文件初版用 **cProfile** 测量，把热点放大了 **3–50 倍**（`set.update` /
`dict.get` / `jieba.cut` 这类高频操作每次调用都被 profiler 追踪）。
初版数字（lint 118 s、build_index 489 s、detect_all 108 s）**不成立**。
下表为纯 wall 时间的修正值；初版的分段归因方向仍可参考，但**量级全部作废**。

## 1. 真实总表（wall time，无 profiler）

| 操作 | wall | 峰值内存 | 说明 |
|---|---:|---:|---|
| `build_index` 首次 | **~39 s** | 112 MB | 词典生成 ~21 s + 1 页重建（DB 已基本追平） |
| `build_index` 重复 | **~1.0 s** | — | ✅ 词典跳过 + 全部页面未变更（见 §3） |
| `generate_user_dict` 首次 | **21–34 s** | — | jieba 全库分词（1439 页 / 199 万 CJK 字符） |
| `generate_user_dict` 重复 | **0.2–0.4 s** | — | ✅ 内容指纹命中，已跳过 |
| `graph_analyze(force)` | **~1.7 s** | 71 MB | ✅ 换 networkx 内置 Louvain（见 §3.A4） |
| `search` 首次 | **0.44 s** | 48.6 MB | jieba `initialize()` 0.38 s（一次性；曾误报 10.5 s，见方法论说明） |
| `search` 第 2 次 | **0.05 s** | — | 稳态 |
| `lint(force=True)` | **2.0–2.7 s** | 23 MB | 含首次读 1438 个文件 |
| `lint` 热 | **0.06–0.3 s** | 1 MB | 指纹缓存 |
| `fix_wikilinks(dry_run)` | **0.6 s** | 2.5 MB | O(N²) 已修 ✓（历史 143.4 s） |

**优化前基线**（同一 wiki，纯 wall）：`build_index` 46.9–60.6 s、`generate_user_dict` 34 s、
`build_index_from_files` 26.8 s（其中 `_segment`/`jieba.cut` 8.9 s = 33%）。

**内存不是瓶颈**：峰值 112 MB，常驻大头是 jieba 词典 ~48 MB。

## 2. 真实瓶颈排序（优化后现状）

| 排名 | 项 | 耗时 | 说明 |
|---|---|---:|---|
| **1** | `generate_user_dict` 首次 | 21–34 s | jieba 全库分词；**重复调用已跳过（0.2–0.4 s）** |
| **2** | `build_index` 首次 | ~39 s | 词典首次 + 1 页重建；**重复调用 ~1 s** |
| **3** | `search` 首次 | 0.44 s | jieba `initialize()` 一次性；之后 0.05 s |
| 4 | `graph_analyze(force)` | 1.7–2.1 s | 已换 Louvain |
| 5 | `lint` 冷 / 热 | 2.7 s / 0.13 s | `detect_all` 仅 ~0.85 s |
| — | `fix_wikilinks` | 0.6 s | 历史 143.4 s，已修 ✓ |

**结论**：优化后已无秒级以上瓶颈。最大的单项是**首次** `generate_user_dict`
（21–34 s，只在内容变化时发生）；重复路径全部在 1–3 s 内。

## 3. 本轮落地的两项优化

### A. `generate_user_dict` 内容指纹缓存 ✅ 已验证

**改动**（`kernel/storage/jieba_dict_gen.py`）：
- 新增 `_content_fingerprint(pages)` — SHA-256 over **排序后**的页面正文
  （排序使指纹与 `SELECT` 返回顺序无关；两趟生成都是 Counter 聚合，
  同一内容多重集必然产出同一词典）
- `generate_user_dict` 先算指纹，与 `.wiki/jieba.meta.json` 的
  `content_fingerprint` 比对；命中且产物文件仍在 → **整段跳过**
- 页面只从 DB 读一次（原先 fast/slow 各读一次），拆出
  `_generate_fast_from_pages` / `_generate_slow_from_pages` 复用
- **返回结构不变**（`{"fast","slow","page_count"}`），不破坏调用方与测试

**实测**：

| | 之前 | 之后 |
|---|---:|---:|
| `generate_user_dict` 首次 | 34.23 s | 34.23 s（仍需算一次） |
| `generate_user_dict` 重复 | 34.23 s（每次全量） | **0.12 s（310×）** |
| `build_index` 首次 → 重复 | 76.9 → 60 s | 76.9 → **47.2 s** |

**注意（初版的错误归因）**：初版说「`build_index` 先写 `index.md` 导致指纹变」
——查证后**不成立**（该 wiki 磁盘上根本没有 `index.md` / `log.md`）。真正原因是
**DB 落后于磁盘**（磁盘 1442 个 md，DB 只有 1439 条），`build_index_from_files`
把缺的页补进 DB → `pages_fts` 内容变 → 指纹变。这是一次性的（DB 追平后稳定）。

### A2. 词典输入改从磁盘读，与 DB 解耦 ✅ 已验证

**改动**：`generate_user_dict` 改用 `_load_wiki_contents(wiki_root, db_path)`
——优先读 `wiki_root.rglob("*.md")`（`is_path_excluded` 过滤，与
`build_index_from_files` **同一文件集**），无 md 文件时回退 DB（测试 fixture
只 seed 索引不写文件）。

**收益**：
1. 指纹不再随 DB 重建而移动 → `build_index` 连续调用从第 2 次起稳定跳过
2. **消除乒乓**：CLI `llmwikify dict update` 与 `build_index` 不再互相触发重算
3. `page_count` 改为 `len(pages)`（实际喂给词典的页数），生产环境 = 磁盘文件数

**实测**（同一份 1438 页 wiki）：

| 调用 | 词典耗时 |
|---|---:|
| `build_index` #1 | 21.47 s REGEN |
| `build_index` #2 | **0.36 s SKIP** |
| `build_index` #3 | **0.20 s SKIP** |
| `dict update`（build 之后） | **0.39 s SKIP** |
| `dict update` 再来一次 | **0.43 s SKIP** |

重复 `build_index` 净省 **~21 s/次**。

### A3. `build_index_from_files` 未变更页整页跳过 ✅ 已验证

**改动**（`kernel/storage/index.py`）：原先 `DELETE FROM pages_fts/page_links/pages`
全表清空后逐页重建（每页 = jieba 分词 + 链接正则 + 多条 SQL）。改为：

1. 先 `SELECT page_name, content FROM pages_fts` 读出现有内容（一次查询）
2. 逐文件比对：内容一致 → **整页跳过**（不重分词、不重解析链接、不写 SQL）
3. 内容变了 / 新文件 → `upsert_page`
4. 磁盘上已消失的页 → 从三张表删除（原全表 DELETE 的清理语义保留）
5. 单次 `_commit()`

**语义等价验证**：同一份 wiki 上，基线全量重建 vs 新增量重建的三张表
**逐行完全一致**——`pages_fts` 1440 行、`page_links` 16869 行、`pages` 1440 行；
删除一个文件后两边同样降到 1439 / 15397 / 1439。

**实测**：

| 场景 | 基线（全量） | 新（增量） | 加速 |
|---|---:|---:|---:|
| `build_index_from_files` 1 页变更 | 48.34 s | **1.00 s** | 48× |
| 全部未变更 | 48.89 s | **0.66 s** | 74× |
| 删除 1 个文件 | 49.18 s | **0.72 s** | 68× |
| **`build_index` 端到端 #2** | **46.9–60.6 s** | **1.05 s** | **~50×** |
| **`build_index` 端到端 #3** | — | **1.01 s** | — |

> 注：`extract_tags` 只存在于 `jieba_dict_gen`（已由 §3.A 指纹缓存覆盖），
> 初版报告把它归到 `upsert_page` 是错的。`upsert_page` 里的真实热点是
> `_segment()` → `jieba.cut`，占 `build_index_from_files` 的 33%（8.9 s / 26.8 s）。

### A4. `graph_analyze` 社区检测换 networkx 内置 Louvain ✅ 已验证

**改动**（`kernel/graph/export.py`）：

- `detect_communities` 的默认路径（`algorithm="leiden"` 实际落到这里——
  代码里**没有 Leiden 实现**，只有 louvain / else 两个分支）原先依赖
  `python-louvain`，未安装时回退到 networkx 的 `greedy_modularity_communities`
- 改为优先用 **networkx 内置 `louvain_communities`**（3.0+ 自带，无需额外依赖），
  `seed=0` 保证可复现；仅在 networkx < 3 时才回退 greedy
- `_compute_modularity` 同样补上 networkx 实现——原先 `python-louvain` 缺失时
  **直接返回 0.0**，modularity 一直是假的
- `algorithm="louvain"` 分支保留（装了 `python-louvain` 时行为不变）

**实测**（同一 1438 页 wiki，`force=True`）：

| | greedy（原） | networkx Louvain |
|---|---:|---:|
| `graph_analyze(force)` | 4.89 s | **1.66 s**（2.9×） |

返回结构不变：`num_communities=17`、`modularity=0.5971`、
`stats={nodes:1446, edges:20232}`、`suggestions` 7 条。

> 诚实说明：换算法会改变社区划分（Louvain 与 greedy 的最优解不同），
> `surprise_score` 的「跨社区 +1」维度结果会略有差异。测试只断言
> `num_communities >= 1` 与 `0 <= modularity <= 1`，不受影响。

### B. `missing_cross_refs` 首词过滤 ✅ 已验证（收益有限）

**改动**（`kernel/wiki/lint/rules/missing_cross_refs.py`）：
外层循环从「每页 × `MAX_TITLE_WORDS` 个 n-gram 滑窗」改为「只在
**首词属于索引键首词集** 的位置展开 n-gram」。语义**严格等价**——
被跳过位置的 gram 不可能是索引键，`.get()` 本来就会返回空。

**实测**：`detect_all` 1.02–1.92 s → **0.85 s**（约 2×）。
**语义等价验证**：baseline 与新代码在同一份 wiki 上 `lint(force=True)`
产出的 12 条 issue **逐条完全一致**。

**但要诚实**：`detect_all` 本来就只占 `lint` 的 ~1 s，所以这项优化的
绝对收益很小（lint 总耗时 2–4 s 里的零点几秒）。保留它是因为算法更干净、
且在更大 wiki 上会按比例放大。

## 4. 语义等价与测试

| 检查 | 结果 |
|---|---|
| `lint` issue 列表 baseline vs 新 | **12 条逐条一致** ✅ |
| `test_jieba_dict_gen` + `test_multi_wiki_dict` + `test_perf_batch2` | 23 passed ✅ |
| `test_lint_missing_cross_refs` + `test_lint_rules_behavior` + `test_lint_engine` + `test_index_rebuild_perf` | 57 passed ✅ |
| ruff / `check_architecture.py` | 全过，0 violation / 0 peer / 0 broken import ✅ |

## 5. 后续建议（按真实 ROI 重排）

| # | 改动 | 预期 | 说明 |
|---|---|---|---|
| 1 | ~~`build_index_from_files` 未变更页跳过~~ | ✅ **已完成** | `build_index` 重复 **~50 → 1 s** |
| 2 | ~~`generate_user_dict` 指纹缓存 + 磁盘输入解耦~~ | ✅ **已完成** | 21 s → 0.2–0.4 s；乒乓已消除 |
| 3 | ~~`missing_cross_refs` 去滑窗~~ | ✅ **已完成** | 2×，但基数小 |
| 4 | ~~`graph_analyze` 换 Louvain~~ | ✅ **已完成** | 4.89 s → 1.66 s（2.9×） |
| 5 | ~~jieba 词典预热~~ | ⛔ **不需要** | 首次 search 真实仅 **0.44 s**（原报 10.5 s 是 tracemalloc 放大） |

**累计效果**（同一 1438 页 wiki，纯 wall、无 profiler）：

| 指标 | 优化前 | 优化后 |
|---|---:|---:|
| `build_index` 重复 | 46.9–60.6 s | **~1.0 s** |
| `build_index_from_files` | 26.8–49 s | **0.66–1.0 s** |
| `generate_user_dict` 重复 | 21–34 s | **0.2–0.4 s** |
| `graph_analyze(force)` | 4.89 s | **1.66 s** |
| `detect_all` | 1.02–1.92 s | **0.85 s** |
| `search` 首次 | 0.44 s | 0.44 s（无需优化） |

初版报告里「lint 118 s → 秒级」的目标**不成立**——lint 本来就只有 2–4 s。

## 6. 复现

```bash
python <scratch>/clean_timing.py     # build_index / lint 纯 wall 计时
python <scratch>/phase_timing.py     # 分段计时
python <scratch>/equiv_check.py lint out.json   # baseline vs 新 issue 比对
# 输入：C:\Users\1\Documents\CKbase-test-2026-10-22\CKbase（1438 页）
```
