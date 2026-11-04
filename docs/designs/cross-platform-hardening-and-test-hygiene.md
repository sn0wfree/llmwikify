# 跨平台收尾 + 健壮性 + 测试卫生

> 分支 `feat/auto-doc-ingest` · 2026-07 · 对应审查中优 B / C / D 三组

## B 跨平台收尾

### B1 `.gitattributes`（新增）

仓库**存储已是 LF**（`i/lf`），但工作区 CRLF 取决于各人本机的
`core.autocrlf`——本机是 `true`，别人可能是 `false`，导致同一文件在
不同机器上换行不同、diff 全文件变更。

```
* text=auto eol=lf
*.bat text eol=crlf     # cmd.exe 需要 CRLF
*.cmd text eol=crlf
*.sh text eol=lf        # shebang + CRLF 不可执行
```

二进制资产显式标 `binary`，避免被行尾转换。

### B2 生成内容的换行统一为 LF

Windows 文本模式写文件会把 `\n` 翻译成 `os.linesep`，于是**所有
write 出来的 wiki 页面、index、log、sink 文件在 Windows 上都是
CRLF**——追加到已有 LF 文件还会产生混合换行。

- 53 处 `Path.write_text(...)` 补 `newline="\n"`
- 9 处文本模式 `open(...)` 补 `newline="\n"`

用 AST 审计脚本确认：`src/llmwikify` 下所有 `write_text` 与文本模式
`open` 现在都同时固定了 `encoding` 与 `newline`。

### B3 图谱导出的实体链接失效（真 bug）

`export.py` 用 `_slugify(base_name)` 拼实体页路径，但实体页是
**原样命名**的（`entities/Machine Learning.md`）：

| 实体名 | 真实文件 | export 拼的路径 | 结果 |
|---|---|---|---|
| `Machine Learning` | `entities/Machine Learning.md` | `entities/machine-learning.md` | 找不到 → 无链接 |
| `人工智能` | `entities/人工智能.md` | `entities/.md` | 空文件名 → 无链接 |

也就是说**导出的图谱里实体链接几乎从不生效**。

**修复**：改用原名查文件，slug 仅作回退候选；href 走 `urllib.parse.quote`
做 URL 转义。点击处理器改为接收已解析好的 href 映射（调用方解析过
磁盘文件），不再自己猜名字。

## C 健壮性

### C1 lint 单规则失败不可见

`LintEngine.run_all` 捕获规则异常后只 `logger.warning`，返回的 issue
列表看不出「有检查根本没跑」。

**修复**：新增 `LintEngine.failed_rules`（规则名 → 错误信息），`run_all`
每次重置；`wiki.lint()` 结果新增 `failed_rules` 字段，HTTP/CLI 都能看到。

### C2 `_file_locks` 只增不删

`auto_ingest._file_locks` 按文件名 `setdefault` 建锁，从不清理——长期
运行内存缓慢增长。

**修复**：加引用计数 `_lock_refs`；最后一个使用者离开时（`finally`）
连同计数一起删除。计数在拿锁前自增，因此等待中的协程不会让锁被提前
回收（那会导致同文件并发进入临界区）。

### C3 gap_filler 搜索失败静默降级

`_web_search` 失败只 `logger.debug` 就返回 `[]`——gap 照填，但缺了本该
从外部补进来的上下文，且完全无迹可寻。

**修复**：日志升到 `warning`，新增 `GapCycleResult.web_search_failures`
计数并写进周期汇总日志。

## D 测试卫生

### D1 计时断言 flaky

| 断言 | 原值 | 实测 | 新值 |
|---|---|---|---|
| `test_lint_missing_cross_refs` 1400 页扫描 | `< 5.0s` | 1.29s | `< 30.0s` |
| `test_index_rebuild_perf` cold / warm | `< 2.0s` / `< 1.0s` | 亚秒级 | `< 10.0s` / `< 5.0s` |
| `test_perf_no_n_squared` fix_wikilinks | `< 10.0s` | 0.27s | `< 30.0s` |
| `test_perf_no_n_squared` add_relations | `< 3.0s` | 0.15s | `< 10.0s` |

阈值按「当前耗时 × 大余量，但仍低于回归值」重设——这些是防 O(N²) 的
护栏，回归值分别是分钟级和 18s，新阈值仍能拦住，同时慢 CI 不会假失败。

### D2 全局 stub teardown 不还原

`test_webui_proposal_loop` 的 fixture 把全局 `AGENT_SERVICE` 置为 stub，
teardown 时置 `None`（不是还原原值），且 setup 失败时 stub 会泄漏到
后续测试。

**修复**：保存原值，`try/finally` 中还原。

### D3 集成测试文件从不被收集

`tests/integration_minimax_web_search.py` 不匹配 `python_files =
["test_*.py"]` → **从未被 pytest 收集**。文件里还有个更隐蔽的问题：
`pytest_collection_modifyitems` 写在测试模块里不是合法 hook 位置
（pytest 只认 conftest / plugin），marker 从未生效。

另外 skip 条件接受 `LLM_API_KEY`——那是聊天 key，而 search 端点要的是
coding-plan key（`sk-cp-...`），用错 key 会 401。

**修复**：
- 重命名为 `tests/test_integration_minimax_web_search.py`
- 用模块级 `pytestmark` 一次性应用 `integration_live` + `skipif`，
  删掉无效的 hook
- 只认 `MINIMAX_SEARCH_KEY`
- pyproject 注册 `integration_live` marker（`--strict-markers` 开着，
  未注册会直接报错），默认 `-m` 排除它

### D4 全局 `ignore F401` 掩盖 47 处未用 import

ruff 配置全局忽略 F401，掩盖了 60 处未用 import（含 `src/` 里的
`sqlite3`、`pathlib.Path` 等，以及 `cli/commands/__init__.py` 里漏登记
`__all__` 的 re-export）。

**修复**：移除全局忽略，逐个清理：
- 57 处自动移除
- `apps/chat/memory/__init__.py` 与 `apps/agent/tools/__init__.py` 的
  `sqlite3` 手工移除
- `cli/commands/__init__.py` 把 `MigrateConfigCommand` /
  `run_migrate_config` 补进 `__all__`（与其余命令一致）

## 验证

- 全量 `pytest tests/ --ignore=tests/e2e`：失败+错误集合与基线**零新增**
  （基线 364 → 当前 361，消失的 3 个是 flaky：`test_scan_accepts_home_relative`、
  `test_get_events_since_returns_only_newer`、`test_fallback_proposal_persists_to_db`）
- `ruff check src/ tests/` 通过（F401 已启用）
- `scripts/check_architecture.py` 0 violation
- 406 文件编译通过
