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
- [ ] 拆分 `FactorRunner.run_one_factor` 内部 7 步骤为更小的方法
- [ ] 提取 `_llm_code_react` 和 `_run_pipeline_backtest` 为顶层函数
- [ ] 添加单元测试（每个 stage 一个测试文件）
- [ ] 验证 v1 与 v2 输出完全等价
