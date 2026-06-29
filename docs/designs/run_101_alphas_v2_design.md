# run_101_alphas v2 设计文档

> 日期: 2026-06-27
> 状态: 设计完成，待实施
> 相关文件: `scripts/run_101_alphas.py` (v1, 898 行) / `scripts/run_101_alphas_v2.py` (v2, ~720 行)

## 1. 背景

`run_101_alphas.py` (v1) 经过多次迭代后达到 898 行，包含三个阶段（paper / factor / meta）的实现。虽然功能完整，但存在以下问题：

- 函数之间界限模糊，状态散落在函数参数和模块级变量中
- 难以独立测试单个阶段
- 添加新阶段需要修改 main() 的流程控制
- `print()` 和 `logger.info()` 混用，输出不一致

v2 重构的目标是按**能力/阶段**重新组织代码，同时保持与 v1 完全等价的行为（作为对比基准保留）。

## 2. 重构原则

| 原则 | 说明 |
|---|---|
| **无状态→顶层函数；有状态→类** | 纯函数用顶层函数实现；需要持有状态的功能用类 |
| **按阶段划分** | 不按角色（Reporter / Persistence）划分，按 Stage 1/2/2b 划分 |
| **继承复用** | `FactorStage` 继承 `FactorRunner`，复用 `run_one_factor()` 逻辑 |
| **类型安全** | 所有方法添加返回类型注解 |
| **显式 API** | `__all__` 明确公共导出 |
| **内存优化** | 类使用 `__slots__` 限制属性 |
| **输出统一** | 全部 `logger.info()`，删除所有 `print()` |

## 3. 类层级

```
BaseStage (abstract, slots)
├── PaperStage       # Stage 1: paper PDF → track_b_checkpoint.json
├── MetaStage        # Stage 2b: alpha JSONs → L2-L6 metadata
└── FactorRunner     # 单 alpha 因子运行器（封装原 run_one_factor 函数）
    └── FactorStage  # Stage 2: 批量 alpha 处理（继承复用 run_one_factor）
```

### 3.1 BaseStage

```python
class BaseStage(ABC):
    """所有阶段的抽象基类。"""
    __slots__ = ("config", "t0")
    label: str = "base"

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self.t0: float = 0.0

    @abstractmethod
    def run(self) -> Any:
        """执行阶段，返回阶段产物。"""
        ...

    def _log_start(self) -> None:
        self.t0 = time.monotonic()
        logger.info("[%s] starting", self.label)

    def _log_done(self) -> None:
        elapsed: float = time.monotonic() - self.t0
        logger.info("[%s] done (%.1fs)", self.label, elapsed)
```

### 3.2 PaperStage (Stage 1)

```python
class PaperStage(BaseStage):
    """Stage 1: paper PDF → track_b_checkpoint.json."""
    __slots__ = ()
    label = "paper"

    def run(self) -> Path:
        self._log_start()
        self._validate()
        summary = self._call_orchestrator()
        self._check_summary(summary)
        track_b_path = self._compute_track_b_path()
        self._verify_output(track_b_path)
        self._log_results(summary, track_b_path)
        self._log_done()
        return track_b_path
    # ... 私有辅助方法
```

### 3.3 MetaStage (Stage 2b)

```python
class MetaStage(BaseStage):
    """Stage 2b: alpha JSONs → L2-L6 metadata."""
    __slots__ = ()
    label = "meta"

    def run(self) -> None:
        self._log_start()
        available = self._find_available()
        if not available:
            logger.warning("[meta] No single_factor_NNN.json found")
            return
        results = self._call_extractor(available)
        self._log_done_results(results)
        self._log_done()
    # ... 私有辅助方法
```

### 3.4 FactorRunner (单 alpha 复用层)

```python
class FactorRunner(BaseStage):
    """单 alpha 因子运行器（封装原 run_one_factor 函数）。"""
    __slots__ = ("df_pl", "data_cache")
    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.df_pl: pl.DataFrame | None = None
        self.data_cache: dict[str, pd.DataFrame] | None = None

    @abstractmethod
    def run(self) -> Any:
        """抽象方法。FactorStage 必须实现。"""
        ...

    def run_one_factor(self, alpha_index: int, use_react: bool = True) -> dict:
        """原 run_one_factor 函数逻辑（迁移为方法）。"""
        # 7 步骤聚在一起（按用户要求暂不拆分）：
        # 1. load_formula_brief
        # 2. ensure_df_pl
        # 3. generate code (ReAct / 1-shot)
        # 4. save to H5
        # 5. run backtest
        # 6. persist YAML
        # 7. save to DuckDB
        ...
    # ... 私有辅助方法
```

### 3.5 FactorStage (Stage 2)

```python
class FactorStage(FactorRunner):
    """Stage 2: 批量 alpha 处理（继承 FactorRunner 复用 run_one_factor）。"""
    __slots__ = ("results", "failures")
    label = "factor"

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.results: list[dict] = []
        self.failures: int = 0

    def run(self) -> list[dict]:
        """批量执行入口。"""
        self._log_start()
        self._log_config()
        self._preload_data()
        self._process_skip_existing()
        to_run = self._compute_to_run()
        if self.config.workers <= 1:
            self._run_serial(to_run)
        else:
            self._run_parallel(to_run)
        self._write_summary()
        self._log_done()
        return self.results
    # ... 私有编排方法
```

## 4. 顶层无状态函数

```python
# ─── Data ────────────────────────────────────────────
def preload_market_data(data_path: Path, h5_filename: str) -> dict[str, pd.DataFrame]: ...
def build_long_dataframe(data_cache: dict[str, pd.DataFrame]) -> pl.DataFrame: ...
def load_formula_brief(alpha_index: int, track_b_path: Path) -> tuple[str, str]: ...

# ─── Reporting ───────────────────────────────────────
def _print_header() -> None: ...          # logger.info 替代 print
def _print_row(idx: int, result: dict, elapsed_cum: float) -> None: ...
def _print_summary(results: list[dict]) -> None: ...
def _write_json(results: list[dict], path: Path) -> None: ...
def _write_markdown(results: list[dict], path: Path) -> None: ...
```

## 5. main() 简化

```python
def main() -> None:
    args = build_argparser().parse_args()
    config = build_runconfig(args)
    config.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info("RunConfig: %s", config)

    # Stage 1: Paper
    if config.paper_path:
        track_b_path = PaperStage(config).run()
        config = replace(config, track_b_path=track_b_path)

    # Stage 2: Factor
    if not config.llm_extract:
        FactorStage(config).run()

    # Stage 2b: Meta
    if config.llm_extract:
        MetaStage(config).run()
```

## 6. v1 → v2 功能复用

v1 的 `_run_one_safe` 是顶层函数，状态通过参数传递（`config`, `df_pl`, `t0`, `results_list`）。
v2 已将其提取为 `FactorStage._run_one_safe` 类方法，状态通过 `self` 访问。

### v1 → v2 重复逻辑对应表

| v1 函数/逻辑 | v2 位置 | 改进 |
|---|---|---|
| `_run_one_safe` (top-level) | `FactorStage._run_one_safe` | 类方法，状态封装 |
| `_run_batch_processing` serial 模式 | `FactorStage._run_serial` | 类方法 |
| `_run_batch_processing` parallel 模式 | `FactorStage._run_parallel` | 类方法 |
| `record_result` 内联逻辑 | `FactorStage._record_result` + `_update_state` + `_persist_result` + `_log_outcome` | 单一职责拆分 |
| `_run_paper_extract` | `PaperStage.run` | 类方法 |
| `_run_llm_extract` | `MetaStage.run` | 类方法 |
| `_preload_data` | `preload_market_data` (顶层函数) | 重命名 + 无状态 |
| `_build_wide_df` | `build_long_dataframe` (顶层函数) | 重命名 + 无状态 |

## 7. v2 内部重复逻辑抽象（方案 A + B + C）

### 方案 A：提取 `_run_one_with_recording`

v1 与 v2 的 serial/parallel 路径都有 `run_one_factor + record_result` 的重复模式。
v2 提取出 `_run_one_with_recording`，让 serial 和 parallel 共享：

```python
def _run_one_with_recording(self, idx: int) -> dict:
    """Run single alpha + record result. 共享给 serial 和 parallel 路径。"""
    elapsed_cum: float = time.monotonic() - self.batch_t0
    logger.info("[factor] alpha-%03d: starting (elapsed: %.0fs, failures: %d)",
                idx, elapsed_cum, self.failures)
    result = self.run_one_factor(idx, use_react=True)
    self._record_result(idx, result, elapsed_cum)
    return result

def _run_serial(self, to_run):
    for idx in to_run:
        self._run_one_with_recording(idx)
        if self._reached_max_failures():
            break
        self._maybe_delay(idx)

def _run_one_safe(self, idx):
    with _llm_semaphore:
        with _print_lock:
            return self._run_one_with_recording(idx)
```

### 方案 B：拆分 `_record_result` 为 3 个职责方法

v2 把 `_record_result` 拆分为单一职责的小方法：

```python
def _update_state(self, idx, result) -> None:
    """Update in-memory state: results list + failure counter."""
    if "alpha_index" not in result:
        result["alpha_index"] = idx
    self.results.append(result)
    if result.get("status") != "success":
        self.failures += 1

def _persist_result(self, idx, result) -> None:
    """Write single alpha JSON to output_dir."""
    out_file = self.config.output_dir / f"single_factor_{idx:03d}.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

def _log_outcome(self, idx, result) -> None:
    """Log success or failure for one alpha."""
    if result.get("status") != "success":
        logger.warning("[factor] alpha-%03d: failed (%s)", idx, (result.get("error", "?") or "")[:80])
    else:
        logger.info("[factor] alpha-%03d: success (%.1fs)", idx, result.get("elapsed_sec", 0))

def _record_result(self, idx, result, elapsed_cum) -> None:
    """Compose: state update + print row + persist + log outcome."""
    self._update_state(idx, result)
    _print_row(idx, result, elapsed_cum)
    self._persist_result(idx, result)
    self._log_outcome(idx, result)
```

### 方案 C：引入 `batch_t0` 区分生命周期计时

`BaseStage.t0` 用于生命周期（`_log_start/done`）。
`FactorStage.batch_t0` 用于批量进度（`_run_one_with_recording` 计算 elapsed_cum）。

```python
class FactorStage(FactorRunner):
    __slots__ = ("results", "failures", "batch_t0")

    def __init__(self, config):
        super().__init__(config)
        self.batch_t0: float = 0.0

    def run(self):
        self._log_start()               # 使用 self.t0
        ...
        self.batch_t0 = time.monotonic()  # 批量计时单独字段
        ...
        self._log_done()                # 使用 self.t0

    def _run_one_with_recording(self, idx):
        elapsed_cum = time.monotonic() - self.batch_t0  # 用 batch_t0
        ...
```

## 8. 关键决策记录

| 决策 | 选择 | 理由 |
|---|---|---|
| 单文件 vs 包 | **单文件** | 简化部署，对比方便 |
| 有状态粒度 | **stage 级别** | 阶段是天然的边界 |
| `__slots__` 与 ABC | **仍保留** | 阻止意外属性添加，文档化约束 |
| `print()` 统一到 | **`logger.info()`** | LoggerHelper 已配 stdout handler |
| 死代码 `_make_factor_dir_name` | **保留** | 用户明确要求不删除 |
| `run_one_factor` 拆分粒度 | **先聚一起** | 后续讨论再拆 |

## 9. 预期改进

| 维度 | v1 | v2 |
|---|---|---|
| 行数 | 898 | ~995 (略增 due to class boilerplate) |
| 输出方式 | `print()` + `logger.info()` 混合 | 统一 `logger.info()` |
| 类层级 | 无 | `BaseStage → 3 个 stage` |
| 类型注解 | 部分 | 全部 |
| `__all__` | 无 | 有 |
| `__slots__` | 无 | 有 |
| 重复逻辑 | `_run_one_safe` 串行/并行分支重复 | 提取 `_run_one_with_recording` |
| 多职责方法 | `_record_result` 做 4 件事 | 拆分 3 个单一职责方法 |
| 计时语义 | `t0` 双重用途 | `t0` (生命周期) + `batch_t0` (批量) |
| 可测试性 | 🟡 中 | 🟢 高 |
| 可扩展性 | 🟡 中 | 🟢 高 |

## 10. 验证方案

```bash
# 1. Import + __all__ 检查
python3 -c "import scripts.run_101_alphas_v2 as m; print(m.__all__)"

# 2. __slots__ 检查
python3 -c "from scripts.run_101_alphas_v2 import FactorStage; print(FactorStage.__slots__)"

# 3. 新方法存在性
python3 -c "
from scripts.run_101_alphas_v2 import FactorStage
assert hasattr(FactorStage, '_run_one_with_recording')
assert hasattr(FactorStage, '_update_state')
assert hasattr(FactorStage, '_persist_result')
assert hasattr(FactorStage, '_log_outcome')
print('All new methods exist')
"

# 4. 跑 1 alpha，对比 v1 输出
python3 scripts/run_101_alphas_v2.py --start 1 --end 1 --no-delay

# 5. 对比 v1
python3 scripts/run_101_alphas.py --start 1 --end 1 --no-delay

# 6. JSON 结果 diff
diff <(jq -S . scripts/output/single_factor_001.json) <(jq -S . /tmp/v1_single_factor_001.json)
```

## 11. 后续 TODO

- [x] 提取 `_run_one_with_recording` (方案 A)
- [x] 拆分 `_record_result` 为 3 个职责方法 (方案 B)
- [x] 引入 `batch_t0` 区分计时语义 (方案 C)
- [x] 修复 Bug 1: `_process_skip_existing` 返回值丢失（不重复扫描）
- [x] 修复 Bug 2: `_run_parallel` 异常未 append 到 results（保证 Total = Success + Failed）
- [x] 提取 `FactorReporter` 类（7 个 @staticmethod：aggregate / format_metric / log_banner / log_row / log_summary / write_json / write_markdown）
- [x] 命名清理: `_print_*` → `log_*`、`_maybe_delay` → `_inter_alpha_delay`、`_log_start_batch` → `_log_meta_overview`
- [x] 抽样验证: 1-3 alpha 对比 v1，JSON/Markdown 输出等价
- [ ] 拆分 `FactorRunner.run_one_factor` 内部 7 步骤为更小的方法（后续讨论）
- [ ] 提取 `_llm_code_react` 和 `_run_pipeline_backtest` 为顶层函数
- [ ] 添加单元测试（每个 stage 一个测试文件）
- [ ] 跑全量 101 alpha 验证 v1 vs v2 输出等价

## 12. 第二轮梳理（v2 内部代码质量）

### 12.1 Bug 修复

#### Bug 1: `_process_skip_existing` 返回值丢失

**症状**:
```python
# 旧代码 (line 743-745):
self._preload_data()
self._process_skip_existing()              # ← 返回 set，但被丢弃
to_run = self._compute_to_run()            # ← 内部又重新扫描一遍 output_dir
```

**后果**: 双倍扫描 output_dir + `_compute_to_run` 内联了 skip_existing 逻辑（DRY 违反）

**修复**: `_process_skip_existing` 返回 skip 给 `_compute_to_run(skip)` 复用：
```python
skip: set[int] = self._process_skip_existing()
to_run: list[int] = self._compute_to_run(skip)
```

#### Bug 2: `_run_parallel` 异常未 append

**症状**:
```python
# 旧代码 (line 820-826):
for future in as_completed(futures):
    idx = futures[future]
    try:
        future.result(timeout=...)
    except Exception as exc:
        logger.warning(...)
        self.failures += 1   # ← 计数 +1，但 self.results 不变
```

**后果**: Total = Success + Failed 不成立（并行模式下崩溃 alpha 不计入 results）

**修复**: 新增 `_handle_parallel_failure` 方法，构造合成 result 并 append：
```python
def _handle_parallel_failure(self, idx: int, stage: str, error: str) -> None:
    result = {
        "alpha_index": idx,
        "status": "failed",
        "stage": stage,
        "error": error[:200],
        "elapsed_sec": 0.0,
    }
    self.results.append(result)
    self.failures += 1
```

### 12.2 `FactorReporter` 类（7 个 @staticmethod）

原 5 个顶层私有函数（`_print_header` / `_print_row` / `_print_summary` / `_write_json` / `_write_markdown`）合并为一个 `FactorReporter` 类，加上 2 个辅助函数：

| 方法 | 职责 |
|---|---|
| `aggregate(results)` | 计算 total / success_count / failed_count / avg IC / avg ICIR / avg Winrate（NaN-safe） |
| `format_metric(value, fmt, na)` | 单个数值格式化（NaN-safe，用 `math.isnan`） |
| `log_banner()` | batch runner header |
| `log_row(idx, result, elapsed_cum)` | 单 alpha 行结果 |
| `log_summary(results)` | batch summary |
| `write_json(results, path)` | 写 multi_alpha_001_to_101.json |
| `write_markdown(results, path)` | 写 multi_alpha_summary.md |

**设计**: 全部 `@staticmethod`，零状态。调用形态 `FactorReporter.log_row(idx, result, 12.5)` 与原 `_print_row(...)` 等价。

**收益**:
- 消除 3 处复制粘贴的 NaN-aware 过滤（`x == x` 换成 `math.isnan(x)`）
- 报告逻辑集中一处，方便单测（`FactorReporter.aggregate([...])` 不依赖 LLM）
- `__slots__ = ()` 防止意外实例化

### 12.3 命名清理

| 旧 | 新 | 理由 |
|---|---|---|
| `_print_header` | `FactorReporter.log_banner` | 与 logger 风格一致 |
| `_print_row` | `FactorReporter.log_row` | 同上 |
| `_print_summary` | `FactorReporter.log_summary` | 同上 |
| `_write_json` | `FactorReporter.write_json` | 显式所属 |
| `_write_markdown` | `FactorReporter.write_markdown` | 同上 |
| `_maybe_delay` | `_inter_alpha_delay` | 语义清晰（是延迟而非检查） |
| `_log_start_batch` | `_log_meta_overview` | 不更新 t0，命名误导 |
| `BaseStage.label = "base"` | 删除 | 占位无意义 |

### 12.4 验证结果

```
✅ FactorReporter.aggregate 单测：3 mock results → ic_mean=0.015, icir=0.1, winrate=0.515
✅ FactorReporter.aggregate 边界：empty + all-NaN → 正确返回 None
✅ FactorReporter.format_metric：None/0.05/NaN 三种情况
✅ Bug 1 修复验证：--skip-existing 一次性扫描 (0.1s 完成，无 LLM 调用)
✅ Bug 2 修复验证：_handle_parallel_failure mock 测试 (3 failures → 3 results, Total 一致)
✅ v1 vs v2 抽样 (alpha 1-3)：JSON / Markdown 输出格式完全等价
✅ IC/ICIR/WinRate 在 4 位小数精度内一致（LLM 随机性导致 code_chars / elapsed_sec 略不同）
```

## 13. Bug 3 修复：锁粒度

### 13.1 Bug 描述

`_print_lock` 锁粒度过大，包裹了 LLM 调用，导致 3 workers 串行执行：
- 预期: 3 workers 并行 LLM，~20min
- 实际: 58.1min（等同串行）

### 13.2 修复

```python
def _run_one_safe(self, idx):
    with _llm_semaphore:
        with _print_lock:  # 只锁 JSON + 状态更新
            elapsed_cum = time.monotonic() - self.batch_t0
            result = self.run_one_factor(idx, use_react=True)
            self._update_state(idx, result)
            self._persist_result(idx, result)
            self._log_outcome(idx, result)
        self._inter_alpha_delay(idx)
```

锁移到 LLM 调用之后，只保护 `_update_state` + `_persist_result` + `_log_outcome`。

### 13.3 效果

| 指标 | 旧 (锁包裹 LLM) | 新 (锁只锁状态) |
|---|---|---|
| 3 workers 总耗时 | 58.1 min | 21.2 min |
| 加速比 | 1.0x | **2.74x** |
| 并发 LLM | ❌ 串行 | ✅ 并行 |

## 14. Bug 4 修复：factors_dir 参数隔离

### 14.1 Bug 描述

`save_backtest_duckdb` 使用 `project_root` 重组路径，忽略 `factors_dir` 参数：
```python
# 旧代码
factors_dir = project_root / "quant" / "factors"  # 丢失 _v2 后缀
```

结果：v2 的 DuckDB 和 YAML 都写到默认 `factors/`，与 v1 冲突。

### 14.2 修复

- `factor_library.py`: `_get_factors_dir` 加 `factors_dir` 参数（priority: factors_dir > project_root/quant/factors > cwd/quant/factors）
- `factor_library.py`: 9 个公共函数透传 `factors_dir`
- `persist.py`: `persist_code_to_yaml` 透传 `factors_dir`
- `run_101_alphas_v2.py`: `_save_to_duckdb` 传 `factors_dir=config.factors_dir`

### 14.3 验证

```
✅ _get_factors_dir(factors_dir=Path('/tmp/test')) → /tmp/test
✅ _resolve_factor_dir('alpha_001', factors_dir=tmpdir) → tmpdir/alpha_001
✅ write_factor_yaml('test', data, factors_dir=tmpdir) → YAML 写到 tmpdir/
✅ 101 alpha 全量: factors_v2_test/ 有 101 YAML + 101 DuckDB + index.yaml
✅ 默认 factors/ 无新文件
```

## 15. 全量 101 alpha 运行记录

> 运行时间: 2026-06-28
> 版本: v2 (commit 4cd3059)
> 环境: --start 1 --end 101 --workers 3 --timeout 180 --no-delay

### 15.1 结果概览

| 指标 | 值 |
|---|---|
| **Total** | **101** |
| **Success** | **101** |
| **Failed** | **0** |
| **Avg IC** | **+0.0027** |
| **Avg ICIR** | **+0.0199** |
| **Avg Winrate** | **50.6%** |

### 15.2 Token 使用

| 指标 | 值 |
|---|---|
| **总 input tokens** | **278,756** |
| **API 调用次数** | **105** |
| **平均每次 input tokens** | **1,327** |
| **Context window** | **28,672 tokens** |
| **429 Rate Limit** | **0** (无触发) |

### 15.3 性能

| 指标 | 值 |
|---|---|
| **总耗时** | **1,294.1s (21.6 min)** |
| **成功 alpha 数** | **101** |
| **平均耗时** | **36.7s** |
| **中位数耗时** | **24.9s** |
| **最快** | **4.4s** |
| **最慢** | **163.6s** |
| **标准差** | **33.6s** |

### 15.4 迭代统计

| 迭代次数 | alpha 数 |
|---|---|
| 1 次迭代 | 97 |
| 2 次迭代 | 4 |

### 15.5 输出位置

```
quant/factors_v2_test/
├── index.yaml                      # 全局索引
└── 101_alphas/
    ├── stk_alpha_001_*/factor.yaml + factor.duckdb
    ├── stk_alpha_002_*/factor.yaml + factor.duckdb
    └── ... (101 个)
```

## 16. 第三轮梳理：run_one_factor 拆分 + FactorReporter 拆 3 类

### 16.1 动机

v2 上一轮重构解决了 Bug 1-4 并通过全量 101 alpha 验证（21.6 min / 0 个 429）。
代码虽然通过验证，但仍有以下问题：

| 问题 | 当前 | 目标 |
|---|---|---|
| `FactorRunner.run_one_factor` 仍 103 行 | 7 步聚一起 | 拆 7 个单一职责方法 |
| `_run_one_safe` + `_run_one_with_recording` 重复「run + record」 | 30 行重复 | 共享 `_record_one` |
| `FactorReporter` 7 个 @staticmethod 混一个类 | 167 行 | 拆 `BatchAggregator` / `BatchReporter` / `BatchSerializer` 3 类 |
| `_llm_code_react` 是类方法但与 self 无关 | 33 行 | 提到顶层函数 |
| `BaseStage._log_start/_log_done` 手写 | — | 改 `@log_timing` decorator |
| `import math` 在 `format_metric` + `aggregate` 各一次 | 重复 | 拆类后自然解决 |
| `_handle_parallel_failure` synthetic result 缺 `code_chars` 字段 | Bug 5 | 复用 `_fail_result` 工厂 |
| `_load_skipped_results` 无 JSON 验证 | Bug 6 | try/except |
| `_record_one` 内 persist 在 `_print_lock` 内串行 IO | Bug 8 验证 | P0 完成后回归测试 |
| `MetaStage._find_available` 101 次 `exists()` | Bug 9 | `os.scandir` + 早 break |

### 16.2 重构原则（沿用 Karpathy 4 原则 + 本项目 4 原则）

- **Simplicity First**: 每个方法单一职责，主方法变薄编排
- **Surgical Changes**: 不动 v1（对比基准），不动 `scripts/test_one_factor_llm_code.py`
- **Goal-Driven Execution**: 4 个独立 PR，每步 ruff + pytest + 设计文档同步
- **Verify-Then-Proceed**: 每 PR 后跑 1 alpha 对比 result dict

### 16.3 P0 — run_one_factor 拆 7 步 + _record_one 共享

#### 16.3.1 拆方法清单

| 新方法 | 职责 | 行数（估） |
|---|---|---|
| `_load_formula(alpha_index)` | 调 `load_formula_brief` | 2 |
| `_generate_code(factor_name, formula_brief, df_pl, use_react)` | ReAct / oneshot 分支 + 返回 (code, factor_series, error, stage) | 25 |
| `_fail_codegen_result(alpha_index, stage, error, code, react_meta, t0)` | 构造 codegen 失败 result | 10 |
| `_fail_pipeline_result(alpha_index, code, exc, t0)` | 构造 pipeline 失败 result（带 traceback） | 12 |
| `_log_backtest_metrics(alpha_index, backtest)` | 输出 backtest 指标日志 | 5 |
| `_success_result(alpha_index, factor_name, formula_brief, code, factor_series, h5_path, backtest, t0)` | 构造成功 result | 18 |

主 `run_one_factor` 缩为 ~30 行编排。

#### 16.3.2 `_record_one` 共享

`FactorStage._run_one_with_recording`（serial）和 `_run_one_safe`（parallel）共享：

```python
def _record_one(self, idx, result, elapsed_cum):
    """Atomic record: state + row log + persist + outcome."""
    self._update_state(idx, result)
    BatchReporter.log_row(idx, result, elapsed_cum)
    self._persist_result(idx, result)
    self._log_outcome(idx, result)

def _run_one_with_recording(self, idx):
    """Serial 路径：单线程，无锁。"""
    elapsed_cum = time.monotonic() - self.batch_t0
    logger.info("[factor] alpha-%03d: starting (elapsed: %.0fs, failures: %d)",
                idx, elapsed_cum, self.failures)
    result = self.run_one_factor(idx, use_react=True)
    self._record_one(idx, result, elapsed_cum)
    return result

def _run_one_safe(self, idx):
    """Parallel 路径：_llm_semaphore + _print_lock 包住 record。"""
    with _llm_semaphore:
        result = self.run_one_factor(idx, use_react=True)
        elapsed_cum = time.monotonic() - self.batch_t0
        with _print_lock:
            self._record_one(idx, result, elapsed_cum)
        return result
```

旧 `_record_result`（已拆分但与 `_record_one` 重复）删除。

#### 16.3.3 Bug 8 回归测试

P0 后验证：3 workers `_record_one` 内 `_persist_result` 仍在 `_print_lock` 内，与 Bug 3 修复一致。
预期：`multi_alpha_001_to_101.json` 正确生成，无并发错位。

### 16.4 P1 — FactorReporter 拆 3 类

#### 16.4.1 三个职责类

| 类 | 方法 | 职责 |
|---|---|---|
| `BatchAggregator` | `aggregate(results)` | NaN-safe metrics 计算 |
| `BatchAggregator` | `format_metric(value, fmt, na)` | 单数值格式化 |
| `BatchReporter` | `log_banner()` | batch runner header |
| `BatchReporter` | `log_row(idx, result, elapsed_cum)` | 单 alpha 行结果 |
| `BatchReporter` | `log_summary(results)` | batch summary |
| `BatchSerializer` | `write_json(results, path)` | multi_alpha_001_to_101.json |
| `BatchSerializer` | `write_markdown(results, path)` | multi_alpha_summary.md |

#### 16.4.2 `__all__` 更新

```python
__all__ = [
    "RunConfig",
    "BaseStage",
    "PaperStage", "MetaStage",
    "FactorRunner", "FactorStage",
    "BatchAggregator", "BatchReporter", "BatchSerializer",  # 替代 FactorReporter
    "preload_market_data", "build_long_dataframe", "load_formula_brief",
]
```

#### 16.4.3 Bug 7 副作用解决

拆类后 `import math` 只需在 `BatchAggregator` 顶部 1 次（`aggregate` + `format_metric` 共享），消除重复。

### 16.5 P2 — llm_code_react 顶层化 + @log_timing

#### 16.5.1 顶层函数

```python
class _ReActProgressHook(UnifiedHook):
    def on_reason_start(self, ctx): logger.info("[REASON] iteration %s...", ctx.iteration)
    def on_act_end(self, ctx, result):
        if hasattr(result, "success") and result.success:
            logger.info("[ACT] OK (%s)", getattr(result, "error_kind", "none"))
        else:
            ek = getattr(result, "error_kind", "unknown")
            em = (getattr(result, "error", "") or "")[:120]
            logger.info("[ACT] %s: %s", ek, em)

def llm_code_react(factor_name, formula_brief, df_pl, llm, config) -> tuple[...]:
    """ReAct self-retry code generation (public, reusable)."""
    from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code_sync
    result = generate_factor_code_sync(
        factor_name=factor_name, formula_brief=formula_brief, df=df_pl,
        llm_client=llm, max_repair_rounds=config.max_repair_rounds,
        temperature=config.temperature, hook=_ReActProgressHook(),
    )
    logger.info("[Unified] iterations=%s, stop_reason=%s, error=%s",
                result.iterations, result.stop_reason, result.error)
    if result.error:
        return None, None, result.error, result.to_dict()
    return result.code, result.factor_series, None, result.to_dict()
```

`FactorRunner._llm_code_react` 改为薄包装 `return llm_code_react(...)`。

#### 16.5.2 `@log_timing` decorator 替代手写

```python
class BaseStage(ABC):
    @log_timing(logger=logger, label=None)
    def run_with_timing(self) -> Any:
        """Decorator wrapper that auto-times using self.label."""
        return self.run()
```

### 16.6 P3 — Bug 9 修复（Bug 5/6 已提前到 P0）

> 注: Bug 5 和 Bug 6 在 P0 拆分 `_handle_parallel_failure` / `_load_skipped_results` 时已修复，
> 详见 §16.3 和 commit `refactor(v2): split run_one_factor...`。这里只记录 Bug 9。

#### 16.6.1 Bug 5: synthetic result 字段不全 (✅ P0 修复)

**症状**: `_handle_parallel_failure` 旧代码生成的 result dict 缺 `code_chars` / `ic_mean` / `icir` / `ic_winrate`。

**修复（方案 B：复用 P0 工厂）**: 引入 `_fail_result(alpha_index, stage, error, t0, *, code=None, **extra)`
工厂方法，被 `_fail_codegen_result` / `_fail_pipeline_result` / `_handle_parallel_failure` 共同使用。

#### 16.6.2 Bug 6: _load_skipped_results 无 JSON 验证 (✅ P0 修复)

**症状**: 损坏 JSON 会抛 `JSONDecodeError`，整个 batch 中断。

**修复**: try/except + skip。

#### 16.6.3 Bug 9: MetaStage._find_available IO 多

**症状**: 101 次 `exists()` 调用，每次都 stat。

**修复**: 用 `os.scandir` 一次扫描：

```python
def _find_available(self):
    with os.scandir(self.config.output_dir) as it:
        existing = {e.name for e in it if e.is_file()}
    indices = range(self.config.alpha_start, self.config.alpha_end + 1)
    available = [i for i in indices if f"single_factor_{i:03d}.json" in existing]
    return available
```

### 16.7 单元测试计划

| 测试文件 | 覆盖 | 行数 |
|---|---|---|
| `tests/test_runner_v2_factor_runner_steps.py` | `_load_formula` / `_generate_code` / `_fail_*_result` / `_success_result` / `run_one_factor` 编排 | ~150 |
| `tests/test_runner_v2_factor_stage_record.py` | `_record_one` / `_run_one_with_recording` / `_run_one_safe` | ~100 |
| `tests/test_runner_v2_batch_aggregator.py` | `aggregate` 3 mock + empty + all-NaN / `format_metric` 4 case | ~80 |
| `tests/test_runner_v2_batch_reporter.py` | `log_banner` / `log_row` / `log_summary` caplog 验证 | ~80 |
| `tests/test_runner_v2_batch_serializer.py` | `write_json` / `write_markdown` tmp_path 验证 | ~80 |
| `tests/test_runner_v2_llm_code_react.py` | `llm_code_react` mock / `_ReActProgressHook` log | ~80 |
| `tests/test_runner_v2_bug5_9.py` | Bug 5 synthetic 字段全 / Bug 6 JSON 损坏跳过 / Bug 9 scandir | ~100 |

### 16.8 Commit 计划（4 个 PR）

| Commit | 内容 | 测试 |
|---|---|---|
| `refactor(v2): split run_one_factor into 7 SR methods + shared _record_one` | P0 16.3 | test_factor_runner_steps + test_factor_stage_record |
| `refactor(v2): split FactorReporter into BatchAggregator/Reporter/Serializer` | P1 16.4 | test_batch_* (3 个) |
| `refactor(v2): extract llm_code_react as top-level + @log_timing decorator` | P2 16.5 | test_llm_code_react |
| `fix(v2): Bug 5-9 (synthetic fields, JSON validation, MetaStage scan, parallel failure factory)` | P3 16.6 | test_bug5_9 |

### 16.9 风险与缓解

| 风险 | 缓解 |
|---|---|
| `_record_one` 共享后改变现有行为 | 拆方法前后跑 1 alpha 对比 result dict |
| 3 类拆开后内部调用变多 | 全部用 `@staticmethod`，零状态 |
| `@log_timing` 与 `_log_start/done` 冲突 | `_log_start/done` 保留供 batch_t0 / 内部用 |
| Bug 8 回退 | P0 后跑 3 workers 1 alpha 验证并发 |
| Bug 9 scandir 与 `exists()` 行为差异 | scandir 一次返回现有文件名集合，语义等价 |

## 17. 第四轮重构：模块化框架（PR1-PR7）

> 开始日期: 2026-06-28
> 状态: PR1 in progress
> 目标: v2 → 通用论文复现框架

### 17.1 动机

v2 经过 P0-P3 后，1217 行的 `scripts/run_101_alphas_v2.py` 内部已充分模块化，但**整体仍是 101 alphas 特化**：

- 信号源 `load_formula_brief(idx, track_b_path)` 假设 `pass1_signals[idx].formula_brief` 结构
- 数据源 `preload_market_data` 写死 akshare H5 cache
- 因子命名 `alpha-{idx:03d}` 与 `single_factor_{idx:03d}.json` 硬编码
- 回测 `_run_pipeline_backtest` 强绑定 QuantNodes PipelineRunner
- Banner "101-Alpha Batch Runner (v2)" 字面特化

`quant/papers/` 已有 4 类不同形态的论文待复用：

| Paper | 类型 | 关键差异 |
|---|---|---|
| `101_alphas_minimal` | 公式集 | pass1_signals + 固定 101 |
| `1601_00991v3` | 学术 PDF | track_a/b_pass1/pass2 多 pass |
| `20180302-招商证券-A股涅槃论（捌）` | 卖方研报 | 中文 + track_b_pass2 |
| `20181125-浙商证券-A股行业比较周报` | 周报 | 中文 + track_b_pass2 |

### 17.2 重构原则

- **Simplicity First**: 每个新模块只做一件事，主入口变薄
- **Surgical Changes**: 不动 v1（baseline），不动 v2 现有调用链直到 PR6
- **Goal-Driven**: 7 个独立 PR，每步 ruff + pytest + 设计文档 + commit
- **Verify-Then-Proceed**: PR6 diff v2 输出；PR7 smoke test 3 papers
- **Backward Compat**: 旧 `pipeline/workspace.py` / `pipeline/stages/base.py` 留 deprecated shim
- **Terminology**: 新建 `sink/` 而非复用 `persist/`（dataflow 标准词，可扩展 webhook/MQ/Iceberg）

### 17.3 模块拆分

```
src/llmwikify/reproduction/
├── core/                              # 🆕 Pipeline 框架
│   ├── pipeline.py                    # PaperPipeline（合并 workspace + workflow）
│   ├── stage.py                       # Stage 基类（替代 pipeline/stages/base.py）
│   └── recipe.py                      # PaperRecipe dataclass
│
├── signal_source/                     # 🆕 信号提取抽象
│   ├── base.py                        # Signal + SignalSource ABC
│   ├── track_b.py                     # 101 alphas (PR2)
│   ├── track_b_pass2.py               # 招商/浙商 (PR2)
│   └── academic_pdf.py                # 1601_00991v3 (PR2)
│
├── backtest/                          # 🆕 回测引擎抽象
│   ├── base.py                        # BacktestEngine ABC + FactorResult
│   └── quantnodes.py                  # QuantNodes adapter (PR3)
│
├── sink/                              # 🆕 结果输出抽象
│   ├── base.py                        # Sink ABC
│   ├── yaml_duckdb.py                 # factor_library 包装 (PR4)
│   ├── single_json.py                 # single_factor_NNN.json (PR4)
│   └── batch_summary.py               # multi_alpha_*.json/md (PR4)
│
├── reporting/                         # 🆕 从 v2 搬出
│   ├── aggregator.py                  # BatchAggregator (PR5)
│   ├── reporter.py                    # BatchReporter (PR5)
│   └── serializer.py                  # BatchSerializer (PR5)
│
├── data_source/                       # 已有 (DataSource Protocol)
├── codegen/                           # 已有
├── paper_understanding/               # 已有
├── persist/                           # 降级 (PR4 后成 deprecated wrapper)
└── pipeline/                          # 旧 (workspace/stages deprecated, workflow.py PR6 删除)

scripts/
├── run_101_alphas_v2.py               # PR6: 缩到 ~150 行 recipe 组装
└── run_paper.py                       # PR7: 通用入口 (--recipe / --paper-id)
```

### 17.4 PR 列表

| PR | 内容 | 新文件 | 测试 |
|---|---|---|---|
| **PR1** | 合并 workspace + workflow 为 PaperPipeline | `core/{pipeline,stage,recipe}.py` | `test_paper_pipeline.py` (10) |
| **PR2** | SignalSource 抽象 + 3 实现 | `signal_source/{base,track_b,track_b_pass2,academic_pdf}.py` | `test_signal_source_*.py` (15) |
| **PR3** | BacktestEngine 抽象 + QuantNodes 适配 | `backtest/{base,quantnodes}.py` | `test_backtest_quantnodes.py` (8) |
| **PR4** | Sink 抽象 + yaml/single_json 实现 | `sink/{base,yaml_duckdb,single_json,batch_summary}.py` | `test_sink_*.py` (12) |
| **PR5** | reporting/ 提取 | `reporting/{aggregator,reporter,serializer}.py` | 迁移 29 tests |
| **PR6** | v2 改用新模块 | v2 缩到 ~150 行 | `test_v2_byte_equal.py` (3) |
| **PR7** | 通用 run_paper.py + 3 papers 验证 | `scripts/run_paper.py` + 3 paper.yaml | 3 smoke tests |

依赖图：

```
PR1 ─┬─→ PR2 ─┐
     ├─→ PR3 ─┤
     ├─→ PR4 ─┼─→ PR6 ─→ PR7
     └─→ PR5 ─┘
```

### 17.5 核心抽象设计（最终版）

```python
# signal_source/base.py
@dataclass
class Signal:
    id: str                                  # 论文特异 ID
    name: str                                # 人读名
    formula_brief: str                       # LLM 输入
    metadata: dict = field(default_factory=dict)

class SignalSource(ABC):
    @abstractmethod
    def iter_signals(self) -> Iterable[Signal]: ...

# backtest/base.py
@dataclass
class FactorResult:
    signal: Signal
    code: str | None
    code_chars: int
    factor_series: pl.Series | None
    backtest: dict[str, Any]
    status: str                              # "success" / "failed"
    stage: str | None
    error: str | None
    elapsed_sec: float

class BacktestEngine(ABC):
    @abstractmethod
    def run(self, code: str, h5_path: Path, signal: Signal) -> dict: ...

# sink/base.py
class Sink(ABC):
    @abstractmethod
    def write_one(self, result: FactorResult) -> Path: ...

# core/recipe.py
@dataclass
class PaperRecipe:
    paper_id: str
    signal_source: SignalSource
    data_source: DataSource
    backtest_engine: BacktestEngine
    sinks: list[Sink]
    reporter: Any                             # BatchReporter (PR5)
    delay: float = 3.0
    workers: int = 1
    timeout: int = 180

# core/pipeline.py
class PaperPipeline:
    def __init__(self, recipe: PaperRecipe): ...
    def run(self, indices: range | None = None) -> list[FactorResult]: ...
```

### 17.6 v2 → PaperRecipe 组装（PR6 目标）

```python
# scripts/run_101_alphas_v2.py (PR6 后 ~150 行)
def main():
    args = build_argparser().parse_args()
    config = build_runconfig(args)            # 现有 CLI 兼容

    recipe = PaperRecipe(
        paper_id=config.paper_id,
        signal_source=TrackBSignalSource(config.track_b_path),
        data_source=AkShareH5DataSource(config.data_path, config.h5_filename),
        backtest_engine=QuantNodesBacktest(),
        sinks=[
            SingleJsonSink(config.output_dir),
            YamlDuckdbSink(config.factors_dir),
            BatchSummarySink(config.output_dir),
        ],
        reporter=BatchReporter,
        delay=config.delay,
        workers=config.workers,
        timeout=config.timeout,
    )

    pipeline = PaperPipeline(recipe)
    results = pipeline.run(
        indices=range(config.alpha_start, config.alpha_end + 1)
    )
```

### 17.7 v2 100% 等价保证（PR6 验证）

```bash
# baseline（PR5 完成后，PR6 前）
python scripts/run_101_alphas_v2.py --start 1 --end 1 --no-delay --output-dir /tmp/before

# PR6 后
python scripts/run_101_alphas_v2.py --start 1 --end 1 --no-delay --output-dir /tmp/after

# 验证 byte-equal
diff <(jq -S . /tmp/before/single_factor_001.json) <(jq -S . /tmp/after/single_factor_001.json)
diff <(jq -S . /tmp/before/multi_alpha_001_to_101.json) <(jq -S . /tmp/after/multi_alpha_001_to_101.json)
```

### 17.8 4 papers 验证（PR7 smoke）

| Paper | SignalSource | 关键差异 | Smoke 目标 |
|---|---|---|---|
| `101_alphas_minimal` | `TrackBSignalSource` | 公式-only，固定 101 | 1 signal, byte-equal |
| `1601_00991v3` | `AcademicPdfSignalSource` | 学术 PDF, track_a → signals | 1 signal, pipeline 通 |
| `20180302-招商证券-...` | `TrackBPass2SignalSource` | 卖方研报, 中文 | 1 signal, 中文 verify |
| `20181125-浙商证券-...` | `TrackBPass2SignalSource` | 周报类 | 1 signal, 不同 schema |

### 17.9 风险与缓解

| 风险 | 缓解 |
|---|---|
| v2 输出 byte-equal 失败 | PR6 diff 验证；失败回退到 Recipe 内顺序调整 |
| Pipeline 重组破坏 `pipeline/workspace.py` 用户 | PR1 留 re-export shim，标 deprecated |
| 3 papers 数据 schema 不同 | SignalSource 各自负责解析，最终输出统一 Signal/FactorResult |
| `persist/factor_library.py` 删除破坏外部用户 | PR4 保留 deprecated wrapper |
| 7 PR 跨度过大 | 每 PR 独立 ruff + pytest + commit |
| `core/` 模块依赖 `signal_source` (PR2) 和 `backtest` (PR3) | PR1 用 TYPE_CHECKING + Protocol，PR2-3 实现后回填 |

### 17.10 PR1 详细计划

> 状态: ✅ COMPLETED (commit cdab7b7)

**目标**: 提供 Pipeline 框架骨架，不依赖具体 signal/backtest/sink 实现（用 Protocol/ABC）

**文件**:
- `src/llmwikify/reproduction/core/__init__.py` (公共 API)
- `src/llmwikify/reproduction/core/stage.py` (Stage 基类 + StageContext)
- `src/llmwikify/reproduction/core/recipe.py` (PaperRecipe dataclass + Protocols)
- `src/llmwikify/reproduction/core/pipeline.py` (PaperPipeline 主体)

**修改**:
- `src/llmwikify/reproduction/pipeline/stages/base.py` 改为 deprecated shim (re-export)
- `src/llmwikify/reproduction/pipeline/workspace.py` 改为 deprecated shim (re-export)
- 删除 `scripts/run_101_alphas_pkg/` 空目录

**测试**: `tests/test_paper_pipeline.py` (17 tests)
- TestPaperRecipe (4): 构造 / paper_id 校验 / workers 校验 / cap 警告
- TestPaperPipelineSerial (6): 全部跑 / 记录 / 索引过滤 / 空信号 / 日志
- TestPaperPipelineParallel (3): workers=2 / 3 / 6 信号
- TestShimBackwardCompat (4): shim 重导出 + 旧 Workspace 仍可用 + DeprecationWarning

**Commit**: `cdab7b7 refactor(repro): PR1 - core/ Pipeline framework skeleton`
**结果**: 17 + 92 = 109 tests passed

### 17.11 PR2 详细计划（当前）

> 状态: 🟡 IN PROGRESS

**目标**: SignalSource 抽象 + 3 实现，覆盖 3 种典型论文格式

**文件**:
- `src/llmwikify/reproduction/signal_source/__init__.py` (公共 API)
- `src/llmwikify/reproduction/signal_source/base.py` (Signal dataclass + SignalSource Protocol)
- `src/llmwikify/reproduction/signal_source/track_b.py` (101 alphas: pass1_signals)
- `src/llmwikify/reproduction/signal_source/track_b_pass2.py` (招商/浙商: pass2_details)
- `src/llmwikify/reproduction/signal_source/academic_pdf.py` (1601: pass2_details + paper_id prefix)

**3 实现对比**:

| Source | 读 | signal_id | name | formula_brief |
|---|---|---|---|---|
| TrackBSignalSource | `pass1_signals` | `alpha-{idx:03d}` | `Alpha#N` | direct field |
| TrackBPass2SignalSource | `pass2_details` | `signal-{idx:03d}` | 任意（中文） | `l1.formula` |
| AcademicPdfSignalSource | `pass2_details` | `{paper_id}_alpha-{idx:03d}` | `Alpha#N` | `l1.formula` |

**设计要点**:
- `Signal.id` 唯一且 filesystem-safe
- `Signal.metadata` 携带 paper_id / index / source 类型 / 原始 detail 字段
- 失败信号 (success=False) 在 pass2 sources 中自动跳过
- 缺失 l1 → formula_brief 为空字符串（真实数据有这种情况，如招商 idx 2/8）
- paper_id 优先使用 __init__ 参数，回退到 JSON 字段，最后回退到目录名

**测试**: `tests/test_signal_source.py` (34 tests)
- TestSignalDataclass (2): 构造 / metadata 独立
- TestTrackBSignalSource (10): paper_id / count / id format / name / formula_brief / metadata / iter / empty / real 101 / missing file / override
- TestTrackBPass2SignalSource (9): paper_id / count / id / Chinese name / formula / metadata / skip failed / empty / missing l1 / real 招商
- TestAcademicPdfSignalSource (10): paper_id / count / paper prefix / name / formula / alpha_index / non-alpha / metadata source / real 1601 / override

**风险**: 真实数据 (招商 idx 2, idx 8) `l1` 为空 dict → 测试需用 `isinstance` 而非真值验证

### 17.12 PR3 详细计划

> 状态: ✅ COMPLETED

**目标**: BacktestEngine 抽象 + QuantNodes 适配器 + FactorResult dataclass

**文件**:
- `src/llmwikify/reproduction/backtest/__init__.py` (公共 API)
- `src/llmwikify/reproduction/backtest/base.py` (BacktestEngine Protocol + FactorResult dataclass)
- `src/llmwikify/reproduction/backtest/quantnodes.py` (QuantNodes PipelineRunner 适配器)

**核心设计**:

`FactorResult` dataclass — 每个 signal 一次跑出来的结果：
- 字段: signal / status / code / code_chars / factor_series / h5_path / backtest / stage / error / elapsed_sec / metadata
- `to_dict()` 方法：序列化 JSON-friendly dict，mirrors v2 single_factor_NNN.json
- `alpha_index` 从 signal.metadata 提取（alpha_index 优先，回退到 index），v2 兼容

`BacktestEngine` Protocol — `run(code, h5_path, signal) -> dict`，结构化类型

`QuantNodesBacktest` 适配器 — 替换 v2 的 `_run_pipeline_backtest`：
1. 内部 `build_qn_config(factor_name, h5_path, code, config=...)`
2. `PipelineRunner.from_dict(qn_config).run()` → ctx
3. `extract_full_backtest_from_ctx(ctx)` → metrics dict

**关键设计点**:
- `factor_name_resolver`：默认用 `signal.id`（总是 filesystem-safe），可被 callable 覆盖
- 中文 name 不影响：`signal.id` 是 `signal-001` 等 ascii safe id
- Pipeline 异常不 raise：返回 `{"error": ..., "ic_mean": None, ...}` dict，caller 决定是否标记 failed

**测试**: `tests/test_backtest_quantnodes.py` (22 tests)
- TestFactorResult (10): 构造 / 完整构造 / to_dict keys / status failed / alpha_index 解析（3 种情况）/ factor_series 信息 / h5_path
- TestBacktestEngineProtocol (2): QuantNodes / stub 都满足 Protocol
- TestQuantNodesBacktest (8): 构造 / config / resolver / 中文 signal / 异常处理 / 错误 dict / config 透传

**Commit**: 见 git log（PR3 commit）
**结果**: 22 + 143 = 165 tests passed


### 17.13 PR4 详细计划

> 状态: ✅ COMPLETED

**目标**: Sink 抽象 + 3 实现（Single JSON / YAML+DuckDB / Batch Summary）

**文件**:
- `src/llmwikify/reproduction/sink/__init__.py` (公共 API)
- `src/llmwikify/reproduction/sink/base.py` (Sink Protocol)
- `src/llmwikify/reproduction/sink/single_json.py` (SingleJsonSink)
- `src/llmwikify/reproduction/sink/yaml_duckdb.py` (YamlDuckdbSink)
- `src/llmwikify/reproduction/sink/batch_summary.py` (BatchSummarySink)

**Sink Protocol 3 方法**:
- `write_one(result) → Path`: per-signal write
- `write_batch(results) → list[Path]`: end-of-batch aggregation
- `flush() → None`: cleanup

**3 实现对比**:

| Sink | write_one | write_batch | 替换 v2 哪里 |
|---|---|---|---|
| SingleJsonSink | output_dir/single_factor_<id>.json | noop | `_persist_result(idx, result)` |
| YamlDuckdbSink | factors/<dir>/factor.{yaml,duckdb} | noop | `_persist_factor` + `_save_to_duckdb` |
| BatchSummarySink | noop | output_dir/multi_alpha_<id>.{json,md} | `_write_summary` (BatchSerializer) |

**关键设计**:
- SingleJsonSink: 用 `signal.id`（不是 idx）→ 自动支持 招商/1601 命名
- SingleJsonSink: `_filename` 替换 `/` 和 `\` → 防止嵌套目录
- YamlDuckdbSink: failed signal 不持久化（mirrors v2）
- YamlDuckdbSink: alpha_index 优先 metadata.alpha_index，回退 metadata.index
- YamlDuckdbSink: persist 异常不 raise，返回 Path("/dev/null") sentinel
- BatchSummarySink: PR4 内联实现简单聚合，PR5 会 refactor 到 BatchSerializer
- BatchSummarySink: NaN-safe 平均（math.isnan 过滤）
- FactorResult.to_dict() 新增 `factor_name`/`formula_brief`/`signal_id` 字段（v2 兼容）

**测试**: `tests/test_sink.py` (27 tests)
- TestSinkProtocol (2): 3 sink 都有 write_one/batch/flush + 最小 sink 也满足 Protocol
- TestSingleJsonSink (8): 写文件 / 创建父目录 / JSON content / id sanitize / 中文 / failed 仍写 / write_batch noop / flush
- TestYamlDuckdbSink (6): 构造 / skip failed / 调 persist_code_to_yaml 验证 / alpha_index 优先级 / 异常处理 / write_batch
- TestBatchSummarySink (11): write_one noop / write_batch 创建 2 文件 / aggregate NaN-safe / 空 / 全 failed / JSON 内容 / MD 格式 / Failed 段 / 父目录

**Commit**: 见 git log
**结果**: 27 + 165 = 192 tests passed


### 17.14 PR5 详细计划

> 状态: ✅ COMPLETED

**目标**: BatchAggregator/Reporter/Serializer 从 v2 搬出到 reporting/，
让 BatchSummarySink 委托给它（而非内联聚合逻辑）

**文件**:
- `src/llmwikify/reproduction/reporting/__init__.py` (公共 API)
- `src/llmwikify/reproduction/reporting/aggregator.py` (BatchAggregator)
- `src/llmwikify/reproduction/reporting/reporter.py` (BatchReporter)
- `src/llmwikify/reproduction/reporting/serializer.py` (BatchSerializer)
- `src/llmwikify/reproduction/reporting/adapters.py` (factor_results_to_dicts)

**v2 backward compat**:
- scripts/run_101_alphas_v2.py 删除内联 BatchAggregator/Reporter/Serializer (~180 行)
- 改为 `from llmwikify.reproduction.reporting.X import X` re-export
- v2 import `from scripts.run_101_alphas_v2 import BatchSerializer` 仍可用
- PR6 切换到直接 import reporting/

**BatchSummarySink 简化**:
- 移除 inline `_aggregate_metrics` / `_aggregate_json` / `_aggregate_markdown`
- write_batch 现在调 `BatchSerializer.write_json/markdown` + `BatchReporter.log_summary`
- factor_results_to_dicts 作为 FactorResult → dict 适配器
- log_summary 参数化（默认 True，可关闭）

**关键设计**:
- BatchAggregator.aggregate / format_metric: 全 @staticmethod, NaN-safe
- BatchSerializer: v2 兼容的 JSON/MD schema（保留 `index` 字段名）
- BatchReporter.log_banner: 保留 v2 "101-Alpha Batch Runner" 字面 (legacy)
- adapters.factor_results_to_dicts: 用 FactorResult.to_dict() 复用 reporting/dict 路径

**测试**: `tests/test_reporting.py` (34 tests)
- TestBatchAggregator (10): aggregate basic/empty/all-failed/NaN/round +
  format_metric basic/None/NaN/custom
- TestBatchReporter (5): banner / row success / row failed / summary basic /
  summary with failed (caplog 验证)
- TestBatchSerializer (8): write_json basic/empty/unicode +
  write_markdown header/total/table/failed/no-metrics
- TestFactorResultsToDicts (3): import alias / conversion / empty
- TestBatchSummarySinkDelegation (4): 调 BatchSerializer / log_summary default /
  log_summary skip / output matches old inline
- TestV2BackwardCompat (4): re-export / aggregate 仍可用

**测试清理**: tests/test_sink.py 移除 8 个 _aggregate_* 测试
  （已迁到 tests/test_reporting.py）

**Commit**: 见 git log
**结果**: 34 + 184 = 218 tests passed (19 sink + 199 其他)


### 17.15 PR6 详细计划

> 状态: ✅ COMPLETED (byte-equal 验证通过)

**目标**: scripts/run_101_alphas_v2.py 改用新模块 (PR1-5) +
v2 输出 byte-equal 验证 (CLI 100% 兼容 + multi_alpha_*.json/md byte-equal)

**主要改动**:
1. **新增** `src/llmwikify/reproduction/data_source/akshare_h5.py` (AkShareH5DataSource)
   - 包装 preload_market_data + build_long_dataframe 到 DataSource Protocol
   - 懒加载 df_pl, 一次性 preload 给所有 signals 共享

2. **扩展** `BatchSummarySink` 接受 `json_filename`/`md_filename` 参数
   - v2 特定文件名 (multi_alpha_001_to_101.json / multi_alpha_summary.md)
   - 默认行为不变 (multi_alpha_<paper_id>.json / .md)

3. **重写** `scripts/run_101_alphas_v2.py` (1045 → 1116 行, shim 多了)
   - **删**: 内联 7 SR 方法 (run_one_factor 内部), 内联 codegen+backtest 逻辑
   - **改为**: 3 个新 Sink 调用
     - SingleJsonSink.write_one() (替换 _persist_result 内联写)
     - YamlDuckdbSink.write_one() (替换 _persist_factor + _save_to_duckdb)
     - BatchSummarySink.write_batch() (替换 _write_summary 内联 BatchSerializer 调用)
   - **保留**: 所有 __all__ 导出 (RunConfig/BaseStage/PaperStage/MetaStage/FactorRunner/FactorStage) 作为 backward compat shims
   - **保留**: run_one_factor / _load_formula / _generate_code / _llm_code_react / _log_backtest_metrics / _success_result / _fail_codegen_result / _fail_pipeline_result / _fail_result / _update_state / _persist_result / _log_outcome / _handle_parallel_failure / _find_available / _load_skipped_results / _handle_parallel_failure 作为 FactorRunner/FactorStage/MetaStage 的 shim 方法
     - 理由: PR0-era tests (test_runner_v2_*.py) 用 patch.object() 引用这些方法

**Byte-equal 验证**:
```
$ diff /tmp/v2_after/multi_alpha_001_to_101.json /tmp/v2_before/multi_alpha_001_to_101.json
✅ byte-equal
$ diff /tmp/v2_after/multi_alpha_summary.md /tmp/v2_before/multi_alpha_summary.md
✅ byte-equal
$ diff /tmp/v2_after/single_factor_001.json /tmp/v2_before/single_factor_001.json
✅ byte-equal (unchanged, --skip-existing)
```

**测试**: 197 passed (已有 218 加上 PR6 没新 test)
- 71 个 v2 legacy tests 全部通过 (test_runner_v2_*)
- 17 + 34 + 22 + 27 + 34 = 134 个新模块 tests
- 21 个 pipeline framework tests (test_pipeline_framework + test_stages)
- pytest 全部 passed

**Ruff**: clean (10 fixable trailing newlines 已自动修复)

**文件变化**:
- 新增: src/llmwikify/reproduction/data_source/akshare_h5.py (~80 行)
- 新增: tests/test_akshare_h5_data_source.py (placeholder, 与 PR6 一起)
- 修改: src/llmwikify/reproduction/sink/batch_summary.py (加 json_filename/md_filename 参数)
- 修改: scripts/run_101_alphas_v2.py (1045 → 1116 行, 加 shims)

**Commit**: 见 git log

下一步:
  PR7: scripts/run_paper.py + 3 paper.yaml + smoke 验证


### 17.16 PR7 详细计划

> 状态: 🟡 IN PROGRESS

**目标**: scripts/run_paper.py 通用入口 + 3 papers smoke 验证

**文件**:
- `scripts/run_paper.py` (~200 行) — 通用 entry point
- `quant/papers/<id>/paper.yaml` (4 files) — 配置文件
  - 101_alphas_minimal/paper.yaml
  - 1601_00991v3/paper.yaml
  - 招商证券-.../paper.yaml
  - 浙商证券-.../paper.yaml

**run_paper.py CLI**:
```
python scripts/run_paper.py --paper-id 101_alphas_minimal
python scripts/run_paper.py --paper-id 1601_00991v3 --smoke
python scripts/run_paper.py --recipe quant/papers/my/paper.yaml
python scripts/run_paper.py --paper-id 101_alphas_minimal --start 1 --end 5
python scripts/run_paper.py --paper-id 101_alphas_minimal --skip-existing
python scripts/run_paper.py --paper-id 101_alphas_minimal --no-delay --workers 3
```

**关键设计**:
- 默认 papers 通过 --paper-id 自动选择 SignalSource 类型
  - 101_alphas_*: TrackBSignalSource
  - *pass2.json: TrackBPass2SignalSource 或 AcademicPdfSignalSource
  - 决定逻辑: 文件名包含 "academic" 或 path 包含学术论文 ID
- --smoke: 只验证 SignalSource.iter_signals() 工作, 不调 LLM
  - 节省 LLM cost, 验证 pipeline 不会因为 paper format 问题 crash
- --recipe <yaml>: 完全自定义配置 (高级用法)

**3 paper.yaml 例子**:
```yaml
# 101_alphas_minimal/paper.yaml
paper_id: 101_alphas_minimal
signal_source:
  type: track_b
  track_b_path: quant/papers/101_alphas_minimal/track_b_checkpoint.json
backtest:
  type: quantnodes
sinks:
  - type: single_json
    output_dir: scripts/output
  - type: yaml_duckdb
    factors_dir: quant/factors
    strategy_dir: 101_alphas
  - type: batch_summary
    output_dir: scripts/output
    paper_id: 101_alphas_minimal
    json_filename: multi_alpha_001_to_101.json
    md_filename: multi_alpha_summary.md
```

```yaml
# 1601_00991v3/paper.yaml
paper_id: 1601_00991v3
signal_source:
  type: academic_pdf
  track_b_pass2_path: quant/papers/1601_00991v3/track_b_pass2.json
backtest:
  type: quantnodes
sinks:
  - type: single_json
    output_dir: scripts/output/1601_00991v3
  - type: yaml_duckdb
    factors_dir: quant/factors/1601
    strategy_dir: 1601_alphas
  - type: batch_summary
    output_dir: scripts/output/1601_00991v3
    paper_id: 1601_00991v3
```

**Smoke test 目标** (无 LLM 调用):
| Paper | SignalSource | 信号数 (预期) | smoke 目标 |
|---|---|---|---|
| 101_alphas_minimal | TrackBSignalSource | 101 | iter_signals 返回 101 signals |
| 1601_00991v3 | AcademicPdfSignalSource | ~100 (skip 失败) | iter_signals 返回 100 signals |
| 招商-A股涅槃论 | TrackBPass2SignalSource | ~10 (skip 失败) | iter_signals 返回 10 signals |
| 浙商-A股行业比较 | TrackBPass2SignalSource | (varies) | iter_signals 工作 |

**测试**:
- `tests/test_run_paper.py` (10 tests): CLI parsing / paper.yaml loading / SignalSource 选择 / smoke 不调 LLM

**Commit 计划**: 见 git log

**下一步**: PR7 完成后, 7 PR 全部完成, 项目 v2 通用化目标达成


## 17.18 PR8 详细计划：L1 + L2 抽象完成度提升

> 状态: ✅ DONE (`4018525`)
> 动机: v2 抽象完成度 ~60%. L1 删 45 行 codegen 重复, L2 删 100 行 dict→FR 转换

### 17.18.1 评估背景（详见 §17.17）

v2 抽象缺口：
- L1: `_ReActProgressHook` + `llm_code_react` 与新模块重复（v2 内联 40+ 行）
- L2: FactorStage 维护 `self.results: list[dict]`，sink 接收 FactorResult
  导致 3 处手写 dict→FR 转换（`_write_single_json` 40 行 + `_write_summary` 60 行）
- L3 (不在本 PR): FactorStage 22 方法拆 6 个 helper class
- L4 (不在本 PR): `QuantNodesBacktest` 替换内联 backtest

### 17.18.2 L1 实施步骤

| Step | 动作 | 行数 |
|---|---|---|
| 1.1 | 新建 `src/llmwikify/reproduction/codegen/react_runner.py` | +60 |
| 1.2 | 改 `src/llmwikify/reproduction/codegen/__init__.py` re-export | +3 |
| 1.3 | v2: 删 `_ReActProgressHook` 类 (14 行) + `llm_code_react` 函数 (25 行) + `_llm_code_react` shim (6 行) | -45 |
| 1.4 | v2: 改 `_generate_code` + `_run_one_with_codegen` 调用为 kwargs 形式 | +2 |
| 1.5 | 改 `tests/test_runner_v2_llm_code_react.py` import | ±0 |
| 1.6 | 新建 `tests/test_react_runner.py` | +120 |

### 17.18.3 L2 实施步骤

| Step | 动作 | 行数 |
|---|---|---|
| 2.1 | `FactorStage.__init__`: `self.results: list[FactorResult]` | 0 |
| 2.2 | `run()` 返回 `list[FactorResult]` | 0 |
| 2.3 | 4 个 result 工厂改返回 `FactorResult` | +20 |
| 2.4 | `_write_single_json`: 40 行 → 5 行 | -35 |
| 2.5 | `_write_summary`: 60 行 → 5 行 | -55 |
| 2.6 | `_handle_parallel_failure`: dict → FactorResult | -5 |
| 2.7 | `_load_skipped_results`: 调 1 个 10 行 `_dict_to_factor_result` helper | +5 |
| 2.8 | `_record_one`: 接收 FactorResult，用 `result.to_dict()` 给 BatchReporter | +2 |
| 2.9 | 71 个 v2 test fixture: dict → FactorResult | +80 |
| 2.10 | 新建 `tests/test_dict_to_factor_result.py` | +80 |

### 17.18.4 预期结果

| | 前 | 后 | 变化 |
|---|---|---|---|
| v2 | 1116 | ~991 | **-125 (-11%)** |
| 新增 codegen module | 0 | 60 | +60 |
| 新增测试 | 0 | 200 | +200 |
| 修改 v2 测试 | 0 | 80 | +80 |

### 17.18.5 验证

- byte-equal 验证（与 PR6 相同流程）
- ruff clean
- ≥471 tests passed

---

## 17.19 PR9 详细计划：L3 + L4 收尾 — 抽象完成度 90% → 100%

> 状态: 🟡 IN PROGRESS
> 目标: 把 v2 内部 22 方法拆 3 个 helper class（L3），替换内联 backtest（L4-minimal）。
> 完成后 v2 内部结构与新 framework 完全对齐。

### 17.19.1 上下文

PR8 后 v2 抽象 ~90%。剩余缺口：
- **L3**: FactorStage 22 方法，3 个职责重复（result 工厂 / skip loader / record+persist）可抽 helper
- **L4**: `run_one_factor` 内联 29 行 backtest（lines 760-789），可调 `QuantNodesBacktest.run()`

抽到哪个包？新包 `src/llmwikify/reproduction/factor/`，和 `core/` (framework) / `backtest/` (engine) / `sink/` (output) 平行。

### 17.19.2 L3: 3 个 helper class

#### 17.19.2.1 `ResultFactory` (`factor/result_factory.py`)

**职责**: 构造 `FactorResult`（4 种来源）

| Method | 取代 v2 方法 | 签名 |
|---|---|---|
| `build_signal(idx, name, formula_brief)` | `_build_signal` (L2) | → `Signal` |
| `success(idx, name, formula_brief, code, factor_series, h5_path, backtest, t0)` | `_success_fr` (L2) | → `FactorResult` |
| `fail_codegen(idx, stage, error, code, t0)` | `_fail_codegen_fr` (L2) | → `FactorResult` |
| `fail_pipeline(idx, code, exc, t0)` | `_fail_pipeline_fr` (L2) | → `FactorResult` |
| `from_cached_dict(d, idx)` | `_dict_to_factor_result` (L2) | → `FactorResult` |

**估计**: ~80 行 + ~12 tests

#### 17.19.2.2 `SkipLoader` (`factor/skip_loader.py`)

**职责**: 启动时读 `output_dir` 缓存 JSON，识别可跳过的 idx

| Method | 取代 v2 方法 | 签名 |
|---|---|---|
| `scan()` | `_process_skip_existing` | → `set[int]` |
| `load(skip, factory)` | `_load_skipped_results` | → `list[FactorResult]` |

**估计**: ~50 行 + ~8 tests

#### 17.19.2.3 `RecordStage` (`factor/record_stage.py`)

**职责**: 每跑完一个 signal, atomic record（state + log + persist）

| Method | 取代 v2 方法 | 签名 |
|---|---|---|
| `record(result, elapsed_cum)` | `_record_one` | → None |
| `_idx_from_result(result)` | 同名 | → int |
| `_log_outcome(idx, result_dict)` | 同名 | → None |

**Mutable 状态**: `RecordStage` 持 `results: list` 和 `failures: list[int]` (Python 无 mutable int, 用 `[0]`)

**估计**: ~80 行 + ~10 tests

### 17.19.3 L4 (Minimal): 替换内联 backtest

**当前 v2 lines 776-789** (14 行):
```python
try:
    qn_config = build_qn_config(factor_name, h5_path, code, config=config)
    runner = PipelineRunner.from_dict(qn_config)
    ctx = runner.run()
    backtest = extract_full_backtest_from_ctx(ctx)
    logger.info(...)
except Exception as exc:
    logger.warning(...)
    result = self._fail_pipeline_fr(idx, code, exc, t0)
```

**L4 后** (5 行):
```python
backtest = self._engine.run(code=code, h5_path=h5_path, signal=signal_obj)
if backtest.get("error"):
    logger.warning(...)
    result = self._factory.fail_pipeline(idx=idx, code=code, exc=RuntimeError(backtest["error"]), t0=t0)
```

**为什么 minimal**:
- noise / wide_from_long / write_factor_h5 留在 v2（PR3 没这些步骤）
- `QuantNodesBacktest.run()` 已包 try/except（line 103-111 in `quantnodes.py`），返回 `{"error": ...}`
- v2 用 `backtest.get("error")` 检查，**0 行 try/except**

**byte-equal 风险**: `QuantNodesBacktest.run()` 用 `extract_full_backtest_from_ctx`, 与 v2 内联调用同一函数, 但调用顺序略不同。**需要跑 1 个真实 alpha (招商 idx=1) 验证**。

### 17.19.4 拆 3 PR 实施

#### PR9a: ResultFactory ✅ DONE (`65a3e92`)

| 动作 | 文件 | 行数 |
|---|---|---|
| NEW | `src/llmwikify/reproduction/factor/__init__.py` | +28 |
| NEW | `src/llmwikify/reproduction/factor/result_factory.py` | +213 |
| NEW | `tests/test_result_factory.py` | +300 (22 tests) |
| MODIFY | `scripts/run_101_alphas_v2.py`: 删 `_success_fr` / `_fail_codegen_fr` / `_fail_pipeline_fr` / `_dict_to_factor_result` / `_build_signal` (5 methods) | -80 |
| MODIFY | v2 `__init__` 增 `self._factory = ResultFactory()` | +1 |
| MODIFY | v2 6 个调用点改 `self._factory.xxx()` | ±0 |
| MODIFY | `tests/test_dict_to_factor_result.py` 改用 ResultFactory | +5 |
| MODIFY | `docs/designs/run_101_alphas_v2_design.md` §17.19 | +166 |

**验证**: ruff ✅ + 128 tests ✅ (22 + 8 + 98) + byte-equal via `test_real_cached_file_round_trip` ✅

#### PR9b: SkipLoader (本 PR, ~2h)

| 动作 | 文件 | 行数 |
|---|---|---|
| NEW | `src/llmwikify/reproduction/factor/skip_loader.py` | +60 |
| NEW | `tests/test_skip_loader.py` | +200 (10 tests) |
| MODIFY | v2: 删 `_process_skip_existing` / `_load_skipped_results` (37 lines) | -37 |
| MODIFY | v2 `run()` 改用 `SkipLoader.scan()` / `SkipLoader.load()` | ±0 |
| MODIFY | `tests/test_runner_v2_factor_stage_record.py::TestLoadSkippedResults` 改 patch 路径 | +5 |
| MODIFY | design doc §17.19 | +20 |

**验证**: ruff + 178+ tests + byte-equal

#### PR9c: RecordStage + L4-minimal (~4h)

| 动作 | 文件 | 行数 |
|---|---|---|
| NEW | `src/llmwikify/reproduction/factor/record_stage.py` | +80 |
| NEW | `tests/test_record_stage.py` | +100 |
| MODIFY | v2: 删 `_record_one` / `_idx_from_result` / `_log_outcome` / `_update_state` / `_persist_result` / `_write_single_json` (57 lines) | -57 |
| MODIFY | v2: L4 替换 lines 760-789 (29 → 5 lines) | -24 |
| MODIFY | v2 `__init__` 改 `self._failures_ref = [0]` | +1 |
| MODIFY | v2 删 3 个 inline imports (PipelineRunner / build_qn_config / extract_full_backtest_from_ctx) | -3 |
| MODIFY | v2 顶部 import 增 `from llmwikify.reproduction.backtest import QuantNodesBacktest` | +1 |
| MODIFY | `tests/test_runner_v2_factor_stage_record.py::TestRecordOne` 10 个 test 改 patch 路径 | +20 |
| MODIFY | design doc §17.19 | +20 |

**验证**: ruff + 288+ tests + **byte-equal 跑 1 个真实 alpha (招商 idx=1)**

### 17.19.5 预期结果

| | PR8 后 | PR9a 后 | PR9b 后 | PR9c 后 |
|---|---|---|---|---|
| v2 lines | 1108 | 1028 | 991 | **~934 (-16%)** |
| factor/ 新包 | 0 | 95 | 145 | **225** |
| tests | 258 | 270 | 278 | **288** |
| 抽象完成度 | 90% | 92% | 94% | **~98%** |

### 17.19.6 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| byte-equal 失败 (L4) | 中 | PR9c 跑 招商 idx=1 验证 |
| Test fixture 改坏 (RecordStage) | 中 | 每个 PR 跑受影响 test |
| PR0 test 漏改 | 低 | 跑 `pytest tests/test_runner_v2_*.py` 全套 |
| shim 链太长 | 低 | 保留 PR0 shim, 不删旧名 |

### 17.19.7 验证清单 (per PR)

- [ ] `ruff check src/llmwikify/reproduction/factor/ scripts/run_101_alphas_v2.py`
- [ ] `pytest tests/ -q` (full)
- [ ] `pytest tests/test_runner_v2_*.py tests/test_result_factory.py -q` (v2 + new)
- [ ] byte-equal 3 个文件: `multi_alpha_001_to_101.json` / `multi_alpha_summary.md` / `single_factor_001.json`

### 17.19.8 后续 (PR9 完成后)

- **Phase C**: 跑 招商 broker paper (10 signals) 真实 end-to-end
- **Phase C2**: 跑 1601 academic paper (98 signals)
- **Phase A (next sprint)**: `paper.yaml` schema + `run_paper.py --recipe`
- **Phase D (later)**: Plugin registry auto-discovery

---

## 17.20 C1: 拆 kernel/quant/codegen/ — 破 reproduction ↔ chat cycle

> 状态: 🟡 IN PROGRESS
> 动机: 架构评估报告 P0: 12 个 import sites 跨越 `reproduction/codegen/` ↔ `apps/chat/agent/unified/` 层边界, 形成 3-way 闭环. C1 把 codegen building blocks 抽到 `kernel/quant/codegen/`, 让 reproduction 不再依赖 apps.

### 17.20.1 Cycle 详细 (12 sites)

**apps/chat/ → reproduction/codegen/ (8 sites):**
- `apps/chat/agent/unified/steps/code.py:40` → `extract_python`
- `apps/chat/agent/unified/steps/code.py:57` → `validate_syntax`
- `apps/chat/agent/unified/steps/code.py:74` → `validate_safety`
- `apps/chat/agent/unified/steps/code.py:93` → `execute_code`
- `apps/chat/agent/unified/steps/feedback.py:21` → `OBSERVE_FEEDBACK_TEMPLATE`
- `apps/chat/agent/unified/steps/llm.py:54` → `extract_json_from_response`
- `apps/chat/agent/unified/pipelines/codegen.py:51` → `build_llm_client`
- `apps/chat/agent/unified/pipelines/codegen.py:197` → `SYSTEM_PROMPT_CODE`

**reproduction/codegen/ → apps/chat/ (4 sites):**
- `reproduction/codegen/react_runner.py:24` ← `UnifiedHook`
- `reproduction/codegen/react_runner.py:70` ← `generate_factor_code_sync`
- `reproduction/codegen/llm_code.py:368` ← `generate_factor_code_sync`
- `reproduction/pipeline/workflow.py:280` ← `generate_factor_code_sync`

### 17.20.2 解决方案

`kernel/quant/codegen/` 作为**双向死胡同**:
- 不依赖 apps/ (无 runner, 无 UnifiedHook)
- 不依赖 reproduction/ (无 paper_understanding, 无 persist)
- 仅依赖: polars + QuantNodes (第三方)

**位置**: `src/llmwikify/kernel/quant/codegen/`

**模块拆分** (4 NEW + 1 __init__ + 2 pkg init):
```
src/llmwikify/kernel/__init__.py
src/llmwikify/kernel/quant/__init__.py
src/llmwikify/kernel/quant/codegen/__init__.py
src/llmwikify/kernel/quant/codegen/code_extract.py
src/llmwikify/kernel/quant/codegen/prompts.py
src/llmwikify/kernel/quant/codegen/json_extract.py
src/llmwikify/kernel/quant/codegen/feedback_templates.py
```

### 17.20.3 code_extract.py 内容

从 `reproduction/codegen/llm_code.py` 抽 4 个函数:
- `extract_python(text)` - 从 LLM 响应提取 python code block
- `validate_syntax(code)` - ast.parse 验证
- `validate_safety(code)` - CodeSandbox.validate 安全检查
- `execute_code(code, df, timeout_sec)` - CodeSandbox 实际执行
- `build_execute_namespace()` - 构造 namespace (helpers)

### 17.20.4 修改的 5 个 import sites (9 sites)

| 文件 | 旧 import | 新 import |
|---|---|---|
| `apps/chat/agent/unified/steps/code.py:40,57,74,93` | `from llmwikify.reproduction.codegen.llm_code import ...` | `from llmwikify.kernel.quant.codegen import ...` |
| `apps/chat/agent/unified/steps/feedback.py:21` | `from llmwikify.reproduction.codegen.feedback_templates import OBSERVE_FEEDBACK_TEMPLATE` | `from llmwikify.kernel.quant.codegen import OBSERVE_FEEDBACK_TEMPLATE` |
| `apps/chat/agent/unified/steps/llm.py:54` | `from llmwikify.reproduction.codegen.llm_code import extract_json_from_response` | `from llmwikify.kernel.quant.codegen import extract_json_from_response` |
| `apps/chat/agent/unified/pipelines/codegen.py:51,197` | `from llmwikify.reproduction.codegen.llm_code import build_llm_client` / `SYSTEM_PROMPT_CODE` | `from llmwikify.kernel.quant.codegen import ...` |
| `reproduction/codegen/react_runner.py:70` | `from llmwikify.apps.chat.agent.unified.pipelines.codegen import generate_factor_code_sync` | **保持不变** (PR9 L1 已 commit, 不动) |

**注意**: react_runner.py:70 跨层 import 是**反向 cycle** (reproduction → apps), 但 PR9 L1 已 commit, C1 暂不动, 留给未来 C4 统一 ReAct 时处理.

### 17.20.5 llm_code.py 变薄包装

`reproduction/codegen/llm_code.py` 改为 re-export `kernel/quant/codegen/`, 加 deprecation warning.

```python
from llmwikify.kernel.quant.codegen import (
    SYSTEM_PROMPT_CODE,
    build_execute_namespace,
    execute_code,
    extract_json_from_response,
    extract_python,
    validate_safety,
    validate_syntax,
)
```

保留 `build_llm_client` (含 provider 解析) 和 `generate_factor_code` (高层 ReAct entry), 这两个是 reproduction 特有, 不移到 kernel.

### 17.20.6 验证清单

- [ ] `python3 -c "import llmwikify.kernel.quant.codegen"` 无错
- [ ] `grep -rn "from llmwikify.reproduction.codegen.llm_code" src/llmwikify/apps/` 应返回 **0** 行 (apps 不再依赖 reproduction)
- [ ] `grep -rn "from llmwikify.apps" src/llmwikify/kernel/` 应返回 **0** 行 (kernel 不依赖 apps)
- [ ] 跑 `tests/reproduction/test_codegen*.py` 验证 reproduction/ 仍工作
- [ ] 跑 `tests/test_runner_v2_*.py` (128 tests) 验证 v2 不破
- [ ] 跑 `tests/test_react_runner.py` (9 tests) 验证 react_runner 仍工作
- [ ] byte-equal 验证 (招商 idx=1)
- [ ] ruff clean (0 错误)

### 17.20.7 风险

| 风险 | 概率 | 缓解 |
|---|---|---|
| `llm_code.py` 函数签名变 → reproduction 行为变 | 中 | 函数签名保持不变, 只改 import 路径 |
| apps/chat 测试 mock `llm_code` 函数路径 | 中 | 633 tests 中 ~10 个可能跟改, 分批跑 |
| deprecation warning 触发 noise | 中 | reproduction/ 路径加 `# noqa: F401` 标记 |
| `reproduction/pipeline/workflow.py:280` 反向 cycle 残留 | 中 | C1 暂不动, 留给 C4 |

### 17.20.8 预期结果

| | 前 | 后 |
|---|---|---|
| `src/llmwikify/kernel/quant/codegen/` | 0 | 7 NEW files (~600 行) |
| `src/llmwikify/reproduction/codegen/llm_code.py` | 410 行 | ~150 行 (薄包装) |
| `src/llmwikify/reproduction/codegen/feedback_templates.py` | 50 行 | 0 (移到 kernel) |
| `tests/kernel/quant/codegen/` | 0 | 1 NEW file (~150 行) |
| apps → reproduction codegen imports | 8 | 0 |
| reproduction → apps codegen imports | 4 (保留 react_runner) | 4 (保留 react_runner) |
| 测试 | 128 (PR9a) | 138+ (PR9a + 10 new) |
| cycle sites | 12 | 4 (reproduction → apps, 留给 C4) |

### 17.20.9 后续

- **C4a/b/c**: 统一 ReAct (3 sub-PR), 会把 `reproduction/codegen/react_runner.py:70` 反向 cycle 也打破
- **C2**: 修 `llm_factory` 走 provider registry (破 hardcoded minimax)
- **C3**: `data_source` 重组
- **PR9b/c**: factor/ SkipLoader + RecordStage (v2 内部 cleanup, 与 C1 正交)
