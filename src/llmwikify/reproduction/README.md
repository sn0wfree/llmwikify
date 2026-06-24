# Paper Reproduction Pipeline

> LLM-driven paper → factor metadata extraction. v3.2 hybrid mode (2026-06-19).
> **20-phase refactor complete** (2026-06-24): 8 subpackages, 0 top-level files.

## Module Structure

```
reproduction/
├── common/              # 基础设施 (config, paths, errors, utils, llm_factory)
├── data_source/         # 数据源 (router, universe, akshare, clickhouse, ifind)
├── codegen/             # 代码生成 (llm_code, react_engine, compiler, repair, semantic, metadata)
│   └── ast/             # AST 处理 (compiler, nodes, complexity, extractor)
├── prompts/             # Prompt 系统 (group, registry, loader, renderer, store)
│   └── builtin/         # 内置模板 (code_gen, react_feedback, metadata_extract, track_a/b, hypothesis_test, risk_analyze)
├── backtest_pkg/        # 回测 (factor_backtest, run_backtest, metrics, strategies, l5_validation, l5_orchestrator, factor_value_store, quantnodes_repro)
├── persist/             # 持久化 (factor_library, sessions, run)
├── paper_understanding/ # 论文理解 (extract_paper, extract_factors, extract_strategy, quant_wiki, schemas, contracts)
│   └── llm_extraction/  # LLM 提取 (orchestrator, planner, track_a, track_b, validator, ...)
└── pipeline/            # 流水线框架 (config, runner, workspace, react, stages/)
```

## Quick Start

### Process a single paper

```bash
llmwikify reproduce single /path/to/paper.pdf
```

Output: `{wiki_root}/quant/papers/{paper_id}/`

```
parsed.md             # Stage 0 (PDF → markdown)
plan.json             # Stage 1 (sections + schema + token_budget)
track_a.json          # Track A tier-1 + tier-2 metadata
track_b_pass1.json    # Pass 1: signal enumeration (101 alphas → 101 signals)
track_b_pass2.json    # Pass 2: per-factor L1-L4 details
preview.md            # Human-readable summary
```

### Batch process a directory

```bash
llmwikify reproduce batch /path/to/papers/ \
  --workers 3 \
  --skip-existing \
  --output {wiki_root}/quant/papers
```

Options:
- `--limit N` — process only first N PDFs
- `--workers N` — concurrent workers (1=sequential)
- `--skip-existing` / `--no-skip-existing` — skip papers with existing `preview.md`
- `--no-pass2` — skip Track B Pass 2 (only Stage 0/1 + Pass 1)
- `--json` — output structured JSON to stdout

## Pipeline Stages

### Stage 0 — Ingest (PDF → markdown)

Uses MarkItDown to convert PDF → `parsed.md`. Cache hit = 0ms.

### Stage 1 — Section Detection + Planning

- **Call 1:** LLM identifies sections (16-section typology).
- **Call 2:** LLM classifies paper into `summary` / `factor` / `signal` / `allocation` schema, plans token budget, validates with self-feedback replan (up to 2 attempts).

### Track A — Paper-Level Metadata

Tier 1 (schema-specific) + Tier 2 (5-section narrative). Serial LLM calls.

### Track B — Factor-Level Extraction

Two passes:

#### Pass 1: Enumerate Signals

Single multi-turn LLM call. `max_tokens=32000` for up to ~200 signals.
Returns `SignalStub` list with `name`, `formula_brief`, `context_excerpt` (≥ 2000 chars each).

#### Pass 2: Extract L1-L4 Per Signal

L1 (Logic): definition, formula, input_columns, frequency, constraints
L2 (Calculation): step-by-step pipeline, edge cases, complexity
L3 (Financial Understanding): intuition, market behavior, theoretical basis
L4 (Meaning): testable hypotheses with expected IC sign

**Modes (smart auto-select, `PASS2_MODE_AUTO=True`):**

| Mode | When | Speed | Depth |
|------|------|-------|-------|
| **parallel** | Complex papers (>20 signals, complex formulas) | ⭐⭐⭐ | ⭐⭐ |
| **adaptive** | Simple papers (<20 signals, simple formulas, long context) | ⭐ | ⭐⭐⭐ |
| **hybrid** | 30+ signals where adaptive would help | ⭐⭐ | ⭐⭐⭐ |

Manual override:
```bash
PASS2_MODE_OVERRIDE=parallel llmwikify reproduce single paper.pdf
PASS2_MODE_OVERRIDE=adaptive llmwikify reproduce single paper.pdf
PASS2_MODE_OVERRIDE=hybrid llmwikify reproduce single paper.pdf
```

## v3.2 Hybrid Mode (Recommended)

> **Achievement: 8.7-17.1x depth improvement on shallow factors.**

Hybrid mode combines parallel speed with adaptive depth:

1. **Phase 1: Parallel** (3 concurrent) — extract L1-L4 for all signals. ~30 min for 101 alphas.
2. **Assess** — for each factor, compute shallow_score based on:
   - `l3.financial_intuition` < 150 chars
   - `l3.theoretical_basis` < 50 chars
   - `l4.hypotheses` count < 2
3. **Select** — bottom 20% (or min 3) most shallow factors.
4. **Phase 2: Supplement** — re-extract shallow factors with `PROMPT_PASS2_SUPPLEMENT`:
   - **Required lengths:** intuition ≥ 200, theoretical ≥ 80, market_behavior ≥ 100 chars
   - **No nulls:** all L3 fields must be substantive
   - **No need_more_context:** context already provided
   - **≥ 3 hypotheses** each with priority + source
5. **Merge** — replace original shallow factors with supplement versions.

### A/B Results (101 Formulaic Alphas)

| Metric | v3.0 Parallel | v3.2 Hybrid | Improvement |
|--------|---------------|-------------|-------------|
| l3.intuition (supplement only, 20 targets) | 74.8 chars | **649.6 chars** | **8.7x** |
| l3.theoretical (supplement only) | 30.0 chars | **512.5 chars** | **17.1x** |
| l4.hypotheses (supplement only) | 2.6 | **5.0** | **1.9x** |
| Overall l3.intuition (101 signals) | 107.1 chars | **218.8 chars** | **2.0x** |
| Overall success rate | 99/101 | **101/101** | +2 |
| Total time | 33.7 min | ~55 min | +63% |

20/20 supplement targets significantly improved (max +1021 chars).

See `docs/summaries/pipeline_optimization_summary.md` for full history.

## Configuration

All v3.2 hybrid config (in `paper_understanding/llm_extraction/track_b.py`):

```python
# Smart mode selection
PASS2_MODE_AUTO = True           # Auto-select based on complexity
PASS2_MODE_OVERRIDE = ""         # Force mode: "adaptive" | "parallel" | "hybrid" | ""

# Complexity thresholds (for auto-select)
ADAPTIVE_MIN_SIGNALS = 20        # < 20 → parallel
ADAPTIVE_MAX_SIGNALS = 200       # > 200 → parallel
ADAPTIVE_AVG_FORMULA_LEN = 80    # > 80 → parallel
ADAPTIVE_AVG_CONTEXT_LEN = 2000  # < 2000 → parallel

# Hybrid supplement
PASS2_HYBRID_ENABLED = True
HYBRID_INTUITION_THRESHOLD = 150
HYBRID_THEORETICAL_MIN = 50
HYBRID_HYPOTHESES_MIN = 2
HYBRID_SUPPLEMENT_RATIO = 0.2    # Supplement 20% of factors
HYBRID_MIN_SUPPLEMENTS = 3
HYBRID_SUPPLEMENT_USE_SPECIFIC_PROMPT = True  # Use PROMPT_PASS2_SUPPLEMENT
```

## Output Schema (per factor)

```yaml
factor_id: Alpha#52
paper_id: 1601.00991v3
l1:
  definition: "捕捉动量 regime switching..."
  formula: "rank(...) - 0.5"
  input_columns: [returns, close]
  frequency: 日频
l2:
  calculation_steps: [...]
  complexity: O(n log n)
l3:
  financial_intuition: "≥ 200 chars in Chinese"
  market_behavior: "≥ 100 chars"
  theoretical_basis: "≥ 80 chars"
  related_factors: "≥ 50 chars"
l4:
  hypotheses:
    - id: H1
      name: 动量崩溃反转假设
      description: ≥ 30 chars
      expected_ic_sign: 正
      source: 行为金融学：动量崩溃后超卖反转
      priority: 主假设
```

## Tested Papers

| Paper | Signals | Mode | Time | Success | Notes |
|-------|---------|------|------|---------|-------|
| 101 Formulaic Alphas (v3.0) | 101 | parallel | 33.7 min | 99/101 | baseline |
| 101 Formulaic Alphas (v3.2 hybrid) | 101 | hybrid | ~55 min | **101/101** | +20 supplement targets depth 8.7-17.1x |
| 天风证券-20160803 | 15 | parallel | 5.86 min | 20/21 | schema=allocation, 15 signals |

## API Reference

```python
from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper

result = run_one_paper(
    paper_id="my_paper",
    source_path="path/to/paper.pdf",
    output_root=Path("quant/papers"),
    run_pass2=True,
    llm_client=None,  # auto-build default client
)
# Returns: dict with success, n_signals, n_pass2_complete, etc.
```

## Related

- `docs/designs/pipeline_framework.md` — 20-phase refactor design + implementation summary
- `docs/designs/paper_extraction_pipeline.md` — pipeline design
- `docs/designs/adaptive_pass2_multiturn.md` — adaptive mode design
- `docs/summaries/pipeline_optimization_summary.md` — optimization history (v1 → v3.2)
- `docs/plan/paper-reproduction.md` — implementation plan

## Refactor Status

**20-phase refactor complete** (2026-06-24):

| Gate | Phase | Status | Verification |
|------|-------|--------|--------------|
| G1 | Phase 3 | ✅ | 91/91 import compatibility tests |
| G4 | Phase 12B | ✅ | 16 files moved, internal imports pass |
| **G5** | **Phase 14F2** | ✅ | **99/99 alpha e2e, 1313 unit tests** |

- **Unit tests**: 1313 passed, 0 failed, 13 skipped
- **E2E**: 99 alpha all completed (H5 + YAML)
- **Commits**: 18 (each independently revertable)
- **Module**: 8 subpackages, 0 top-level files