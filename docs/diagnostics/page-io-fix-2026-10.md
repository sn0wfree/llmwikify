# page_io 两处修复 — write/read page_type 不对称 + 摘要截断切断 wikilink

> 日期: 2026-10-15
> 范围: `kernel/wiki/mixins/io/page_io.py`（write_page / read_page / _extract_page_summary）
> 背景: CKbase 实测数据受损（6 个双层目录文件 + index.md 4 处未闭合 `[[` + DB 脏行）反向溯源
> 状态: **修复完成，验证通过**；已提交并合并（PR #6, merge `0d71ce1`）；CKbase 数据清理已执行（2026-10-15）

---

## 1. TL;DR

`page_io.py` 中存在两组读写/生成不一致:

1. **Bug A** — `write_page` 的 `page_type` 分支无 `"/"` 守卫，而 `read_page` 有：
   含路径的页名 + page_type 组合会被**再拼一次目录**（`sources/X` → 写
   `sources/sources/X`，读却按 `sources/X`）→ **同一组参数写进去、读不出来**。
2. **Bug B** — `_extract_page_summary` 的 3 处截断均为硬切 `[:117] + "..."`，
   截断点落在 `[[wikilink]]` 中间时产生**未闭合 `[[`** → index.md 括号失衡，
   解析时吞跨行文本并产生无法解析的 link target。

修复: A = 镜像 read_page 守卫（1 处）；B = 新增 `_truncate_summary()` 统一 3 处
（截断点落入未闭合 `[[` 时回退到该 `[[` 之前）。

## 2. Bug A — write/read page_type 路径不对称

### 2.1 根因（修复前行号）

| 方法 | 行 | 条件 | 行为 |
|---|---|---|---|
| `write_page` | 48 | `if page_type:` | 无守卫 → `full_path = f"{directory}/{page_name}"` → `sources/sources/X` ❌ |
| `read_page` | 124 | `if page_type and "/" not in page_name:` | 有守卫 → `full_path = page_name` → `sources/X` ✅ |

git 历史: `83a9bc1`（2026-04-15，page_type 特性首个提交）引入时即不对称，
非后续回归——属**上游工具 bug**。

### 2.2 复现（沙盒 `/tmp/opencode/wiki_probe_20261015`）

```python
# 修复前
write_page('sources/Probe B', type='ResearchReport')  # → sources/sources/Probe B ❌
read_page ('sources/Probe B', type='ResearchReport')  # → Page not found: sources/Probe B ❌

# 修复后
write_page('sources/Probe E', type='ResearchReport')  # → sources/Probe E ✅
read_page ('sources/Probe E', type='ResearchReport')  # → 往返一致 ✅
```

### 2.3 修复（镜像 read_page 守卫 + 合并同体分支）

```diff
-        if page_type:
+        if page_type and "/" not in page_name:
             ...
             full_path = f"{directory}/{page_name}"
-        elif "/" in page_name:
-            full_path = page_name
         else:
             full_path = page_name
```

语义: 名字含 `/` → 视为完整路径（type 不参与拼接）；不含 `/` → 按 Page Types
映射拼目录。读写完全对称。

### 2.4 影响面（核实收窄）

- 仅 CLI `write_page --type`（`interfaces/cli/commands/write_page.py:30`）与直调
  Python API 受此 bug 影响
- HTTP / MCP / agent tools / relation engine 均不传 page_type，不受影响
- 现有测试的 page_type 调用均传纯名（无 `/`）→ 修复零影响（回归 106 passed）

## 3. Bug B — _extract_page_summary 截断切断 wikilink

### 3.1 根因（修复前行号）

3 处截断均为硬切（`max_len=120` → `[:117] + "..."`）：

| 行 | 优先级路径 |
|---|---|
| 251 | frontmatter `summary:` 字段 |
| 262 | `## Summary` 首行（Source 页） |
| 282 | 兜底首段落（板块页品种列表，**最常见触发点**） |

截断点落在 `[[symbols/...]]` 中间 → 未闭合 `[[`。
实测: 黑色 / 能化 / 农产品 三板块失衡，贵金属正常。

### 3.2 后果

- index.md `[[` 836 vs `]]` 832（失衡 4）
- 解析 index.md 时未闭合 `[[` 吞跨行文本 → 4 条畸形 target 进 DB

### 3.3 修复

新增 `page_io.py::_truncate_summary(text, max_len)` staticmethod，
3 处调用点统一替换：

```python
if len(text) <= max_len:
    return text
cut = text[: max_len - 3]
if cut.count("[[") > cut.count("]]"):
    cut = cut[: cut.rfind("[[")].rstrip()
return cut + "..."
```

（回退到最后一个未闭合 `[[` 之前；完整链接落在截断点内时不受影响。）

## 4. 回归测试与验证（TDD 记录）

- **测试先行（红）**: `tests/test_page_io_symmetry.py`（新，4 用例）+ 
  `tests/test_v029_index_enhancement.py`（+3 用例）→ 跑出 **4 failed**
  （双层目录 ×2、截断吞链接 ×2），对照组通过
- **修复（绿）**: 上表代码修改 → 两文件 **25 passed**
- **周边回归**: `test_v026_wikilink_fix` / `test_direct_lint` /
  `test_wiki_backend` / `test_wiki_core` / `test_wiki_analyzer` → **106 passed**
- **沙盒探针**: `/tmp/opencode/wiki_probe_20261015` 往返一致，
  双层目录不再产生
- **lint**: black / ruff 干净；全量 pytest 见提交说明

## 5. 数据清理（CKbase，✅ 已执行 2026-10-15）

受影响数据（`/home/ll/Public/CKbase`）:

- 3 个双层目录 / 6 个文件（与正确副本**逐字节相同**，已删除）:
  `symbols/symbols/{纯碱,玻璃}.md`、`sectors/sectors/黑色.md`、
  `metrics/metrics/{浮法玻璃库存,浮法玻璃日熔量,纯碱产能与库存}.md`
- DB: `CKbase/.llmwikify.db`
- index.md: 6 条嵌套条目 + 4 处未闭合 `[[`

执行结果:

| 项 | 清理前 | 清理后 |
|---|---|---|
| 双层目录 | 3 目录 / 6 文件 | **0**（正确副本完好） |
| pages | 797（6 文件 + 3 陈旧行脏） | **788 = 磁盘 `.md` 文件数** |
| page_links | 8411（255+9 行脏） | **8150**（嵌套 0 / 不可解析 0） |
| relations | 2838 | 2838（0 脏） |
| index.md 括号 | `[[`836 vs `]]`832 失衡 | **819 = 819 平衡** |

关键执行细节:

1. 删除前逐字节复核 6 文件 identical；全量备份至
   `/tmp/opencode/ckbase-cleanup-backup`（6 文件 + DB + index.md，27MB）
2. 删除 = 显式文件名 + `rmdir`（无通配符）
3. `build-index` 全量重建 → **显式 `_update_index_file()` 重建 index.md**
   （`build_index()`（page_io.py:200）只重建 SQLite + jieba 词典 + export，
   不重写 index.md）
4. **顺序注意**: index.md 自身也是被索引页 — 先 rebuild 后重建 index.md 会
   使 DB 残留旧 index 链接（实测 6 条嵌套 target）；需再跑一轮 build-index
   对齐最终版 index.md。收敛验证: index.md `[[` 数 == DB source=index 数（819）、
   抽样入链计数一致（如 `sectors/农产品` 147）
5. 读页往返: `symbols/纯碱` / `sectors/黑色` / `metrics/纯碱产能与库存` ✅
6. 不可解析 target **归零**（原报告 9 条：5 条历史残留 + 4 条 index 畸形全消）
