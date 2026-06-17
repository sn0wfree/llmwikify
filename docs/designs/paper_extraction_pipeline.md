# Paper Extraction Pipeline 设计方案

> 基于本项目 6 层因子框架的论文自动抽取 pipeline。
>
> **状态**: 设计完成，待实施
> **目标**: 将 `~/Public/strategy/raw/` 下 111 个 PDF 论文抽取为结构化数据
> **最后更新**: 2026-06-17

## 1. 目标

将 `~/Public/strategy/raw/` 下的 **111 个 PDF 量化研究论文** 抽取为结构化数据（factor / signal / rule / summary），输出到 `quant/papers/{id}/`，由用户/API 显式触发。

**关键问题**：
- 101 Alphas 类大论文的 JSON 截断
- 行业轮动类论文（~85 篇）的小 signal 抽取
- 启示录/复盘类（~32 篇）的纯文本总结
- PDF 解析、LLM 失败、缓存复用

## 2. 设计原则

| 原则 | 来源 |
|---|---|
| 不要怕浪费 token | 用户决策 |
| 跨 section signal 增量合并（lifecycle）| 用户决策（Q2C）|
| 单 paper 内 3 路并发 | 用户决策（Q4）|
| 失败 signal 用 3 层重试 + deferred 队列 | 用户决策（Q5）|
| 大量借鉴 `wiki.ingest` | 用户决策 |
| 不自动入库 `quant/factors/` | 用户决策（Hybrid 暂存）|
| 取消批处理，per-paper 触发 | 用户决策（Q3 修订）|
| 两个独立提取逻辑：factor 逻辑 + paper/strategy 逻辑 | 用户决策 |
| 动态 max_tokens 由 Planner LLM 决定 | 用户决策 |

## 3. 整体架构

```
用户/API 触发 POST /api/paper/extract/{id}
              ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 0: Ingest (复用 wiki.ingest_source)                    │
│   - extract() 自动检测格式 (PDF/DOCX/URL/MD...)              │
│   - extract_section_metadata() 得到 page 级 sections         │
│   - _generate_lint_hint() 预检（过短/已存在/图片）            │
│   - 源文件存到 raw/{paper_id}.pdf（与 wiki 通用源文件混用）   │
│   - 后续 Stage 1-4 输出统一到 quant/papers/{paper_id}/       │
│   - 不写入 wiki/（AGENTS.md 量化研究 ≠ 通用知识）            │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 1: Plan (LLM, 2 calls)                                 │
│                                                               │
│   ├─ Call 1: Section Detector                                │
│   │   输入: parsed.md 全文（保留 MarkItDown 原始格式）        │
│   │   输出: sections[] (id, title, level,                     │
│   │                   char_start, char_end)                   │
│   │   max_tokens: 4096-8192                                    │
│   │   写入: plan.json.sections                                 │
│   │                                                            │
│   └─ Call 2: Planner                                          │
│       输入: sections + parsed.md 全文 + title                 │
│       输出: {                                                  │
│         schema_choice, paper_type, n_signals_estimate,         │
│         extraction_strategy, token_budget                     │
│         (LLM-decided dynamic max_tokens),                     │
│         temperature, confidence                                │
│       }                                                        │
│       max_tokens: 1024-2560                                    │
│       写入: plan.json.plan                                     │
│                                                                │
│   re-plan: confidence < 0.6 → Call 2 再调一次                  │
│   Call 1 失败 → 退到"无 sections"模式（Call 2 仍执行）         │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 2: Extract (LLM, dual-track)                            │
│                                                               │
│   ├─ 轨道 A: Paper/Strategy-level                            │
│   │   ├─ Tier 1 (8 sections, max_tokens=3072-6144)           │
│   │   │   paper_metadata, abstract_summary,                  │
│   │   │   strategy_logic, data_requirements,                 │
│   │   │   operation_steps, model_framework,                  │
│   │   │   strengths_weaknesses, suggested_signal              │
│   │   │                                                      │
│   │   └─ Tier 2 (5 sections, max_tokens=2048-4096)           │
│   │       backtest_spec, performance_claimed,                │
│   │       risk_analysis, implementation_assessment,          │
│   │       datasets                                            │
│   │                                                           │
│   └─ 轨道 B: Factor-level (if enabled)                       │
│       ├─ Pass 1: Enumerate (max_tokens=2048-4096)            │
│       │   → [name, formula, ...] × N                          │
│       │                                                      │
│       └─ Pass 2: Detail (3 路并发, max_tokens=4096-8192)     │
│           → for each signal: L1-L4                            │
│           → lifecycle: pending → extracted → complete/        │
│             partial/deferred/incomplete                       │
│                                                               │
│   失败: 3 层重试 → deferred 队列 → 全文上下文兜底             │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 3: Validate                                             │
│   - schema 校验（必填字段）                                    │
│   - LLM 自检（"是否完整"，max_tokens=1024-2048）              │
│   - 缺字段：定向 retry 最多 2 次                              │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────┐
│ Stage 4: Save                                                 │
│   - result.yaml (status: complete/partial/incomplete)          │
│   - plan.json (含 token_budget)                               │
│   - extraction.log                                             │
│   - llm_calls.jsonl (每次 LLM 一行)                           │
│   - preview.md (max_tokens=1536-3072)                         │
│   - factors/ (draft YAML)                                     │
└──────────────────────────────────────────────────────────────┘
```

## 4. 借鉴 wiki.ingest 清单（节省 7h）

| 来源文件 | 函数 | 用在 |
|---|---|---|
| `kernel/wiki/mixins/io/ingest.py:229` | `ingest_source()` | Stage 0 统一入口 |
| `kernel/wiki/mixins/io/ingest.py:111` | `targeted_read()` | Stage 2 字符切片（改为按 char_start/end）|
| `kernel/wiki/mixins/io/ingest.py:195` | `_generate_lint_hint()` | Stage 0 预检 |
| `foundation/extractors/__init__.py:67` | `extract()` | Stage 0 多格式分发 |
| `foundation/extractors/markitdown_extractor.py` | MarkItDown | 多格式支持（含 PDF markdown 提取）|

**说明**：原计划复用 `extract_section_metadata()` 给 Stage 1 输入，但**实测不适用 PDF**（仅匹配 markdown `#` 标题，PDF 纯文本无此结构）。改为 **Stage 1 Call 1 由 LLM 主动识别 sections**，不需要本地启发式 helper。

## 5. Signal Lifecycle 状态机

```
                  ┌─→ complete (success, all fields)
                  │
pending → extracted ─┼─→ partial (some optional fields missing)
   │        │       │
   │        │       └─→ deferred (3 layers all failed)
   │        │              │
   │        │              └─→ re-extract with full context
   │        │                       │
   │        │                       ├─→ complete
   │        │                       └─→ incomplete (all failed)
   │        │
   │        └─→ retry (current layer, max 2)
   │
   └─→ (enumeration stage)
```

**6 个状态**：pending / extracted / complete / partial / deferred / incomplete

## 6. 失败层级处理（L1-L5）

| 层级 | 场景 | 处理策略 |
|---|---|---|
| **L1** 单 signal LLM 失败 | 超时/JSON 截断 | 3 层重试（每层 2 次）→ deferred |
| **L2** Pass 1 估错 | 实际 signal < plan × 0.5 | re-plan |
| **L3** Planner 失败 | plan JSON 解析失败 | 重试 1 次（temp=0）→ Fallback default plan |
| **L4** PDF 提取失败 | 加密 PDF / 扫描件 | 换 MarkItDown → skip 标记 |
| **L5** 大面积失败 | 连续 N 个 deferred | 早停标记 `partial_extraction` |

## 7. 3 层重试策略

```
Layer 1: 同参重试
  - temperature: 0.1
  - max_tokens: Planner 估算值
  - attempts: 2

Layer 2: 异参重试
  - temperature: 0.0
  - max_tokens: Planner 估算值 × 1.5 (clamp to max)
  - 简化 prompt
  - attempts: 2

Layer 3: 全文上下文重抽
  - 给 LLM 整篇 paper 内容
  - 指定该 signal 的位置（从 signal_section_map）
  - max_tokens: max
  - attempts: 1

全部失败 → 标记 deferred → 进 Stage 2 末尾的 deferred 队列
```

**Stage 1 Call 1 失败处理**：
- Call 1 失败 → 退到"无 sections"模式
- Call 2 仍执行（基于全文）
- Stage 2 用**全文切片**（不用 `targeted_read` 按 sections 取）
- `result.yaml` 标记 `sections_detected: false`

## 8. Schema 库（4 个）

| Schema | 适用 | Track A | Track B | 触发 |
|---|---|---|---|---|
| `factor` | 101 Alphas 类 (8 篇) | Tier 1 + Tier 2 全开 | ✓ (N=100+) | n_signals > 20 |
| `signal` | 轮动/择时/风格 (85 篇) | Tier 1 + Tier 2 部分 | ✓ (N=1-5) | n_signals 3-20 |
| `allocation` | 资产配置 (30 篇) | Tier 1 + Tier 2 部分 | ✓ (N=1-3 rules) | 含"配置/资产" |
| `summary` | 启示录/复盘 (32 篇) | Tier 1 + Tier 2 (仅 implementation) | ✗ | n_signals < 3 |

## 9. Track A 字段（双层结构）

### Tier 1 - 核心层（必抽，max_tokens=3072-6144）

| Section | 字段 |
|---|---|
| **`paper_metadata`** (NEW) | title, authors, institution, date, doi, keywords, paper_subtype (academic/industry_report/internal/working_paper) |
| **`abstract_summary`** (NEW) | one_sentence, three_bullets, main_contribution, main_finding |
| **`strategy_logic`** (增强) | core_hypothesis, market_logic, alpha_source, applicable_conditions, market_regime, long_short_bias, holding_period_estimate, capacity_estimate |
| **`data_requirements`** (增强) | fields, frequency, universe, data_source, data_quality, survivorship_handling, look_ahead_prevention, liquidity_filter |
| **`operation_steps`** (增强) | signal_generation, position_sizing, rebalance_frequency, stop_loss, stop_profit, transaction_cost, rebalance_threshold, position_count, leverage |
| **`model_framework`** (保持) | model_type, framework, validation, evaluation_metrics, complexity_rating, reproducibility_score |
| **`strengths_weaknesses`** (保持) | strengths, weaknesses, improvement_directions |
| **`suggested_signal`** (保持) | signal_type, signal_params, strategy_class, confidence, reasoning |

### Tier 2 - 详情层（按需抽，max_tokens=2048-4096/section，5 个独立 prompt）

| Section | 字段 | 触发条件 |
|---|---|---|
| `backtest_spec` | in_sample_period, out_of_sample_period, benchmark, transaction_cost_model, slippage_model, initial_capital, position_sizing_method | 论文含具体回测 |
| `performance_claimed` | annual_return, sharpe_ratio, max_drawdown, win_rate, ic_mean, ic_ir, turnover, source, caveat | **全部 schema 抽**（加 warning）|
| `risk_analysis` | regime_risk (bull/bear/sideways), tail_risk, crowding_risk, decay_risk, capacity_risk, assumption_risks | 论文含风险讨论 |
| `implementation_assessment` | implementation_complexity, data_availability, code_reusability, typical_use_case, estimated_effort_days | 始终抽 |
| `datasets` | name, source, time_range, processing | 论文有具体数据集 |

**5 个独立 prompt 文件**：
- `repro_extract_tier2_backtest.yaml`
- `repro_extract_tier2_performance.yaml`
- `repro_extract_tier2_risk.yaml`
- `repro_extract_tier2_implementation.yaml`
- `repro_extract_tier2_datasets.yaml`

## 10. 缓存策略

### 决策表

| 缓存状态 | `force_replan=false` | `force_replan=true` |
|---|---|---|
| 不存在 | 全新抽取 | 全新抽取 |
| `complete` | **返回缓存** | 重抽 |
| `partial` | **返回缓存 + warning** | 重抽 |
| `incomplete` | **自动重抽** | 重抽 |
| 未知 | 重抽 | 重抽 |

### 缓存命中响应

```json
// partial 状态
{
    "paper_id": "abc",
    "status": "cached",
    "result": {
        "status": "partial",
        "n_signals": 5,
        "n_complete": 3,
        "n_incomplete": 2,
        "...": "..."
    },
    "extracted_at": "2026-06-17T10:30:00",
    "warning": "extraction was partial, 2 signals incomplete",
    "force_replan_suggested": true,
    "incomplete_signals": [
        {"name": "signal_3", "reason": "llm_timeout"},
        {"name": "signal_4", "reason": "json_truncated"}
    ]
}

// complete 状态
{
    "paper_id": "abc",
    "status": "cached",
    "result": {...},
    "extracted_at": "...",
    "warning": null,
    "force_replan_suggested": false,
    "incomplete_signals": []
}
```

### 重抽响应（异步）

```json
{
    "paper_id": "abc",
    "status": "started",        // 或 "restarted"（incomplete 自动重抽时）
    "job_id": "job_xyz",
    "force_replan": true
}
```

## 11. 异步执行（Job 状态机）

```
POST /api/paper/extract/{paper_id}
  → 立即返回 {job_id, status: "started"}
  → 后台异步执行

Job 状态：pending → running → completed / failed / cancelled

GET /api/paper/jobs/{job_id}
  → {stage, progress, cost_so_far, current_signal, eta}

DELETE /api/paper/jobs/{job_id}
  → 取消 running job
```

## 12. API Endpoints（7 个）

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/paper/extract/{paper_id}` | 触发抽取（异步） |
| GET | `/api/paper/status/{paper_id}` | 单篇状态 |
| GET | `/api/paper/jobs/{job_id}` | job 详情 |
| DELETE | `/api/paper/jobs/{job_id}` | 取消 job |
| GET | `/api/paper/incomplete` | 列出失败论文 |
| POST | `/api/paper/retry/{paper_id}` | 手动重试 |
| GET | `/api/paper/list` | 列出所有论文（已有） |

## 13. 文件结构

### 新增

```
src/llmwikify/reproduction/llm_extraction/
├── __init__.py
├── section_detector.py   # Stage 1 Call 1: LLM 主动识别 sections
├── planner.py            # Stage 1 Call 2: classify + token_budget
├── extractor.py          # Adaptive Extractor (Stage 2)
├── validator.py          # Result Validator (Stage 3)
├── lifecycle.py          # Signal Lifecycle Manager
├── retry.py              # 3-Layer Retry Handler
├── streaming_json.py     # Incremental JSON parser
└── token_config.py       # Dynamic max_tokens config

src/llmwikify/foundation/prompts/_defaults/
├── repro_extract_section.yaml            # Stage 1 Call 1: section detector
├── repro_extract_plan.yaml               # Stage 1 Call 2: planner
├── repro_extract_factor.yaml             # Schema: factor
├── repro_extract_signal.yaml             # Schema: signal
├── repro_extract_allocation.yaml         # Schema: allocation
├── repro_extract_summary.yaml            # Schema: summary
├── repro_extract_validate.yaml           # Validator prompt
├── repro_extract_tier2_backtest.yaml     # Tier 2: backtest_spec
├── repro_extract_tier2_performance.yaml  # Tier 2: performance_claimed
├── repro_extract_tier2_risk.yaml         # Tier 2: risk_analysis
├── repro_extract_tier2_implementation.yaml # Tier 2: implementation_assessment
└── repro_extract_tier2_datasets.yaml     # Tier 2: datasets

src/llmwikify/reproduction/llm_extraction/
└── metadata_lookup.py     # CrossRef/arxiv API 客户端

tests/reproduction/
└── test_adaptive_extractor.py
```

### 修改

- `src/llmwikify/reproduction/extract_paper.py` → 简化为 thin wrapper（仅 trigger 新 pipeline，不保留旧 factor_list 路径）
- `src/llmwikify/interfaces/server/http/paper.py` → 加 6 个新 endpoint

### 文件边界（重要）

| 目录 | 角色 | 写入策略 |
|---|---|---|
| `raw/{paper_id}.pdf` | 源文件（PDF/URL 内容） | ✅ 允许（Stage 0，与 wiki 通用源文件混用）|
| `wiki/` | 既有 wiki 页面（factors/factorbacktest）| ❌ **不写入**（AGENTS.md 量化研究 ≠ 通用知识）|
| `quant/papers/{id}/` | 抽取工作区（plan/result/preview/llm_calls/factors）| ✅ Stage 4 全部输出 |
| `quant/factors/` | 因子库 | ❌ **不直接写入**（人工 review 后从 `quant/papers/{id}/factors/` 迁移）|

## 14. 输出目录结构

**目录分层原则**：原始文件 `raw/` 混用 OK；抽取输出全部在 `quant/`；绝不写 `wiki/`。

```
quant/papers/{paper_id}/
├── parsed.md             # MarkItDown 解析的全文（保留原始 markdown 格式）
├── plan.json             # Planner 决策记录（Call 1 sections + Call 2 plan + token_budget）
├── result.yaml           # 主结果（status: complete/partial/incomplete）
├── preview.md            # 人类可读摘要（max_tokens=1536-3072）
├── llm_calls.jsonl       # 每次 LLM 调用记录（追加）
├── extraction.log        # 抽取过程日志
└── factors/              # draft YAML（待用户 review 后手动迁移到 quant/factors/）
    ├── alpha-001.yaml
    └── ...
```

## 15. Dynamic max_tokens 机制

### 核心思想
**当前 max_tokens = 最小值（floor）**
**Planner LLM 估算 = 目标值（target）**
**实际响应截断 = 触发扩展（expand）**
**max = 硬上限（ceiling）**

### 3 层动态调整（Planner 决策为主，截断扩展为兜底）

```
              ┌─────────────────────────────────┐
              │  Layer 1: Planner 估算          │
              │  plan.token_budget → 目标值     │
              └────────────┬────────────────────┘
                           ↓
              ┌─────────────────────────────────┐
              │  Layer 2: LLM 重问（fallback）  │
              │  Planner 没给 → 小 LLM call    │
              └────────────┬────────────────────┘
                           ↓
              ┌─────────────────────────────────┐
              │  Layer 3: 截断触发扩展          │
              │  finish_reason=length → 1.5x    │
              │  最多 2 次扩展                   │
              └─────────────────────────────────┘
```

### Planner 输出 token_budget 字段

```json
{
  "token_budget": {
    "strategy": "llm_decided",
    "rationale": "101 alphas paper, each with full L1-L4, paper is 45K chars, need expanded token budget for detailed extraction",

    "track_a": {
      "tier1": {
        "estimated_tokens": 4500,
        "reasoning": "8 sections, paper has detailed strategy + 5-year backtest data"
      },
      "tier2_backtest_spec": {
        "enabled": true,
        "estimated_tokens": 2500,
        "reasoning": "Paper has 2 backtest periods, 3 benchmarks"
      },
      "tier2_performance_claimed": {
        "enabled": true,
        "estimated_tokens": 3500,
        "reasoning": "Multiple performance metrics in 6 tables"
      }
    },
    "track_b": {
      "pass1_enumerate": {
        "estimated_tokens": 3000,
        "reasoning": "101 alphas × ~25 chars per name+formula = 2525 chars, need buffer"
      },
      "pass2_per_factor": {
        "estimated_tokens": 5500,
        "reasoning": "L1-L4 detailed, 5 hypotheses avg, formulas with LaTeX"
      }
    }
  }
}
```

### max_tokens 范围表

| 组件 | min (floor) | max (ceiling) | Planner 决定 |
|---|---|---|---|
| Stage 1 Call 1 Section Detector | 4096 | 8192 | 中间任意值 |
| Stage 1 Call 2 Planner | 1024 | 2560 | 中间任意值 |
| Stage 2 Track A Tier 1 | 3072 | 6144 | 中间任意值 |
| Stage 2 Track A Tier 2 / section | 2048 | 4096 | 中间任意值 |
| Stage 2 Track B Pass 1 enumerate | 32000 | 32000 | 固定（multi-turn continuation） |
| Stage 2 Track B Pass 2 per factor | 4096 | 8192 | 中间任意值 |
| Stage 3 Validator | 1024 | 2048 | 中间任意值 |
| Stage 4 Preview.md | **1536** | **3072** | **动态（Planner 估算）** |

**Preview.md 也是动态的**：Planner 在 token_budget 中输出 `preview.estimated_tokens`，取值范围 [1536, 3072]。如果论文信号多、metadata 复杂，Planner 可以给到 2500-3072；如果是简单论文，给到 1536-2000 即可。

## 16. 关键技术参数

| 参数 | 值 | 理由 |
|---|---|---|
| Planner temperature | 0.1 | 分类稳定 |
| Stage 1 re-plan 阈值 | confidence < 0.6 | 经验值 |
| 单 paper 内并发 | 固定 3 | 限流友好 |
| 重试 | 每层 2 次 × 3 层 = 6 次 | 平衡 |
| 降级 temperature | 0.0（异参层）| 确定性强 |
| Targeted read max_chars | 8000/signal | 覆盖 1-2 section |
| Token 硬上限 | **100 元/paper**（临时设定）| 防御性 |
| 截断扩展 | 1.5x，最多 2 次 | 平衡 |

## 17. LLM Calls 记录（llm_calls.jsonl）

```json
// 每行一次 LLM call
{
  "ts": 1718000000.123,
  "job_id": "abc123",
  "stage": "stage_2_track_a_tier1",   // stage_0 | stage_1_plan | stage_2_* | stage_3_validate | stage_4_preview
  "section": "tier1",                  // tier1 | tier2_backtest_spec | ...
  "attempt": 1,                        // 1, 2, 3... (retry count)
  "model": "MiniMax-M2.5",
  "prompt_tokens": 2500,
  "completion_tokens": 800,
  "total_tokens": 3300,
  "cost_cny": 0.012,
  "temperature": 0.1,
  "max_tokens": 4500,                  // Planner 估算值
  "finish_reason": "stop",             // stop | length | error
  "latency_ms": 8500,
  "status": "success",                 // success | failed
  "error": null,                       // or error message
  "response_preview": "..."            // first 200 chars
}
```

## 18. 实施步骤

> **Phase 1 范围**：Track A + Track B（不含 Track C）
> **Phase 2 范围**：Track C 策略复现（待 Phase 1 完成后启动）

| 阶段 | 内容 | 工时 | Phase |
|---|---|---|---|
| **P0** | Stage 0 适配 wiki.ingest_source（MarkItDown → `parsed.md`；源文件存 `raw/`，后续输出到 `quant/papers/{id}/`）| 1-2h | 1 |
| **P1** | Streaming JSON parser | 2-3h | 1 |
| **P2** | Lifecycle Manager + 状态机 | 2-3h | 1 |
| **P3a** | Stage 1 Call 1: Section Detector (LLM 识别 sections) | 1-2h | 1 |
| **P3b** | Stage 1 Call 2: Planner (classify + token_budget) | 2-3h | 1 |
| **P4** | 4 个 Schema prompt + 5 个 Tier 2 prompt + section detector prompt | 3-4h | 1 |
| **P5a** | Track A: Paper-level extractor (Tier 1 + Tier 2 调度) | 2-3h | 1 |
| **P5b** | Track B: Factor-level extractor (Pass 1 multi-turn + Pass 2 3 路并发) | 4-6h | 1 |
| **P6** | 3-Layer Retry Handler (Track B + Stage 1 Call 1 退路) | 2-3h | 1 |
| **P7** | Result Validator + status 判定 + preview.md | 1-2h | 1 |
| **P8** | Logging & checkpoint (extraction.log + llm_calls.jsonl) | 1-2h | 1 |
| **P9** | 6 个新 API endpoint | 2-3h | 1 |
| **P10** | Pilot 5-10 篇（手动触发）| 2-3h | 1 |
| **P11** | 调优 + 跑剩余（手动）| 由用户控制节奏 | 1 |
| **~~P12~~** | ~~Track C: Strategy extractor~~ | ~~2-3h~~ | **2 (暂缓)** |

**Phase 1 总工时**: ~25-37h
**Phase 2 工时（暂缓）**: ~2-3h（待 Phase 1 完成后启动）

## 19. 成本估算

| 项 | 单 paper | 111 篇 |
|---|---|---|
| Stage 1 Call 1 (section detector) | ~0.08 元 | ~9 元 |
| Stage 1 Call 2 (planner) | ~0.05 元 | ~5 元 |
| Track A Tier 1 | ~0.04 元 | ~4.4 元 |
| Track A Tier 2 (avg 2 sections) | ~0.04 元 | ~4.4 元 |
| Track B Pass 1 | ~0.15 元 | ~16.7 元 |
| Track B Pass 2 (avg 10 factors) | ~0.20 元 | ~22 元 |
| Retry overhead | ~30% 增量 | ~10 元 |
| Validator + Preview | ~0.03 元 | ~3.3 元 |
| **总计** | | **~75 元** |

## 20. 风险与缓解

| 风险 | 缓解 |
|---|---|
| Planner 分类不准 | re-plan + confidence < 0.6 阈值 |
| Streaming JSON 解析 bug | 单元测试 + fallback 整体解析 |
| 6 次重试浪费 token | 各层上限 + 早停 deferred |
| 3 并发不够快 | 后续动态调整（先稳后快）|
| 111 篇 checkpoint IO | 写盘节流 + 异步 |
| MarkItDown 依赖 | Legacy fallback |
| 异常论文烧钱 | 100 元硬上限 + 超限跳过 |
| Dynamic max_tokens 估错 | min 边界 + 截断扩展兜底 |
| CrossRef/arxiv API 失败 | 标记 partial + metadata_warnings |

## 21. 完整决策清单

| 决策点 | 决策 |
|---|---|
| Q1 输出形式 | 仅 API |
| Q2 result 落地 | Hybrid 暂存（不污染 `quant/factors/`）|
| Q3 调度 | 取消批处理，per-paper 触发 |
| Q4 并发 | 单 paper 内 3 路并发 |
| Q5 成本 | **100 元/paper 硬上限**（临时设定）|
| Q6 wiki 回写 | 不回写 |
| Q7 失败 review | `GET /api/paper/incomplete` API |
| 异步执行 | HTTP 返回 job_id，用户轮询 status |
| 缓存 | complete/partial 返回 + warning，incomplete 自动重抽，force=true 强制重抽 |
| 缓存响应 | warning + force_replan_suggested + incomplete_signals |
| LLM 记录 | `llm_calls.jsonl` |
| Preview max_tokens | 1536-3072（floor=1536）|
| 失败策略 | 3 层重试（每层 2 次）→ deferred → 全文上下文 |
| Token 硬上限 | **100 元/paper**（临时，可调）|
| Signal lifecycle | 6 状态机 |
| Schema 库 | 4 个（factor/signal/allocation/summary）|
| Stage 策略 | 5 阶段（Ingest/Plan/Extract/Validate/Save）|
| 借鉴 | wiki.ingest 5 个函数 + MarkItDown |
| Track A | 双层 Tier 1 (8 sections) + Tier 2 (5 sections) |
| Track B 替换 | **完全替换现有 `factor_list`**，无向后兼容；轻装上阵（用户决策）|
| `extract_paper.py` | 简化为 thin wrapper（仅 trigger 新 pipeline，不保留旧 `factor_list` 路径）|
| Tier 2 prompt | 5 个独立 prompt 文件 |
| paper_metadata | LLM 抽 + CrossRef/arxiv API 校验增强 |
| 顺序 | 串行 Tier 1 → Tier 2（Track A 内部）|
| performance_claimed | 全部 schema 抽 + warning 文本 |
| Tier 2 失败 | 标记 partial + 空值字段 + extraction_warnings |
| Track A 内部 | Tier 1 → Tier 2 串行 |
| Dynamic max_tokens | Planner LLM 决定（Layer 1） + LLM 重问（Layer 2） + 截断扩展（Layer 3） |
| TokenConfig 边界 | min = floor, max = 2x floor |
| 截断扩展 | 1.5x，最多 2 次 |
| Stage 1 调用数 | **2 calls**（Call 1 section detector + Call 2 planner）|
| Stage 1 Call 1 输入 | parsed.md 全文 |
| Stage 1 Call 1 输出 | sections[]（id/title/level/char_start/char_end）|
| Stage 1 Call 1 model | M2.7 |
| Stage 1 Call 2 model | M2.7 |
| sections 位置 | 绝对字符位置（在 parsed.md 字符串中）|
| `targeted_read` 改动 | 改用 `char_start/end` 切片 |
| Stage 0 输出 | `parsed.md` 保留 MarkItDown 原始 markdown 格式 |
| `parsed.md` 路径 | `quant/papers/{id}/parsed.md` |
| Stage 1 Call 1 失败 | 退到"无 sections"模式（Call 2 仍执行；result 标记 `sections_detected: false`）|
| pdf_splitter.py | ❌ 删除（不需要本地启发式 helper）|
| Track B 替换 | **完全替换现有 `factor_list`**，无向后兼容；轻装上阵（用户决策）|
| `extract_paper.py` | 简化为 thin wrapper（仅 trigger 新 pipeline，不保留旧 `factor_list` 路径）|

## 22. 验收标准

### Pilot 阶段（5-10 篇）

- [ ] Stage 0 正确解析 95%+ 论文
- [ ] Planner 分类准确率 ≥ 80%
- [ ] 简单 paper（< 10K chars）单轮抽取 < 2 min
- [ ] 中等 paper（10-50K）抽取 < 5 min
- [ ] 101 Alphas 类抽取 < 15 min，能恢复 ≥ 80 alphas
- [ ] JSON 截断时 `_repair_truncated_json` 有效
- [ ] incomplete 论文自动重抽机制工作
- [ ] llm_calls.jsonl 记录完整
- [ ] Dynamic max_tokens 触发条件正确（Planner 估算、截断扩展）
- [ ] CrossRef/arxiv 校验增强有效（如 DOI 存在时）
- [ ] partial 状态返回 warning + force_replan_suggested
- [ ] preview.md 包含核心结论和前 5 个 signal

### 全量阶段（111 篇）

- [ ] 95%+ 论文 status=complete 或 partial
- [ ] 失败论文 < 5%，且都有明确 reason
- [ ] 总成本 < 60 元
- [ ] 无超 100 元/paper 的异常
- [ ] llm_calls.jsonl 完整可追溯

## 23. 后续讨论点

### Phase 1 当前讨论点

- 异步 job 状态机细节（pending/running/completed/failed/cancelled）
- LLM calls.jsonl 的具体 schema 验证规则
- Pilot 阶段的具体测试 case 选择
- 某个 stage 的具体实现细节
- Tier 2 sections 失败时的重试策略
- Wiki 端是否需要展示 incomplete 论文列表
- 实施顺序调整
- 异步 job 的并发上限
- 失败论文的人工 review 流程

### Phase 2 暂缓讨论点（Phase 1 完成后启动）

- ⏸ Track C: Strategy Reproduction 实施
- ⏸ `repro_extract_strategy.yaml` prompt 设计
- ⏸ Track C 与 Track B 的 signal_refs 引用机制
- ⏸ Strategy YAML 在 `quant/strategies/` 下的命名规范
- ⏸ 与 `src/llmwikify/strategy/` 的对接（multi_factor.py, trend.py）
- ⏸ Strategy 级别的回测验证（区别于 L5 因子回测）

## 24. 整体框架（Framework Overview）

### 24.1 5 层架构

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Pipeline Stage (5 stages)                              │
│   Ingest → Plan → Extract → Validate → Save                    │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Extraction Track (2 tracks)                            │
│   Track A: Paper/Strategy-level  |  Track B: Factor-level      │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Schema Library (4 schemas)                            │
│   factor | signal | allocation | summary                        │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Layer 4: Signal Lifecycle (6 states)                            │
│   pending → extracted → complete                                │
│              ↓           ↓                                      │
│           partial     deferred → incomplete                     │
└─────────────────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────────────────┐
│ Layer 5: Token Budget & Dynamic Control                        │
│   Planner LLM 估算 + 截断扩展 + 100 元硬上限                    │
└─────────────────────────────────────────────────────────────────┘
```

### 24.2 5 Stage Pipeline

| Stage | 输入 | 输出 | 关键技术 |
|---|---|---|---|
| **Stage 0: Ingest** | PDF 路径 | content + section_metadata + lint_hint | 复用 `wiki.ingest_source` |
| **Stage 1: Plan** | content + sections | plan (含 token_budget) | LLM-as-Planner |
| **Stage 2: Extract** | plan + content | Track A result + Track B signals | 双轨 + Lifecycle + 3 层重试 |
| **Stage 3: Validate** | Track A + Track B | status: complete/partial/incomplete | Schema 校验 + LLM 自检 |
| **Stage 4: Save** | 全部结果 | result.yaml + plan.json + preview.md + llm_calls.jsonl + extraction.log | Async write |

### 24.3 双轨设计

```
Track A: Paper/Strategy-level (Always run)
  ├─ Tier 1: 8 sections (core)
  │   paper_metadata, abstract_summary, strategy_logic,
  │   data_requirements, operation_steps, model_framework,
  │   strengths_weaknesses, suggested_signal
  │
  └─ Tier 2: 5 sections (按需)
      backtest_spec, performance_claimed, risk_analysis,
      implementation_assessment, datasets

Track B: Factor-level (if schema != summary)
  ├─ Pass 1: Enumerate signals (multi-turn continuation)
  │   → 单 session 多轮对话, LLM 自己决定输出量
  │   → max_tokens=32000, 支持 100+ signals 一次输出
  │   → 终止条件: done=true / 达到估计数 / 连续两轮无新增 / MAX_ROUNDS=10
  │   → [name, formula, ...] × N
  │
  └─ Pass 2: Detail extraction (3 路并发)
      → for each signal: L1-L4
```

### 24.4 4 Schema 决策矩阵

| Schema | n_signals | Track A | Track B | 策略 |
|---|---|---|---|---|
| `factor` | > 20 | Tier 1 + Tier 2 全 | ✓ | map_reduce 2-pass |
| `signal` | 3-20 | Tier 1 + Tier 2 部分 | ✓ | single_pass + map_reduce |
| `allocation` | 1-3 | Tier 1 + Tier 2 部分 | ✓ (rules) | single_pass |
| `summary` | < 3 | Tier 1 + Tier 2 (impl only) | ✗ | single_pass |

### 24.5 Lifecycle 状态机

```
                  ┌─→ complete (success, all fields)
                  │
pending → extracted ─┼─→ partial (some optional fields missing)
   │        │       │
   │        │       └─→ deferred (3 layers all failed)
   │        │              │
   │        │              └─→ re-extract with full context
   │        │                       │
   │        │                       ├─→ complete
   │        │                       └─→ incomplete (all failed)
   │        │
   │        └─→ retry (current layer, max 2)
   │
   └─→ (enumeration stage)
```

### 24.6 Token Budget 三层控制

```
┌─────────────────────────────────────┐
│  Layer 1: Planner LLM 估算          │  ← 主决策
│  plan.token_budget[section]         │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  Layer 2: LLM 重问（fallback）      │  ← Planner 没给时
│  ask_llm_for_token_estimate         │
└────────────┬────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  Layer 3: 截断扩展                  │  ← 兜底
│  finish_reason=length → 1.5x        │
│  最多 2 次                          │
└─────────────────────────────────────┘
             ↓
┌─────────────────────────────────────┐
│  Hard Cap: 100 元/paper             │  ← 防御性
└─────────────────────────────────────┘
```

### 24.7 失败处理矩阵

| 失败层级 | 场景 | 处理 |
|---|---|---|
| L1 | 单 signal LLM 失败 | 3 层重试 → deferred |
| L2 | Pass 1 估错 | re-plan |
| L3 | Planner 失败 | 重试 1 次 → Fallback |
| L4 | PDF 提取失败 | 换 MarkItDown → skip |
| L5 | 大面积失败 | 早停 partial_extraction |

### 24.8 核心数字一览

| 维度 | 值 |
|---|---|
| Pipeline 阶段数 | 5 |
| 提取轨道数 | 2 |
| Schema 库大小 | 4 |
| Lifecycle 状态数 | 6 |
| Token 控制层数 | 3 |
| 失败层级数 | 5 |
| API endpoint 数 | 7 |
| 重试层数 | 3 |
| 每层重试次数 | 2 |
| 单 paper 内部并发 | 3 |
| Token 硬上限 | 100 元 |
| 借鉴的 wiki.ingest 函数 | 6 |
| 新增 Prompt 文件 | 11 |
| 计划实施工时 | 25-37h |

## 25. 设计历练（Design Journey）

### 25.1 起点：单 prompt 一把梭

**原始方案**：1 个 LLM call，max_tokens=81920，一次性抽完整篇论文。

```yaml
# 原 repro_extract.yaml
params:
  max_tokens: 81920
  temperature: 0.1
```

**遇到的问题**：
- 101 Alphas 论文（45554 chars 输入）需要 30 分钟
- 30 分钟后 JSON 在 99.8% 处截断
- M2.7 reasoning 模型让 max_tokens 81920 触发深度思考，单篇成本极高
- 所有工作丢失，无法恢复

### 25.2 第一个分歧：max_tokens 大小

**用户问题**：「为什么这么长时间？chat 10s 就有回复了」

**调查发现**：
- chat 默认 max_tokens=2048
- extraction 用 max_tokens=81920（40x）
- 81920 不是太小，**是太大**
- M2.7 reasoning 模型：reasoning_content 占输出 2-5x
- 81920 → 实际生成 90k-130k tokens @ 20 tokens/s → 75-175 分钟

**决策**：不调整 max_tokens，而是从架构层面解决。

### 25.3 第二个分歧：一轮 vs ReAct vs Map-Reduce

**用户问题**：「是不是应该采用 ReAct 架构完成」

**讨论过程**：
- 一轮：简单但慢，30 分钟
- ReAct：动态但每轮都要 reasoning，更慢
- Map-Reduce：每 pass 短而快，可控

**关键洞察**：我们的任务是**结构化数据提取**，不是动态决策任务。ReAct 反而是过度设计。

### 25.4 第三个分歧：实际数据规模

**用户问题**：「为什么 raw 中都是 txt 文件？请访问 ~/Public/strategy/raw」

**发现**：
- 真实论文库有 **111 个 PDF**（不是 raw/research/ 的 15 个 txt）
- 91% 是量化相关
- **64 篇是行业轮动**（最大类别）
- 8 篇是因子论文（类似 101 Alphas）
- 30 篇是资产配置

**影响**：factor_list schema 不再适用，需要重新设计。

### 25.5 第四个分歧：LLM 自主决策

**用户问题**：「能否让 LLM 直接选择决策」

**原计划**：硬编码 6-7 个 paper type → 6-7 个 prompt

**用户洞察**：让 LLM 自主决定 paper type 和提取策略

**设计方案**：LLM-as-Planner
- Stage 1: LLM 分析 paper，输出 plan
- Stage 2: 根据 plan 选择提取策略
- 不硬编码 type → prompt 映射

### 25.6 第五个分歧：借力现有代码

**用户问题**：「提取 PDF 的时候，是否可以借鉴 wiki ingest 的功能」

**调查发现**：wiki.ingest 已有：
- `ingest_source()` - 统一入口
- `extract_section_metadata()` - 章节解析
- `targeted_read()` - 精准读取（杀手锏）
- `_generate_lint_hint()` - 预检
- `MarkItDown` - 多格式支持

**节省工作量**：~7h 实现

### 25.7 第六个分歧：批处理 vs 单独处理

**用户决策**：「取消批处理，per-paper 触发」

**原计划**：批量跑 111 篇

**新方案**：
- 每个 paper 单独触发
- 异步执行（job_id + 轮询）
- 用户控制节奏
- 7 个 API endpoint

### 25.8 第七个分歧：单层 vs 双层提取逻辑

**用户问题**：「抽取的时候还需要一个提取具体逻辑，第一个因子的逻辑 第二个是 paper 或者策略的逻辑」

**关键洞察**：
- 现有 8 categories 混淆了"论文元数据"和"策略细节"
- 需要两个独立轨道：
  - Track A: Paper/Strategy-level（论文层面）
  - Track B: Factor-level（单个因子层面）

**影响**：Stage 2 从 1 个混合轨道改为 2 个独立轨道

### 25.9 第八个分歧：Track A 字段不足

**用户问题**：「还需要扩充的，你的建议是什么」

**问题诊断**：
- 缺文献元数据
- 缺 TL;DR
- 缺 backtest 配置
- 缺实施评估
- 缺论文声称的绩效
- 缺风险分层

**解决方案**：
- Tier 1: 8 sections（核心，必抽）
- Tier 2: 5 sections（详情，按需）
- 5 个独立 prompt 文件（精细控制）

### 25.10 第九个分歧：max_tokens 大小

**用户问题**：「修订后的 max_tokens 分配可以在加大些吗」

**用户决策**：所有 max_tokens 上调
- Tier 1: 2048 → 3072
- Tier 2: 1024 → 2048
- Preview: 1024 → 1536

**成本影响**：~+10%，可接受

### 25.11 第十个分歧：动态 max_tokens

**用户问题**：「是否可以设置一个动态的 max_token 根据实际情况动态调节一下」

**原设计**：固定 max_tokens
**新需求**：动态调节

### 25.12 第十一个分歧：动态由谁决定

**用户问题**：「这个动态能否让 LLM 来确定第一步的时候」

**原设计**：3 层（Planner + 公式 + 截断）
**用户决策**：让 Planner LLM 作为主决策者

**最终设计**：
- Layer 1: Planner LLM 估算（主）
- Layer 2: LLM 重问（fallback，Planner 没给时）
- Layer 3: 截断扩展（兜底）
- 删除：公式 fallback（不需要了）
- 100 元硬上限（防御性）

### 25.13 关键决策时间线

| 时间 | 决策 | 影响 |
|---|---|---|
| T1 | 一轮抽取 + max_tokens=81920 | 起点 |
| T2 | max_tokens 不是问题，是架构问题 | 转向架构重构 |
| T3 | Map-Reduce > ReAct（结构化提取）| Stage 2 分轮设计 |
| T4 | 真实数据是 111 PDF 不是 15 txt | Schema 重设计 |
| T5 | LLM-as-Planner | 4 schemas + 1 planner |
| T6 | 借鉴 wiki.ingest | 节省 7h |
| T7 | 取消批处理 | 7 个 API endpoint |
| T8 | 双轨提取（Track A + B）| Stage 2 拆分 |
| T9 | Track A 12 sections 分 2 层 | 5 个 Tier 2 prompt |
| T10 | max_tokens 上调 | 成本 +10% |
| T11 | Dynamic max_tokens | 3 层控制 |
| T12 | LLM 决定 dynamic 值 | Planner 主导 |
| T13 | Token 硬上限 2→100 元 | 防御性增强 |

### 25.14 设计原则的演化

| 阶段 | 原则 | 演化 |
|---|---|---|
| 初始 | 简单优先 | 1 prompt 解决所有问题 |
| 中期 | 灵活 + 鲁棒 | LLM 自主决策 + 多层重试 |
| 后期 | 借力 + 简洁 | 复用现有代码 + 状态机清晰 |
| 最终 | LLM-first | Planner 全局决策，System 局部执行 |

### 25.15 经验总结

**1. 先理解问题再设计**
- 看到 30 分钟慢不能立刻调慢 LLM
- 要先理解是 max_tokens 问题、还是 prompt 问题、还是模型问题

**2. 让 LLM 做决策而非硬编码**
- 硬编码 type → prompt 映射：每次新论文类型要改代码
- LLM 自主分类：自动适应新类型

**3. 借力现有代码**
- 不要重新发明轮子
- wiki.ingest 已实现的：`ingest_source()`, `targeted_read()` 等

**4. 任务本质决定架构**
- 结构化提取 → Map-Reduce
- 动态决策 → ReAct
- 简单分类 → 关键词

**5. 状态机 + Lifecycle 思维**
- 信号不是"成功/失败"二态
- 6 个状态（pending/extracted/complete/partial/deferred/incomplete）能覆盖所有情况

**6. 防御性设计**
- 100 元硬上限（防异常烧钱）
- 截断扩展（防 LLM 输出超长）
- fallback default plan（防 planner 失败）

**7. 异步 + 缓存**
- 长任务必须异步（HTTP 立即返回 job_id）
- 缓存避免重复工作
- incomplete 状态自动重抽

**8. 完整可追溯**
- llm_calls.jsonl：每次 LLM 调用都记录
- extraction.log：过程日志
- plan.json：决策可审计
- result.yaml：结果可读

### 25.16 与原方案对比

| 维度 | 原方案 | 新方案 |
|---|---|---|
| 抽取策略 | 一轮 81920 tokens | 双轨 + Map-Reduce |
| 论文分类 | 关键词硬编码 | LLM Planner |
| Schema 库 | 1 个 | 4 个 |
| 字段数 | 8 categories | 13 sections (Tier 1 + Tier 2) |
| 重试策略 | 无 | 3 层 × 2 次 |
| 状态机 | 无 | 6 状态 |
| 缓存 | 无 | 完整 + warning |
| 异步 | 无 | job_id + 轮询 |
| max_tokens | 固定 81920 | 动态 + 100 元上限 |
| 实施工时 | 20h+ | **24-35h**（删除 P0.5，Stage 1 拆 2 calls）|
| 预期成功率 | < 50% | > 95% |
| 预期成本 | 高（重抽多）| 中（缓存命中率高）|

### 25.17 Issue #1 解决记录

**问题**：`extract_section_metadata` 不适用 PDF（仅识别 markdown `#` 标题）

**调研过程**：
1. 实测 101 Alphas PDF → 0 个 markdown 标题
2. 实测 MarkItDown 模式 PDF → 纯文本流，无 page 标记，无字体信息
3. 实测 pymupdf 模式 PDF → 有 page 标记和字体信息
4. 实测中文研报 → 字体差异小（10/11/12），子章节难以识别

**方案探索**：
- **A. 本地启发式（pdf_splitter.py）**：字体分析 + 数字模式 + 关键词 → 学术 95%、中文 70%
- **B. 字体 + LLM 补充**：准确率高但实现复杂
- **C. 扔给 LLM**：Stage 1 Call 1 由 LLM 主动识别 sections
- **D. 去掉 sections**：Planner 直接看全文

**最终决策**（用户 2026-06-17）：
- **选 C 方案**：扔给 LLM
- 2 次 LLM call：Call 1 detect sections（全文输入）→ Call 2 classify+plan
- 解析后文本 `parsed.md` 保存到 `quant/papers/{id}/`（避免 re-parse）
- sections 位置用绝对字符（`char_start/end` 在 `parsed.md` 字符串中）
- `targeted_read` 改为按 `char_start/end` 切片
- 删除 `pdf_splitter.py` 和 P0.5 实施步骤
- Call 1 失败 → 退到"无 sections"模式

**影响**：
- 节省 1h P0.5 实施
- Stage 1 成本 +0.08 元/篇（Call 1）→ 总成本 50 → 60 元
- 跨论文类型通用（学术/研报/复盘都适用）
- 与 LLM-as-Planner 哲学一致

### 25.17 关键洞察清单

1. **任务本质 > 技术潮流**：ReAct 流行但不适合结构化提取
2. **真实数据 > 假设数据**：111 PDF 不是 15 txt
3. **LLM 决策 > 硬编码**：让模型自己分类
4. **借力 > 造轮子**：wiki.ingest 节省 7h
5. **状态机 > 二元判断**：6 状态覆盖所有情况
6. **异步 > 同步**：长任务必须异步
7. **可追溯 > 黑盒**：llm_calls.jsonl 让一切可审计
8. **防御性 > 信任**：100 元硬上限防异常

## 26. 与因子库框架的衔接（Upstream Output）

> 本节说明本 pipeline 的产出如何作为因子库实施的**上游输入**。

### 26.1 因子库框架位置

因子库的完整 6 层（L1-L6）设计见：
- 📄 **[`docs/designs/factor_library_framework.md`](./factor_library_framework.md)** (570 行)
  - 6 层定义、字段表、YAML 模板
  - 评分规则（Rubric）、阈值
  - 命名规范、分类体系
- 📄 **[`docs/designs/factor_reflection_design.md`](./factor_reflection_design.md)** (501 行)
  - L5 反思机制
- 📄 **[`docs/designs/factor_library_design_discussion.md`](./factor_library_design_discussion.md)** (681 行)
  - 设计讨论记录

**本 pipeline 不重新发明 L1-L4 框架**，而是作为上游产出 L1-L4 的**初始内容**。

### 26.2 字段映射表（论文抽取 → 因子 L1-L4）

本 pipeline 的 Track B (Factor-level) 输出映射到 6 层框架的 L1-L4：

| 因子库字段 | 论文抽取字段（Track B）| 抽取位置 | 来源 |
|---|---|---|---|
| **L1: 逻辑层** | | | |
| `l1.definition` | `factor.description` | Pass 2 per signal | 论文 |
| `l1.formula` | `factor.formula` | Pass 2 per signal | 论文 |
| `l1.input_columns` | `factor.input_columns` | Pass 2 per signal | 论文 |
| `l1.frequency` | `factor.frequency` | Pass 2 per signal | 论文 |
| `l1.default_params` | `factor.default_params` | Pass 2 per signal | 论文 |
| `l1.param_constraints` | `factor.param_constraints` | Pass 2 per signal | 论文 |
| `l1.business_constraints` | `factor.business_constraints` | Pass 2 per signal | 论文 |
| **L2: 计算定义层** | | | |
| `l2.calculation_steps` | `factor.calculation_steps[]` | Pass 2 per signal | 论文 + 推断 |
| `l2.edge_case_handling` | `factor.edge_case_handling` | Pass 2 per signal | 论文 |
| `l2.missing_value_handling` | `factor.missing_value_handling` | Pass 2 per signal | 论文 |
| `l2.complexity` | `factor.complexity` | Pass 2 per signal | 推断 |
| `l2.code_location` | *（本 pipeline 不填）* | — | L2 实施时填 |
| **L3: 金融理解层** | | | |
| `l3.financial_intuition` | `factor.financial_intuition` | Pass 2 per signal | 论文 |
| `l3.market_behavior` | `factor.market_behavior` | Pass 2 per signal | 论文 |
| `l3.theoretical_basis` | `factor.theoretical_basis` | Pass 2 per signal | 论文 |
| `l3.historical_effectiveness` | *（论文如有则填）* | Pass 2 per signal | 论文 |
| `l3.related_factors` | *（论文如有则填）* | Pass 2 per signal | 论文 |
| **L4: 因子含义层** | | | |
| `l4.hypotheses[]` | `factor.hypotheses[]` | Pass 2 per signal | 论文 + 推断 |
| `l4.meaning_summary` | *（L5 验证后填）* | — | L5 实施时填 |
| `l4.key_insights` | *（L5 验证后填）* | — | L5 实施时填 |
| `l4.uncertainty` | *（L5 验证后填）* | — | L5 实施时填 |
| `l4.final_meaning` | *（L5 验证后填）* | — | L5 实施时填 |

**关键观察**：
- **L1**：本 pipeline **直接产出**（论文中通常有明确公式）
- **L2**：`code_location` 留空，**L2 实施阶段**填
- **L3**：本 pipeline **直接产出**（论文中通常有金融直觉讨论）
- **L4**：`hypotheses` 部分产出，但 `meaning_summary/key_insights/uncertainty/final_meaning` 留空，**L4 实施阶段**填
- **L5**：完全留空，**L5 验证阶段**填
- **L6**：完全留空，**L6 风险阶段**填

### 26.3 factor.yaml 输出模板

本 pipeline 的 `factors/{name}.yaml` 输出（draft 版本，待 L1-L4 实施时完善）：

```yaml
factor:
  # === 元数据（由本 pipeline 填）===
  name: stock_price_momentum_20d
  name_cn: 20日动量因子
  asset_type: stock
  category: price
  subcategory: momentum
  version: 1
  created_at: 2026-06-17
  updated_at: 2026-06-17
  status: draft  # 本 pipeline 产出后状态
  source_paper: 101_formulaic_alphas  # 来自哪篇论文
  source_paper_id: 1601.00991v3

  # === L1 逻辑层（本 pipeline 填）===
  l1:
    definition: 过去20个交易日的涨跌幅
    formula: f_t = close_t / close_{t-20} - 1
    input_columns: [close]
    frequency: 日频
    output_schema: "[date × Code]"
    nan_meaning: 早期数据不足20日
    default_params: { period: 20 }
    param_constraints: { period: "≥5" }
    business_constraints: 个股上市不足period日时不可算

  # === L2 计算定义层（本 pipeline 部分填，code_location 留空）===
  l2:
    calculation_steps:
      - step: 1
        description: 取close序列
        formula: close_series
      - step: 2
        description: 计算20日收益率
        formula: f_t = close_t / close_{t-20} - 1
    edge_case_handling: 前20个日期输出NaN
    missing_value_handling: 保持NaN（不插值）
    data_alignment: T+1
    complexity: O(T × N)
    code_location: null  # L2 实施阶段填

  # === L3 金融理解层（本 pipeline 填）===
  l3:
    financial_intuition: 过去20天市场对该股票的认可程度
    market_behavior: 价格相对于近期均值的偏离
    theoretical_basis: 行为金融学的锚定效应、动量效应
    historical_effectiveness: null  # L3 实施阶段填
    related_factors: null  # L3 实施阶段填

  # === L4 因子含义层（本 pipeline 部分填）===
  l4:
    hypotheses:
      - id: H1
        name: 动量延续
        description: 高动量→未来继续涨
        expected_ic_sign: 正
        source: 行为金融学动量效应
        priority: 主假设
        status: 未验证
    hypothesis_limit: 5
    archived_hypotheses: []
    meaning_summary: null  # L4 实施阶段填
    key_insights: null  # L4 实施阶段填
    uncertainty: null  # L4 实施阶段填
    final_meaning: null  # L5 验证后填

  # === L5 验证层（完全留空）===
  l5: null

  # === L6 风险层（完全留空）===
  l6: null
```

### 26.4 状态流转（draft → 已注册 → 已验证）

```
本 pipeline 产出
    ↓
status: draft
    ↓ 用户 review + 编辑
status: 已注册
    ↓ L2 实施（计算 + 回测）
status: 已注册 + L2 filled
    ↓ L4 实施（假设 + 含义）
status: 已注册 + L2/L4 filled
    ↓ L5 验证（IC + 分组 + OOS）
status: 通过 / 待更新 / 失败
    ↓ L6 实施
status: 完整
```

### 26.5 输出目录映射

```
本 pipeline 输出                              因子库 L1-L6 实施后
─────────────────                          ─────────────────────
quant/papers/{id}/                          quant/factors/{asset}/{category}/{slug}.yaml
├── plan.json                             
├── result.yaml (含 factor_list[])   ─→   └── factor.yaml (status: draft)
├── preview.md                            
├── llm_calls.jsonl                       
├── extraction.log                        
└── factors/                              
    ├── alpha-001.yaml  ──────────────→   quant/factors/stock/price/alpha-001.yaml
    ├── alpha-002.yaml  ──────────────→   quant/factors/stock/price/alpha-002.yaml
    └── ...                               
```

**用户的迁移动作**：
1. Review `quant/papers/{id}/preview.md`
2. 检查 `quant/papers/{id}/factors/alpha-XXX.yaml`
3. 如满意：`cp` 到 `quant/factors/stock/price/alpha-XXX.yaml`
4. 编辑完善 L2/L3/L4 字段
5. 触发 L5 验证
6. LLM 自动填 L6

### 26.6 与 L5 验证的衔接

本 pipeline 的 `performance_claimed` 字段（论文声称的绩效）和 L5 实际验证的关系：

```yaml
# 本 pipeline 产出（论文声称的）
performance_claimed:
  annual_return: 0.25
  sharpe_ratio: 1.5
  max_drawdown: -0.15
  source: "原文 Table 3"
  caveat: "论文声明的绩效，未经验证。L5 validation 阶段会执行实际回测对比。"

# L5 实施后（实际验证）
l5:
  factor_analysis:
    return_analysis:
      ann_return: 0.22  # 实际回测
      ann_return_diff: -0.03  # 与论文声称的差异
      sharpe: 1.35  # 实际
      sharpe_diff: -0.15
  conclusion: "论文声称的绩效略高于实际回测，可能由于交易成本/样本期不同"
```

**L5 实施时可以自动对比**，给出差异分析。

### 26.7 本 pipeline 不做的事

明确**不属于本 pipeline 范围**的：
- ❌ 实际回测计算（属于 L5 验证）
- ❌ IC/分组/OOS 指标计算（属于 L5 验证）
- ❌ 因子评分（属于 L5 验证）
- ❌ 风险分析（属于 L6 风险）
- ❌ 反思机制（属于 L5 反思）
- ❌ 假设检验（属于 L5 验证）
- ❌ 代码生成（属于 L2 实施，但本 pipeline 已部分支持 `formula` factor_class）

**本 pipeline 的定位**：**论文 → 因子元数据**（L1-L4 初始内容 + 论文上下文）。

### 26.8 下一步：因子库完整实施

完成本 pipeline 后，因子库实施按以下顺序：

| 阶段 | 内容 | 工时估算 |
|---|---|---|
| **Stage A** | 因子 YAML 解析 + 校验 | 2-3h |
| **Stage B** | L2 实施（计算 + CodeSandbox）| 4-6h（部分已有）|
| **Stage C** | L3 字段完善（人工 review）| 1-2h（基于本 pipeline 输出）|
| **Stage D** | L4 实施（LLM 推断 meaning_summary）| 2-3h |
| **Stage E** | L5 验证（IC + 分组 + OOS）| 6-8h（部分已有）|
| **Stage F** | L6 风险分析 | 3-4h |
| **Stage G** | Factor Library API + UI | 4-6h |

**总计**：~22-32h

**L2 和 L5 部分已在本项目有基础实现**（`factor_backtest.py`, `l5_validation.py`, `l5_orchestrator.py`），主要工作是**补全字段**和**串联流程**。

### 26.9 关键依赖关系

```
本 pipeline (Paper → Factor Metadata)
  ↓ 产出
quant/papers/{id}/factors/*.yaml (status: draft)
  ↓ 用户迁移
quant/factors/{asset}/{category}/{slug}.yaml (status: draft)
  ↓ L2 实施
status: 已注册 + L2 filled
  ↓ L4 实施
status: 已注册 + L2/L4 filled
  ↓ L5 验证
status: 通过 / 待更新 / 失败
  ↓ L6 实施
status: 完整
```

**本 pipeline 是链路的第一步**，完成 L1-L4 初始内容填充。

## 27. 策略复现输出（Strategy Reproduction Output）

> **状态**: ⏸ **Phase 2 暂缓实施**
> **触发条件**: Paper → Factor 链路走通后（即因子库 P0-P11 + Pilot 全量跑通）
> **记录原因**: 用户决策"等 paper 到因子走通了再进行实施"
> **本节内容**: 保留设计但不实施，作为下一阶段工作的依据

### 27.1 问题定义

**当前缺口**：
- Track A：论文元数据（8 categories + 5 Tier 2）
- Track B：因子元数据（L1-L4）
- **缺失**：论文中描述的**完整策略**如何复现

**为什么需要**：
- 64 篇行业轮动论文，**核心是策略**（不是单个因子）
- 30 篇资产配置论文，需要**组合规则**而非单因子
- 论文通常描述：`1-3 个 signals + 组合规则 + 调仓 + 风控`
- 这是**比因子更高一层**的抽象

**典型例子**（招商证券行业轮动）：
```
论文描述：
  Signals: momentum_20d (权重 0.4), pe_ratio (权重 0.3), vol_60d (权重 0.3)
  组合: weighted_score = 0.4 * momentum_rank + 0.3 * -pe_rank + 0.3 * -vol_rank
  选股: top 10% 行业
  调仓: 月度
  仓位: 等权
  风控: 止损 10%

需要抽取 → 结构化 → 可执行
```

### 27.2 设计：Track C（策略复现轨道）

新增第 3 个提取轨道：

```
┌──────────────────────────────────────────────────────────────┐
│ Stage 2: Extract                                             │
│                                                               │
│   ├─ 轨道 A: Paper/Strategy-level     (always)               │
│   ├─ 轨道 B: Factor-level             (if has factors)        │
│   └─ 轨道 C: Strategy Reproduction   (NEW, if strategy paper)│
│       - signal_combination                                   │
│       - universe_filter                                      │
│       - rebalance_rules                                      │
│       - position_sizing                                      │
│       - risk_management                                      │
│       - backtest_config                                      │
└──────────────────────────────────────────────────────────────┘
```

### 27.3 Track C 触发条件

```python
# Stage 1 Planner 决定
def should_run_track_c(plan):
    if plan.schema_choice in ["factor"]:
        # 纯因子论文（如 101 Alphas）无 Track C
        return False
    if plan.schema_choice == "summary":
        # 战略分析类无 Track C
        return False
    if plan.paper_type in ["rotation", "allocation", "signal"]:
        # 行业轮动/资产配置/信号策略类
        return True
    return False
```

**触发矩阵**：

| schema | paper_type | Track C |
|---|---|---|
| `factor` | 101 Alphas 类 | ✗（纯因子定义）|
| `signal` | 行业轮动、择时 | ✓ |
| `signal` | 风格轮动 | ✓ |
| `allocation` | 资产配置 | ✓ |
| `summary` | 启示录、框架、复盘 | ✗ |

### 27.4 Track C Schema（6 个 sections）

```yaml
strategy_reproduction:
  # === 1. 信号组合 ===
  signal_combination:
    method: "weighted_score"  # equal_weight | ic_weight | rank_weight | weighted_score
    signals:
      - name: "momentum_20d"
        weight: 0.4
        transform: "rank"  # raw | rank | z_score
        direction: "positive"  # positive (high is good) | negative (low is good)
      - name: "pe_ratio"
        weight: 0.3
        transform: "rank"
        direction: "negative"  # 低 PE 更好
      - name: "vol_60d"
        weight: 0.3
        transform: "rank"
        direction: "negative"
    aggregation: "weighted_sum"  # weighted_sum | rank_sum | z_score_sum
    composite_score: "0.4 * rank(mom) + 0.3 * (-rank(pe)) + 0.3 * (-rank(vol))"

  # === 2. 选股规则 ===
  universe_filter:
    type: "top_n_by_score"  # all_stocks | top_n | top_pct | industry_rotation | factor_threshold
    top_n: 50
    top_pct: 0.10  # 前 10%
    industry_constraints:
      - "exclude: 金融"
      - "max_per_industry: 0.3"  # 单一行业不超过 30%
    market_cap_filter:
      min: 0  # 不限
      max: null
    liquidity_filter:
      min_avg_amount: 10000000  # 最小日均成交额

  # === 3. 调仓规则 ===
  rebalance:
    frequency: "monthly"  # daily | weekly | monthly | quarterly
    rebalance_day: "first_trading_day"
    threshold_rebalance: 0.05  # 仅当持仓偏离 > 5% 才调仓
    execution_window: "morning"  # morning | afternoon | close
    execution_price: "vwap"  # open | vwap | close
    slippage_bps: 5  # 5 个基点滑点

  # === 4. 仓位管理 ===
  position_sizing:
    method: "equal_weight"  # equal_weight | score_proportional | volatility_target | kelly
    long_only: true
    max_position_pct: 0.05  # 单只最大 5%
    max_industry_pct: 0.30
    min_position_pct: 0.005  # 最小 0.5%
    target_volatility: null  # 波动率目标（可选）

  # === 5. 风控规则 ===
  risk_management:
    stop_loss: 0.10  # 个股止损 10%
    stop_profit: null  # 止盈（可选）
    max_drawdown: 0.20  # 组合回撤 20% 触发警报
    market_regime_filter:
      enabled: false
      bullish: "normal"
      bearish: "reduce_exposure"
      sideways: "normal"
    industry_concentration_limit: 0.40
    single_stock_limit: 0.05

  # === 6. 回测配置 ===
  backtest_config:
    in_sample_period:
      start: "2015-01-01"
      end: "2018-12-31"
    out_of_sample_period:
      start: "2019-01-01"
      end: "2020-12-31"
    benchmark: "000300.SH"  # 沪深 300
    initial_capital: 1000000
    transaction_cost:
      commission_rate: 0.0003  # 万三
      stamp_tax: 0.001  # 千一（卖出）
      slippage_bps: 5
    rebalance_assumption: "next_day_open"  # next_day_open | next_day_close
    data_alignment: "T+1"
```

### 27.5 Stage 1 Plan 输出增强

```json
{
  "schema_choice": "signal",
  "paper_type": "rotation",
  "track_a": {...},
  "track_b": {...},
  "track_c": {
    "enabled": true,
    "estimated_tokens": 3500,
    "max_tokens": 4096,
    "reasoning": "Paper is industry rotation, 3 signals described, need full strategy spec",
    "sections": ["signal_combination", "universe_filter", "rebalance", "position_sizing", "risk_management", "backtest_config"]
  }
}
```

### 27.6 Stage 2 决策流程（修订）

```
Stage 2: Extract
  │
  ├─ 轨道 A: Paper-level
  │   Tier 1 (8 sections) + Tier 2 (5 sections)
  │
  ├─ 轨道 B: Factor-level
  │   Pass 1 enumerate + Pass 2 detail
  │   (if has factors)
  │
  └─ 轨道 C: Strategy Reproduction (NEW)
      if should_run_track_c(plan):
        max_tokens = plan.track_c.estimated_tokens
        response = llm_call_with_truncation_retry(
          prompt=load_prompt("repro_extract_strategy"),
          max_tokens=max_tokens
        )
        result_c = parse_strategy_reproduction(response)
        save(result_c)
      else:
        skip
```

### 27.7 与 Track A 的边界

| 字段 | Track A | Track C | 关系 |
|---|---|---|---|
| `operation_steps.position_sizing` | 简要描述 | 详细规则 | Track A 是概述，Track C 是可执行规则 |
| `backtest_spec` | 论文提到的设置 | 完整可执行配置 | Track C 是细化版 |
| `risk_management` | 风险类别 | 具体止损/限额 | Track A 是分类，Track C 是数值 |
| `strategy_logic` | 核心假说 | - | 仅 Track A |

**设计原则**：
- Track A：**论文说了什么**（paper-level understanding）
- Track C：**如何复现**（execution-ready specification）

### 27.8 与 Track B 的关系

Track B 抽取的 signals 是 Track C 的输入：

```python
# Track C 引用 Track B 输出的 signals
signal_combination:
  signals:
    - name: "{track_b_signal.name}"  # 引用 Track B 的 signal
      weight: 0.4
      ...
```

**好处**：
- Track C 复用 Track B 的 signal 元数据
- 不会重复抽取
- 信号定义唯一来源（Single Source of Truth）

### 27.9 输出目录

```
quant/papers/{paper_id}/
├── plan.json
├── result.yaml
│   ├── track_a: {...}
│   ├── track_b: [...]
│   └── track_c: {...}  ← NEW
├── preview.md
├── llm_calls.jsonl
├── extraction.log
├── factors/                    # Track B 输出（待 review）
│   ├── alpha-001.yaml
│   └── ...
└── strategies/                 # Track C 输出（待 review）← NEW
    └── rotation_strategy.yaml  # 一篇论文一个 strategy yaml
```

### 27.10 Strategy YAML 模板

```yaml
strategy:
  # === 元数据 ===
  name: industry_rotation_momentum_value
  name_cn: 行业轮动-动量价值复合
  source_paper: 招商证券_A股行业轮动
  source_paper_id: 20190301_guangfa
  version: 1
  created_at: 2026-06-17
  status: draft  # draft → reviewed → registered → live

  # === 信号引用（从 Track B 引用）===
  signal_refs:
    - factor_ref: "stock/price/momentum_20d.yaml"
      weight: 0.4
    - factor_ref: "stock/fundamental/pe_ratio.yaml"
      weight: 0.3
    - factor_ref: "stock/price/vol_60d.yaml"
      weight: 0.3

  # === 组合层（来自 Track C）===
  signal_combination:
    method: weighted_score
    aggregation: weighted_sum
    composite_score: "0.4 * rank(mom) + 0.3 * (-rank(pe)) + 0.3 * (-rank(vol))"

  # === 选股 ===
  universe:
    type: industry_rotation
    top_pct: 0.10
    constraints:
      - "exclude: 金融"
      - "max_per_industry: 0.3"

  # === 调仓 ===
  rebalance:
    frequency: monthly
    threshold: 0.05

  # === 仓位 ===
  position_sizing:
    method: equal_weight
    max_position_pct: 0.05
    long_only: true

  # === 风控 ===
  risk_management:
    stop_loss: 0.10
    max_drawdown: 0.20

  # === 回测配置 ===
  backtest:
    in_sample: [2015, 2018]
    out_of_sample: [2019, 2020]
    benchmark: 000300.SH
    initial_capital: 1000000
```

### 27.11 与 strategy 实施的对接

下游 strategy 实施（`src/llmwikify/strategy/`）可直接消费 Track C 输出：

```python
# 假设 strategy 实施已就绪
from llmwikify.strategy.stock.multi_factor import MultiFactorStrategy

# 加载 Track C 输出
strategy_config = load_yaml("quant/papers/xxx/strategies/rotation_strategy.yaml")

# 实例化策略（可执行）
strategy = MultiFactorStrategy.from_config(strategy_config)

# 跑回测
backtester = Backtester(strategy)
results = backtester.run(start="2015-01-01", end="2020-12-31")
```

**这是本 pipeline 的第 2 条下游链路**：
- 链路 1：论文 → 因子元数据 → L1-L4 实施
- 链路 2：论文 → 策略元数据 → 策略复现实施

### 27.12 实施影响

| 项 | 原 | 修订后（Phase 2）|
|---|---|---|
| 提取轨道 | A + B | A + B + C |
| Prompt 文件 | 11 | **12**（+1 strategy）|
| Stage 1 Plan | 2 轨道配置 | 3 轨道配置 |
| 实施工时 | 25-37h | **27-39h**（+2h, Track C）|
| 输出目录 | factors/ | factors/ + **strategies/** |

**当前阶段（Phase 1）暂不实施 Track C**，相关字段留空。

### 27.13 新增 Prompt

```
src/llmwikify/foundation/prompts/_defaults/
└── repro_extract_strategy.yaml    # Track C prompt (NEW)
```

**Prompt 设计要点**：
- 输入：full paper text + Track B signals（引用）
- 输出：6 个 sections 的结构化 YAML
- 重点：execution-ready（可执行），不是论文复述

### 27.14 下游链路总览

```
论文 (PDF)
  ↓
本 pipeline (Paper Extraction)
  ├─ 链路 1：Track B → 因子元数据 → quant/factors/.../*.yaml
  │              ↓ L1-L6 实施
  │              ↓ L5 验证
  │              ↓ L6 风险
  │
  └─ 链路 2：Track C → 策略元数据 → quant/strategies/.../*.yaml  ⏸ Phase 2
                ↓ 策略复现（multi_factor.py, trend.py）
                ↓ backtest 验证
                ↓ 实盘或 paper trading
```

**两条链路独立演进**，但**底层都依赖 Track A 的论文元数据**（共享 Layer）。

### 27.15 Phase 划分

| Phase | 范围 | 实施时间 | 验证标准 |
|---|---|---|---|
| **Phase 1（当前）** | Track A + Track B → 因子元数据 | P0-P11 | 111 篇 95%+ status=complete/partial |
| **Phase 2（暂缓）** | + Track C → 策略元数据 | Phase 1 完成后 | 策略可执行回测 |
| **Phase 3** | L1-L6 因子库完整实施 | Phase 1 完成后 | 因子评分通过率 ≥ 60% |
| **Phase 4** | 策略实盘/paper trading | Phase 2 完成后 | 跟踪策略表现 |

**Phase 1 → Phase 2 切换条件**：
- ✅ Pilot 阶段 5-10 篇验证通过
- ✅ 因子库 draft YAML 可正常 review 和迁移
- ✅ L2 实施（计算 + CodeSandbox）跑通
- ✅ Track B 的 signals 质量满足 L5 验证要求

**未达条件前，Track C 相关代码、prompt、目录都不实施**。

## 28. Track B Pass 1: Multi-turn Continuation 实现

### 28.1 背景

最初的实现使用 batch 分批逻辑（`BATCH_SIZE=10`），但发现严重问题：
- `sorted(seen)[-15:]` 字典序裁剪导致 skip list 失真
- LLM 重复输出被 dedup 砍光，触发提前 break
- 实际测试结果：25/101（比旧版 80/101 还差）

### 28.2 设计方案

采用 **multi-turn continuation**：单 session 多轮对话，LLM 自己决定输出量。

**核心规则**：
1. 不预设 batch size，`max_tokens` 拉满到 32000
2. 上下文自然累加（LLM 通过 attention 看到历史输出）
3. LLM 主动标记 `done: true` 表示完成

**终止条件**（优先级从高到低）：
1. LLM 在 JSON 中返回 `done: true`
2. 累计 factor 数目 ≥ `plan.n_signals_estimate`
3. 连续两轮 `len(new) = 0`（无新增）
4. 轮次 ≥ `MAX_ROUNDS = 10`

### 28.3 实现细节

**Prompt 修改**：
- 添加 `done` 字段到 JSON schema
- System prompt 补充 multi-turn 协议说明
- `max_tokens` 12000→32000

**代码改动**：
- 删除 `BATCH_SIZE`/`BATCH_MAX_TOKENS`/`MAX_BATCHES`/`_build_batch_spec`
- 新增 `_run_pass1` multi-turn 循环
- `_parse_signals_from_response` 返回 `(list[SignalStub], done: bool)`

### 28.4 测试结果

**101 Alphas 论文实测**：
- 一次调用拿完所有 101 个因子
- LLM 主动标记 `done=True`
- 覆盖率 100%
- 延迟 106 秒

**对比**：
| 版本 | 调用次数 | 结果 |
|---|---|---|
| 旧 batching（`sorted[-15:]`） | 11 次 | 25/101 ❌ |
| 新 multi-turn continuation | 1 次 | 101/101 ✅ |

### 28.5 后续优化

1. **动态 `MAX_ROUNDS`**：根据 `plan.n_signals_estimate` 动态调整
2. **Token 预算优化**：如果 LLM 一次输出全部，可以节省多轮开销
3. **错误处理**：API 拒绝 `max_tokens=32000` 时自动 fallback 到 16384
