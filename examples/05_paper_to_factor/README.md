# 05 — Paper → Factor → Backtest

> 对应 [docs/TUTORIAL.md §场景 5](../../docs/TUTORIAL.md#场景-5quant-复现-paper--factor--backtest)

## 跑法

```bash
cd examples/05_paper_to_factor
python play.py
```

预期输出：

```
📁 quant/ scaffolded at /tmp/.../quant
   ['factorbacktest', 'factors', 'papers', 'datacache']

✍️  Wrote factor YAML: /tmp/.../quant/factors/stock/price/momentum_20d.yaml
📚 list_factors: 1 factors
   - momentum_20d                   price

🔍 read_factor_yaml('stock/price/momentum_20d'):
   L1: 20 日动量因子：过去 20 个交易日的对数收益率。
   L2 code (前 60 字符): import pandas as pd...

🗂️  index.yaml updated: True

🦆 DuckDB ready: /tmp/.../quant/factor.duckdb
   tables: [('factor_values',)]

📂 File tree:
   factor.duckdb
   factorbacktest/
   factors/
     index.yaml
     stock/
       price/
         momentum_20d.yaml
   papers/
   datacache/

🎉 Done. quant/ scaffold ready.
```

## 涉及 API

| API | 用途 |
|---|---|
| `write_factor_yaml(name, data, project_root)` | 写 6-layer YAML |
| `list_factors(project_root)` | 列所有因子 |
| `read_factor_yaml(name, project_root)` | 读单个 |
| `update_index(project_root)` | 重建 `factors/index.yaml` |
| `duckdb` | 直接建表（不依赖 quantnodes） |

## CLI 完整流程（需 LLM + 数据源）

```bash
# 0. 装额外依赖
pip install 'llmwikify[quantnodes,llm,web,mcp]'

# 1. 初始化
mkdir -p ~/quant-research && cd ~/quant-research
llmwikify quant-init

# 2. 启 server
llmwikify serve --web --port 8765

# 3. 触发论文抽取（需 OPENAI_API_KEY）
curl -X POST http://localhost:8765/api/paper/start \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer mysecret" \
     -d '{"paper_id": "momentum-101",
          "source": "raw/papers/momentum-101.pdf"}'

# 4. 查进度
curl http://localhost:8765/api/paper/status?run_id=<id>

# 5. 列因子库
curl http://localhost:8765/api/factor/library/list

# 6. 跑回测
curl -X POST http://localhost:8765/api/factor/momentum_20d/backtest
```

## 6-Layer Factor YAML 结构

| 层 | 字段 | 内容 |
|---|---|---|
| L1 | `L1_logic` | 公式描述、tags |
| L2 | `L2_computation` | 可执行 Python 代码 |
| L3 | `L3_intuition` | 金融含义、符号预期 |
| L4 | `L4_hypothesis` | 假设、依据 |
| L5 | `L5_validation` | 验证指标、稳定性 |
| L6 | `L6_risk` | 风险、缓解 |

## 对应 TUTORIAL 节

- §5.2 步骤 0-8
- §5.4 故障排查
- §5.5 进阶：101 Alphas
