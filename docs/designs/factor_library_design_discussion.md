# 因子库设计讨论文档

> 本文档记录因子库框架的所有设计讨论和决策，包括 6 层框架、存储架构、量化研究分离方案、基准测试结果。

---

## 1. 讨论背景

### 1.1 项目定位

llmwikify 是一个知识库项目。因子库是其额外功能，需要在不污染知识库核心的前提下复用知识库的基础设施（LLM、frontmatter、文件存储等）。

### 1.2 核心需求

- 建立基于 6 层方法论的因子库框架
- 因子定义、计算、理解、假设、验证、风险管理全流程覆盖
- 量化研究（Paper/Factor/Strategy）与知识库（Wiki）完全分离
- 因子数据高效存储，支持 L5 自动化验证

---

## 2. 6 层框架设计决策

### 2.1 L1/L2 边界

**决策**：L1 = 数学定义 + 使用规则，L2 = 计算实现 + 工程细节

| 层 | 职责 | 字段 |
|---|---|---|
| **L1 逻辑层** | 因子是什么（纯数学） | definition, formula, input_columns, frequency, output_schema, nan_meaning, default_params, param_constraints, business_constraints |
| **L2 计算定义层** | 怎么算出来（代码实现） | calculation_steps, edge_case_handling, missing_value_handling, data_alignment, complexity, **code_location** |

**关键变更**：`code_location` 从 L1 移到 L2。理由：L1 是数学定义，不应包含代码信息。

### 2.2 L3/L4 边界

**决策**：L3 = 金融教科书内容（理论，不一定对），L4 = 针对具体因子的猜想

| 层 | 归属 | 示例 |
|---|---|---|
| 动量效应理论 | L3 | 已有的金融理论 |
| "A股短期动量可能表现为反转" | L4 | 对该因子的假设（待验证） |
| "高动量→未来继续涨" | L4 | 对该因子的假设（待验证） |

**重要观点**：L3 的理论也需要被检验，不是绝对真理。

### 2.3 L5 评分规则

**决策**：7 维度加权评分（满分 100），60 分通过

| 维度 | 权重 | 指标 |
|---|---|---|
| IC 分析 | 25 | \|IC mean\|、\|ICIR\|、\|RankIC\| |
| 分组分析 | 20 | 多空 Sharpe、分组单调性、多空最大回撤 |
| 收益分析 | 20 | 年化 Sharpe、Calmar、Sortino |
| 换手分析 | 10 | 平均换手率、换手率稳定度 |
| 稳定性分析 | 10 | 分年度一致性、分行业一致性、分市值一致性 |
| 样本外分析 | 10 | OOS RankIC、OOS 多空 Sharpe、IS vs OOS 衰减 |
| 成本分析 | 5 | 扣费后年化收益、成本敏感度 |

**评分阈值**：

| 维度 | 优秀 | 良好 | 及格 | 不及格 |
|---|---|---|---|---|
| \|IC mean\| | >0.05 | 0.03-0.05 | 0.01-0.03 | <0.01 |
| \|ICIR\| | >1.0 | 0.5-1.0 | 0.2-0.5 | <0.2 |
| 多空 Sharpe | >1.5 | >0.5 | >0 | <0 |
| 年化 Sharpe | >1.0 | >0.5 | >0 | <0 |
| Calmar | >1.0 | >0.3 | >0 | <0 |
| Sortino | >1.5 | >0.7 | >0 | <0 |
| 平均换手率 | <20% | <50% | <80% | >80% |
| OOS RankIC | >0.03 | >0.01 | >0 | <0 |
| 扣费后年化 | >5% | >0% | - | <0% |

**status 判定规则**：
- `score ≥ 60` 且无致命缺陷 → `通过`
- `score < 60` → `失败`
- 验证中 / 数据不足 → `待更新`

### 2.4 L5 触发机制

**决策**：混合模式

1. 新因子注册 → 自动触发
2. 用户手动触发（UI 点击"验证因子"按钮）
3. 定时检查（扫描因子，判断是否需要更新，不执行验证）

### 2.5 data_alignment

**决策**：支持两种对齐方式，默认 T+1

- 默认：T 日信号 → T+1 日调仓
- 也支持：T 日对齐（T 日收盘价计算，T 日收盘调仓）

### 2.6 版本控制

**决策**：使用 git

- 因子修改时递增 `version` 字段，更新 `updated_at`
- commit message 格式：`factor({factor_name}): v{version} - {变更摘要}`
- 不需要额外的 changelog 机制（git diff 已记录历史）

### 2.7 L4 假设上限

**决策**：保持 5 个未验证假设上限。超出时归档旧假设。

---

## 3. 量化研究与知识库分离

### 3.1 问题

当前 Paper、Factor、Strategy 全部写入 `wiki/` 目录，污染知识库：

```
Paper 提取 → 写入 wiki/sources/paper-*.md
           → 写入 wiki/factors/factor-*.md     ← 污染
           → 写入 wiki/strategies/strategy-*.md ← 污染

Factor 回测 → 读取 wiki/factor/{slug}.md
            → 写入 wiki/factor/factor-*-{run_id}.md  ← 污染
```

### 3.2 解决方案

**两套 Wiki 实例，共享引擎**

```
wiki/     → 知识库（纯知识）
quant/    → 量化研究（论文/因子/策略）
```

Wiki 引擎是通用的文件存储 + 前端解析 + 全文索引，可以实例化多份。

### 3.3 目录结构

```
your-project/
├── wiki/                         ← 知识库（llmwikify init）
│   ├── sources/
│   ├── entities/
│   ├── concepts/
│   ├── comparisons/
│   ├── synthesis/
│   ├── claims/
│   └── index.md
│
├── quant/                        ← 量化研究（llmwikify quant-init）
│   ├── papers/                   ← 论文理解结果（wiki markdown）
│   ├── factors/                  ← 因子库 6 层 YAML（唯一存储）
│   │   ├── index.yaml
│   │   ├── stock/price/momentum_20d.yaml
│   │   └── stock/fundamental/value_60d.yaml
│   ├── factorbacktest/           ← 回测结果报告（wiki markdown）
│   ├── strategies/               ← 策略定义（wiki markdown）
│   ├── datacache/                ← OHLCV 缓存（Parquet）
│   ├── factor.duckdb             ← 因子值矩阵（DuckDB）
│   └── index.md                  ← 量化研究索引
│
├── raw/                          ← 原始素材
├── index.md
├── log.md
└── wiki.md
```

### 3.4 三者关系

```
┌─────────────────────────────────────────────────────┐
│                    Wiki 引擎                         │
│  (文件存储 + frontmatter + 全文索引 + 页面CRUD)       │
├──────────────────────┬──────────────────────────────┤
│  wiki/ 实例           │  quant/ 实例                 │
│  (知识库)             │  (量化研究)                   │
│                      │                              │
│  sources/            │  papers/    ← Paper 写入      │
│  entities/           │  factors/   ← Factor 定义     │
│  concepts/           │  factorbacktest/ ← 回测写入   │
│  comparisons/        │  strategies/ ← Strategy 写入  │
│  synthesis/          │  factor.duckdb ← 因子值矩阵   │
│  claims/             │  datacache/ ← OHLCV 缓存     │
├──────────────────────┴──────────────────────────────┤
│  factors/ (根目录) 已删除，统一到 quant/factors/      │
└─────────────────────────────────────────────────────┘
```

### 3.5 量化研究初始化命令

**决策**：`llmwikify quant-init` 独立命令

```bash
llmwikify init          ← 初始化知识库
llmwikify quant-init    ← 初始化量化研究
```

`quant-init` 创建：
- `quant/` 目录结构
- `quant/factors/` 含 stock/price/, stock/fundamental/ 子目录
- `quant/factors/index.yaml`（空索引）
- `quant/datacache/`（OHLCV 缓存目录）
- `quant/factor.duckdb`（因子值矩阵）
- `quant/index.md`（量化研究索引）

行为：已存在则跳过（幂等），同 `llmwikify init` 的模式。

---

## 4. 因子数据存储架构

### 4.1 数据类型

| 数据类型 | 说明 | 存储位置 |
|---|---|---|
| 因子定义 | 6 层 YAML（L1-L6） | `quant/factors/*.yaml` |
| 原始 OHLCV | 行情数据 | `quant/datacache/*.parquet` |
| 因子值矩阵 | 每只股票每天的因子值 | `quant/factor.duckdb` |
| 回测结果 | IC series、分组收益、多空曲线 | SQLite + `quant/factorbacktest/*.md` |
| 验证结论 | score/status/final_meaning | YAML L5 节 |

### 4.2 基准测试结果

经过三轮测试逐步缩小方案范围：

#### 第一轮：四方案全面对比（30 因子）

**评估维度**：从速度、压缩、可维护性三个角度对比 Parquet、DuckDB 单表、DuckDB 分表、SQLite。

**速度对比要点**：
- Parquet：单因子按日期查询极快（pandas 内存索引 0.02ms），但批量查询需循环打开文件（223ms）
- DuckDB：SQL 引擎优化，批量查询快（3.76ms），但单因子查询需 SQL 解析开销
- SQLite：读取全面慢（54ms-1627ms），无 CORR 等分析函数

**压缩对比要点**：
- DuckDB 单表压缩最好（0.7x），长表格式 + 内置压缩
- Parquet 宽表压缩 0.6x，但文件分散（100 个文件）
- SQLite 压缩最差（0.1x），无列式存储

**可维护性对比要点**：
- DuckDB：SQL 接口、pandas 集成、schema 变更灵活
- Parquet：简单直接、无依赖、但 schema 变更需重写文件
- SQLite：最成熟但无分析函数、并发写受限

**测试规模**：120 dates × 280 stocks × 30 factors（1M 行）

| 场景 | Parquet | DuckDB 单表 | DuckDB 分表 | SQLite |
|---|---|---|---|---|
| 单因子全量读取 | 7.33ms | 3.61ms | **1.93ms** | 54.25ms |
| 单因子按日期 | **0.02ms** | 0.87ms | 0.60ms | 0.32ms |
| L5 批量（所有因子某天） | 223.24ms | **3.76ms** | 10.31ms | 12.41ms |
| 跨因子相关 | 10.44ms | 2.08ms | **1.54ms** | 1.93ms |
| L5 统计（所有因子均值） | 226.45ms | **3.93ms** | 3.30ms | 205.51ms |
| 增量写入 | 21.77ms | 2.43ms | 1.99ms | **1.57ms** |
| 删除重算 | **13.34ms** | 21.54ms | 15.15ms | 147.90ms |
| 顺序读所有因子 | 212.49ms | 109.41ms | **58.90ms** | 1627.65ms |

**存储**：DuckDB 单表 10.26MB，分表 23.76MB，SQLite 73.29MB

**第一轮结论**：SQLite 全面排除（读取太慢、无分析函数、文件太大）。DuckDB 单表 L5 批量快 3x，推荐单表。

#### 第二轮：单表 vs 分表深入对比（30 因子）

**发现单表 factor_name 字段冗余**：每个因子 33,600 行，每行重复存储 factor_name 字符串，浪费 27% 存储。

**分表优化**：去掉 factor_name 列，每个因子一个表。

| 场景 | 单表 | 分表 | 胜出 |
|---|---|---|---|
| 单因子全量读取 | 3.54ms | **1.81ms** | 分表 2.0x |
| 单因子按日期 | 0.75ms | **0.49ms** | 分表 1.5x |
| **L5 批量（所有因子某天）** | **3.16ms** | 9.86ms | **单表 3.1x** |
| 跨因子相关 | 1.73ms | **1.39ms** | 分表 1.2x |
| L5 统计 | 4.05ms | **2.69ms** | 分表 1.5x |
| 增量写入 | 7.20ms | 7.69ms | 持平 |
| 删除重算 | 18.28ms | **11.81ms** | 分表 1.5x |

**第二轮结论**：L5 批量查询单表快 3x 是关键优势。单表文件更小（10MB vs 23MB）。推荐单表。

#### 第三轮：大规模验证（100 因子）

**测试规模**：500 dates × 5000 stocks × 100 factors（250M 行）

| 场景 | Parquet | DuckDB 单表 | DuckDB 分表 |
|---|---|---|---|
| 单因子全量读取 | 265ms | 329ms | **180ms** |
| L5 批量（所有因子某天） | ~13ms(估) | **390ms** | 438ms |
| 单因子按日期 | **0.03ms** | 6.41ms | 5.13ms |
| L5 统计（所有因子均值） | - | 175ms | **117ms** |
| 增量写入 | - | 13.5ms | **9.1ms** |
| 删除重算 | - | 823ms | **575ms** |

**存储**：DuckDB 单表 2533MB，分表 3716MB，Parquet 2457MB

**第三轮关键发现**：

1. **小规模（<30 因子）**：DuckDB 单表 L5 批量快 3x
2. **大规模（100 因子）**：DuckDB 分表全面反超（单因子读取快 1.8x，L5 统计快 1.5x）
3. **Parquet 批量查询灾难**：需循环打开 100 个文件，223ms vs 3.76ms
4. **SQLite 全面落后**：读取慢 15x、无 CORR 函数、文件大 7x

#### 最终决策

| 因子规模 | 推荐方案 | 理由 |
|---|---|---|
| < 30 因子 | DuckDB 单表 | L5 批量快 3x，代码简单 |
| 30-100 因子 | DuckDB 分表 | 全面更快，文件更紧凑 |
| > 100 因子 | ClickHouse | 生产级分析引擎 |

**当前项目（9 因子）**：DuckDB 单表足够。未来切 ClickHouse 时 SQL 几乎不用改。

### 4.3 最终存储决策

| 阶段 | 存储方案 | 理由 |
|---|---|---|
| 当前（9 因子） | DuckDB 单表 | 零配置、L5 批量快、代码简单 |
| 未来（100+ 因子） | ClickHouse | 生产级分析引擎、分布式、高并发 |
| 迁移方式 | 改连接字符串 | SQL 兼容，成本极低 |

### 4.4 OHLCV 缓存

**决策**：Parquet

理由：
- 访问模式简单（按 universe 整体读写）
- Parquet 更轻量、更小、更快
- 文件大小：HS300 半年约 452KB

### 4.5 因子值矩阵

**决策**：DuckDB 单表

```sql
CREATE TABLE factor_values (
    date DATE,
    stock VARCHAR,
    factor_name VARCHAR,
    value DOUBLE
)
```

理由：
- 当前 9 因子完全够用
- L5 批量查询快（单表一条 SQL）
- 代码最简单（一个连接、一个表）
- 未来切 ClickHouse 时 SQL 几乎不用改

### 4.6 回测结果存储

**决策**：SQLite + wiki markdown

- SQLite：用于查询和 L5 自动化（批量计算 IC、score）
- wiki markdown（`quant/factorbacktest/`）：用于人类可读和 git 版本控制

### 4.7 ClickHouse 兼容性

**DuckDB → ClickHouse 迁移路径**：

```python
# 统一接口，底层可切换
class FactorStore:
    def __init__(self, backend="duckdb"):
        if backend == "duckdb":
            self.con = duckdb.connect("factor.duckdb")
        elif backend == "clickhouse":
            self.con = clickhouse_connect.get_client(...)
    
    def query(self, sql):
        return self.con.execute(sql).fetchdf()
```

ClickHouse 表结构：

```sql
CREATE TABLE factor_values (
    date Date,
    stock String,
    factor_name String,
    value Float64
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (factor_name, date, stock)
```

SQL 兼容性：DuckDB SQL ≈ ClickHouse SQL（90%+ 兼容），迁移只改连接方式。

---

## 5. 因子库 YAML 结构

### 5.1 命名规范

四段式命名：`{资产类型}_{类别}_{子类}_{参数}`

示例：
- `stock_price_momentum_20d` — 股票-价量-动量-20日
- `stock_fundamental_value_60d` — 股票-基本面-估值-60日

### 5.2 因子分类

| 类别 | 代码 | 子类 |
|---|---|---|
| 价量因子 | price | momentum / reversal / volatility / liquidity / volume |
| 基本面因子 | fundamental | value / growth / quality / size |
| 复合因子 | composite | signal |

### 5.3 完整 YAML 结构

```yaml
factor:
  # === 元数据 ===
  name: stock_price_momentum_20d
  name_cn: 股票20日动量
  asset_type: stock
  category: price
  subcategory: momentum
  version: 1
  created_at: 2024-01-01
  updated_at: 2024-07-19
  status: 已注册

  # === L1 逻辑层 ===
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

  # === L2 计算定义层 ===
  l2:
    calculation_steps: [...]
    edge_case_handling: 前20个日期输出NaN
    missing_value_handling: 保持NaN（不插值）
    data_alignment: 默认 T+1：T日信号→T+1日调仓
    complexity: O(T × N)
    code_location: factor_backtest.py:_compute_factor_values

  # === L3 金融理解层 ===
  l3:
    financial_intuition: 过去20天市场对该股票的认可程度
    market_behavior: 价格相对于近期均值的偏离
    theoretical_basis: 行为金融学的锚定效应、动量效应
    historical_effectiveness: 短期动量在A股2010-2020年有效
    related_factors: 与反转因子方向相反

  # === L4 因子含义层 ===
  l4:
    hypotheses: [...]
    hypothesis_limit: 5
    archived_hypotheses: []
    meaning_summary: |
      20日动量因子捕捉股票在近20个交易日内的价格趋势。
      如果H1成立：趋势跟随信号
      如果H2成立：反转信号
    key_insights: [...]
    uncertainty: |
      因子含义尚不明确，需L5验证后确定
    final_meaning: null  # L5验证后回填

  # === L5 验证层 ===
  l5:
    factor_analysis:
      ic_analysis: {...}
      group_analysis: {...}
      return_analysis: {...}
      turnover_analysis: {...}
      stability_analysis: {...}
      oos_analysis: {...}
      cost_analysis: {...}
    hypothesis_testing: [...]
    overall_assessment:
      score: 45
      status: 待更新
      pass_threshold: 60
      final_meaning: 反转因子（H2成立）
    validation_date: 2024-01-01~2024-07-19

  # === L6 风险层 ===
  l6:
    window_sensitivity: {...}
    regime_sensitivity: {...}
    style_exposure: {...}
    industry_concentration: 中等
    crowding_level: 中等
    decay_analysis: {...}
    failure_conditions: 市场剧烈反转时
    risk_notes: 可能暴露于系统性风险
```

---

## 6. L4 假设生命周期

```
未验证 (unverified)
    ↓ LLM 决定检验
验证中 (verifying)
    ↓ 检验完成
支持 (supported) / 不支持 (unsupported) / 部分支持 (partial)
    ↓ 归档
归档 (archived)
```

---

## 7. L5 自动检验流程

```
触发条件（混合模式）：
  1. 新因子注册 → 自动触发
  2. 用户手动触发（UI 点击"验证因子"）
  3. 定时检查（扫描因子，判断是否需要更新，不执行验证）
    ↓
LLM 读取 L4 假设列表
    ↓
LLM 执行全量因子分析（IC / 分组 / 收益 / 换手 / 稳定性 / OOS / 成本）
    ↓
LLM 检验 L4 每个假设
    ↓
更新 YAML（因子分析结果 + 假设状态 + 综合评估）
    ↓
L4 回填 final_meaning
    ↓
生成验证报告（HTML）
```

---

## 8. 因子详情页内容板块

| 板块 | 内容 | 层级 | 展示形式 |
|---|---|---|---|
| 因子卡片 | 名称、类别、一句话描述、验证状态 | L1+L4+L5 | 顶部卡片 |
| 逻辑定义 | 一句话定义、数学公式、输入列、输出 schema、默认参数、约束 | L1 | 文本 + 公式 + 参数表 |
| 计算过程 | 计算步骤、代码实现、中间产物、边界处理 | L2 | 流程图 + 代码片段 |
| 金融理解 | 金融直觉、理论基础、历史有效性 | L3 | 文本段落 |
| 因子含义 | 假设列表 + 因子含义总结 + 关键洞察 + 不确定性 | L4 | 假设卡片 + 文本段落 |
| 验证结果 | 因子分析（IC/分组/收益/换手/稳定性/OOS/成本）+ 假设检验 + 综合评估 | L5 | 图表 + 表格 |
| 风险诊断 | 窗口敏感度、市场环境对比、风格暴露雷达图 | L6 | 图表 |
| 历史版本 | 因子修改记录、验证更新记录 | 全部 | 时间线 |

---

## 9. 因子目录展示

按类别分组：

```
价量因子
├── 动量类
│   ├── stock_price_momentum_20d — 待验证
│   └── stock_price_momentum_60d — 已通过
├── 波动类
│   └── stock_price_volatility_20d — 已通过
└── ...

基本面因子
├── 估值类
│   └── stock_fundamental_value_60d — 待验证
└── ...
```

---

## 10. 实施计划

### Phase 0：初始化命令

**新建** `src/llmwikify/interfaces/cli/commands/quant_init_cmd.py`

`llmwikify quant-init` 创建 quant/ 目录结构。

### Phase 1：Quant Wiki 模块

**新建** `src/llmwikify/reproduction/quant_wiki.py`

- `get_quant_wiki()` → 返回指向 quant/ 的 Wiki 实例
- 复用 wiki 引擎的 read_page / write_page / index

### Phase 2：Factor Library 模块

**新建** `src/llmwikify/reproduction/factor_library.py`

- `list_factors()` → 读 quant/factors/index.yaml
- `read_factor_yaml(name)` → 读 quant/factors/{path}.yaml
- `write_factor_yaml(name, data)` → 写 quant/factors/{path}.yaml

### Phase 3：Paper 分离

**修改** `src/llmwikify/interfaces/server/http/paper.py`

- wiki.write_page → quant_wiki.write_page
- 论文结果写入 quant/papers/
- 因子提取结果写入 quant/factors/（6 层 YAML）
- 策略提取结果写入 quant/strategies/

### Phase 4：Factor 分离

**修改** `src/llmwikify/interfaces/server/http/factor.py`

- GET /api/factor/list → 从 quant/factors/index.yaml 读取
- GET /api/factor/{slug} → 从 quant/factors/ 读取 YAML
- _persist_factor_result() → 写入 quant/factorbacktest/
- 新增 /api/factor-library/* 端点

**修改** `src/llmwikify/reproduction/extract_factors.py`

- build_factor_pages() → 生成 6 层 YAML
- 删除 read_factor_from_wiki() / list_factors()

### Phase 5：Strategy 分离

**修改** `src/llmwikify/interfaces/server/http/strategy.py`

- 列表和读取从 quant/strategies/ 读取

### Phase 6：因子详情页 UI

**新建** `ui/webui/src/components/factor/FactorDetail.tsx` + 子组件

| 组件 | 说明 |
|---|---|
| FactorDetail.tsx | 6 层 Tab 主页面 |
| HypothesisList.tsx | L4 假设列表 |
| OverallAssessment.tsx | L5 综合评估 |
| RiskRadar.tsx | L6 风险雷达 |

**修改** `App.tsx`（新增路由）
**修改** `api.ts`（新增 API 函数）

---

## 11. 文件变更汇总

| 阶段 | 新建 | 修改 |
|---|---|---|
| Phase 0 | quant_init_cmd.py | |
| Phase 1 | quant_wiki.py | |
| Phase 2 | factor_library.py | |
| Phase 3 | | paper.py |
| Phase 4 | | factor.py, extract_factors.py |
| Phase 5 | | strategy.py |
| Phase 6 | FactorDetail.tsx + 3 子组件 | App.tsx, api.ts |

**不动的文件**：
- 知识库核心代码（wiki/, routes.py）
- 共享组件（FactorSelector.tsx）
- 回测引擎（factor_backtest.py）

---

## 12. 已确定决策汇总

| 决策 | 结论 |
|---|---|
| L1/L2 边界 | L1=数学定义+使用规则，L2=计算实现+工程细节；code_location 在 L2 |
| L3/L4 边界 | L3=金融教科书内容（理论，不一定对），L4=针对具体因子的猜想 |
| L5 评分规则 | 7 维度加权（IC25+分组20+收益20+换手10+稳定性10+OOS10+成本5），60分通过 |
| L5 触发机制 | 混合：新因子自动 + 用户手动 + 定时检查 |
| data_alignment | 支持两种，默认 T+1（T日信号→T+1日调仓） |
| 版本控制 | git commit message 记录 |
| L4 假设上限 | 保持 5 个 |
| 因子唯一存储 | quant/factors/（6 层 YAML） |
| 因子值矩阵 | DuckDB 单表（当前），ClickHouse（未来 100+ 因子） |
| OHLCV 缓存 | Parquet |
| 回测结果 | SQLite + wiki markdown |
| 量化研究初始化 | llmwikify quant-init 独立命令 |
| 知识库影响 | 零——不改任何 wiki 核心代码 |

---

## 13. 待深入讨论

- [ ] L6 风格暴露的 P1 接入方案
- [ ] L5 自动检验的具体实现（LLM prompt 设计）
- [ ] 因子详情页的 UI 交互设计
- [ ] ClickHouse 接入时机和部署方案
- [ ] 因子库与现有 wiki/factorbacktest/ 的迁移关系
