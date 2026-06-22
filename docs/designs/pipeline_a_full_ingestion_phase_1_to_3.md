# Pipeline A 入库 + 回测数据持久化 (Phase 1-3)

> 日期: 2026-06-22
> 作者: sn0wfree
> 状态: 设计稿 (Phase 0 已 commit: cd28265)

## 背景

### 现状

| 路径 | 状态 | 问题 |
|------|------|------|
| `scripts/run_101_alphas.py` (Pipeline A) | ✅ 56/56 success | 只输出 JSON, 不入库 |
| `scripts/stage_c_e2e_smoke.py` (Pipeline B AST) | ❌ 9/9 extract failure | AST 抽取坏, 0 个 alpha 入库 |
| `quant/factors/` | 5 个 stub YAML | 真正数据 0 个 |
| WebUI FactorDetail L5 图表 | 空 (DB 无 row) | "暂无回测结果" |

### 用户要求

> "现在要求 a 必须有完整的流程，包括入库"
> "回测的哪些因子是否保存了回测的各种数据，方便展示"
> "全部满足 (Phase 1+2+3): ~200 行, ~50min 总耗时, 完整因子页面"

### WebUI 实际数据需求 (read-only 验证)

`FactorDetail.tsx` + `FactorPanel.tsx` L5 Tab 实际读取:

| 字段 | 来源 | 缺失 |
|------|------|------|
| `l5.overall_assessment.{score,status,pass_threshold,final_meaning}` | YAML | ✅ 缺, 需改 schema |
| `runs[].metrics.{ic_mean,rank_ic_mean,icir,rank_icir,win_rate,annual_return,longshort_ann_return,longshort_sharpe,longshort_max_dd}` | DB sessions 表 | ✅ 缺, 需写 DB |
| `runs[].ic_series[]` (date-level IC for ICChart) | DB sessions | ✅ 缺 |
| `runs[].group_metrics{G1-G5:{sharpe,max_drawdown,win_rate,turnover,n_stocks}}` | DB sessions | ✅ 缺 |
| `l1.{definition,formula,input_columns,frequency,output_schema,nan_meaning,default_params,param_constraints,business_constraints}` | YAML | 缺 5 字段 |
| `l2.calculation_steps[]` | YAML | ✅ 缺 |
| `l3.{financial_intuition,...}` | YAML | ✅ 缺 |
| `l4.hypotheses[]` | YAML | ✅ 缺 |
| `l5.hypothesis_testing[]` | YAML | ✅ 缺 |
| `l6.{failure_conditions,...}` | YAML | ✅ 缺 |

## 设计目标

让 56 个 PipelineRunner 验证过的 alpha 在 WebUI 因子页面 (L1-L6 + 图表) 完整显示。

### 不在范围内

- ❌ Pipeline B (AST 路径) — Stage C 9/9 失败待另修
- ❌ Pass7 3 modified files — 用户已选"先不动"
- ❌ wiki markdown 同步 — 已 deprecated, 走 WebUI
- ❌ l2-l4 LLM 提取复用 — 必须每次重跑 (无缓存)

## 复用清单 (零造轮子)

| 已有 | 用法 | 位置 |
|------|------|------|
| `factor_library.write_factor_yaml()` | YAML 写入 + 自动 update index.yaml | `factor_library.py:74` |
| `factor_library.read_factor_yaml()` | 读现有 YAML (update 模式) | `factor_library.py:51` |
| `factor_library.list_factors_by_category()` | 列因子 (按 category 分组) | `factor_library.py:102` |
| `persist_l5_to_yaml` 模式 | 模仿其"读→改→写→telemetry" | `factor_compiler.py:574` |
| `sessions.ReproductionDatabase.save_result()` | DB sessions 写入 | `sessions.py:415` |
| `_persist_factor_result` 模板 | DB 写入 + wiki markdown 模式 | `factor.py:225` |
| `run_l5_pipeline()` | L5 hypothesis 自动化 (含 7 analysis + scoring + LLM) | `factor.py:543` |
| `stage_c_e2e_smoke.py` LLM 调用模式 | 借鉴 throttle (3 并发 + sleep 0.3s) | `stage_c_e2e_smoke.py:142` |
| `ICChart`, `GroupReturnBar`, `GroupMetricsTable` | 图表组件 (WebUI 现成) | `ui/webui/src/components/` |

## 阶段划分

### Phase 0: WebUI Bug 修复 (✅ 已 commit cd28265)

**改动**:
- `FactorSelector.tsx`: 改调 `/api/factor/library/list`, flatten categories, 改文案
- `factor.py` docstring: 列出全部 8 端点, 消除"wiki pages"误导

**结果**: 单因子测试页面从 "No factors found" 变为显示 5 个现有 YAML

### Phase 1: L5 综合评估 + 回测图表

**目标**: WebUI L5 Tab 显示完整数据 (8 metric cards + ICChart + GroupReturnBar + GroupMetricsTable + OverallAssessment)

**改动** `scripts/test_one_factor_llm_code.py`:

1. **扩展 ctx 解析** (line 640-650):
   - `ctx["ICAnalyzer"]["ic_series"]` → date-level IC list
   - `ctx["GroupAnalyzer"]["fac_group"]` → 计算 per-group metrics
   - `ctx["LongShort"]` 或类似节点 → longshort 4 字段

2. **`persist_code_to_yaml()`** 新 helper (模仿 `persist_l5_to_yaml` 模式):
   - 调 `factor_library.read_factor_yaml(name)` 读已有
   - 更新 `l5.overall_assessment` 为 WebUI 4 字段:
     - `score` = `clamp(50 + round(icir * 50), 0, 100)`
     - `status` = "通过" (icir>0.1) / "失败" (icir<-0.05) / "待更新"
     - `pass_threshold` = 60
     - `final_meaning` = "" (Phase 3 填)
   - 写 `l5.code` + `l5.code_compile_status` + `l5.code_chars` + `l5.h5_path` + `l5.ast = null`
   - 清理 `l5.ast_compile_status` / `l5.ast_compile_iterations` (失败 stub 痕迹)
   - 调 `factor_library.write_factor_yaml(name, data)` 写

3. **写 DB sessions** (新加):
   ```python
   from llmwikify.reproduction.sessions import ReproductionDatabase
   db = ReproductionDatabase()
   db.save_result(
       run_id=f"pipeline_{alpha_index:03d}",
       session_id=f"pipeline_runner_{alpha_index:03d}",
       result_type="factor_backtest",
       factor_ref=f"alpha_{alpha_index:03d}",
       strategy_ref=None,
       metrics={
           "ic_mean": ic_mean, "icir": icir, "win_rate": ic_winrate,
           "rank_ic_mean": ..., "rank_icir": ..., "annual_return": ...,
           "longshort_ann_return": ..., "longshort_sharpe": ...,
           "longshort_max_dd": ...,
       },
       ic_series=ic_series,        # [{date, ic}, ...]
       group_metrics=group_metrics,  # JSON string
       n_stocks_per_date=...,
       start_date=..., end_date=..., universe=..., adj_mode=...,
   )
   ```

4. **Hook 到 `run_one_factor`**: success return 前调 `persist_code_to_yaml` + `db.save_result`

**工作量**: ~50 行, ~50min (PipelineRunner 重跑 56 alpha × ~55s + sleep 3s)

### Phase 2: L1 字段补全 (无 LLM)

**改动** `persist_code_to_yaml`:

从 formula_brief + defaults 推导:
- `l1.input_columns` = `["open", "high", "low", "close", "volume", "returns", "vwap"]` (formula_brief 含这些 token)
- `l1.nan_meaning` = "上市不足或窗口期数据不足"
- `l1.default_params` = `{}`
- `l1.param_constraints` = `{}`
- `l1.business_constraints` = "支持日频调仓, T+1 信号"

**工作量**: ~15 行, 0 LLM 耗时

### Phase 3: L2-L6 LLM 提取

**目标**: WebUI L2-L6 Tab 不再显示 "EmptyLayer"

**新建** `src/llmwikify/reproduction/factor_extractor.py`:

```python
def extract_factor_metadata(formula_brief: str, code: str) -> dict:
    """Single LLM call returns L2/L3/L4/L6 structured JSON."""
    # Prompt: "Given this alpha formula + Python implementation,
    #   produce structured JSON with:
    #   - l2.calculation_steps: [{step, description, formula}, ...]
    #   - l3.financial_intuition, market_behavior, theoretical_basis, ...
    #   - l4.hypotheses: [{id, name, description, expected_ic_sign}, ...]
    #   - l6.failure_conditions, risk_notes"
```

**改动** `scripts/run_101_alphas.py`:

加 `--llm-extract` 模式:
- 3 并发 (api.minimaxi.com throttle 限制)
- 56 alpha × ~60s / 3 = ~19min
- 读 `single_factor_NNN.json` 拿 formula_brief + code
- 调 `extract_factor_metadata()` 拿 L2-L6 JSON
- 调 `factor_library.write_factor_yaml()` 增量更新 L2-L6

**L5.hypothesis_testing**:
- 调 `run_l5_pipeline(slug)` (`factor.py:543`) 自动化
- 已含 7 analysis + scoring + LLM hypothesis 验证
- 自动写回 `l5.hypothesis_testing[]`

**工作量**: ~120 行, ~19min (3 并发)

## 文件改动总览

| 文件 | Phase | 改动 |
|------|-------|------|
| `ui/webui/src/components/shared/FactorSelector.tsx` | 0 | ✅ committed (cd28265) |
| `src/llmwikify/interfaces/server/http/factor.py` | 0 | ✅ committed (cd28265, 仅 docstring) |
| `scripts/test_one_factor_llm_code.py` | 1, 2 | +65 行 (ctx 解析 + persist_code_to_yaml + DB 写 + L1 推导) |
| `scripts/run_101_alphas.py` | 1, 3 | +30 行 (--yaml-from-json + --llm-extract 模式) |
| `src/llmwikify/reproduction/factor_extractor.py` | 3 | 新建 +90 行 (LLM prompt + parser + 并发调度) |

## 验证清单

### Phase 1 完成后

- [ ] 56 个 `quant/factors/alpha_NNN.yaml` 存在
- [ ] `quant/factors/index.yaml` total = 5 + 56 = 61
- [ ] 每 YAML `l5.overall_assessment.score ∈ [0, 100]`
- [ ] 每 YAML `l5.overall_assessment.status ∈ {通过, 失败, 待更新}`
- [ ] DB sessions 表 = 56 行 (`factor_ref = 'alpha_NNN'`)
- [ ] DB 每行有 `ic_series` (非空 JSON) + `group_metrics` (非空 JSON)
- [ ] 浏览器 `/factor/alpha_001` 显示 ICChart + GroupReturnBar + 8 metric cards

### Phase 2 完成后

- [ ] 每 YAML `l1.*` 9 字段非空

### Phase 3 完成后

- [ ] 每 YAML `l2.calculation_steps` 长度 ≥ 1
- [ ] 每 YAML `l3.financial_intuition` 非空
- [ ] 每 YAML `l4.hypotheses` 长度 ≥ 1
- [ ] 每 YAML `l5.hypothesis_testing` 长度 ≥ 1
- [ ] 每 YAML `l6.failure_conditions` 非空
- [ ] 浏览器 6 个 Tab 全部有内容 (无 EmptyLayer)

## 执行顺序

1. Phase 1 + 2: 一次性改 `run_one_factor`, 重跑 56 alpha (~50min)
2. Phase 3: 单独 `--llm-extract` 模式跑 19min
3. 总验证: 浏览器逐个 alpha 检查 6 Tab

## 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| PipelineRunner 重跑遇 throttle (api.minimaxi.com) | 高 | 3 并发 + sleep 3s (run_101_alphas.py 默认) |
| LLM 提取 JSON 格式错 | 中 | parser 容错 + 失败重试 1 次 |
| `run_l5_pipeline` 内部 LLM hypothesis 失败 | 中 | 已有 fail-tolerant, 无 LLM 时跳过 |
| DB schema 字段不匹配 | 低 | 复用 `_persist_factor_result` 已验证 schema |
| L5 score 算法不准 | 中 | 用 ICIR 简单线性映射, 0-100 clamp |
| LLM Code 重跑超时 | 低 | sleep 3s × 56 = 168s + 实际 ~50min |

## 未来扩展 (本轮不做)

- L4.hypothesis 来源: 当前用 LLM 生成, 未来可改"LLM + 公式语义匹配"
- L5.score 算法: 当前用 ICIR, 未来可加权 (IC + ICIR + WinRate + AnnualReturn)
- WebUI factor 列表 filter: 当前 flat list, 未来可按 category 分组显示
- LLM extraction cache: 当前每次重跑, 未来可按 (formula_brief, code) hash 缓存