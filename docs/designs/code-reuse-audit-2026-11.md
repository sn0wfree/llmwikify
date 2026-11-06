# 代码复用性 / 设计模式 / 性能审计 · 2026-11-06

> 方法：graphify 图谱（`28e6ca73`，24988 节点 / 48492 边）+ AST 指纹扫描 + 逐条源码复核
> 范围：`src/llmwikify` 413 模块 / 81316 LOC
> 结论先行：**有 7 处可落地的复用/样板收敛，2 处真实效率问题；内存无风险；行数收益约 300–400 行（0.4%），主要价值在可维护性而非行数。**

## 一、复用缺口（helper 已存在但没被用）

### 1. `foundation/io.py` — 14 处手写 `json.loads(read_text())`

`foundation/io.py` 已提供 `read_json` / `write_json` / `safe_read_text` / `safe_write_text` / `read_yaml`
（含「文件不存在返回 default」「JSONDecodeError 返回 default」的统一契约），但全库仍有 **14 处**手写：

```python
json.loads(path.read_text(encoding="utf-8"))   # 每处都要自己处理 FileNotFoundError / JSONDecodeError
```

分布：`foundation/llm/client.py:53`、`foundation/migration.py:177`、`foundation/web/search.py:306`、
`apps/agent/maintenance/{__init__,auto_ingest,config}.py`、`apps/chat/memory/__init__.py:325`、
`apps/wiki/scheduler/__init__.py:175`、`interfaces/cli/commands/{doctor_cmd,dict_cmd}.py` 等。

**收益**：每处省 3–5 行 + 统一错误语义；`io.py` 的 docstring 还写着
「Initial version is a placeholder」——已过期，需一并更新。

### 2. `foundation/config.py` — 3 个同构 section getter

`get_mcp_config` / `get_search_config` / `get_wikis_config` 是同一个 8 行函数换了个 key：

```python
cfg = cfg or get_default_config()
out = DEFAULT_CONFIG["mcp"].copy(); out.update(cfg.get("mcp", {})); return out
```

**收益**：抽 `_section_config(cfg, name, *, deepcopy=False)`，3 个函数 → 1 个 + 3 行包装（省约 40 行）。

### 3. `apps/wiki/dream_editor.py` — `approve` / `reject` 仅差一个字符串

```python
def approve(self, id): ... p["status"] = "approved" ...   # 9 行
def reject(self, id):  ... p["status"] = "rejected" ...   # 9 行，其余逐字相同
```

**收益**：`_set_status(self, proposal_id, status)`，省 8 行，且后续加 `batch_reject` 不再复制。

### 4. `kernel/wiki/lint/__init__.py:104-106` — except 分支与 try 完全相同

```python
try:
    pages[name] = page.read_text(encoding="utf-8")
except TypeError:
    pages[name] = page.read_text(encoding="utf-8")   # 与 try 一模一样
```

**成因（git -L 追溯）**：`19e17b5c`（全量补 encoding=utf-8）把 fallback 分支也加了
`encoding=`，抹掉了它原本的语义——原代码是 `page.read_text()`，用于兼容
`read_text()` 不接受 kwargs 的 page 对象（mock / legacy Page）。

**修复**：**不是删掉 try/except，而是恢复 fallback 的原义**。全库同类问题共 **2 处**
（另一处 `kernel/wiki/engines/analyzer.py:63-66`，同一次提交引入）。

### 5. 重复实现指纹（AST 归一化聚类）

15 组 / 40 个函数体完全同构（≥4 条语句），top：

| 组 | 规模 | 位置 |
|---|---|---|
| `_status` 包装 | 6 处 × 4 stmts | `apps/chat/skills/wiki_query_skill.py`（`_status/_recommend/_build_index/_read_schema/_sink_status`） |
| `_ingest/_read_page/_update_schema` | 3 处 × 6 stmts | 同上 |
| `__init__` 存储类样板 | 4 处 × 5 stmts | `apps/chat/memory/__init__.py`、`apps/research/{clarifier,report}.py`、`apps/research/harness/review.py` |
| `list_*` 查询包装 | 3 处 × 5 stmts | `apps/chat/memory/{consolidation_store,facts_store}.py` |
| `handle` 步骤实现 | 2 组 × 2 | `kernel/agent/steps/{code,llm}.py` |
| `_search_youtube` / `_search_news` | 2 处 × 5 stmts | `apps/chat/skills/actions/web_search_action.py` |

`wiki_query_skill.py` 是重灾区：6+3 个同构薄包装，可收敛为一个 `_dispatch(name, handler)` 表驱动。

## 二、装饰器机会

### 6. retry 有两套独立实现（最值得统一）

| 实现 | 位置 | 规模 |
|---|---|---|
| HTTP 指数退避 + Retry-After + metrics | `foundation/llm/streamable.py` `_post_with_retry_{sync,async}`、`stream_chat`、`astream_chat` | 4 个循环骨架，各 ~60–80 行 |
| 通用 async 退避 | `apps/research/retry_managers.py` `retry_async` + `StageRetryManager` + 2 个 manager | 4 个实现 |
| 流式重试 | `apps/chat/agent/tool_executor.py:167` `llm_stream_with_retry` | 1 个 |
| 阶段重试 | `apps/chat/skills/workflows/executor.py:428` `_execute_phase` | 1 个 |

两套 backoff 公式不一致（`min(base*2**attempt, max)` vs `_compute_backoff()`），异常分类、日志、
metrics 各写一遍。

**建议**：在 `foundation/` 加 `@retry(policy=RetryPolicy(...)`（同步/异步各一），把 HTTP 特有的
Retry-After 头解析与 `_record_retry_outcome` 做成 policy 的 hook。`streamable.py` 4 个骨架
约 200 行可收敛到 ~80 行；research 侧 4 个实现可直接改为 policy 组合。

### 7. 单例/惰性初始化样板 25 处 / 14 类

`if self._x is None: self._x = ...` 出现在 14 个类（`WikiService._config_manager` 2 次等）。
其中「纯计算、无构造参数」的可直接换 `functools.cached_property`；带参数的可用一个
`@lazy_attr` 装饰器。每处省 2–3 行，且消除「线程内重复初始化」的隐患写法。

## 三、性能 / 内存（复核后的诚实结论）

### 真问题（2 项）

**P1 — `batch_approve` 每个 id 一次全量 DB 读**
`apps/wiki/dream_editor.py:139` `batch_approve` 循环调 `approve(pid)` → `get_proposal(pid)`
→ `_load_proposals()`（`dream_editor.py:177-181`），即 **n 次全表查询 + n 次线性扫描**。
应改为一次 `get_dream_proposals()` 拿到全部，再按 id 建索引批量处理。
（`auto_approve_pending` 已是单次加载 ✓，只有 batch 路径有此问题。）

**P2 — `foundation/io.py` 文档与实现脱节**
docstring 仍称 placeholder，实际已提供 5 个 helper；是上面第 1 条的根因之一。

### 已排除的候选（复核后不成立，避免误改）

| 扫描信号 | 原始计数 | 复核结论 |
|---|---|---|
| 循环内 `x in <var>` | 98 | **list 反查 = 0**，全部已是 `set`/`dict`，无 O(n²) |
| 函数内 `re.compile` | 11 | 均在**文档级**调用（每次校验一份 synthesis 编译一次），非热循环，收益 µs 级 |
| 循环内 `str +=` | 113 | 多为计数器/短串，CPython 对 `+=` 有原地扩容优化，收益微小 |
| 无界模块级缓存 | 1 | 仅 `init_llm_cmd._ENV_PROVIDER_MAP` 静态映射，**内存无风险** |
| 循环内 IO | 67 | `kernel/wiki/lint/__init__.py` 已用 `shared_pages` 做一次性共享加载（设计正确）；其余为每命令一次的配置读取 |

## 四、优先级与收益估算

| # | 项 | 类型 | 预估省行数 | 风险 | 建议时机 |
|---|---|---|---|---|---|
| 1 | lint `except` 死代码 | 清理 | 3 | 极低 | 立即 |
| 2 | `batch_approve` 批量读 | 性能 | ~5 | 低 | 立即 |
| 3 | `dream_editor._set_status` | 复用 | 8 | 低 | 立即 |
| 4 | 14 处改用 `read_json` | 复用 | ~50 | 低 | 立即 |
| 5 | `config.py` section getter 参数化 | 复用 | ~40 | 低 | 立即 |
| 6 | `wiki_query_skill` 表驱动包装 | 复用 | ~60 | 中 | 下一批 |
| 7 | 统一 `@retry` | 设计模式 | ~150 | 中（动 LLM 热路径） | 与 v0.41 合并时 |
| 8 | `@lazy_attr` / `cached_property` | 设计模式 | ~50 | 低 | 下一批 |

合计约 **350 行**（0.4%）。**判断：这批改动的真正收益是消除重复语义与统一错误处理，
不是压缩行数**——除非你希望以「减 LOC」为 KPI，否则 7、8 两项优先级应让位于 1–5。

## 五、复现

```bash
graphify update .                                  # 图谱
python scripts/check_architecture.py               # 分层 + peer + 坏导入
# AST 指纹 / 样板 / 热点扫描脚本在会话 scratch：
#   reuse_scan.py  reuse_scan2.py（未入库）
```

## 六、落地记录（1–5、8 项，2026-11-06）

| # | 项 | 实际改动 | 结果 |
|---|---|---|---|
| 1 | lint except | 恢复 fallback 为 `page.read_text()`；**并发现同类第 2 处** `engines/analyzer.py`，一并修复 | 2 处 |
| 2 | 批量读 | `ProposalManager.batch_approve` 改为单次 `_load_proposals()`；**真正的 O(n) 在服务层** `WikiService.batch_approve_wiki_dream_proposals`（逐 id 全表读 × 逐 editor），一并改为每 editor 单次加载 | 2 处 |
| 3 | `_set_status` | 抽 `_apply_status(p, status)` + `_set_status(id, status)`，`approve`/`reject` 变 1 行 | −8 行 |
| 4 | `read_json` | **仅 3/11 处可安全替换**（`maintenance._load_history`、`chat/memory._load`、`doctor_cmd._check_llm_connectivity`）。其余 8 处需要异常对象做日志或区分错误串（`logger.warning(..., exc)` / `"config parse error"` vs `"config not found"`），`read_json` 的静默契约不覆盖 | 3 处 |
| 5 | section getter | 抽 `_section_config(section, cfg, *, deep)`；`wikis` 用 `deep_merge`（`deep=True`），`mcp`/`search` 用浅 `update`；默认 `deepcopy` 取代原 `.copy()`，消除与 `DEFAULT_CONFIG` 的共享引用 | 3 → 1 |
| 8 | `cached_property` | **实测 20 处（原估 25）**。安全子集 11 处换 `functools.cached_property`：`harness/service` 6 + `wiki.py` 2（`ref_index_path`/`query_sink`）+ `dream.py` 2 + `consolidator` 1；其中 harness 与 consolidator 的测试断言私有字段（`_quality_gate`/`_store`），同步改为缓存语义断言（`__dict__` 存在性 + reset 后重建）。**未做**：带参构造 5 处（需 `@lazy_attr` 存参）、`skills/service.initialize()` 2 处（显式初始化语义）、`rate_limit.lock` 1 处（asyncio.Lock 必须延迟绑定 loop，属必要 lazy）、`config.py` 2 处（依赖 `read_json` 错误语义） | 11 处 |

**第 8 项验证**：ruff 全过；harness/memory 测试 80 passed + 1 failed（`test_markdown_failure_continues`，**worktree 基线同样失败**，Windows 路径问题）；wiki 四件套与基线**逐条比对 35 failing / 0 differences**。

**修正第 4 项的估算**：原报告按 14 处 × 3–5 行估 ~50 行，实际只有 3 处语义完全匹配
（静默 default）。多数调用点「失败要留痕」，这是 helper 契约太窄，不是调用方偷懒——
若要覆盖它们，应给 `read_json` 加 `on_error` 回调（本次未做，避免推测性扩展）。

**验证**：ruff 全过；`check_architecture.py` 0 violation / 0 peer / 0 broken import；
目标 16 个测试文件 **298 passed / 0 failed**（35 个 ERROR 均为已知 Windows SQLite
teardown 文件锁）；新增 2 个边界测试（`batch_approve` 单次加载 + 服务层 unknown id 契约）
8 passed。

**净变化**：10 文件 +121/−69；另有本报告 1 个新文档。
