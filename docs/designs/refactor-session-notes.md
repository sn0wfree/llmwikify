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

---

## 2026-10-28 · P4-a（p4-lint-snapshot）—— 协议首次端到端跑通

### 结果

任务 = 方案文档 §P4 的 **P4-a**（lint 路径的文件系统访问收敛 + 非 UTF-8 不崩）。
流水线 **Recon → Architect → Implementer → Reviewer → (返工) → Reviewer → Benchmarker**
全程走完，**5/5 门通过**。

| 阶段 | 结果 |
|---|---|
| Recon | 10 条候选，全部带 file:line 与实测数字；**否掉了编排者 3 条怀疑点** |
| Architect | `decision: proceed`；边界限定在 `kernel/wiki` 内 3 个源文件 |
| Implementer | A/B/C 三步落在 3 个源文件 + 2 个新测试文件 |
| Review r1 | **request_changes**（3 medium + 4 low）→ **门挡住流水线** |
| Implementer r2 | 6 条 required_action 全修（5 条实修 + 1 条登记残留风险） |
| Review r2 | **approve** |
| Benchmarker | `regression: false` |

### 关键数字（计数型门禁，合成 wiki：20 平铺 raw / 14 source 页）

| 指标 | before(pristine) | after |
|---|---|---|
| sources 目录 rglob | 8 | **1** |
| sources read_text | 87 | **14** |
| 全量 rglob / read_text | 10 / 103 | **3 / 30** |
| 缓存命中时 `_build_lint_context` 调用 | 1 | **0** |

墙钟（**合成 wiki 的方向性信号，不可作性能承诺**）：p50 16.51 → 7.75 ms（-53.1%），
p95 25.82 → 12.85 ms（-50.2%）。
资源：峰值内存 +6.8 KiB（+2.6%，有界）；句柄数无增长；sqlite 连接 1→1→0 无泄漏。

正确性：非 UTF-8 页面改前让 `wiki.lint()` 抛 `UnicodeDecodeError`（HTTP 500）且
**4/8 条规则被静默吞掉**，改后 8/8 规则跑完。

### 决策

| 决策 | 理由 |
|---|---|
| P4-a 提前到批次 1 执行（方案原排批次 3） | ①§P4 自己给出 P4-a/P4-b 拆分且 P4-a 标注「低风险 ~30 行」；②含正确性缺陷修复 C9，协议规定正确性缺陷优先；③不依赖批次 1 其它事项；④计数型基准在本机无 1400 页 wiki 也能验证 |
| 门禁指标用**计数**而非墙钟 | 本机 `wiki/` 只有 3 页，墙钟是噪声。§P4 本身也要求「用 counter/fake source 断言，不测时间」 |
| 不照抄方案文档的「已有正确写法 safe_read_text」 | 实测 `UnicodeDecodeError` 的 MRO 是 `→ UnicodeError → ValueError`，**不是 `OSError`**，`safe_read_text` 抓不到它（实测 RAISED）；且它失败返回 `""` 会丢整页。改用 `errors="replace"`，与 `kernel/storage/index.py:181` 一致 |
| R8 / R9 登记残留风险而非改代码 | R8 需改 `status.py`，而该文件**正被并行 writer 修改** → 写冲突；R9 的输出层降级属行为变更，超出 P4-a 边界 |
| 基准脚本用 `time.perf_counter()` | 本机 `time.time()` 粒度约 15.6 ms，比要测的量级还粗（这也是 `test_autoresearch.py` 随机失败的根因） |
| A/B 用**原地换文件 + 字节级还原**，不用 worktree | 本机安全策略拦截跨目录复制；且已加**并发写保护**——swap 期间若检测到他人改动该文件则拒绝还原并告警 |

### 遗留风险（已登记在设计文档 §11）

- **R8** fail-open 的连带副作用：坏字节让 `status.py` 的裸读先抛异常 →
  `_exclude_frontmatter_keys` 与 `_archive_dirs` **两个排除判定都不执行**。
- **R9** `errors="replace"` 产生 U+FFFD → 假 `broken_link` / 假 `value_conflict`。
- **R1** `knowledge_gap` 规则裸读 source 摘要页 → 非 UTF-8 source 页仍会静默关掉该规则
  （已由 `test_knowledge_gap_still_fails_on_bad_source_page` 显式钉住）。

### 未解决问题（本轮新增）

6. **仓库的 black 门在 HEAD 上本来就是红的** —— `black --check src/llmwikify tests`
   有 **68 个文件**要重排（本地装的是 26.10.1，仓库显然是用更早版本格式化的；
   CI 装 `black>=23.0.0` 同样会拿到最新版 → CI lint job 当前是红的）。
   tests/ 下 264 个文件中有 78 个含 >88 字符行。本任务**未新增** black 失败。
   → 需要单独决策：钉版本 vs 全量重排。
7. **工作区存在并行 writer** —— `apps/chat/*`、`apps/research/*` 等 12 个文件有
   不属于本任务的未提交改动。本任务全程未触碰，但 A/B 换文件脚本需要并发写保护。
8. **`mypy` 豁免掩盖了一个类型隐患** —— `source_analysis.py` 的
   `return dict.fromkeys(source_paths)` 推断为 `dict[str, None]`，声明返回类型是
   `dict[str, Path | None]`（dict 值类型不变 → 严格模式下是错误）。该模块在
   `ignore_errors = True` 豁免清单里（138 个存量模块之一），CI 不会拦。

