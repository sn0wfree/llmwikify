# 论文研报复现规范

> 版本: v0.4.0
> 日期: 2026-06-11
> 范围: Paper / Factor / Strategy / Backtest 四类页面的命名、存储、代码生成

---

## 1. 命名规范

### 1.1 Paper 页面

| 页面类型 | 命名格式 | 示例 |
|---|---|---|
| Source (逻辑) | `paper-{paper_id}-logic` | `paper-arxiv-2024-momentum-logic` |
| Source (数据) | `paper-{paper_id}-data` | `paper-arxiv-2024-momentum-data` |
| Source (风险) | `paper-{paper_id}-risks` | `paper-arxiv-2024-momentum-risks` |

**paper_id 规则:**
- 格式: `{source_type}-{identifier}` (kebab-case)
- 示例: `arxiv-2024-momentum`, `ssrn-2025-value`, `user-custom-001`
- 禁止: 空格、下划线、大写字母、特殊字符
- 长度: ≤ 80 字符

### 1.2 Factor 页面

**统一命名格式: `factor-{paper_id}-{slug}`**

```python
slug = generate_slug(name)  # 统一函数，见 1.5 节
page_name = f"factor-{paper_id}-{slug}"
```

| 场景 | page_name 示例 |
|---|---|
| 单因子论文 | `factor-arxiv-2024-momentum-momentum-factor` |
| 多因子论文 | `factor-arxiv-2024-multi-absolute-momentum` |
| 多因子论文 | `factor-arxiv-2024-multi-relative-volatility` |

**冲突解决:** 同一篇论文的多个因子通过 slug 后缀区分。`extract_paper.py` 和 `extract_factors.py` 使用相同格式。

### 1.3 Strategy 页面

**统一命名格式: `strategy-{paper_id}`**

一篇论文只生成一个 Strategy 页面（即使包含多个因子）。

### 1.4 Backtest 页面

| 页面类型 | 命名格式 | 示例 |
|---|---|---|
| 策略回测 | `{symbol}-{signal_type}` | `000001-SZ-ma_cross` |
| 参数优化 | `{symbol}-{signal_type}-opt` | `000001-SZ-ma_cross-opt` |
| 因子回测 | `factor-{factor_slug}` | `factor-arxiv-2024-momentum-momentum-factor` |
| 代码生成 | `{paper_id}-{hash前16位}` | `arxiv-2024-momentum-a1b2c3d4e5f6g7h8` |

### 1.5 Slug 生成函数 (统一)

位于 `src/llmwikify/reproduction/utils.py`:

```python
def generate_slug(name: str) -> str:
    slug = name.lower().replace(" ", "-").replace("_", "-")
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug[:80]
```

所有模块(`extract_paper.py`, `extract_factors.py`, `factor.py`, `strategy.py`)使用此函数。

---

## 2. 存储结构

### 2.1 Wiki 目录布局

```
wiki/
├── factor/                    # 因子定义页
│   └── factor-{paper_id}-{slug}.md
├── strategy/                  # 策略定义页 (新)
│   └── strategy-{paper_id}.md
├── trading/                   # 策略定义页 (旧, 保留兼容)
│   └── {legacy_slug}.md
├── codegen/                   # Path B LLM 生成代码
│   └── {paper_id}-{hash}.md
├── backtest/                  # 策略回测结果
│   └── {symbol}-{signal_type}.md
├── factor-backtest/           # 因子回测结果 (自动写入)
│   └── factor-{factor_slug}.md
├── optimization/              # 参数优化结果
│   └── {symbol}-{signal_type}-opt.md
└── sources/                   # 论文摘要
    └── paper-{paper_id}-{suffix}.md
```

### 2.2 Frontmatter Schema

#### Factor 页面

```yaml
---
title: {因子名称}
type: Factor
factor_class: {类别}              # 见 2.3 节
factor_params: {参数字典}          # JSON 格式
factor_source: paper/{paper_id}
signal_type: {信号类型}            # 见 2.4 节
signal_params: {信号参数}          # JSON 格式
status: draft                     # draft | validated | deprecated
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

**必填字段:** title, type, factor_class, factor_params, signal_type, signal_params, status

#### Strategy 页面

```yaml
---
title: Strategy — {paper_id}
type: Strategy
strategy_class: {策略类别}         # 见 2.5 节 (LLM 推断)
signal_type: {信号类型}            # 见 2.4 节
signal_params: {信号参数}          # JSON 格式
factor_refs: [factor-{paper_id}-{slug}]
rebalance_freq: daily             # daily | weekly | monthly | quarterly
status: draft                     # draft | backtested | validated | deprecated
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

**必填字段:** title, type, strategy_class, signal_type, signal_params, status

#### BacktestResult 页面

```yaml
---
title: Backtest — {symbol} — {signal_type}
type: BacktestResult
strategy_ref: {strategy 页面 slug}
symbol: {标的代码}
start: YYYY-MM-DD
end: YYYY-MM-DD
sharpe_ratio: 0.0
max_drawdown: 0.0
win_rate: 0.0
total_return: 0.0
final_cash: 0.0
total_trades: 0
status: success
created: YYYY-MM-DD
---
```

#### FactorBacktest 页面

```yaml
---
title: Factor Backtest — {factor_slug}
type: FactorBacktest
factor_ref: {factor 页面 slug}
symbol: {标的代码}
start: YYYY-MM-DD
end: YYYY-MM-DD
ic_mean: 0.0
icir: 0.0
win_rate: 0.0
annual_return: 0.0
max_drawdown: 0.0
status: success
created: YYYY-MM-DD
---
```

#### Optimization 页面

```yaml
---
title: Optimization — {symbol} — {signal_type}
type: Optimization
strategy_ref: {strategy 页面 slug}
parameter_grid: {参数网格}         # JSON
best_params: {最优参数}            # JSON
created: YYYY-MM-DD
---
```

#### Codegen 页面

```yaml
---
title: Codegen — {paper_id}
type: Codegen
codegen_version: 1
codegen_hash: {sha256 前 16 位}
strategy_ref: {strategy 页面 slug}
created: YYYY-MM-DD
---
```

Body 中存储完整 Python 代码:

```markdown
## Generated Code

```python
{完整代码}
```
```

### 2.3 factor_class 枚举

| 值 | 描述 | 实现文件 |
|---|---|---|
| `momentum` | 动量因子 | `factor_backtest.py` |
| `volatility` | 波动率因子 | `factor_backtest.py` |
| `ma_cross` | 均线交叉因子 | `factor_backtest.py` |
| `rsi` | RSI 因子 | `factor_backtest.py` |
| `value` | 价值因子 | `factor_backtest.py` |
| `quality` | 质量因子 | `factor_backtest.py` |
| `size` | 规模因子 | `factor_backtest.py` |
| `growth` | 成长因子 | `factor_backtest.py` |
| `signal_composite` | 信号复合因子 | `factor_backtest.py` |

**禁止使用 `composite`** — 代码中只实现 `signal_composite`。

### 2.4 signal_type 枚举

| 值 | StrategyNode 类 | 注册表 |
|---|---|---|
| `ma_cross` | `MACrossStrategyNode` | `strategies.py` |
| `rsi` | `RSIStrategyNode` | `strategies.py` |
| `momentum` | `MomentumStrategyNode` | `strategies.py` |
| `volatility` | `VolatilityStrategyNode` | `strategies.py` |
| `factor_rank` | `FactorRankStrategyNode` | `strategies.py` |
| `signal_composite` | `SignalCompositeStrategyNode` | `strategies.py` |
| `codegen` | (LLM 生成) | `backtest.py` |
| `unknown` | (无法识别) | `extract.py` |

### 2.5 strategy_class 枚举

| 值 | 描述 | 推断来源 |
|---|---|---|
| `trend_following` | 趋势跟踪 | LLM 从论文推断 |
| `factor_ranking` | 因子排序 | LLM 从论文推断 |
| `mean_reversion` | 均值回归 | LLM 从论文推断 |
| `stat_arb` | 统计套利 | LLM 从论文推断 |
| `composite` | 复合策略 | LLM 从论文推断 |

**来源:** `repro_extract.yaml` prompt 中的 `strategy_class` 字段，由 LLM 从论文内容推断。

### 2.6 页面间引用关系

```
paper-{paper_id}-logic  ──→  strategy-{paper_id}
paper-{paper_id}-data   ──→  strategy-{paper_id}
factor-{paper_id}-{slug} ──→  strategy-{paper_id} (via factor_refs)
strategy-{paper_id}     ──→  {symbol}-{signal_type} (via strategy_ref)
factor-{paper_id}-{slug} ──→  factor-{factor_slug} (via factor_ref)
```

---

## 3. 代码生成规范 (Path B: QNSandbox)

### 3.1 Prompt 模板规范

#### 模板文件位置

```
src/llmwikify/foundation/prompts/_defaults/
├── repro_extract.yaml          # Phase 1: 论文结构提取
├── repro_factor.yaml           # Phase 2: 因子提取
└── repro_codegen.yaml          # Path B: 策略代码生成
```

#### repro_extract.yaml 新增字段

在 `suggested_signal` 中新增 `strategy_class`:

```yaml
"suggested_signal": {
  "signal_type": "string - one of: ma_cross, rsi, momentum, volatility, factor_rank, signal_composite, unknown",
  "signal_params": {"key": "value"},
  "strategy_class": "string - one of: trend_following, factor_ranking, mean_reversion, stat_arb, composite",
  "confidence": "high|medium|low",
  "reasoning": "string"
}
```

#### repro_factor.yaml 修正

```yaml
"factor_class": "string - momentum|value|volatility|quality|size|growth|signal_composite"
# 注意: composite → signal_composite
```

#### repro_codegen.yaml

生成 Python 策略代码，必须定义 `strategy` 变量 (StrategyNode 子类)。

### 3.2 代码输出 Schema

LLM 生成的代码必须满足:

```python
strategy = MyStrategy(config={
    "signal_params": {...},
})

class MyStrategy(StrategyNode):
    def _generate_signals(self, data: pd.DataFrame) -> list[Signal]:
        signals = []
        # ... 生成信号
        return signals
```

**校验规则:**
1. 代码必须包含 `strategy` 变量 (StrategyNode 实例)
2. 代码必须包含 `quote_data` DataFrame (由 sandbox 注入)
3. 代码必须可被 `CodeSandbox` 安全执行
4. 代码长度 ≤ 500,000 字符

### 3.3 存储规范

生成的代码存储在 `wiki/codegen/{paper_id}-{hash}.md`:
- Frontmatter: `codegen_version`, `codegen_hash`, `strategy_ref`
- Body: 完整 Python 代码 (markdown code block)

Strategy 页面通过 `codegen_ref` 字段引用 Codegen 页面。

### 3.4 版本管理

| 字段 | 说明 |
|---|---|
| `codegen_version` | 代码生成版本号 (整数，从 1 递增) |
| `codegen_hash` | SHA256 哈希前 16 位，用于去重 |

**版本递增规则:**
- 修改 `signal_params` → version +1
- 修改 `strategy_class` → version +1
- 修改 `rebalance_freq` → version +1
- 仅修改注释/格式 → version 不变

### 3.5 安全校验

代码执行前必须通过 QuantNodes `CodeSandbox` 校验:

```python
from QuantNodes.ai.sandbox import CodeSandbox

sandbox = CodeSandbox(max_code_length=500_000)
validation = sandbox.validate(code)
if not validation.is_safe:
    return BacktestResult(status="error", error="; ".join(validation.errors), security_status="unsafe")
```

**禁止项:** 文件系统操作、网络操作、进程操作、反射操作、内存限制突破。

---

## 4. 数据流规范

### 4.1 Paper → Factor → Strategy 完整流程

```
用户输入: PDF/URL
    ↓
POST /api/paper/start
    ↓
extract_paper_structure(paper_content, paper_id, llm_client)
    ↓
LLM 输出 JSON:
{
  "strategy_logic": {...},
  "suggested_signal": {
    "signal_type": "ma_cross",
    "signal_params": {"fast": 5, "slow": 20},
    "strategy_class": "trend_following"    ← LLM 推断
  },
  ...
}
    ↓
build_paper_pages(extraction, paper_id)
    ↓
写入 Wiki:
  wiki/sources/paper-{paper_id}-logic.md
  wiki/sources/paper-{paper_id}-data.md
  wiki/sources/paper-{paper_id}-risks.md
  wiki/factor/factor-{paper_id}-{slug}.md
  wiki/strategy/strategy-{paper_id}.md
    ↓
GET /api/factor/list          → 展示因子列表
GET /api/strategy/list        → 展示策略列表
    ↓
POST /api/factor/{slug}/backtest   → IC/分层回测 + 自动写入 wiki/factor-backtest/
POST /api/strategy/{slug}/backtest → 策略回测 + equity_curve + monthly_returns
    ↓
写入:
  wiki/backtest/{symbol}-{signal_type}.md
  wiki/factor-backtest/factor-{factor_slug}.md
```

### 4.2 5-Phase Pipeline 数据流

```
POST /api/reproduction/start
    ↓
Phase 1: extracting
  extract_strategy_config(wiki)  → 读取 wiki/strategy/ + wiki/trading/
    ↓
Phase 2: data fetching
  DataRouter.get(symbol, start, end)  → 4 层 fallback
    ↓
Phase 3: backtesting
  run_backtest(signal_type, data, config)  → Path A 或 Path B
    ↓ 返回 equity_curve + monthly_returns
Phase 4: analyzing
  写入:
    wiki/backtest/{symbol}-{signal_type}.md
    wiki/optimization/{symbol}-{signal_type}-opt.md
    ↓
Phase 5: done
  update_session_status("done")
  emit "finalize.done" event
```

---

## 5. API 响应规范

### 5.1 Factor 响应

```json
{
  "slug": "factor-arxiv-2024-momentum-momentum-factor",
  "name": "Momentum Factor",
  "factor_class": "momentum",
  "factor_params": {"lookback": 20},
  "signal_type": "momentum",
  "signal_params": {"period": 20},
  "factor_source": "paper/arxiv-2024-momentum",
  "status": "draft",
  "wiki_page": "wiki/factor/factor-arxiv-2024-momentum-momentum-factor.md"
}
```

### 5.2 Strategy 响应

```json
{
  "slug": "strategy-arxiv-2024-momentum",
  "name": "Strategy — arxiv-2024-momentum",
  "strategy_class": "trend_following",
  "signal_type": "ma_cross",
  "signal_params": {"fast": 5, "slow": 20},
  "factor_refs": ["factor-arxiv-2024-momentum-momentum-factor"],
  "rebalance_freq": "daily",
  "status": "draft",
  "wiki_page": "wiki/strategy/strategy-arxiv-2024-momentum.md"
}
```

### 5.3 Backtest 响应

```json
{
  "status": "success",
  "sharpe_ratio": 1.23,
  "max_drawdown": -0.152,
  "win_rate": 0.583,
  "total_return": 0.345,
  "final_cash": 1345000.0,
  "total_trades": 47,
  "equity_curve": [
    {"date": "2024-01-02", "value": 1000000.0},
    {"date": "2024-01-03", "value": 1005000.0}
  ],
  "monthly_returns": {
    "2024-01": 2.3,
    "2024-02": 1.5
  }
}
```

---

## 6. 枚举值对照表

| 维度 | 允许值 | 来源 |
|---|---|---|
| `factor_class` | momentum, volatility, ma_cross, rsi, value, quality, size, growth, signal_composite | `factor_backtest.py` |
| `signal_type` | ma_cross, rsi, momentum, volatility, factor_rank, signal_composite, codegen, unknown | `strategies.py` + `backtest.py` |
| `strategy_class` | trend_following, factor_ranking, mean_reversion, stat_arb, composite | `repro_extract.yaml` |
| `status` (Factor) | draft, validated, deprecated | `schemas.py` |
| `status` (Strategy) | draft, backtested, validated, deprecated | `schemas.py` |
| `status` (Backtest) | success, error | `schemas.py` |
| `rebalance_freq` | daily, weekly, monthly, quarterly | `schemas.py` |
| `source_type` | pdf, url | `paper.py` |

---

## 7. 迁移策略

### 7.1 旧数据兼容

- `wiki/trading/` 目录保留，`extract.py` 继续双扫描
- 旧 `factor-{paper_id}` 格式的 Factor 页面需迁移到 `factor-{paper_id}-{slug}`

### 7.2 渐进式迁移

1. **Phase 1:** 新代码使用统一格式，旧页面保持不变
2. **Phase 2:** 添加迁移脚本，批量重命名旧 Factor 页面
3. **Phase 3:** 废弃 `wiki/trading/` 扫描 (可选，长期)

### 7.3 向后兼容

- API 响应同时返回 `slug` 和 `wiki_page` 字段
- 前端使用 `slug` 作为路由参数
- 旧的 `wiki_page` 路径仍然可读
