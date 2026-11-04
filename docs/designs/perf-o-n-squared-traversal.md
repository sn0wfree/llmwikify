# 性能：消除 O(N²) 遍历 + 建索引事务与 PRAGMA

日期: 2026-11-03 · 分支: `feat/auto-doc-ingest`
上游: [`docs/designs/auto-doc-enrichment.md`](auto-doc-enrichment.md)（Track C 的已知限制）

## 背景

对 1400 页的 wiki 做性能扫描（`build_index` / `lint` / `fix_wikilinks` /
`write_relations` 等关键路径逐个实测 + cProfile），发现四处热点。前两处的
共同根因是：**全树遍历被放在了「每链接 / 每实体」的粒度上**，于是代价是
页数 × 链接数（或实体数）的三重放大。

## #1 `fix_wikilinks`：每个坏链一次全树遍历（143.4 s）

### 现象

`kernel/wiki/mixins/io/link.py:71` 对每条裸 wikilink 调用
`_find_wiki_page_paths(target)`，其实现是
`self.wiki_dir.rglob(f"{name}.md")`（`kernel/wiki/wiki.py:403`）——
**每条链一次全树扫描**。

实测（1400 页、11200 条链）：`fix_wikilinks(dry_run=True)` = **143.4 s**；
N=400 时 30.4 s。仅取 30 页在 N=1400 的树上就要 3.08 s（240 次 rglob，
每次 12.8 ms）。

### 修法

入口处一次遍历建立 `stem → [paths]` 索引，后续查询走内存字典。

**大小写语义必须保持各平台原样**：`Path.rglob` 在 Windows 上大小写不敏感、
在 POSIX 上敏感。用 `os.path.normcase`（Windows 转小写、POSIX 原样）作为
字典键，做到与 `rglob(f"{name}.md")` 在两个平台上分别等价。

索引的页面集合也必须与 `rglob("*.md")` 一致（含 `.sink/`、`index.md`、
`log.md`），否则同名页的匹配结果会变。

## #2 `resolve_entity`：每个实体一次全树遍历（18.0 s）

### 现象

`kernel/wiki/engines/relation.py:259` 的 `resolve_entity()` 第一步是
`self._get_wiki_pages()`（同文件 `:133-148`，一次 `rglob("*.md")`）。
而 `add_relation()` 调用它 **2 次**（source 与 target），`add_relations()`
再逐条循环 —— M 条 relation = **2M 次全树遍历**。

实测（1400 页、60 条 relation）：`add_relations(60)` = **18.0 s**
（300 ms/条）；`resolve_entity` 单次 114 ms，其中 **112 ms 全在 rglob**
（模糊匹配本身只要 2 ms）。

### 修法

`add_relations()` 开头取一次页面清单，逐条传给 `add_relation()` →
`resolve_entity()`。

**不做跨调用的页面清单缓存**：ingest 流程会先写新页再写关系，若缓存了
清单，刚写入的页面将不可见。批次内复用是安全的（同一批不写页面）。

`add_relation()` / `resolve_entity()` 新增可选参数，向后兼容。

## #3 `upsert_page` 每页一次 commit（19.0 s）

### 现象

`kernel/storage/index.py:322` 的 `self._commit()` 被 `build_index_from_files()`
逐页调用 1400 次。Windows 上每次 commit 要 fsync，约 13 ms。

### 修法

`upsert_page()` 增加 `commit: bool = True` 参数；`build_index_from_files()`
用 `commit=False`，循环结束后提交一次。

Python 的 `sqlite3` 默认隐式事务：不做中间 commit 时，写入累积在同一个
事务里，最终一次提交 —— 语义不变（原本每次 commit 也只是把已写入的数据落盘），
只是把 1400 次 fsync 变成 1 次。

实测：37.0 s → 11.2 s（3.3x）。

## #4 `WikiIndex` 没有设置任何 PRAGMA（1.3x）

### 现象

`kernel/storage/index.py:59-63` 建立连接时只设了 `check_same_thread`，
实测 PRAGMA 是：

```
journal_mode = delete     ← 最慢（无 WAL）
synchronous = 2 (FULL)    ← 最保守（每次事务都 fsync）
cache_size  = -2000
```

而 `foundation/db.py:63` 的 `connect()` 已经提供
`wal=True, synchronous="NORMAL"` 的统一工厂 —— 主数据库早就是 WAL，
只有 wiki 索引没有。

### 修法

连接建立时设置 `journal_mode=WAL` / `synchronous=NORMAL` /
`busy_timeout` / `cache_size`，与 `foundation/db.py` 对齐。

实测：26.1 s → 19.9 s（1.3x）；与 #3 叠加后 → 11.0 s（2.4x）。

## 实测收益

1400 页 wiki（11200 条 wikilink）：

| 场景 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| `fix_wikilinks(dry_run=True)` | 143 400 ms | **516 ms** | **278x** |
| `add_relations(60)` | 18 000 ms | **140 ms** | **129x** |
| `build_index` | 26 000 ms | 18 300 ms | 1.4x |
| `lint(check)`（含缓存影响） | 8 000 ms | 5 700 ms | 1.4x |

PRAGMA 实测生效：`journal_mode=wal`、`synchronous=1`（NORMAL）。

## 修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kernel/wiki/mixins/io/link.py` | edit | `fix_wikilinks` 入口建 `stem → paths` 索引 |
| `kernel/wiki/engines/relation.py` | edit | `add_relations` 复用页面清单；`add_relation` / `resolve_entity` 加可选参数 |
| `kernel/storage/index.py` | edit | `upsert_page(commit=False)`；`build_index_from_files` 批量提交；连接加 PRAGMA |
| `tests/test_perf_no_n_squared.py` | NEW | 性能护栏 + 行为等价性测试 |
| `docs/designs/perf-o-n-squared-traversal.md` | NEW | 本文档 |

## 正确性考量

| 风险 | 处理 |
|------|------|
| `stem` 索引与 `rglob` 的大小写语义不一致 | 用 `os.path.normcase`，与各平台 `rglob` 行为分别等价 |
| 索引页面集合与 `rglob("*.md")` 不一致 | 索引同样用 `rglob("*.md")` 构建（含 `.sink/`、`index.md`、`log.md`） |
| 批量提交改变崩溃时的数据可见性 | 原本也是逐页提交（部分可见），现在是一次提交（全有或全无）—— 更安全 |
| 页面清单跨调用缓存导致 ingest 新页不可见 | 不做跨调用缓存，只在 `add_relations` 批次内复用 |
| WAL 模式改变 db 文件格式 | `foundation/db.py` 的主库早已是 WAL，wiki 索引对齐即可；SQLite 两种模式可互读 |

## 与 v0.41-dev 的冲突面

| 文件 | main / v0.41-dev | 差异 | 影响 |
|------|-----------------|------|------|
| `kernel/storage/index.py` | 665 / 667 行 | 10 行（全为 encoding 修复） | 改动**零冲突** |
| `kernel/wiki/engines/relation.py` | — | 待确认 | 需核对 |
| `kernel/wiki/mixins/io/link.py` | — | 待确认 | 需核对 |
| `kernel/wiki/wiki.py` | — | 待确认 | 本次**不改**它 |

## 测试用例

| # | 场景 | 期望 |
|---|------|------|
| 1 | 400 页 + 多条坏链的 `fix_wikilinks` | < 10 s（护栏） |
| 2 | stem 索引与逐名 `rglob` 返回同一组路径 | 完全一致 |
| 3 | stem 索引的大小写规则与各平台 `rglob` 一致 | Windows 不敏感 / POSIX 敏感 |
| 4 | 同名页存在时的歧义判定 | 报 ambiguous，不擅自选 |
| 5 | 唯一目标的裸链被补上目录前缀 | `[[concepts/Foo]]` |
| 6 | `add_relations` 与逐条 `add_relation` 结果一致 | relations 表逐行相同 |
| 7 | `resolve_entity` 传入预取页面清单与重新遍历同解 | 相同 |
| 8 | `add_relations` 批量 | 60 条 < 3 s（护栏） |
| 9 | `upsert_page(commit=False)` 的写入在提交后可见 | 提交后计数正确 |
| 10 | 建索引后的索引内容正确 | 页数正确、FTS 可检索 |
| 11 | PRAGMA 生效 | `journal_mode=wal`、`synchronous=1` |
| 12 | 既有 index / relation / link 测试 | 不回归 |

## 第二批：剩余五项

第一批消除了两处三重放大与两处建索引开销。剩下的五处都是「做了不该做的
重复工作」，逐项修复。

### #5 jieba 词典每次全量重算（19.3 s）

`kernel/storage/jieba_dict_gen.py:148` 的 `generate_fast_dict()` 对**每页全文**
做 `jieba.cut` 与 `jieba.analyse.extract_tags`（TF-IDF 关键词提取，会为每个
候选词触发 `jieba.calc`）。实测 1400 页里 `jieba.calc` 被调用 4.2 万次、
耗时 21.3 s。

**关键事实**：实测 1400 页中**含 CJK 的页是 0**。中文分词词典对纯英文内容
没有任何贡献，却让每次 `build_index` 多付 19 秒。

修法：只对含 CJK 的页做分词与关键词提取。中文 wiki 的行为完全不变
（中文页仍全量处理）。

### #6 lint 走 14 遍全树（4.5 s）

`LintEngine.run_all()` 只让 `CrossPageRule` 共享页面数据；6 条逐页型 `Rule`
各自调 `rule.run(self.wiki)`，于是各自遍历全部页并 `read_text` —— 8400 次
重复读文件。

修法：`Rule` 也接受预加载的 `{name: content}`，`run_all` 加载一次给两类规则
共用。逐页顺序与页集合保持不变（两者都基于 `wiki._wiki_pages()`，排除
`Query:` 前缀）。

### #7 `export_json` N+1 查询（0.5 s）

`kernel/storage/index.py` 的 `export_json()` 对每个有链接的页调一次
`get_outbound_links()` / `get_inbound_links()` —— 1400 页发出 **2804 条 SQL**。

修法：一次取全部 `page_links`，在内存里按 `source_page` / `target_page` 分组，
返回结构与逐页查询一致。

### #8 `QuerySink`：无批量接口 + 重建时 O(N²)（1.0 s + 0.27 s）

- `get_info_for_page()` 逐页调用（每次 `exists()` + `read_text()` + 正则），
  `_update_index_file` 会对每一页调一次 —— 1400 次调用，1.02 s。
- `_rebuild_sink_file()` 对内容存储里的**每个 hash** 都在整篇原文上
  `re.search` 找日期 —— O(条目数 × 原文长度)。实测 200 条 4 ms、
  800 条 112 ms、1600 条 267 ms（4 倍条目 → 67 倍时间）。

修法：加 `get_info_for_pages()` 批量接口（一次列目录 + 只读有 sink 的页）；
日期改为**一次扫描**原文解析出 `hash → date` 映射。

### #9 `RedundancyRule` O(N²) 且重复 `.lower()`（0.41 s）

`kernel/wiki/lint/rules/redundancy.py:37` 在双重循环里每次重新
`name1.lower()` / `name2.lower()`。实测 N=400 → 0.062 s、N=1400 → 0.407 s
（3.5 倍页数 → 6.6 倍时间）。

修法：循环外预计算小写列表。

## 第二批实测收益

同一 1400 页 wiki（8402 条 wikilink），改动前后对照：

| 场景 | 改动前 | 改动后 | 提升 |
|------|--------|--------|------|
| `build_index`（纯英文 wiki） | 12 218 ms | **3 672 ms** | **3.3x** |
| `lint`（首次，force） | 4 719 ms | **3 828 ms** | 1.2x |
| `export_index` | 94 ms | **15 ms** | **6x** |
| `RedundancyRule` | 62 ms | **47 ms** | 1.3x |
| `_update_index_file` | 406 ms | 406 ms | 持平 |

`build_index` 的 3.3x 来自跳过纯英文内容的分词——原实测 1400 页中
**含 CJK 的页是 0**，中文分词词典对它们没有任何贡献。
`_update_index_file` 持平是因为该 wiki 没有 sink 文件，批量接口的收益
（省去每页一次 `exists()`）只在有 sink 时体现。

## 第二批的修改清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `kernel/storage/jieba_dict_gen.py` | edit | #5 只对含 CJK 的页分词（新增 `_has_cjk`） |
| `kernel/wiki/lint/__init__.py` | edit | #6 `_load_pages` 上提到 `Rule`；`Rule.run` 支持共享页面；`run_all` 共享加载 + 失败回退 |
| `kernel/wiki/lint/rules/dated_claims.py` | edit | #6 签名接受 `pages` 并传给基类 |
| `kernel/wiki/lint/rules/knowledge_gaps.py` | edit | #6 签名接受 `pages`（自己扫，忽略） |
| `kernel/wiki/lint/rules/query_page_overlap.py` | edit | #6 签名接受 `pages`（按 stem 扫，忽略） |
| `kernel/wiki/lint/rules/redundancy.py` | edit | #6/#9 签名接受 `pages`；#9 预计算小写列表 |
| `kernel/storage/index.py` | edit | #7 新增 `get_all_links()`；`export_json` 内存分组 |
| `kernel/storage/query_sink.py` | edit | #8 新增 `get_info_for_pages()`；`_rebuild_sink_file` 日期一次解析 |
| `kernel/wiki/mixins/io/page_io.py` | edit | #8 用批量 sink 接口（省每页一次 stat） |
| `tests/test_perf_batch2.py` | NEW | 第二批等价性测试（9 项） |

## 第二批的测试用例

| # | 场景 | 期望 |
|---|------|------|
| 1 | 纯英文 wiki 生成词典 | 不做分词，词典为空，耗时大幅下降 |
| 2 | 含中文的 wiki 生成词典 | 中文词条仍被收录（与原行为一致） |
| 3 | lint 的逐页规则与共享页模式结果一致 | 规则输出逐条相同 |
| 4 | `export_json` 的链接明细与逐页查询一致 | dict 结构与内容相同 |
| 5 | `get_info_for_pages` 与逐页 `get_info_for_page` 一致 | 每页的 has_sink / sink_entries 相同 |
| 6 | `_rebuild_sink_file` 的日期与原实现一致 | 每个 hash 的日期相同 |
| 7 | `RedundancyRule` 的输出不变 | 相似页对相同 |

## 验证

```bash
ruff check src/llmwikify/ tests/
mypy src/llmwikify/kernel/storage/index.py src/llmwikify/kernel/wiki/engines/relation.py
pytest tests/test_perf_no_n_squared.py tests/test_v029_index_enhancement.py \
       tests/test_wiki_analyzer.py tests/test_sink_flow.py
python scripts/check_architecture.py
```
