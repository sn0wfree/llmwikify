# Pass2Config v4.0 — 4-Layer Configuration Architecture

> Status: design (pre-implementation)
> Date: 2026-06-19
> Owner: Track B (paper reproduction pipeline)
> Branch: `refactor/pass2-config-v4`

## 1. Motivation

### 1.1 Symptom

强制 `PASS2_MODE_OVERRIDE=hybrid python3 ...` 跑招商-信贷周期 paper（14 signals）时，
hybrid 完整 run 与 parallel baseline 对比，**l3.intuition 反而下降**（87.6 → 77.2 chars，0.9x）。

但手工调用 `_run_pass2_adaptive(supplement_prompt)` 单独跑 supplement phase 时，
**3 个 targets 全部显著提升**（+136 ~ +226 chars）。

**矛盾**：完整 hybrid run 没提升，但 supplement phase 单独跑有显著提升。

### 1.2 Root Cause (Static Analysis)

`src/llmwikify/reproduction/llm_extraction/track_b.py:55`：
```python
PASS2_MODE_OVERRIDE = ""     # If set: "adaptive" | "parallel" | "serial" | "hybrid" | ""
```

**这是模块级常量，不是 `os.getenv(...)`**！env var 设置**完全无效**。

进一步 `track_b.py:57`：`ADAPTIVE_MIN_SIGNALS = 20` 强制 14 signals 走 parallel，
即使 Bug 1 修复，14 signals paper 仍被 `estimate_complexity()` 强制选 parallel。

### 1.3 Scale of Hardcoded Values

`track_b.py` 共 **33 个模块级常量** + **~20 个函数体内 magic numbers**。
`planner.py` / `track_a.py` / `retry.py` / `preview.py` 还有 **20+ 个**。
**总计 ~70+ 处硬编码**应参数化。

| 模块 | 模块常量 | 函数体内 magic numbers | 优先级 |
|------|---------|----------------------|--------|
| `track_b.py` | 33 | ~20 | P0 (核心 bug) |
| `planner.py` | 2 dict + 1 set | ~10 | P1 |
| `track_a.py` | 0 | 2 | P2 |
| `retry.py` | 0 | 5+ (RetryConfig 调用点) | P1 |
| `preview.py` | 0 | ~10 | P2 |

## 2. Design: 4-Layer Override Architecture

### 2.1 Layers

优先级从低到高：

| 层 | 来源 | 用途 | 示例 |
|----|------|------|------|
| **L0** | Python dataclass 默认值 | 基础默认值（代码内） | `batch_size: int = 3` |
| **L1** | `os.getenv("PASS2_*")` | shell 临时调整 / 脚本 | `PASS2_MODE_OVERRIDE=hybrid` |
| **L2** | `~/.llmwikify/llmwikify.json` 字段 | 用户持久化配置 | `{"pass2_config": {"mode_override": "hybrid"}}` |
| **L3** | CLI flag | 单次运行覆盖 | `--pass2-mode hybrid` |
| **L4** | 函数参数 `cfg: Pass2Config` | 编程 API 显式覆盖 | `run_one_paper(..., cfg=Pass2Config(mode_override="hybrid"))` |

**合并规则**：L_n 覆盖 L_{n-1}，同名字段以最高层为准。

### 2.2 Why 4 Layers

- **L0/L1**：最小改动，复用现有 env var 习惯（`AGENTS.md` 已规范 `api.minimaxi.com` ≤ 3 并发）
- **L2**：用户持久化偏好（`~/.llmwikify/llmwikify.json` 已存在）
- **L3**：单次调试友好，无需改文件
- **L4**：编程 API，向后兼容现有调用代码（`cfg=None` → 用默认 singleton）

### 2.3 Singleton Pattern

`config.py` 提供模块级单例：
```python
PASS2_CONFIG = Pass2Config.from_env()  # L0 + L1
```

函数签名：
```python
def select_pass2_mode(stubs, cfg: Pass2Config | None = None):
    cfg = cfg or PASS2_CONFIG
    ...
```

调用代码：
- CLI（reproduce_cmd）：构造 `PASS2_CONFIG.merge(L2_dict, L3_kwargs)`
- Orchestrator：`run_one_paper(..., cfg=user_cfg)`
- 测试：`Pass2Config(mode_override="hybrid")` 显式传入

## 3. Field Inventory (~50 fields)

### 3.1 Group: Adaptive Multi-Turn (v2.0)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `batch_size` | int | 3 | `PASS2_BATCH_SIZE` |
| `max_history_messages` | int | 20 | `PASS2_MAX_HISTORY_MESSAGES` |
| `max_supplements_per_signal` | int | 5 | `PASS2_MAX_SUPPLEMENTS_PER_SIGNAL` |
| `max_total_rounds` | int | 200 | `PASS2_MAX_TOTAL_ROUNDS` |

### 3.2 Group: Parallel
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `max_concurrency` | int | 3 | `PASS2_MAX_CONCURRENCY` |
| `checkpoint_batch_size` | int | 10 | `PASS2_CHECKPOINT_BATCH_SIZE` |

### 3.3 Group: Smart Mode Selection (v3.0)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `mode_auto` | bool | True | `PASS2_MODE_AUTO` |
| `mode_override` | str | "" | `PASS2_MODE_OVERRIDE` |
| `adaptive_min_signals` | int | 20 | `ADAPTIVE_MIN_SIGNALS` |
| `adaptive_max_signals` | int | 200 | `ADAPTIVE_MAX_SIGNALS` |
| `adaptive_avg_formula_len` | int | 80 | `ADAPTIVE_AVG_FORMULA_LEN` |
| `adaptive_avg_context_len` | int | 2000 | `ADAPTIVE_AVG_CONTEXT_LEN` |

### 3.4 Group: Hybrid Mode (v3.1)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `hybrid_enabled` | bool | True | `PASS2_HYBRID_ENABLED` |
| `hybrid_min_signals_auto` | int | 30 | `HYBRID_MIN_SIGNALS_AUTO` |
| `hybrid_intuition_threshold` | int | 150 | `HYBRID_INTUITION_THRESHOLD` |
| `hybrid_theoretical_min` | int | 50 | `HYBRID_THEORETICAL_MIN` |
| `hybrid_hypotheses_min` | int | 2 | `HYBRID_HYPOTHESES_MIN` |
| `hybrid_supplement_ratio` | float | 0.2 | `HYBRID_SUPPLEMENT_RATIO` |
| `hybrid_min_supplements` | int | 3 | `HYBRID_MIN_SUPPLEMENTS` |
| `hybrid_supplement_batch_size` | int | 4 | `HYBRID_SUPPLEMENT_BATCH_SIZE` |
| `hybrid_supplement_concurrency` | int | 3 | `HYBRID_SUPPLEMENT_CONCURRENCY` |
| `hybrid_supplement_use_specific_prompt` | bool | True | `HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT` |

### 3.5 Group: Success Rate / Retry
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `success_threshold_high` | float | 0.95 | `PASS2_SUCCESS_THRESHOLD_HIGH` |
| `success_threshold_low` | float | 0.80 | `PASS2_SUCCESS_THRESHOLD_LOW` |
| `max_retry_rounds` | int | 1 | `PASS2_MAX_RETRY_ROUNDS` |

### 3.6 Group: Pass 1 Multi-Turn
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `max_rounds` | int | 10 | `PASS1_MAX_ROUNDS` |
| `max_consecutive_zero` | int | 2 | `PASS1_MAX_CONSECUTIVE_ZERO` |
| `pass1_max_tokens_default` | int | 32000 | `PASS1_MAX_TOKENS_DEFAULT` |
| `pass1_max_tokens_fallback` | int | 16384 | `PASS1_MAX_TOKENS_FALLBACK` |

### 3.7 Group: Context Slicing (function-internal magic numbers)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `context_min_chars` | int | 50 | `CONTEXT_MIN_CHARS` |
| `fallback_slice_size` | int | 5000 | `FALLBACK_SLICE_SIZE` |

### 3.8 Group: Supplement Levels (a/b/c)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `level_a_chars` | int | 2000 | `LEVEL_A_CHARS` |
| `level_b_chars` | int | 7000 | `LEVEL_B_CHARS` |
| `level_b_anchor_offset` | int | 1000 | `LEVEL_B_ANCHOR_OFFSET` |
| `level_b_min_chars` | int | 5000 | `LEVEL_B_MIN_CHARS` |

### 3.9 Group: LLM Sampling
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `temperature` | float | 0.1 | `PASS2_TEMPERATURE` |

### 3.10 Group: Display Truncation (preview/log)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `preview_table_max_rows` | int | 30 | `PREVIEW_TABLE_MAX_ROWS` |
| `preview_table_max_kw` | int | 10 | `PREVIEW_TABLE_MAX_KW` |
| `preview_table_max_strat_chars` | int | 300 | `PREVIEW_TABLE_MAX_STRAT_CHARS` |
| `raw_response_preview_chars` | int | 1000 | `RAW_RESPONSE_PREVIEW_CHARS` |
| `issue_bullet_preview_chars` | int | 200 | `ISSUE_BULLET_PREVIEW_CHARS` |
| `suggestion_bullet_preview_chars` | int | 200 | `SUGGESTION_BULLET_PREVIEW_CHARS` |
| `revised_section_preview_chars` | int | 500 | `REVISED_SECTION_PREVIEW_CHARS` |

### 3.11 Group: Estimator Weights (`estimate_complexity`)
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `complexity_signal_weight_high` | float | 0.4 | `COMPLEXITY_SIGNAL_WEIGHT_HIGH` |
| `complexity_formula_weight_max` | float | 0.3 | `COMPLEXITY_FORMULA_WEIGHT_MAX` |
| `complexity_formula_divisor` | float | 300 | `COMPLEXITY_FORMULA_DIVISOR` |
| `complexity_context_threshold` | float | 1500 | `COMPLEXITY_CONTEXT_THRESHOLD` |
| `complexity_context_weight` | float | 0.3 | `COMPLEXITY_CONTEXT_WEIGHT` |

### 3.12 Group: Planner Token Budgets
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `planner_token_budget_default` | dict | {5 entries} | (use `from_dict` override) |
| `planner_token_budget_floor` | dict | {5 entries} | (use `from_dict` override) |
| `valid_schemas` | frozenset | {factor,signal,allocation,summary} | (constant) |

### 3.13 Group: Retry
| Field | Type | Default | Env Var |
|-------|------|---------|---------|
| `retry_max_attempts` | int | 3 | `RETRY_MAX_ATTEMPTS` |
| `retry_backoff_base` | float | 0.5 | `RETRY_BACKOFF_BASE` |

## 4. API Surface

### 4.1 `Pass2Config` (frozen dataclass)

```python
@dataclass(frozen=True)
class Pass2Config:
    """All Pass 2 tunable parameters (see field groups 3.1-3.13)."""
    batch_size: int = 3
    # ... ~50 fields ...

    @classmethod
    def from_env(cls, prefix: str = "PASS2_") -> "Pass2Config": ...

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Pass2Config": ...

    @classmethod
    def from_file(cls, path: str | Path) -> "Pass2Config": ...

    def merge(self, *overrides: "Pass2Config | dict") -> "Pass2Config": ...

    def to_dict(self) -> dict[str, Any]: ...

PASS2_CONFIG = Pass2Config.from_env()  # Module-level singleton (L0 + L1)
```

### 4.2 Migration Pattern (Existing Functions)

```python
# Before
def select_pass2_mode(stubs: list[SignalStub]) -> str:
    if PASS2_MODE_OVERRIDE:
        mode = PASS2_MODE_OVERRIDE.lower()
        if mode in ("adaptive", "parallel", "serial", "hybrid"):
            return mode
    if PASS2_MODE_AUTO:
        complexity = estimate_complexity(stubs)
        ...
        if (
            PASS2_HYBRID_ENABLED
            and complexity["recommendation"] == "adaptive"
            and complexity["signal_count"] >= 30
        ):
            return "hybrid"
        ...

# After
def select_pass2_mode(
    stubs: list[SignalStub],
    cfg: Pass2Config | None = None,
) -> str:
    cfg = cfg or PASS2_CONFIG
    if cfg.mode_override:
        mode = cfg.mode_override.lower()
        if mode in ("adaptive", "parallel", "serial", "hybrid"):
            logger.info("[track_b] pass2 mode: %s (override)", mode)
            return mode
    if cfg.mode_auto:
        complexity = estimate_complexity(stubs, cfg=cfg)
        ...
        if (
            cfg.hybrid_enabled
            and complexity["recommendation"] == "adaptive"
            and complexity["signal_count"] >= cfg.hybrid_min_signals_auto
        ):
            return "hybrid"
        ...
```

### 4.3 CLI Integration

```python
# reproduce_cmd.py
@click.option("--pass2-mode", type=click.Choice(["auto","adaptive","parallel","serial","hybrid"]))
@click.option("--max-concurrency", type=int)
@click.option("--pass2-config", type=click.Path(exists=True))
def single(ctx, ..., pass2_mode, max_concurrency, pass2_config):
    # Layer 4: explicit kwargs
    cli_overrides: dict = {}
    if pass2_mode:
        cli_overrides["mode_override"] = pass2_mode if pass2_mode != "auto" else ""
    if max_concurrency:
        cli_overrides["max_concurrency"] = max_concurrency

    # Layer 3: JSON file
    file_overrides: dict = {}
    if pass2_config:
        file_overrides = Pass2Config.from_file(pass2_config).to_dict()

    # Layer 2-4 merge
    cfg = PASS2_CONFIG.merge(file_overrides, cli_overrides)

    run_one_paper(..., cfg=cfg)
```

## 5. Backward Compatibility

### 5.1 Removed Module Constants

删除 `track_b.py` 模块级常量（33 个）：
- 所有现有 `from track_b import PASS2_BATCH_SIZE` 类引用**失效**
- 解决方案：`grep -r "from track_b import\|from .track_b import" src/ tests/` 全局搜索

### 5.2 Migration Strategy

1. **保留模块常量作为 deprecation shim**（临时）
   ```python
   # track_b.py (过渡期)
   import warnings
   def __getattr__(name: str):
       if name.startswith(("PASS2_", "HYBRID_", "ADAPTIVE_")):
           warnings.warn(
               f"{name} is deprecated, use PASS2_CONFIG.{name.lower()} instead",
               DeprecationWarning,
               stacklevel=2,
           )
           return getattr(PASS2_CONFIG, name.lower())
       raise AttributeError(name)
   ```
2. **更新所有调用点**用 `PASS2_CONFIG.field_name`
3. **删除 shim**

### 5.3 Test Compatibility

- `tests/reproduction/test_track_b_*.py` 中可能 import 模块常量
- 改为 `from llmwikify.reproduction.paper_understanding.llm_extraction.config import Pass2Config`
- 显式构造测试 fixture

## 6. Risk & Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| 现有测试 import 模块常量导致 ImportError | 高 | grep 全局搜索 + deprecation shim |
| env var 命名冲突（v0.4 已用 PASS2_*） | 中 | 沿用现有命名 + README 文档化 |
| `frozen=True` + `dict` 字段不兼容 | 低 | `field(default_factory=dict)` + dataclasses.replace |
| 多层 merge 优先级混乱 | 中 | 单测 4 层覆盖 + 文档明示 |
| `os.getenv` 在 import 时读取（不可变） | 低 | `from_env()` 显式调用，singleton 在模块级 |

## 7. Implementation Plan (~3.5 hours)

| Step | Description | Estimate |
|------|-------------|----------|
| 0 | Bug 1 修复：PASS2_MODE_OVERRIDE 改读 env var + 验证 | 5 min |
| 1 | 新建 `config.py` - Pass2Config dataclass + 4-layer override | 30 min |
| 2 | 替换 `track_b.py` - 删模块常量 + 函数体内 magic numbers | 45 min |
| 3 | 替换 `planner.py` - DEFAULT_TOKEN_BUDGET / TOKEN_BUDGET_FLOOR | 15 min |
| 4 | 替换 `track_a.py` - default_max | 5 min |
| 5 | Retry 装饰器 - DEFAULT_RETRY_CONFIG | 10 min |
| 6 | CLI 参数化 - --pass2-mode / --pass2-config | 30 min |
| 7 | 测试 - test_pass2_config.py + 更新现有测试 | 45 min |
| 8 | 文档 - README + pipeline_optimization_summary.md v4.0 | 20 min |
| 9 | Commit 链 - 9 个独立 commit | 5 min |
| **Total** | | **~3.5h** |

## 8. Commit Chain

1. `docs(reproduction): v4.0 Pass2Config design` （本设计文档）
2. `fix(track_b): PASS2_MODE_OVERRIDE read from env var` (Step 0)
3. `feat(config): Pass2Config dataclass with 4-layer override` (Step 1)
4. `refactor(track_b): migrate module constants to Pass2Config` (Step 2)
5. `refactor(planner): migrate token budgets to Pass2Config` (Step 3)
6. `refactor(track_a): use Pass2Config for default_max` (Step 4)
7. `refactor(retry): DEFAULT_RETRY_CONFIG` (Step 5)
8. `feat(cli): --pass2-mode/--pass2-config flags` (Step 6)
9. `test(config): 4-layer override coverage` (Step 7)
10. `docs(reproduction): configuration guide` (Step 8)

## 9. Verification Strategy

1. **Step 0**：`PASS2_MODE_OVERRIDE=hybrid python3 ...` 跑招商-信贷周期，验证：
   - 日志输出 `[track_b] pass2 mode: hybrid (override)`
   - 总时长 ≈ parallel + supplement
   - l3.intuition 显著提升

2. **Step 1-7**：跑 `pytest tests/reproduction/ tests/test_reproduce_cli.py`
   - 期望 605+ 现有测试通过 + 新增 config 测试 ~150 通过

3. **Step 6**：手工跑 CLI 测试覆盖
   - `llmwikify reproduce single paper.pdf --pass2-mode hybrid`
   - `llmwikify reproduce single paper.pdf --pass2-config config.json`

4. **端到端**：跑 1 个真实 paper（招商-信贷周期）确认行为等价 + 可覆盖

## 10. Future Work (v4.1+)

- [ ] 添加 `validate_schemas` / `validate_token_budget` 字段类型检查
- [ ] YAML config 格式支持（除 JSON）
- [ ] 配置文件加载在 `~/.llmwikify/configs/pass2.yaml`
- [ ] `Pass2Config` 可序列化为 JSON 用于 A/B 测试结果保存
- [ ] 集成到 `llmwikify doctor` 检查配置合法性