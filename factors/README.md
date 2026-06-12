# 因子库

基于 6 层方法论的因子库框架，覆盖因子定义、计算、理解、假设、验证、风险管理全流程。

## 框架概述

| 层 | 名称 | 回答的问题 |
|---|---|---|
| **L1** | 逻辑层 | 这个因子是什么？公式怎么写？ |
| **L2** | 计算定义层 | 代码里怎么实现这个公式？ |
| **L3** | 金融理解层 | 这个指标在金融里描述了什么？ |
| **L4** | 因子含义层 | 提出假设 + 沉淀逻辑 |
| **L5** | 验证层 | 因子分析 + 假设检验 |
| **L6** | 风险层 | 什么时候失效？暴露什么风险？ |

## 目录结构

```
factors/
├── index.yaml                    # 因子目录索引
├── README.md                     # 本文件
├── stock/
│   ├── price/
│   │   ├── momentum_20d.yaml     # 股票20日动量因子
│   │   └── volatility_20d.yaml   # 后续扩展
│   └── fundamental/
│       └── value_60d.yaml        # 股票60日估值因子
├── futures/                      # 后续扩展
└── options/                      # 后续扩展
```

## 命名规范

四段式命名：`{资产类型}_{类别}_{子类}_{参数}`

示例：
- `stock_price_momentum_20d` — 股票-价量-动量-20日
- `stock_fundamental_value_60d` — 股票-基本面-估值-60日
- `futures_price_basis_5d` — 期货-价量-基差-5日

## 因子分类

### 价量因子 (price)
- 动量类 (momentum)
- 反转类 (reversal)
- 波动类 (volatility)
- 流动类 (liquidity)
- 成交量类 (volume)

### 基本面因子 (fundamental)
- 估值类 (value)
- 成长类 (growth)
- 质量类 (quality)
- 规模类 (size)

### 复合因子 (composite)
- 信号类 (signal)

## 使用方式

### 查看因子详情

```bash
# 查看因子 YAML
cat factors/stock/price/momentum_20d.yaml

# 查看因子索引
cat factors/index.yaml
```

### 添加新因子

1. 确定因子的资产类型、类别、子类
2. 创建 YAML 文件：`factors/{asset_type}/{category}/{subcategory}_{param}.yaml`
3. 填写 6 层内容
4. 更新 `factors/index.yaml`

### 验证因子

L5 验证由 LLM 自动执行：
1. LLM 读取 L4 假设列表
2. LLM 执行全量因子分析
3. LLM 检验 L4 每个假设
4. 更新 YAML
5. L4 回填 final_meaning

## 设计文档

详细设计请参考：`docs/designs/factor_library_framework.md`
