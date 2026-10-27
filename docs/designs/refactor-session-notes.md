# 重构会话笔记

> 由编排者维护。每完成一批更新一次：决策、回滚点、未解决问题。
> 协议说明见 `docs/designs/refactor-multi-agent-protocol.md`，
> 任务板见 `docs/designs/refactor-tasks.json`。

---

## 2026-10-27 · 协议落地

### 已完成

- **批次 0（手工完成，未走本协议）** —— 8 个 commit，分支 `v0.41-dev`：
  1. `docs(design): 方案复核与批次 0 落定`
  2. `fix(llm): 统一 achat 返回契约，修复对话压缩静默失效`
  3. `fix(db): 连接生命周期加固，close_all_threads 支持跨线程释放`
  4. `fix(db): get_connection 按 (path, profile) 单例，FK 策略不再由构造顺序决定`
  5. `test(scripts): 为 check_architecture.py 补回归网`
  6. `fix(scripts): check_architecture 修 Windows GBK 控制台崩溃`
  7. `test(scripts): 为 clone_survey.py 补回归网`
  8. `feat(scripts): 新增 AST 归一化克隆检测工具 clone_survey.py`

  8 个 commit 逐个检出到临时 worktree 跑各自负责的测试 → **8/8 GREEN**，
  历史里没有红提交。

- **本协议落地** —— 7 个角色提示词 + `scripts/validate_handoff.py` +
  `tests/test_validate_handoff.py`（30 用例）+ 本文档。
  校验器做过 4 处变异验证（bench 门 / 布尔类型检查 / review 门 / UTF-8 guard），
  **4/4 被测试抓住**。

### 决策

| 决策 | 理由 |
|---|---|
| 提示词改写成 llmwikify 专用版，而不是照抄通用模板 | 通用模板假设 `core/` 布局 + SonarQube + pytest-benchmark，本仓一条都不成立 |
| handoff 目录只放 artifact，任务板与笔记放同级 | 否则校验器每次扫描都要报一个永久的「跳过」警告 |
| `regression` 强制 JSON 布尔值 | 字符串 `"false"` 会同时绕过类型检查和 `is not False` 判断，把回归放行——这正是这道门要防的事 |
| 角色提示词写真实路径与真实工具 | 通用模板里的 `core/index.py` FTS5、`core/graph_analyzer.py` PageRank 在本仓**不存在**；写进去就是让 Agent 去查不存在的东西 |

### 回滚点

- 本协议整组可独立 revert，不影响 `src/` 任何行为。
- 批次 0 的 8 个 commit 互相独立，可单独 revert 其中任何一个。

### 未解决问题

1. **`scripts/repro_bench_graph.py` 基准前提是反的** —— 它把 `status` 当对照组，
   而 `status` 才是阻塞方。Benchmarker 取基线前必须重写它。
2. **P15「worker 线程句柄永不关闭」未闭环** —— 目前只有显式 API
   `close_all_threads()`，根治要靠 worker 线程自己在 `finally` 里 `close()`。
3. **预存 flaky**：`tests/test_autoresearch.py::TestEventsCursor::
   test_get_events_since_returns_only_newer` 受本机 `time.time()` 粒度
   （~15.6 ms）影响随机失败。根因在 `apps/research/db.py::append_events`
   的 ts 生成，需单独 commit 修。
4. **连接未释放导致的预存测试失败**（约 9 个测试文件需在 fixture 里显式 close
   DB）—— 属独立 PR。
5. **协议尚未经真实批次端到端验证** —— 首次使用请按协议 §9 走完整一轮，
   并把暴露的问题回写进本文档。
