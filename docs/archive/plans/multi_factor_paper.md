# 多因子论文提取方案

## 问题

当前 paper extraction 是**单因子模式**：只在 `extraction.suggested_signal.signal_type != "unknown"` 时创建 1 个 Factor YAML。
101 Formulaic Alphas 描述了 101 个 alpha，不符合单因子假设，所以没有生成任何 Factor。

## 方案

在 `repro_extract.yaml` 输出中新增 `factor_list[]` 数组（每个因子含 L1-L4 元数据）。
`_run_paper_extraction()` 遍历 `factor_list`，对每个因子：
1. 写入 6-layer YAML
2. 调用 `repro_factor_codegen.yaml` 生成 pandas 代码
3. 回测 + L5 验证

### 改动清单

| 文件 | 改动 |
|---|---|
| `repro_extract.yaml` | 新增 `factor_list[]` 到输出 schema |
| `extract_paper.py` | 新增 `_extract_factors_from_list()` 函数 |
| `paper.py` `_run_paper_extraction()` | 新增 `factor_list` 分支（多因子循环） |
| `tests/reproduction/test_parquet_and_formula.py` | 新增多因子提取测试 |

### 流程

```
extract_paper_structure() → extraction{factor_list[]}
  ↓
for each factor in factor_list:
  _extract_factor_from_dict(factor, paper_id) → 6-layer YAML
  write_factor_yaml()
  ↓
  LLM codegen (repro_factor_codegen.yaml) → factor code
  ↓
  _compute_factor_from_code() → factor_wide
  ↓
  IC / 分组 / 多空
  ↓
  L5 验证 (7 modules + score)
  ↓
  LLM 假设检验 + 反思
```

### 风险

- 101 个因子逐一 LLM codegen + 回测 + L5 = **大量 LLM 调用**（~300+ 次）
- 建议：先测试 5 个因子，确认流程正确后再跑全量
