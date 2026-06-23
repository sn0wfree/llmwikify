# 101 Formulaic Alphas

WorldQuant 2015 年发表的 101 个公式化 alpha 因子。

## 目录结构

```
101_alphas/
├── _meta.yaml                    # 工作族元数据
├── index.yaml                    # 因子索引
├── README.md                     # 本文档
├── scripts/                      # 生产脚本
│   ├── phase1_code_gen.py        # Phase 1: LLM 代码生成 + 回测
│   ├── phase3_metadata.py        # Phase 3: LLM 提取元数据
│   ├── migrate_factors.py        # 迁移脚本
│   ├── demo_react.py             # ReAct 演示
│   └── config.yaml               # 运行配置
├── data/                         # 数据文件
│   ├── track_b_checkpoint.json   # 公式输入
│   ├── pass2.json                # Phase 1 提取结果
│   ├── h5/                       # H5 数据
│   │   └── stk_daily.h5
│   └── output/                   # 输出文件
│       ├── single_factor_001.json
│       └── ...
├── stk_alpha_001_{hash}/         # 因子目录
│   ├── factor.yaml               # L1-L4, L6
│   ├── code.py                   # L5 代码
│   ├── meta.json                 # 因子元数据
│   └── backtest/
│       └── latest.json           # 回测摘要
└── ...
```

## 快速开始

### 1. 配置 LLM

编辑 `~/.llmwikify/llmwikify.json`:

```json
{
  "llm": {
    "api_key": "sk-...",
    "model": "minimax-M3",
    "provider": "minimax",
    "base_url": "https://api.minimaxi.com/v1",
    "enabled": true
  }
}
```

### 2. 运行 Phase 1

```bash
cd quant/factors/101_alphas

# 运行 1-5 号 alpha
python scripts/phase1_code_gen.py --start 1 --end 5

# 跳过已存在的结果
python scripts/phase1_code_gen.py --start 1 --end 101 --skip-existing

# 使用 1-shot 模式 (不使用 ReAct)
python scripts/phase1_code_gen.py --start 1 --end 5 --no-react
```

### 3. 运行 Phase 3

```bash
# 提取元数据 (L2-L6)
python scripts/phase3_metadata.py --start 1 --end 5

# 跳过已存在的结果
python scripts/phase3_metadata.py --start 1 --end 101 --skip-existing

# 设置批处理大小
python scripts/phase3_metadata.py --start 1 --end 101 --batch-size 3
```

### 4. 迁移因子

```bash
# 将旧格式迁移到新目录结构
python scripts/migrate_factors.py
```

## 配置说明

编辑 `scripts/config.yaml` 修改配置:

```yaml
# 路径配置
paths:
  workspace_root: ..
  data_dir: ../data
  output_dir: ../data/output
  track_b: ../data/track_b_checkpoint.json
  h5_dir: ../data/h5
  factors_dir: ..

# 日期配置
date_range:
  start: 20200101
  end: 20241231

# 数据列配置
data_columns:
  - close
  - open
  - high
  - low
  - volume
  - returns
  - vwap
  - id_citic1

# 回测配置
backtest:
  n_groups: 5
  cost_bps: 15
```

## 因子命名规则

```
{asset_class}_{category}_{identifier}_{hash}
```

| 组成部分 | 说明 | 示例 |
|----------|------|------|
| `asset_class` | 资产大类 | `stk`, `fut`, `idx`, `fund` |
| `category` | 因子类别 | `alpha`, `momentum`, `value`, `quality` |
| `identifier` | 唯一编号 | `001`, `002` |
| `hash` | 代码哈希 (6 位 MD5) | `f9f371` |

示例: `stk_alpha_001_f9f371`

## 因子目录结构

每个因子目录包含:

| 文件 | 说明 |
|------|------|
| `factor.yaml` | 因子定义 (L1-L4, L6) |
| `code.py` | Python 实现代码 (L5) |
| `meta.json` | 因子元数据 |
| `backtest/latest.json` | 最新回测摘要 |

### factor.yaml

```yaml
name: stk_alpha_001_f9f371
display_name: "Alpha #1"
asset_type: stk
category: alpha
status: verified
version: 1
l1:
  definition: "..."
  formula: "..."
  frequency: 日频
l2:
  calculation_steps: [...]
  edge_case_handling: "..."
l3:
  financial_intuition: "..."
  market_behavior: "..."
l4:
  hypotheses: [...]
  meaning_summary: "..."
l6:
  failure_conditions: [...]
  crowding_level: "..."
```

### code.py

```python
def compute_factor(df: pl.DataFrame) -> pl.Series:
    # Factor implementation
    ...
```

### backtest/latest.json

```json
{
  "run_id": "pipeline_a_001",
  "status": "success",
  "metrics": {
    "ic_mean": 0.032,
    "icir": 0.224,
    "win_rate": 0.593,
    "annual_return": 0.0000424,
    "longshort_max_dd": -0.039
  }
}
```

## 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                    因子生成工作流程                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. 准备阶段                                                │
│     ├── 配置 LLM (~/.llmwikify/llmwikify.json)             │
│     ├── 准备公式 (data/track_b_checkpoint.json)             │
│     └── 准备数据 (data/h5/stk_daily.h5)                     │
│                                                             │
│  2. Phase 1: 代码生成 + 回测                                │
│     ├── python scripts/phase1_code_gen.py --start 1 --end 5 │
│     └── 输出: data/output/single_factor_*.json              │
│                                                             │
│  3. Phase 3: 元数据提取                                     │
│     ├── python scripts/phase3_metadata.py --start 1 --end 5 │
│     └── 输出: stk_alpha_*_{hash}/factor.yaml (L2-L6)        │
│                                                             │
│  4. 迁移 (可选)                                             │
│     ├── python scripts/migrate_factors.py                   │
│     └── 输出: stk_alpha_*_{hash}/ (新目录结构)              │
│                                                             │
│  5. 验证                                                    │
│     ├── 检查因子目录结构                                    │
│     ├── 测试 WebUI 显示                                     │
│     └── 验证回测数据                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 常见问题

### Q: 如何修改 LLM 模型?

编辑 `~/.llmwikify/llmwikify.json`，修改 `model` 字段。

### Q: 如何修改回测参数?

编辑 `scripts/config.yaml`，修改 `backtest` 部分。

### Q: 如何跳过已存在的结果?

使用 `--skip-existing` 参数:

```bash
python scripts/phase1_code_gen.py --start 1 --end 101 --skip-existing
```

### Q: 如何查看运行日志?

查看 `data/output/phase1_summary.json` 或 `data/output/phase3_summary.json`。

### Q: 如何修改数据源?

编辑 `scripts/config.yaml`，修改 `paths.h5_dir` 指向新的 H5 文件目录。

## 依赖

- Python 3.10+
- polars
- pandas
- pyyaml
- QuantNodes
- llmwikify

## 许可证

Internal use only.
