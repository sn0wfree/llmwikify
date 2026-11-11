# 平台无关化改造 — 路径分隔符 + Windows 文件名合法性

> 日期: 2026-11-11
> 范围: `kernel/storage/`、`kernel/wiki/`、`apps/wiki/`、`foundation/callback/`、`interfaces/`、`tests/`
> 背景: 代码在 Windows 上跑全量测试暴露两类平台耦合；本次统一收敛为 platform-free
> 状态: **完成，验证通过**（ruff / mypy / 架构门禁 / 全量测试均绿）

---

## 1. TL;DR

修两类平台耦合：

1. **路径分隔符** — `str(Path.relative_to(...))` 在 Windows 返回 `\`，
   但该值被当作**逻辑页名**存进 DB、sink、index、wikilink → 跨平台数据不一致。
   统一改 `.as_posix()`。
2. **文件名合法性** — `:` 是 Windows 保留字符。`Query: X.md` 在 NTFS 上被解析成
   **备用数据流（ADS）**：落成 0 字节的 `Query` 文件，内容全部丢失，且
   `rglob("*.md")` 扫不到 → sink 永远匹配不上（`created` vs `sunk` 失败的根因）。

新增存储层单一映射 `portable_path()`，页名 → 文件名只在这一处转换。

## 2. 两条约定

| 约定 | 规则 | 反例 |
|---|---|---|
| **逻辑路径**（页名 / sink 名 / index 键 / 报告给 LLM 的相对路径） | 永远 POSIX，用 `.as_posix()` | `str(p.relative_to(wiki_dir))` |
| **OS 路径**（`exists()` / `read_text()` / `Path` 对象） | 保持系统原生，不要转 | 对 `Path` 强行 `as_posix()` 再当文件路径用 |

判断法：这个字符串**会不会跨机器持久化或出现在 wikilink 里**？会 → POSIX。

## 3. 改动清单

### 3.1 逻辑路径 → `.as_posix()`（18 处）

| 文件 | 处数 | 值的用途 |
|---|---:|---|
| `kernel/wiki/mixins/io/page_io.py` | 1 | 页名列表 → sink 批量查询 |
| `kernel/wiki/mixins/io/source_analysis.py` | 2 | 源分析缓存 key（**持久化进 DB**） |
| `kernel/wiki/mixins/core/utility.py` | 1 | `_get_existing_page_names()` → HTTP API + prompt |
| `kernel/wiki/mixins/analysis/status.py` | 2 | `pages_by_type` 展示 |
| `kernel/wiki/mixins/io/link.py` | 1 | 歧义匹配候选列表 |
| `kernel/wiki/mixins/io/ingest.py` | 1 | `source_name` |
| `kernel/wiki/mixins/analysis/synthesis.py` | 1 | `rel_path` → `analyze_source` |
| `kernel/wiki/engines/{analyzer,relation,synthesis}.py` | 3 | 页名 / 实体名 / 提示词中的相对路径 |
| `interfaces/cli/commands/analyze_source.py` | 1 | `rel` → `analyze_source` |
| `apps/wiki/dream_editor.py` | 4 | `upsert_page` 的 `file_path` |
| `foundation/callback/integrations/raw_scan.py` | 2 | 新增源文件集合（返回给 agent） |
| `apps/chat/skills/workflows/subagent_worker.py` | 1 | Glob 结果回报给 agent |

配套修正 `tests/test_index_rebuild_perf.py` 的 legacy 参考实现（同病）。

### 3.2 文件名合法性 — `portable_path()`

`kernel/storage/backend.py` 新增模块级 helper（该文件本就标注为
"shared between backend and Wiki mixins"）：

| 函数 | 作用 |
|---|---|
| `portable_component(name)` | 单个路径组件 → 全平台合法；`": "` → `" - "`，替换 `< > : " \ \| ? *`，去尾部点/空格，避让 `CON/PRN/AUX/NUL/COM1-9/LPT1-9` |
| `portable_path(name)` | 按 `/` 切分后逐组件处理，保留目录分隔符 |
| `is_query_page_name(name)` | 同时认 `Query: `（旧）与 `Query - `（新） |
| `strip_query_prefix(name)` | 展示用去前缀 |

**调用点**（逻辑名 → 文件名的所有边界）：

| 文件 | 位置 |
|---|---|
| `kernel/storage/backend.py` | `_page_path()` — `get_page` / `put_page` / `delete_page` 全走这里 |
| `kernel/storage/query_sink.py` | `_sink_file()`（原 6 处 `sink_dir / f"{name}.sink.md"` 收敛为 1 处）+ `get_info_for_pages` 查表键 |
| `kernel/wiki/mixins/io/page_io.py` | `write_page` / `read_page` / sink 分支 |
| `kernel/wiki/mixins/analysis/query.py` | 建页 + sink 路径提示 |
| `kernel/wiki/mixins/analysis/{relation,llm}.py`、`engines/analyzer.py`、`wiki.py`、`apps/wiki/dream_editor.py` | 直接拼路径处 |

**query 页前缀**：`_generate_query_page_name` 由 `Query: {Topic}` 改为
`Query - {Topic}`，保证「逻辑名 == 文件名」这个项目不变量成立。
识别逻辑（`query.py` / `lint/__init__.py` / `lint/rules/query_page_overlap.py` /
`lint/rules/missing_cross_refs.py`）统一走 `is_query_page_name()`，旧 wiki 仍可识别。

**旧数据兼容**：`_page_path()` 先探可移植名，不存在再探字面名。
POSIX 上已有的 `Query: X.md` 继续可读可写；Windows 探测字面名恒为 `False`
（实测 `Path("Query: X.md").exists()` → `False`），自动落到可移植名，无平台分支。

### 3.3 测试环境的 Windows 耦合

| 问题 | 修法 |
|---|---|
| 裸 `shutil.rmtree()` 撞 SQLite 句柄锁 → **26 ERROR** | `conftest.py` / `test_p1_3_graph_analyzer.py` / `test_p1_features.py` / `test_revert.py`（7 处）补 `ignore_errors=True` |
| `subprocess.run(["python3", ...])` → Windows 无此可执行名 | 5 个 `tests/scenarios/*` 共 11 处改 `sys.executable` |
| 测试写死 `Query: X.md` 文件路径 | `test_sink_flow.py`（109 处）、`test_sink_dedup.py`、`test_query_flow.py` 改可移植名 |

`test_sink_dedup.py` 中 legacy 条目日志的 `] Query: Q1` **保留冒号** —
那是文件内容（解析正则的字面量），不是页名。

## 4. 验证

| 检查 | 结果 |
|---|---|
| `ruff check src/ tests/` | All checks passed |
| `mypy src/` | Success: no issues in 410 files |
| `scripts/check_architecture.py` | 0 violations，0 broken imports |
| 全量 pytest（pre-change 基线 `e0219daf` 对照） | **49 failed / 26 errors → 15 failed / 0 errors** |

对照方式：`git worktree add <tmp> e0219daf` 跑同一套，逐条 diff 测试 ID —
**0 新增失败**。剩余 15 条均在基线复现（`test_foundation_migration` ×5、
`test_v020_markitdown` ×2、`test_cli_auth`、`test_doctor_layout`、
`test_extractors`、`test_lint_engine_aggregator`、`test_autoresearch`、
`test_apps_chat_agent_runner_v2`、`test_apps_chat_memory_consolidator`、
`test_maintenance_comprehensive`），与本次改动无关。

## 5. 遗留

- `kernel/storage/backend.py` 与 `kernel/wiki/mixins/core/utility.py` 曾各自
  持有一份 `_WINDOWS_RESERVED_NAMES`，已收敛为 `backend.WINDOWS_RESERVED_NAMES` 单一来源。
- `interfaces/server` 返回的绝对路径字段（如 lint issue 的 `file`）保持 OS 原生 —
  绝对路径本就平台相关，转 POSIX 反而错。

## 6. 第二轮：清零剩余失败（2026-11-11）

上一轮结束时余 15 条失败。逐条定根因后**全数修完**，
全量基线由 `49 failed / 26 errors` 降至 **`0 failed / 0 errors`**（5048 passed）。

### 6.1 根因归类

| 根因 | 条数 | 修法 | 层 |
|---|---:|---|---|
| 测试只设 `HOME`，产品读不到 | 6 | 改设 `LLMWIKIFY_HOME` | 测试 |
| `_extract_pdf` 只 catch `ImportError`，坏 PDF 触发 `pymupdf.FileDataError` 穿透 | 3 | 捕获解析失败 → `source_type="error"` | **产品** |
| `migration.py` / `doctor_cmd.py` 用 `Path.home()`，绕过 `LLMWIKIFY_HOME` | 3 | 抽 `global_config_home()` 统一解析 | **产品** |
| 测试用 POSIX 假路径/字符串当 dict 键 | 2 | 键用 `str(Path(...))`；失败条件改「父级是文件」 | 测试 |
| Windows 忽略 `chmod 0o600` | 1 | 权限断言仅在 POSIX 执行 | 测试 |
| `lint()` 折行后行数断言 `<= 1` 过脆 | 1 | 放行纯闭括号续行 | 测试 |

计时 flaky（`test_autoresearch::TestEventsCursor`）本轮未复现，属 flaky 而非恒失败。

### 6.2 关键发现：`LLMWIKIFY_HOME` 是唯一可靠的 home 覆盖

三个 home 解析入口行为不一致，是本批失败的共同根源：

| 入口 | 原实现 | `LLMWIKIFY_HOME` | `$HOME`（Linux） | `USERPROFILE`（Windows） |
|---|---|---|---|---|
| `foundation/config.py` | `expanduser("~")` | ✓ 优先 | ✓ | ✓ |
| `foundation/migration.py` | `Path.home()` | ✗ 被忽略 | ✗ 看 `/etc/passwd` | ✓ |
| `interfaces/.../doctor_cmd.py` | `Path.home()`，**模块级常量** | ✗ 被忽略 | ✗ | ✓ |

`Path.home()` 与 `os.path.expanduser("~")` 都**不看 `$HOME`**（前者看
`/etc/passwd` / `USERPROFILE`，后者在 Windows 上看 `USERPROFILE`），
所以测试里 `monkeypatch.setenv("HOME", ...)` 是无效的。
已统一为 `config.global_config_home()`，并在 doctor 侧把模块级常量改成
按调用时解析的函数 —— 模块级路径常量会在 import 期定死，无法被测试重定向。

### 6.3 测试隔离隐患（**未处理，建议跟进**）

`test_cli_auth.py` / `test_cli_serve_auth.py` / `test_foundation_auth.py`
在**模块导入期**写 `os.environ["LLMWIKIFY_HOME"]` 且不还原：

```python
os.environ.setdefault("LLMWIKIFY_HOME", tempfile.mkdtemp(...))   # cli_auth / cli_serve_auth
os.environ["LLMWIKIFY_HOME"] = str(TEST_HOME)                    # foundation_auth（无条件覆盖）
```

pytest 收集阶段 import 模块 → 变量泄漏到整个进程。doctor 修复前
（用 `Path.home()`）对它免疫；修复后 doctor 正确读了该变量，
于是 `test_cli_auth` 跑在 `test_doctor_layout` 前面就会让后者挂掉
（`next(...)` 抛 `StopIteration`）。已让 doctor 侧测试显式传
`LLMWIKIFY_HOME` 屏蔽掉泄漏，但**泄漏本身仍在**。

根治方向二选一：
1. `foundation/auth` 改为按调用时解析配置路径（与 `doctor_cmd` 同样的教训），
   测试即可用 `monkeypatch` 正常隔离；
2. 或在 `tests/conftest.py` 加 session 级 `LLMWIKIFY_HOME` 隔离
   （照 `_isolate_llmwikify_data_dir` 的做法），并把 `foundation_auth`
   的无条件赋值改成 `setdefault`。

