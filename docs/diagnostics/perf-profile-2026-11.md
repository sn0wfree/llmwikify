# 性能 / 内存瓶颈实测 · 2026-11-06（已修正）

> 数据源：真实 wiki `CKbase-test-2026-10-22`（**1438 页 / 9.4 MB**）
> 方法：复制到临时目录（不碰原数据）→ **纯 `time.perf_counter` wall 计时** + `tracemalloc`
> 复现：会话 scratch `clean_timing.py` / `phase_timing.py` / `equiv_check.py`

## ⚠️ 修正说明

本文件初版用 **cProfile** 测量，把热点放大了 **3–50 倍**（`set.update` /
`dict.get` / `jieba.cut` 这类高频操作每次调用都被 profiler 追踪）。
初版数字（lint 118 s、build_index 489 s、detect_all 108 s）**不成立**。
下表为纯 wall 时间的修正值；初版的分段归因方向仍可参考，但**量级全部作废**。

## 1. 真实总表（wall time，无 profiler）

| 操作 | wall | 峰值内存 | 说明 |
|---|---:|---:|---|
| `build_index` 首次 | **47–77 s** | 112 MB | 词典生成 34 s + 索引构建 22–40 s |
| `build_index` 重复 | **~47 s** | — | 词典已跳过（见 §3），剩余为索引构建 |
| `generate_user_dict` 首次 | **34.2 s** | — | jieba 全库分词（1439 页 / 199 万 CJK 字符） |
| `generate_user_dict` 重复 | **0.12 s** | — | ✅ 内容指纹命中，已跳过 |
| `graph_analyze(force)` | **~13 s** | 71 MB | networkx greedy modularity |
| `search` 首次 | **~10.5 s** | 48.6 MB | jieba 词典 `marshal.load`（一次性） |
| `search` 第 2 次 | **0.06 s** | — | 稳态 |
| `lint(force=True)` | **2–4 s** | 23 MB | 冷文件缓存时可达 ~22 s（读 1438 个文件） |
| `lint` 热 | **0.06–0.3 s** | 1 MB | 指纹缓存 |
| `fix_wikilinks(dry_run)` | **0.6 s** | 2.5 MB | O(N²) 已修 ✓（历史 143.4 s） |

**内存不是瓶颈**：峰值 112 MB，常驻大头是 jieba 词典 ~48 MB。

## 2. 真实瓶颈排序

| 排名 | 项 | 耗时 | 根因 |
|---|---|---:|---|
| **1** | `build_index` | **47–77 s** | ① `generate_user_dict` 34 s（jieba 全库分词，**无缓存**→已修）② `build_index_from_files` 22–40 s，其中每页 `extract_tags` TF-IDF |
| **2** | `graph_analyze` | ~13 s | networkx `greedy_modularity_communities`（纯 Python） |
| **3** | `search` 首次 | ~10.5 s | jieba 词典一次性加载（之后 0.06 s） |
| 4 | `lint` 冷 | 2–4 s | 读 1438 个文件 + 各规则；`detect_all` 仅 ~1 s |
| — | `lint` 热 / `fix_wikilinks` | <1 s | 已优化 ✓ |

**结论修正**：`lint` **不是瓶颈**（2–4 s）。真正的瓶颈是 `build_index`。

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
| 1 | `build_index_from_files` 里的 `extract_tags` 缓存/可选 | `build_index` **~34 → ~15 s** | 词典已跳过，这是最大剩余项 |
| 2 | `graph_analyze` 换 Louvain 或加结果缓存 | 13 → ~2 s | |
| 3 | jieba 词典预热（启动后台 `initialize()`） | 首次 search 10.5 s → ~0 | |
| 4 | ~~`generate_user_dict` 指纹缓存 + 磁盘输入解耦~~ | ✅ **已完成** | 21 s → 0.2–0.4 s；乒乓已消除 |
| 5 | ~~`missing_cross_refs` 去滑窗~~ | ✅ **已完成** | 2×，但基数小 |

初版报告里「lint 118 s → 秒级」的目标**不成立**——lint 本来就只有 2–4 s。

## 6. 复现

```bash
python <scratch>/clean_timing.py     # build_index / lint 纯 wall 计时
python <scratch>/phase_timing.py     # 分段计时
python <scratch>/equiv_check.py lint out.json   # baseline vs 新 issue 比对
# 输入：C:\Users\1\Documents\CKbase-test-2026-10-22\CKbase（1438 页）
```
