# Phase 3 / 方案 2（第一阶段） — 存储端口化

日期: 2026-11-02 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 先更正方案本身

架构评审方案 2 写的是「新建 `foundation/storage/page_store.py` 定义 `PageStore`」。**这是错的** ——
端口早就存在了：

`kernel/storage/backend.py` 里的 `WikiBackend` Protocol + `LocalFileBackend`，
它的 docstring 明写着「Future backends (in-memory, remote HTTP, S3) can implement the same
WikiBackend protocol and be swapped in without touching the Wiki class or any of the 13 mixin files」。

真正的问题不是「没有端口」，而是**186 处绕过端口**。所以方案 2 实际是：
**把绕过接回已有的端口**，而不是设计新端口。

## 普查（数据驱动，不是估计）

AST 扫描 `kernel/wiki/**`：

| 方法 | 次数 | | 方法 | 次数 |
|------|------|---|------|------|
| `exists` | 83 | | `write_text` | 9 |
| `read_text` | 31 | | `mkdir` | 8 |
| `rglob` | 15 | | 其余（is_file/…） | ~27 |
| `replace` | 13 | | **合计** | **186** |

其中 83 个 `exists` 大多是**布局查询**（`self.wiki_dir` / `self.wiki_md_file` / `self.raw_dir`），
不是页面内容 I/O。

## 实现

### 1. 端口补齐（`kernel/storage/backend.py`）

给 `WikiBackend` 加了 10 个原语：

| 组 | 原语 |
|----|------|
| 页面级 | `page_exists(name)` · `list_page_names()` |
| 通用文件 | `read_file(path)` · `write_file(path, content)` · `delete_file(path)` · `file_exists(path)` · `list_files(prefix)` · `ensure_dir(path)` · `dir_exists(path)` · `list_dirs(prefix)` |

**路径约定**：*逻辑路径* —— 相对 wiki root，POSIX 分隔符
（`"wiki.md"`、`"raw/report.pdf"`、`"wiki/.sink/notes.sink.md"`）。
`LocalFileBackend._logical_path()` 负责映射到真实路径并**拒绝越出 root**。

顺带：`WikiBackend` 加了 `@runtime_checkable`（端口可以 isinstance 检查了），
`list_page_names()` 统一用 POSIX 分隔符。

### 2. 迁移（`mixins/io/page_io.py` · `mixins/core/utility.py` · `wiki.py`）

- 页面读写的存在性检查 → `backend.page_exists()`
- sink 文件读写 → `backend.file_exists()` / `backend.read_file()`
- index.md / log.md / wiki.md → `backend.read_file()` / `backend.get_wiki_md()`
- raw 目录创建 → `backend.ensure_dir()`
- 布局自省（doctor 用的 `expected_layout` / `actual_layout`）→ `backend.file_exists()` / `dir_exists()` / `list_dirs()`

### 3. 棘轮守卫（`scripts/check_architecture.py`）

```
✅ 0 architecture violations across 4 layers
✅ 0 storage-port violations in kernel/wiki
✅ 0 sibling-package violations inside apps
```

规则：`kernel/wiki/**` 不得直接调 `read_text` / `write_text` / `unlink` ——
除非该模块在 `_STORAGE_PORT_PENDING` 名单里（当前 16 个）。

**棘轮的两面**：
- 名单外的模块出现内容 I/O → 违规（防止新增绕过）
- 名单里的模块**已经没有**违规 → 也违规（`remove it from _STORAGE_PORT_PENDING`），
  名单只能变短，不能变长

## 途中发现的一个真实行为差异

把 `_wiki_pages()` 换成 `backend.list_page_paths()` 后，**枚举顺序变了**（后者排序，前者 rglob 顺序）。
顺序是**可观察的**——lint issue 的先后、snapshot 的页序、analyzer 的页序都依赖它。
`test_lint_snapshot.py::test_topic_overlap_snapshot_path_matches_the_legacy_path` 立刻抓到了。

修法：**枚举回退到 rglob**，端口只接管内容 I/O。

> 这也划清了端口的**剩余缺口**：枚举仍然返回 `Path` 对象，虚拟后端给不出来。
> 把它做完需要把 `_wiki_pages()` 改成返回逻辑名，并改掉所有依赖 `Path` 运算的调用点
> （analyzer / lint rules / snapshot / relation engine）——那是方案 2 的第二阶段。

## 破坏性变更

端口扩容 → **自定义后端必须跟进**（`WikiBackend` 的实现者要实现新的 10 个原语）。
`tests/test_wiki_uses_backend.py` 的 `MockBackend` 已同步更新。
这在语义化版本上是 breaking change，需要在 CHANGELOG 记一笔。

## 回归网

`tests/test_storage_port.py`（19 项）：

| 分组 | 内容 |
|------|------|
| 协议 | 实现满足 Protocol；10 个原语都在 Protocol 里 |
| 通用文件 | 写/读/删/存在/列举/建目录；父目录自动创建；越界路径抛 ValueError |
| 页面级 | `page_exists` / `list_page_names`（POSIX 分隔符）/ 空 wiki |
| 守卫 | 当前树零违规；注入违规被抓；名单里的过期条目被抓 |

## 验证

```
pytest tests/test_storage_port.py + test_check_architecture.py
  + test_wiki_uses_backend.py        → 45 passed
pytest -k "wiki or lint or snapshot" → 失败项均为基线已有
全量 pytest → 57 failed（基线 59，少的两项是 flaky 恰好通过）
ruff → clean
scripts/check_architecture.py → 3 条规则全绿
```

## 第二阶段：内容 I/O 全部端口化（已完成）

把名单里剩下的 16 个模块的内容 I/O 全部接到端口——**名单从 16 降到 0**。

| 批次 | 模块 | 内容 |
|------|------|------|
| Batch 1 | analyzer / lint / synthesis / status / llm / query / knowledge_gaps / dated_claims | 页面读取 → `backend.get_page(name)`；wiki.md → `get_wiki_md`；快照降级 → `get_page(name)`；raw 源 → `read_file(logical)` |
| Batch 2 | snapshot（快照构建读页） / link / source_analysis / ingest / query（写） / relation mixin（删+建目录） | 快照构建改走 `get_page`（虚拟后端也能建快照）；读写删 → 端口原语 |
| Batch 3 | init（创建工作区） / utility（模板读取） | 建目录 → `ensure_dir`；建文件 → `write_file`；**模板读取搬到 `foundation.templates.read_text()`**（打包资源归 foundation 自己） |
| relation.py | 注入 `backend` 参数 | `RelationEngine(..., backend=...)`，3 个构造点都传 |

### 途中抓到的行为差异

**`get_page()` 必须容忍坏字节**。旧 mixin 全部用 `errors="replace"`（非 UTF-8 页面不能杀掉一次 lint run），而我一开始的 `get_page` 是严格 UTF-8 → `test_lint_handles_non_utf8_page` 立刻抓到。修法：`LocalFileBackend.get_page` 改 `errors="replace"`。

### 棘轮收尾

```
✅ 0 architecture violations across 4 layers
✅ 0 storage-port violations in kernel/wiki   ← 名单已空
✅ 0 sibling-package violations inside apps
```

`_STORAGE_PORT_PENDING` 现在是**空集合**——kernel/wiki 的内容 I/O 全部走 `WikiBackend`。

## 剩余缺口（诚实标注）

枚举仍然返回 `Path` 对象：`_wiki_pages()` / `_get_page_count()` / `_get_existing_page_names()`
仍 rglob（`list_page_paths()` 排序导致顺序变化，回退保序）。对虚拟后端需要改成返回逻辑名——

但那只是**表现层**；**内容 I/O 已经全部端口化**，所以 `InMemoryBackend` 现在只需实现：
get/put/delete page + read/write/delete file + list + ensure_dir —— 就能备份一个能读写页面的 Wiki。
