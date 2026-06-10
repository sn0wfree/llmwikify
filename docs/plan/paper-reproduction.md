# 论文研报策略复现 — 实施计划

> 创建时间：2026-06-10
> 状态：规划文档（待切分支后实现）
> 版本目标：v0.4.0
> 核心原则：不造新引擎，不造新框架，只做薄适配。

---

## 一、决策汇总

| 决策项 | 选择 |
|---|---|
| M4（券商研报 + arXiv）| 不砍，全做 |
| 数据源 | AKShare（主）+ iFinD（补），不用 Tushare |
| 代码沙箱 | KernelGateway（安全隔离，~200行）|
| 复现层调用方式 | SkillRuntime.execute() 直接调用（方式 A，确定性流程）|
| WebUI | 新增独立 Reproduction 页面（与 Research 平级）|
| 分支 | 当前不切，规划完成后再切 |
| 目标版本 | v0.4.0 |
| 分析层深度 | 后续讨论（M4 阶段再定）|

---

## 二、整体架构

```
用户输入 PDF/URL/arXiv/DOI
  ↓
┌─────────────────────────────────────────────────────────────┐
│ ① 输入 + 通用理解（完全复用 llmwikify，零新代码）            │
│                                                              │
│ extractors.extract() → wiki.ingest_source()                 │
│   → wiki.analyze_source() → generate_wiki_ops()             │
│   → execute_operations()                                    │
│                                                              │
│ 产出：Source Summary 页 + entities/relations/claims          │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ② 论文结构化抽取（1 个新 prompt + 1 个薄函数）              │
│                                                              │
│ repro_extract.yaml prompt：                                 │
│   读取 Source Summary                                       │
│   按 wiki.md 模板抽取：                                     │
│     Logic / Data / Steps / Factors / Model                  │
│     Analysis / Datasets / Risks / References                │
│   写入 wiki 页面                                            │
│                                                              │
│ 路径：strategy/reproduction/extract.py（~80行）             │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ③ 复现层（ChatBase + Skill，SkillRuntime.execute()）        │
│                                                              │
│ Skill: repro.generate                                       │
│   读取 wiki 知识库（Logic/Data/Steps/Factors/Model）         │
│   LLM 生成 backtrader 策略代码 + 回测脚本                    │
│   产出 .ipynb / .py                                         │
│                                                              │
│ Skill: repro.validate                                       │
│   静态校验 + 语法检查                                        │
│                                                              │
│ 调用方式：SkillRuntime.execute("repro", "generate", {...})  │
│ 路径：apps/chat/skills/actions/repro_action.py（~300行）    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ④ 验证层（回测）                                            │
│                                                              │
│ Skill: repro.sandbox                                        │
│   KernelGateway 执行 .ipynb                                 │
│   超时 120s / 隔离执行                                       │
│                                                              │
│ backtrader + DataRouter（AKShare / iFinD）                  │
│   数据获取 → 回测执行 → 指标计算                              │
│   净值曲线 + 交易记录 + 已知偏差                              │
│                                                              │
│ 产出：wiki Backtest.md + Optimization.md                    │
│ 路径：strategy/reproduction/backtest.py（~250行）           │
│ 路径：strategy/data/router.py（~120行）                      │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 分析层                                                   │
│                                                              │
│ 理解层中（前置）：                                            │
│   repro_analyze_strategy.yaml → Analysis 页                  │
│                                                              │
│ 验证层后（后置）：                                            │
│   repro_analyze_backtest.yaml → Optimization 页              │
│   复用 GraphAnalyzer 做知识图谱分析                           │
│                                                              │
│ Prompt：2 个新 YAML                                         │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│ 知识图谱（持续积累）                                         │
│   公式→公式  因子→因子  策略→优势  策略→劣势                  │
│   复现→回测  回测→优化  论文→数据                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 三、wiki.md 模板

wiki.md 定义论文结构化页面模板，引导 LLM 按固定格式抽取：

```markdown
# 论文/研报策略复现

## 页面类型定义

### Papers/<id>/Logic（策略逻辑）
- 核心假设：这篇论文的核心逻辑是什么？
- 市场逻辑：基于什么市场现象/规律？
- 收益来源：alpha 从哪里来？
- 适用条件：什么条件下有效？

### Papers/<id>/Data（数据需求）
- 字段列表：需要哪些数据字段
- 时间粒度：日/分钟/tick
- 标的范围：股票/期货/期权/指数
- 数据来源：Wind/AKShare/iFinD/其他

### Papers/<id>/Steps（操作步骤）
1. 信号生成：什么条件触发买入/卖出
2. 仓位管理：单票仓位上限/总仓位
3. 换仓频率：日/周/月
4. 止损止盈：具体规则
5. 交易成本：手续费/滑点假设

### Papers/<id>/Factors（因子/指标）
每个因子：
- 名称
- 定义（文字描述）
- 公式（LaTeX 或代码）
- 超参数值
- 计算周期

### Papers/<id>/Model（模型/框架）
- 模型类型：统计/ML/DL/规则
- 框架：backtrader/pandas/sklearn/pytorch
- 训练/验证划分
- 评价指标

### Papers/<id>/Analysis（优劣分析）
- 优势：为什么有效
- 劣势：潜在风险、失效条件
- 适用场景：市场类型、标的范围、时间周期
- 与其他策略的关系
- 改进方向

### Papers/<id>/Datasets（数据集）
- 数据集名称
- 来源
- 时间范围
- 处理方式（清洗/复权/标准化）

### Papers/<id>/Risks（风险与偏差）
- 已知局限
- 假设风险
- 实现偏差
- 数据局限

### Papers/<id>/References（参考文献）
- 原文引用
- 相关论文
- 代码仓库

### Papers/<id>/Backtest（回测结果）
- 指标汇总
- 净值曲线
- 交易记录
- 已知偏差说明

### Papers/<id>/Optimization（优化建议）
- 参数调整
- 因子改进
- 风控增强
- 其他改进
```

---

## 四、各层详解

### 4.1 输入层（零新代码）

完全复用 llmwikify 现有链路：

```
llmwikify ingest <source>
  → extractors.extract(source)        # 30+ 格式
  → wiki.ingest_source(content)       # raw/ + 元数据
  → wiki.analyze_source(raw_path)     # LLM 提取
  → execute_operations()              # 写入 wiki 页
```

### 4.2 论文结构化抽取（Phase 2）

Phase 1 产出 Source Summary 后，Phase 2 读取它并生成论文专属页面：

```python
# strategy/reproduction/extract.py（~80行）

async def extract_paper_structure(wiki, source_summary_page):
    """读取 Source Summary，按 wiki.md 模板生成论文结构化页面"""
    summary = wiki.read_page(source_summary_page)
    # 调用 repro_extract.yaml prompt
    # LLM 返回结构化 JSON
    # 按 wiki.md 模板写入各页面
    for page_name, content in extraction_result.items():
        wiki.write_page(f"Papers/{paper_id}/{page_name}", content)
    # 写入知识图谱
    wiki.write_relations(relations)
```

### 4.3 复现层（Skill + ChatBase）

```python
# 注册 Skill
class ReproSkill(Skill):
    name = "repro"
    actions = {
        "generate": SkillAction(handler=generate_handler, ...),
        "validate": SkillAction(handler=validate_handler, ...),
        "sandbox":  SkillAction(handler=sandbox_handler, ...),
    }

# 程序化调用（方式 A，确定性流程）
async def reproduce(wiki, paper_id):
    runtime = SkillRuntime.default()
    ctx = SkillContext(wiki=wiki, llm_client=llm)

    # 1. 读取 wiki 知识库
    pages = {
        "logic": wiki.read_page(f"Papers/{paper_id}/Logic"),
        "data": wiki.read_page(f"Papers/{paper_id}/Data"),
        "steps": wiki.read_page(f"Papers/{paper_id}/Steps"),
        "factors": wiki.read_page(f"Papers/{paper_id}/Factors"),
        "model": wiki.read_page(f"Papers/{paper_id}/Model"),
    }

    # 2. 生成代码
    result = await runtime.execute("repro", "generate", {"pages": pages}, ctx)
    code = result.data["code"]

    # 3. 校验
    result = await runtime.execute("repro", "validate", {"code": code}, ctx)

    # 4. 执行
    result = await runtime.execute("repro", "sandbox", {"code": code}, ctx)

    # 5. 写回 wiki
    wiki.write_page(f"Papers/{paper_id}/Backtest", result.data["report"])
```

### 4.4 验证层（backtrader）

```python
# strategy/reproduction/backtest.py（~250行）

class BacktestRunner:
    def run(self, code, data, config):
        """执行 backtrader 回测"""
        cerebro = bt.Cerebro()
        # ... 加载策略、数据、配置
        results = cerebro.run()
        return {
            "metrics": {sharpe, mdd, total_return, ...},
            "pnl_curve": ...,
            "trades": [...],
        }
```

### 4.5 分析层（LLM prompt）

前置分析（理解层中）：`repro_analyze_strategy.yaml` → Analysis 页
后置分析（验证层后）：`repro_analyze_backtest.yaml` → Optimization 页

---

## 五、文件清单

| 文件 | 行数 | 说明 |
|---|---|---|
| `strategy/reproduction/config.py` | ~50 | AKShare/iFinD/backtest 配置 |
| `strategy/reproduction/extract.py` | ~80 | 论文结构化抽取（调 LLM + write_page）|
| `strategy/reproduction/backtest.py` | ~250 | backtrader 薄封装 |
| `strategy/data/router.py` | ~120 | AKShare + iFinD 路由 |
| `apps/chat/skills/actions/repro_action.py` | ~300 | 3 个 SkillAction（generate/validate/sandbox）|
| `prompts/_defaults/repro_extract.yaml` | ~80 | 结构化抽取 |
| `prompts/_defaults/repro_analyze_strategy.yaml` | ~60 | 策略优劣分析 |
| `prompts/_defaults/repro_codegen.yaml` | ~100 | 代码生成 |
| `prompts/_defaults/repro_code_review.yaml` | ~60 | 代码审查 |
| `prompts/_defaults/repro_analyze_backtest.yaml` | ~80 | 回测分析 |
| `prompts/_defaults/repro_plan.yaml` | ~50 | 执行步骤拆解 |
| **合计** | **~1230** | **Python ~800 + YAML ~430** |

---

## 六、时间线

| 周 | 里程碑 | 交付 |
|---|---|---|
| W1 | M0 骨架 | config + 路由 + Skill 注册 + POC 验证 |
| W2-3 | M1 理解层 | 3 篇论文端到端 → wiki 页 + 图谱 + 策略分析 |
| W4-5 | M2 复现层 | Skill 生成代码 + sandbox 跑通 |
| W6-7 | M3 验证层 | AKShare/iFinD + 回测报告 + 偏差声明 |
| W8 | M4 分析层 | 结果分析 + 优化建议 + 全链路串通 |
| W9-10 | M5 Multi-input | arXiv/DOI/券商研报 |
| W11-12 | M6 测试 + RC | e2e 30+、性能、文档、v0.4.0-rc |
| W13-16 | 缓冲 | bug fix、边缘场景、优化 |

---

## 七、M0 POC 验证（3 个快速验证）

| POC | 内容 | 耗时 | 目的 |
|---|---|---|---|
| AKShare 数据 | 能否拿到 A 股日线？期货？期权？ | 30min | 验证数据源可用性 |
| wiki.md 模板 | repro_extract prompt 能否从 Source Summary 生成正确页面？ | 1h | 验证抽取可行性 |
| KernelGateway | 能否启动 + 执行简单 notebook？ | 30min | 验证沙箱可行性 |

---

## 八、依赖

```toml
[project.optional-dependencies]
repro = [
  "jupyter-kernel-gateway>=2.5",
  "jupyter-client>=8.6",
  "nbformat>=5.10",
  "akshare>=1.16",
  "backtrader>=1.9.78",
  "arxiv>=2.1",
  "habanero>=1.2",
]
ifind = [
  "ifind-py>=1.0",
]
```

---

## 九、MCP 工具（5个）

| 工具名 | 输入 | 输出 |
|---|---|---|
| `wiki_paper_repro_start` | wiki_id, source_type, source_ref | session_id |
| `wiki_paper_repro_status` | session_id | status, progress |
| `wiki_paper_repro_report` | session_id | 抽取结果 |
| `wiki_paper_repro_code` | session_id | notebook 路径 |
| `wiki_paper_repro_backtest` | session_id, symbol, start, end | metrics, curves |

---

## 十、风险与缓解

| 风险 | 缓解 |
|---|---|
| 论文回测数字对不上 | UI「已知偏差」模板 + 逻辑一致 ≠ 数字一致 |
| KernelGateway 复杂度 | M0 POC 验证，失败则降级为 subprocess |
| LLM 不可重现 | seed + low temp + prompt 版本号 |
| iFinD 无 token | fallback 到 AKShare |
| 券商研报 OCR 成本 | 仅按需触发 |
| 代码生成质量 | 三层校验 + smoke test |
