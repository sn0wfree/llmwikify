# Pipeline 框架设计文档

> 最后更新: 2026-06-23
> 状态: 设计阶段 → 实施阶段 (20 阶段 + 单元测试 + AI 执行原则 + 测试规划 + 设计模式 + 部署与运维)

## 1. 设计目标

将 101 alpha 这类论文因子提取工作流抽象为**通用 Pipeline 框架**, 通过配置文件 + prompt group 即可运行新工作流, 无需修改 Python 代码。

**核心思路**: Pipeline 是论文理解的下游消费者, 利用 pipeline 将 paper → factor → strategy 串起来, 每一步都是解耦的、可组合的、中间过程全部沉淀。pipeline 专门负责**高纬度 ReAct/loop**, 调用各 stage 子包的具体功能。

## 2. 整体架构

### 2.1 4 层分层

```
┌──────────────────────────────────────────────────────────────────────┐
│ Layer 4: pipeline/  (顶层编排 - 高纬度 ReAct/loop)                   │
│          runner.py + stages/ + react.py                              │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 3: 子包 (各 stage 的实现)                                       │
│          paper_understanding/ + codegen/ + backtest/ + persist/      │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 2: prompts/ + common/  (跨 stage 共享)                        │
│          prompts/registry.py + common/config.py + common/errors.py   │
├──────────────────────────────────────────────────────────────────────┤
│ Layer 1: data_source/  (数据源, Stage 2 的输入)                      │
│          router.py + akshare + clickhouse + ifind + universe         │
└──────────────────────────────────────────────────────────────────────┘
```

**核心规则**:
- **Layer 4 (pipeline/)**: 只编排, 不写业务逻辑
- **Layer 3 (子包)**: 自包含, 每个子包有独立的 `__init__.py` 暴露公共 API
- **Layer 2 (prompts/, common/)**: 跨 stage 共享, 任何子包可 import
- **Layer 1 (data_source/)**: 独立, 可被任何 stage 调用

### 2.2 包结构 (实际英文名, 不用 stage 数字)

```
src/llmwikify/reproduction/
│
├── __init__.py                       # 公共 API 入口 (兼容旧路径)
│
├── common/                           # ─── Layer 2: 跨 stage 基础 ───
│   ├── __init__.py
│   ├── config.py                     # 全局配置
│   ├── paths.py                      # 路径常量
│   ├── run_id.py                     # run ID 生成
│   ├── telemetry.py                  # 遥测
│   ├── errors.py                     # 错误分类
│   ├── utils.py                      # 工具函数
│   └── llm_factory.py                # LLM 客户端工厂
│
├── prompts/                          # ─── Layer 2: Prompt 子系统 ───
│   ├── __init__.py
│   ├── registry.py                   # PromptRegistry
│   ├── group.py                      # PromptGroup
│   ├── loader.py                     # 从 YAML 加载
│   ├── renderer.py                   # Jinja2 渲染
│   ├── version.py                    # 语义版本
│   ├── store.py                      # 路径管理 (builtin + workspace)
│   └── builtin/                      # 内置 prompt (跟代码走 git)
│       ├── code_gen/
│       │   ├── v1.yaml
│       │   ├── v2.yaml               # 当前默认
│       │   └── v3_experimental.yaml
│       ├── react_feedback/
│       │   ├── v1.yaml
│       │   └── v2.yaml
│       ├── track_a/
│       │   └── v2.yaml
│       ├── track_b/
│       │   └── v2.yaml
│       ├── metadata_extract/
│       │   ├── v1.yaml
│       │   └── v2.yaml
│       ├── hypothesis_test/
│       │   └── v1.yaml
│       └── risk_analyze/
│           └── v1.yaml
│
├── data_source/                      # ─── Layer 1: 数据源 ───
│   ├── __init__.py
│   ├── router.py                     # 链式回退
│   ├── akshare.py
│   ├── clickhouse.py
│   ├── ifind.py
│   ├── universe.py
│   └── quantnodes_adapter.py
│
├── paper_understanding/              # ─── Layer 3: Stage 0 ───
│   ├── __init__.py
│   ├── extract_paper.py
│   ├── extract_factors.py
│   ├── extract_strategy.py
│   ├── quant_wiki.py
│   ├── schemas.py
│   ├── contracts.py
│   └── llm_extraction/               # 整体搬入
│       ├── __init__.py
│       ├── orchestrator.py
│       ├── planner.py
│       ├── track_a.py
│       ├── track_b.py
│       ├── stage0_ingest.py
│       ├── section_detector.py
│       ├── validator.py
│       ├── retry.py
│       ├── defer.py
│       ├── runlog.py
│       ├── preview.py
│       ├── plan_saver.py
│       ├── log_decorator.py
│       └── config.py
│
├── codegen/                          # ─── Layer 3: Stage 1 ───
│   ├── __init__.py
│   ├── llm_code.py                   # 原 codegen_utils.py
│   ├── react_engine.py               # 原 factor_compiler_react.py
│   ├── compiler.py                   # 原 factor_compiler.py
│   ├── repair.py                     # 原 self_repairing.py
│   ├── semantic.py                   # 原 semantic_registry.py
│   ├── metadata.py                   # 原 factor_extractor.py
│   └── ast/                          # AST 子包
│       ├── __init__.py
│       ├── compiler.py
│       ├── nodes.py
│       ├── complexity.py
│       └── extractor.py
│
├── backtest/                         # ─── Layer 3: Stage 2 ───
│   ├── __init__.py
│   ├── runner.py                     # 原 quantnodes_repro.py
│   ├── engine.py                     # 原 factor_backtest.py
│   ├── api.py                        # 原 backtest.py
│   ├── strategies.py
│   ├── metrics.py
│   ├── value_store.py                # 原 factor_value_store.py
│   ├── l5_validation.py
│   └── l5_orchestrator.py
│
├── persist/                          # ─── Layer 3: Stage 3 ───
│   ├── __init__.py
│   ├── factor_library.py
│   ├── sessions.py
│   └── run.py                        # 旧 5-Phase (标记 deprecated)
│
└── pipeline/                         # ─── Layer 4: 顶层编排 ───
    ├── __init__.py
    ├── runner.py                     # PipelineRunner
    ├── workspace.py                  # Workspace
    ├── config.py                     # WorkspaceConfig
    ├── react.py                      # 三层 ReAct
    ├── data_loader.py
    ├── backtest_config.py
    ├── backtest_extract.py
    ├── score.py
    ├── factor_fix.py
    ├── quantnodes_patch.py
    ├── persist.py
    └── stages/
        ├── __init__.py
        ├── base.py                   # Stage ABC
        ├── paper_understanding.py    # Stage 0
        ├── codegen.py                # Stage 1
        ├── backtest.py               # Stage 2
        ├── persist_factor.py         # Stage 3
        └── strategy.py               # Stage 4 (占位)
```

### 2.3 命名映射 (数字 → 实际英文名)

| 数字 | 实际英文名 | 包路径 |
|------|-----------|--------|
| Stage 0 | **paper_understanding** | `reproduction/paper_understanding/` |
| Stage 1 | **codegen** | `reproduction/codegen/` |
| Stage 2 | **backtest** | `reproduction/backtest/` |
| Stage 3 | **persist** | `reproduction/persist/` |
| Stage 4 | **strategy** | `reproduction/strategy/` (暂不做) |

### 2.4 端到端数据流

```
┌────────────────────────────────────────────────────────────────────┐
│ Stage 0: paper_understanding (论文理解)                            │
│ 输入: PDF / parsed.md                                              │
│ 输出: tier1.json + tier2.json + track_b.json + pass2.json          │
│ 实现: paper_understanding/ (含 llm_extraction/ 子包)                │
│ 沉淀: quant/papers/<paper_id>/                                    │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Stage 1: codegen (LLM 代码生成)                                    │
│ 输入: track_b.json + market data (H5)                              │
│ 输出: code.py + single_factor_NNN.json + factor_NNN.h5             │
│ 实现: codegen/  (调用 codegen.llm_code + codegen.react_engine)      │
│ 沉淀: quant/factors/<workspace>/data/output/                      │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Stage 2: backtest (回测验证)                                       │
│ 输入: factor_NNN.h5 + code.py + QN config                          │
│ 输出: backtest_report/ + single_factor_NNN.json (补全 backtest)    │
│ 实现: backtest/  (调用 QuantNodes PipelineRunner)                  │
│ 沉淀: scripts/output/report/ + data/output/                       │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Stage 3: persist_factor (因子定义入库)                             │
│ 输入: formula_brief + code + backtest + pass2.json                 │
│ 输出: factor.yaml (L1-L6) + code.py + meta.json + backtest/        │
│ 实现: persist/  (调用 persist.factor_library + persist.sessions)   │
│ 沉淀: quant/factors/<workspace>/stk_alpha_NNN_HASH/               │
└───────────────────────────────┬────────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────┐
│ Stage 4: strategy (策略组合) [暂不实现]                             │
│ 占位: pipeline/stages/strategy.py                                   │
└────────────────────────────────────────────────────────────────────┘
```

## 3. Stage 解耦设计

### 3.1 通用 Stage 接口 (含 Prompt 依赖声明)

```python
# pipeline/stages/base.py
@dataclass
class StageContext:
    """整个流水线的累积上下文, 替代纯 dict 提供类型标注.

    各 Stage 只读需要的字段, 写自己产出的字段. 中间产物落盘.
    """
    # Stage 0 (paper_understanding)
    paper_dir: Path | None = None
    tier1_path: Path | None = None
    tier2_path: Path | None = None
    track_b_path: Path | None = None
    pass2_path: Path | None = None

    # Stage 1 (codegen)
    formula: str | None = None
    code: str | None = None
    code_path: Path | None = None
    factor_json_path: Path | None = None
    factor_h5_path: Path | None = None

    # Stage 2 (backtest)
    backtest_report_path: Path | None = None
    backtest_metrics: dict | None = None

    # Stage 3 (persist)
    factor_dir: Path | None = None
    factor_yaml_path: Path | None = None
    meta_json_path: Path | None = None
    backtest_latest_path: Path | None = None
    db_session_id: str | None = None

    # 运行状态 (跨 stage 共享)
    error: str | None = None
    alpha_index: int | None = None


class Stage(ABC):
    """Stage 是 pipeline 编排的最小单元, 薄包装, 不含业务逻辑.

    设计选择: 用 ctx 字典 (强类型 dataclass) 而非 Generic[IT, OT]:
      - 14 字段累积, Generic 难以表达
      - 各 Stage 输出类型多样 (Path / dict / dataclass)
      - PipelineRunner 需要 thread 整个 ctx
      - 类型安全靠内部 stage 方法签名, 不靠 ABC
    """
    name: str
    required_prompts: list[str] = []   # 声明 Prompt 依赖

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace

    @abstractmethod
    def run(self, ctx: StageContext, config: WorkspaceConfig, prompts: PromptRegistry) -> StageContext:
        """调子包业务逻辑, 返回更新后的 ctx, 中间产物落盘"""
        ...

    def load(self, ctx: StageContext) -> StageContext:
        """从磁盘加载中间产物, 供后续 Stage 恢复 (默认实现: 无)"""
        return ctx

    def exists(self, ctx: StageContext) -> bool:
        """检查中间产物是否已存在, 支持 --skip-existing (默认实现: False)"""
        return False
```

**StageContext vs dict 选择**:
- StageContext dataclass 提供类型标注 + IDE 补全
- 仍可当 dict 用 (`ctx.code`, `ctx.factor_dir`)
- 字段默认 None, 各 Stage 只设关心的字段
- 替代纯 dict 避免 14 字段拼写错误

### 3.2 Context 字段说明

字段顺序与所属 Stage 已在 StageContext 定义中标注 (Section 3.1)。

**关键约定**:
- 各 Stage 只**读**自己依赖的字段, **写**自己产出的字段
- 中间产物立即落盘 (写 `code_path` / `factor_json_path` 等), ctx 只保留**路径**不保留大数据
- `error` 字段跨 stage 传递, 用于 Level 2 ReAct 决策
- `alpha_index` 是当前处理的 alpha 序号, 用于多 alpha 批处理

**ctx 演化** (典型 101_alphas 流程):
```
Stage 0: paper_dir, tier1_path, tier2_path, track_b_path (LLM 抽取)
Stage 1: + formula, code, code_path, factor_json_path, factor_h5_path (LLM 编码)
Stage 2: + backtest_report_path, backtest_metrics (回测)
Stage 3: + factor_dir, factor_yaml_path, meta_json_path, backtest_latest_path, db_session_id
```

### 3.3 可组合性体现

| 场景 | 触发方式 |
|------|----------|
| 跑全部 | `pipeline.run_all(workspace)` |
| 只跑某些 stage | `pipeline.run(stages=["codegen", "backtest"])` |
| 从中间恢复 | `pipeline.resume_from(workspace, stage="backtest")` |
| 跳过已有 | `pipeline.run_all(workspace, skip_existing=True)` |
| 从 WebUI 单步触发 | POST `/api/pipeline/<workspace>/run_stage` |
| 批量并行 | `pipeline.run_all(workspace, parallel=3)` (默认串行) |

## 4. 三层 ReAct 失败处理

### 4.1 核心思想

"使用 ReAct 框架" 不能简单理解为 "在 PipelineRunner 上也跑一个 ReAct 循环"。ReAct 是"观察-推理-行动"的单步决策循环, 而流水线是"步骤串行"。

需要把 ReAct 思想**纵向分层落地**:

### 4.2 三层架构

```
┌────────────────────────────────────────────────────────────────────┐
│ Level 3: Workspace-level ReAct (跨因子智能重试)                    │
│ ─────────────────────────────────────────────                      │
│ 观察: 多个 alpha 失败模式分类                                       │
│   • 50% 失败 = 系统性问题 (H5 缺失、配置错、API 限流)               │
│   • 30% 失败 = 单点问题 (某 alpha 公式特殊)                         │
│   • 20% 失败 = LLM 不可恢复 (prompt 缺陷)                          │
│                                                                    │
│ 推理: 失败是同一原因吗? 需要全局调整吗?                              │
│ 行动:                                                              │
│   • 同一原因 → 全局调整 (H5 修复、prompt 改写、参数调整)            │
│   • 单点问题 → 跳过该 alpha, 继续                                    │
│   • 不可恢复 → 中断 + 报告                                          │
└────────────────────────────────────────────────────────────────────┘
                                ▲
                                │ (失败模式汇总)
┌───────────────────────────────┴────────────────────────────────────┐
│ Level 2: Pipeline-level ReAct (跨 stage 智能重试)                  │
│ ────────────────────────────────────────────                      │
│ 观察: Stage N 失败, 输出什么? 能否用前序 stage 产物恢复?           │
│                                                                    │
│ 推理: 这是 stage 内部错误还是 stage 间不一致?                       │
│   • stage 内部 → 内部重试 (3 轮 + 错误反馈)                         │
│   • stage 间不一致 → 重新跑前置 stage                                │
│   • 数据问题 → 跳过 (标记为 failed)                                │
│                                                                    │
│ 行动:                                                              │
│   • LLM 生成的可恢复错误 → 切换 prompt 版本重试                    │
│   • 数据/IO 错误 → 重试 N 次后跳过                                  │
│   • 逻辑错误 → 标记 + 上报                                          │
└────────────────────────────────────────────────────────────────────┘
                                ▲
                                │ (LLM 输出错误反馈)
┌───────────────────────────────┴────────────────────────────────────┐
│ Level 1: Stage-level ReAct (单 stage 内部)                        │
│ ──────────────────────────────────────────                         │
│ CodeGen Stage:                                                     │
│   REASON: LLM 生成 code                                            │
│   ACT: extract → sanitize → syntax → safety → execute              │
│   OBSERVE: 失败 → 错误反馈注入 → REASON (最多 4 轮)                 │
│   DECIDE: 成功 → break                                             │
│                                                                    │
│ Backtest Stage:                                                    │
│   ACT: PipelineRunner.run()                                        │
│   OBSERVE: 异常 → 重试 (3 次, 退避 1/2/5s)                        │
│   DECIDE: 仍失败 → 标记 failed + 记录原因                          │
│                                                                    │
│ PersistFactor Stage:                                               │
│   ACT: write YAML + DB                                            │
│   OBSERVE: IO 错误 → 重试 (3 次)                                   │
│   DECIDE: 仍失败 → 标记 failed                                      │
└────────────────────────────────────────────────────────────────────┘
```

### 4.3 Level 1: Stage-internal ReAct

**CodeGen Stage** (已实现, 保留):
- ReAct 状态机: `factor_compiler_react.py::compile_to_code_react`
- 错误类型: EXTRACT / SYNTAX / SAFETY / EXECUTE
- 反馈机制: `OBSERVE_FEEDBACK_TEMPLATE` 注入到 messages
- 重试次数: `max_repair_rounds=3` (4 轮 LLM)

**Backtest Stage** (新增简单 ReAct):
- 状态机: ACT → OBSERVE → DECIDE
- 错误类型: PipelineRunner 异常 / OOM / QN bug
- 反馈: 错误信息记录到 ctx
- 重试: 3 次退避重试 (1s / 2s / 5s)

**PersistFactor Stage** (新增简单 ReAct):
- 状态机: ACT → OBSERVE → DECIDE
- 错误类型: IO 错误 / 磁盘满 / 权限
- 重试: 3 次退避重试

### 4.4 Level 2: Pipeline-level ReAct (新增)

**触发条件**: Level 1 ReAct 用尽后仍然失败

**观察 (Observe)**:
```python
@dataclass
class StageFailure:
    stage: str                    # "codegen" / "backtest" / "persist_factor"
    error_type: str               # "LLM_PERSISTENT" / "QN_BUG" / "IO_ERROR"
    error_message: str
    retry_count: int
    intermediate_outputs: dict    # 失败的中间产物
```

**推理 (Reason)**:
```
判断分支:
1. LLM_PERSISTENT  → 切换 prompt 版本 (v1 → v2 → v3)
2. QN_BUG          → 记录 + 跳过 (不可恢复)
3. IO_ERROR        → 检查磁盘 + 重试
4. DATA_MISSING    → 检查 H5 + 重试
5. UNKNOWN         → 标记 + 跳过 + 记录
```

**行动 (Decide)**:
```python
class PipelineReActDecider:
    def decide(self, failure: StageFailure) -> Decision:
        if failure.error_type == "LLM_PERSISTENT" and self.can_switch_prompt():
            return Decision.SWITCH_PROMPT
        if failure.error_type in ("QN_BUG", "UNKNOWN"):
            return Decision.SKIP
        if failure.retry_count < 3:
            return Decision.RETRY
        return Decision.SKIP_AND_LOG
```

**实现位置**: `reproduction/pipeline/react.py`

### 4.5 Level 3: Workspace-level ReAct (新增)

**触发条件**: 跑完一批 alpha 后, 失败率 > 阈值

**观察 (Observe)**:
```python
@dataclass
class BatchSummary:
    total: int
    success: int
    failed: int
    failures: list[StageFailure]   # 所有失败
    failure_patterns: dict         # 失败模式聚类
```

**推理 (Reason)**:
```
模式识别:
1. 单一错误占 >50% → 系统性问题
2. 错误分散 → 正常 (个别 alpha 公式难)
3. 同一 stage 多失败 → stage 实现 bug
```

**行动 (Decide)**:
```python
class WorkspaceReActDecider:
    def decide(self, summary: BatchSummary) -> Decision:
        # 聚类失败原因
        clusters = self.cluster_failures(summary.failures)
        dominant = max(clusters, key=lambda c: len(c))

        if dominant.ratio > 0.5:
            if dominant.error_type == "LLM_PERSISTENT":
                return Decision.SWITCH_PROMPT_AND_RETRY_BATCH
            if dominant.error_type == "QN_BUG":
                return Decision.ABORT_AND_ALERT
            if dominant.error_type == "IO_ERROR":
                return Decision.WAIT_AND_RETRY

        return Decision.CONTINUE_WITH_FAILURES
```

**实现位置**: `reproduction/pipeline/react.py`

### 4.6 失败处理决策树

```
Stage 执行失败
    │
    ▼
┌─ Level 1: Stage-internal ReAct (3 轮)
│
│   ├─ 成功 → 继续
│   └─ 仍失败 → 进入 Level 2
│
└─ Level 2: Pipeline ReAct 决策
    │
    ├─ 错误类型 = LLM_PERSISTENT
    │   ├─ prompt 可切换 (有备用版本) → 切换 prompt + 重试
    │   └─ 无备用 → 跳过
    │
    ├─ 错误类型 = QN_BUG
    │   └─ 跳过 (不可恢复)
    │
    ├─ 错误类型 = IO_ERROR / DATA_MISSING
    │   ├─ 重试次数 < 3 → 退避重试
    │   └─ 重试次数 >= 3 → 跳过
    │
    └─ 错误类型 = UNKNOWN
        └─ 跳过 + 记录日志
            │
            ▼
    ┌─ Level 3: Batch 模式分析
    │
    │   ├─ 失败率 < 30% → 继续后续 alpha
    │   └─ 失败率 >= 30% → 同类错误主导?
    │       ├─ 是 → 全局调整 (切 prompt / 报警) + 重试
    │       └─ 否 → 继续后续 alpha
```

## 5. WorkspaceConfig 设计

### 5.1 YAML Schema (含 prompts 字段)

```yaml
# quant/factors/<workspace>/config.yaml
workspace:
  name: 101_alphas
  display_name: "101 Formulaic Alphas"
  description: "WorldQuant 2015 年发表的 101 个公式化 alpha"

# ── 数据源 ──
data:
  h5_path: ~/.llmwikify/akshare_cache/quantnodes_h5_long
  load_keys: [cp, open, high, low, volume, returns, vwap, id_citic1]
  date_range: { start: 20200101, end: 20241231 }
  frequency: daily

# ── 公式输入 ──
formula_source:
  type: track_b_checkpoint
  path: ./data/track_b_checkpoint.json
  key: pass1_signals
  index_field: index
  formula_field: formula_brief

# ── Prompt 引用 (关键字段) ──
prompts:
  - name: code_gen
    version: v2                    # 用 builtin v2
  - name: react_feedback
    version: v2
  - name: track_a
    version: v2
  - name: track_b
    version: v2
  - name: metadata_extract
    version: v2
  - name: code_gen                 # 同名多版本: workspace 覆盖
    version: v3_experimental
    source: ./prompts/code_gen/v3_experimental.yaml

# ── 代码生成 ──
codegen:
  max_repair_rounds: 3
  temperature: 0.3
  timeout_sec: 120
  binary_fix:
    enabled: true
    noise: 1e-7

# ── 回测 ──
backtest:
  pipeline: quantnodes
  template: ./scripts/qn_config_template.yaml
  n_groups: 5
  cost_bps: 15
  patches:
    - module: QuantNodes.research.factor_test.nodes.sample_pool_filter_node
      class: SamplePoolFilterNode
      fix: _patch_sample_pool_filter

# ── 元数据提取 ──
metadata:
  batch_size: 3
  layers: [l2, l3, l4, l6]       # 不写 l1, l5
  input_dir: ./data/output
  existing_metadata_dir: ./data

# ── 命名规则 ──
naming:
  asset_class: stk
  category: alpha
  hash:
    algorithm: md5
    length: 6
    source: code.py

# ── 持久化 ──
storage:
  factors_dir: .
  db:
    path: ~/.llmwikify/agent/reproduction.db
    wiki_id: default
    paper_id: 101_alphas_minimal
    source_type: pipeline_a
  slug_template: "{asset_class}_{category}_{index:03d}_{hash}"
  factor_layout: directory

# ── 流水线编排 ──
stages:
  - paper_understanding
  - codegen
  - backtest
  - persist_factor
```

## 6. prompts/ 子系统 ★

### 6.1 三级加载优先级

```
workspace/prompts/<name>/<version>.yaml           (用户覆盖, 不入仓, 最高)
              ↓ 不存在
reproduction/prompts/builtin/<name>/<version>.yaml (内置默认, 入仓)
              ↓ 不存在
代码中硬编码字符串                                  (兜底, 最低)
```

### 6.2 PromptGroup 数据模型

```python
# prompts/group.py
@dataclass
class PromptGroup:
    """一组相关 prompt, 通常对应一个 stage 的一种使用方式"""
    name: str                        # e.g. "code_gen"
    version: str                     # e.g. "v2.0.0"
    source: Literal["builtin", "workspace"]
    system: str                      # 渲染后的 system prompt
    user_template: str               # Jinja2 模板
    feedback_template: str | None    # ReAct 反馈模板 (可选)
    metadata: dict                   # author, created_at, notes...
    raw: dict                        # 原始 YAML (用于调试)

    def render_user(self, **vars) -> str:
        """渲染 user message"""
        return jinja2.Template(self.user_template).render(**vars)

    def render_feedback(self, **vars) -> str:
        """渲染 ReAct 反馈"""
        if not self.feedback_template:
            raise ValueError(f"PromptGroup {self.name} has no feedback_template")
        return jinja2.Template(self.feedback_template).render(**vars)
```

### 6.3 PromptRegistry

```python
# prompts/registry.py
class PromptRegistry:
    """全局 prompt 注册表, 启动时一次性加载"""

    def __init__(self, groups: dict[str, dict[str, PromptGroup]]):
        # groups[name][version] = PromptGroup
        self._groups = groups

    @classmethod
    def from_config(cls, config: list[dict], workspace_path: Path) -> "PromptRegistry":
        """从 workspace config 加载"""
        ...

    def get(self, name: str, version: str = "latest") -> PromptGroup:
        """按 name (+ version) 获取, version='latest' 取最新"""
        ...

    def get_required(self, name: str) -> PromptGroup:
        """获取必需 prompt, 缺失时抛错"""
        ...

    def require(self, *names: str) -> None:
        """批量验证必需 prompt 已加载"""
        for n in names:
            self.get_required(n)

    def list_versions(self, name: str) -> list[str]:
        """列出某 prompt 的所有可用版本"""
        ...
```

### 6.4 PromptGroup YAML 格式 (Jinja2)

```yaml
# prompts/builtin/code_gen/v2.yaml
name: code_gen
version: 2.0.0
description: "LLM code generation for compute_factor()"

system: |
  You are a quant factor code generator.

  DO NOT:
  {% for rule in rules.do_not %}
  - {{ rule }}
  {% endfor %}

  DO:
  {% for rule in rules.do %}
  - {{ rule }}
  {% endfor %}

user_template: |
  Factor: {{ factor_name }}
  Formula (pseudo-code): {{ formula_brief }}

  Available data: {{ available_columns | join(', ') }}

  Output ONLY the python code block.

feedback_template: |
  Your previous code failed.

  Error type: {{ error_type }}
  Error message: {{ error_message }}

  WRONG example:
  ```
  {{ wrong_example }}
  ```

  RIGHT example:
  ```
  {{ right_example }}
  ```

  Fix and output ONLY the code block.

metadata:
  author: "llmwikify"
  created_at: 2026-06-23
  expected_success_rate: 0.95
  notes: "v2 adds with_columns() materialization rules"

required_vars:
  user: [factor_name, formula_brief, available_columns]
  feedback: [error_type, error_message, wrong_example, right_example]
```

### 6.5 Workspace 覆盖示例

```
quant/factors/101_alphas/
├── config.yaml                      # 引用 builtin v2
└── prompts/
    └── code_gen/
        └── v3_experimental.yaml     # 用户自定义实验版
```

```yaml
# quant/factors/101_alphas/prompts/code_gen/v3_experimental.yaml
name: code_gen
version: 3.0.0-experimental
description: "Experimental v3 with stricter rules"

system: |
  You are a quant factor code generator (v3 experimental).
  ... 更严格的规则 ...

user_template: |
  Factor: {{ factor_name }}
  Formula: {{ formula_brief }}
  ... 不同的 prompt 结构 ...

metadata:
  author: "user"
  based_on: "v2.0.0"
  expected_success_rate: null     # 实验中
```

### 6.6 内置 PromptGroup 清单

| PromptGroup | 默认版本 | 用于 Stage | 模板类型 |
|-------------|---------|-----------|----------|
| `paper_ingest` | v1 | Stage 0 | system + user |
| `track_a` | v2 | Stage 0 | system + user |
| `track_b` | v2 | Stage 0 | system + user |
| `code_gen` | v2 | Stage 1 | system + user + feedback |
| `react_feedback` | v2 | Stage 1 | system + user + feedback |
| `metadata_extract` | v2 | **Stage 1** (codegen 时同步提取) | system + user |
| `hypothesis_test` | v1 | Stage 2 (backtest 后期) | system + user |
| `risk_analyze` | v1 | Stage 2 (backtest 后期) | system + user |
| `strategy_compose` | v1 | Stage 4 (占位) | system + user |

**注**: `metadata_extract` 归属 Stage 1 而非 Stage 3, 因为:
- `factor_extractor.py::extract_factor_metadata(llm, formula_brief, code)` 需要 `code` 作为输入
- 必须在 codegen 产生 code 之后才能抽取 metadata
- `codegen/metadata.py` 与 `codegen/llm_code.py` 同包, 共享 LLM client
- Stage 3 (persist) 只写 YAML/DB, 不调 LLM

`hypothesis_test` / `risk_analyze` 归属 Stage 2, 因为:
- 需要 backtest_metrics (IC, ICIR) 作为输入
- 属于"回测后分析", 与 backtest 阶段逻辑连续
- 实际在 `backtest/l5_orchestrator.py` 实现

### 6.7 Stage 声明 Prompt 依赖

```python
# codegen/__init__.py
REQUIRED_PROMPTS = ["code_gen", "react_feedback"]

# codegen/llm_code.py
def generate_factor_code(..., prompts: PromptRegistry):
    prompts.require("code_gen", "react_feedback")

    code_group = prompts.get("code_gen")
    feedback_group = prompts.get("react_feedback")

    system = code_group.system
    user = code_group.render_user(
        factor_name=factor_name,
        formula_brief=formula_brief,
        available_columns=df.columns,
    )
    ...
```

### 6.8 子包与 Prompt 的对应关系

| 子包 | 使用的 Prompt | 通过 |
|------|--------------|------|
| paper_understanding/llm_extraction/ | track_a, track_b, paper_ingest | 参数注入 |
| codegen/llm_code.py | code_gen, react_feedback | 参数注入 |
| codegen/react_engine.py | code_gen, react_feedback | 参数注入 |
| codegen/metadata.py | metadata_extract | 参数注入 |
| backtest/l5_orchestrator.py | hypothesis_test, risk_analyze | 参数注入 |
| persist/run.py | (无, 不需 LLM) | — |

**核心**: 任何需要 LLM 的函数, **第一个 prompt 相关参数**都是 `prompts: PromptRegistry`。

### 6.9 现存硬编码 Prompt 迁移到 builtin/

| 原文件 | 搬入 |
|--------|------|
| `codegen_utils.py:35` `SYSTEM_PROMPT_CODE` | `prompts/builtin/code_gen/v2.yaml` |
| `factor_compiler_react.py:162` `OBSERVE_FEEDBACK_TEMPLATE` | `prompts/builtin/react_feedback/v2.yaml` |
| `factor_extractor.py:41` `SYSTEM_PROMPT_METADATA` | `prompts/builtin/metadata_extract/v1.yaml` |
| `factor_extractor.py:101` `SYSTEM_PROMPT_METADATA_V2` | `prompts/builtin/metadata_extract/v2.yaml` |
| `llm_extraction/track_a.py` | `prompts/builtin/track_a/v2.yaml` |
| `llm_extraction/track_b.py` | `prompts/builtin/track_b/v2.yaml` |
| `l5_orchestrator.py` (hypothesis prompt) | `prompts/builtin/hypothesis_test/v1.yaml` |
| `l5_orchestrator.py` (risk prompt) | `prompts/builtin/risk_analyze/v1.yaml` |

## 7. CLI 设计

### 7.1 双入口并存

CLI 存在**两个入口**, 服务不同场景, **不冲突**:

| 入口 | 命令 | 用途 | 用户群 |
|------|------|------|--------|
| **旧 CLI** (已有, 保留) | `llmwikify reproduce single <paper.pdf>` / `llmwikify reproduce batch <dir>/` | 论文 → 因子 (走 Stage 0 LLM 抽取) | 论文阅读用户 |
| **新 CLI** (Phase 14E 新增) | `python -m llmwikify.reproduction.cli run 101_alphas` | 配置驱动批量 (跳过 Stage 0, 跑 Stage 1-3) | 因子研究用户 |

**两 CLI 共用 `PipelineRunner` 内核**, 不同入口。

**过渡策略**:
1. Phase 14E 上线时, 旧 CLI 标记 `deprecated` (在 docstring 警告)
2. 1-2 个月后 (Phase 14F2 之后) 视情况删除旧 CLI
3. 删除前, 新旧 CLI 必须**功能等价** (旧 CLI 也能跑 101_alphas)

### 7.2 新 CLI (Phase 14E)

```bash
# 跑全部
python -m llmwikify.reproduction.cli run 101_alphas

# 只跑某些 stage
python -m llmwikify.reproduction.cli run 101_alphas --stages codegen,backtest

# 从中间恢复
python -m llmwikify.reproduction.cli run 101_alphas --from backtest

# 跳过已有
python -m llmwikify.reproduction.cli run 101_alphas --skip-existing

# 范围
python -m llmwikify.reproduction.cli run 101_alphas --start 1 --end 10

# 重试失败的
python -m llmwikify.reproduction.cli run 101_alphas --retry-failed

# Level 1 控制
python -m llmwikify.reproduction.cli run 101_alphas --rounds 5

# Level 2 控制
python -m llmwikify.reproduction.cli run 101_alphas --max-stage-retry 5
python -m llmwikify.reproduction.cli run 101_alphas --no-prompt-switch

# Level 3 控制
python -m llmwikify.reproduction.cli run 101_alphas --batch-fail-threshold 0.3

# Prompt 管理
python -m llmwikify.reproduction.cli prompts list 101_alphas
python -m llmwikify.reproduction.cli prompts show code_gen v2

# 列出 workspace
python -m llmwikify.reproduction.cli list

# 创建 workspace 模板
python -m llmwikify.reproduction.cli new my_paper
```

### 7.3 旧 CLI 兼容层 (Phase 1-14E 之间)

旧 CLI 位于 `src/llmwikify/interfaces/cli/commands/reproduce_cmd.py`, 调用 `llm_extraction.run_one_paper`。
**不删除**, 通过兼容层 (`reproduction/__init__.py` PEP 562) 保持工作。

Phase 14E 完成后, 旧 CLI 可选切换到 `PipelineRunner` (功能等价):
```python
# interfaces/cli/commands/reproduce_cmd.py 内部 (Phase 14E 后)
from llmwikify.reproduction.pipeline import PipelineRunner  # 新
# from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper  # 旧
```

## 8. 与 WebUI 集成

```
论文页面 (PaperDetail)
  ┌──────────────────────────────────────────────────┐
  │ Tier 1 / Tier 2 / Track B / Pass 2 (Stage 0)     │
  │ ─────────────────────────────────────────        │
  │ Pipeline 状态:                                    │
  │  • Stage 1 (codegen): 90/99 ✓ (5 重试中)         │
  │  • Stage 2 (backtest): 80/85 ✓ (2 跳过)          │
  │  • Stage 3 (persist_factor): 80/80 ✓              │
  │ 失败模式: [LLM_PERSISTENT: 3, QN_BUG: 2]        │
  │ ─────────────────────────────────────────        │
  │ [继续 Pipeline] [跳过失败] [重试失败]             │
  └──────────────────────────────────────────────────┘
```

WebUI 暴露 3 个操作:
- **继续 Pipeline**: 从下一个 alpha 继续
- **跳过失败**: 标记失败, 继续后续
- **重试失败**: 触发 Level 2/3 ReAct 决策

## 9. 整合散落代码

将 41 个顶层 .py 文件按 stage 归属搬入子包, git mv 保留 blame:

| 原文件 | 搬入子包 |
|--------|----------|
| `extract_paper.py` | `paper_understanding/extract_paper.py` |
| `extract_factors.py` | `paper_understanding/extract_factors.py` |
| `extract.py` | `paper_understanding/extract_strategy.py` |
| `quant_wiki.py` | `paper_understanding/quant_wiki.py` |
| `schemas.py` | `paper_understanding/schemas.py` |
| `contracts.py` | `paper_understanding/contracts.py` |
| `llm_extraction/` | `paper_understanding/llm_extraction/` (整体) |
| `codegen_utils.py` | `codegen/llm_code.py` |
| `factor_compiler_react.py` | `codegen/react_engine.py` |
| `factor_compiler.py` | `codegen/compiler.py` |
| `self_repairing.py` | `codegen/repair.py` |
| `semantic_registry.py` | `codegen/semantic.py` |
| `factor_extractor.py` | `codegen/metadata.py` |
| `ast_compiler.py` | `codegen/ast/compiler.py` |
| `ast_nodes.py` | `codegen/ast/nodes.py` |
| `ast_complexity.py` | `codegen/ast/complexity.py` |
| `ast_extractor.py` | `codegen/ast/extractor.py` |
| `quantnodes_repro.py` | `backtest/runner.py` |
| `factor_backtest.py` | `backtest/engine.py` |
| `backtest.py` | `backtest/api.py` |
| `strategies.py` | `backtest/strategies.py` |
| `metrics.py` | `backtest/metrics.py` |
| `factor_value_store.py` | `backtest/value_store.py` |
| `l5_validation.py` | `backtest/l5_validation.py` |
| `l5_orchestrator.py` | `backtest/l5_orchestrator.py` |
| `quantnodes_adapter.py` | `data_source/quantnodes_adapter.py` |
| `factor_library.py` | `persist/factor_library.py` |
| `sessions.py` | `persist/sessions.py` |
| `run.py` | `persist/run.py` (deprecated) |
| `config.py` | `common/config.py` |
| `paths.py` | `common/paths.py` |
| `run_id.py` | `common/run_id.py` |
| `telemetry.py` | `common/telemetry.py` |
| `error_categorizer.py` | `common/errors.py` |
| `utils.py` | `common/utils.py` |
| `llm_extraction/llm_factory.py` | `common/llm_factory.py` |
| `router.py` | `data_source/router.py` |
| `akshare_data.py` | `data_source/akshare.py` |
| `clickhouse_data.py` | `data_source/clickhouse.py` |
| `ifind_data.py` | `data_source/ifind.py` |
| `universe.py` | `data_source/universe.py` |

将 `scripts/test_one_factor_llm_code.py` (873 行) 拆分到 pipeline/:

| 原位置 | 搬入 |
|--------|------|
| `_patch_sample_pool_filter` | `pipeline/quantnodes_patch.py` |
| `_wide_from_long` | `pipeline/data_loader.py` |
| `_write_factor_h5` | `pipeline/data_loader.py` |
| `_load_market_data` | `pipeline/data_loader.py` |
| `_build_qn_config` | `pipeline/backtest_config.py` |
| `_extract_full_backtest_from_ctx` | `pipeline/backtest_extract.py` |
| `_compute_score` + `_compute_status` | `pipeline/score.py` |
| `persist_code_to_yaml` | `pipeline/persist.py` |
| `save_backtest_to_db` | `pipeline/persist.py` |
| `_derive_input_columns` | `pipeline/data_loader.py` |
| `_is_binary` + `_add_noise` | `pipeline/factor_fix.py` |
| `_llm_code_react` | `pipeline/stages/codegen.py` |
| `_llm_code_oneshot` | `pipeline/stages/codegen.py` |
| `run_one_factor` | `pipeline/runner.py::PipelineRunner.run_one` |

## 10. Workspace 实例

```
quant/factors/101_alphas/
├── _meta.yaml
├── config.yaml                    # WorkspaceConfig (含 prompts 引用)
├── prompts/                       # workspace override
│   └── code_gen/
│       └── v3_experimental.yaml   # 用户实验版
├── data/                          # Stage 0/1/2 中间产物
│   ├── tier1.json
│   ├── tier2.json
│   ├── track_b.json
│   ├── pass2.json
│   ├── output/                    # single_factor_NNN.json
│   └── h5/                        # factor_NNN.h5
├── scripts/                       # workspace 特定 (QN patch 等)
│   └── quantnodes_patch.py
└── stk_alpha_NNN_HASH/            # Stage 3 因子目录
    ├── factor.yaml                # L1-L6
    ├── code.py
    ├── meta.json
    └── backtest/latest.json
```

## 11. 关键设计决策

| 决策 | 理由 |
|------|------|
| 4 层分层 (pipeline/ → 子包 → prompts+common → data_source) | 单一职责, 依赖单向 |
| 子包用实际英文名 (paper_understanding/codegen/backtest/persist) | 比 stage 数字更易理解 |
| prompts/ 独立子系统 | 跨 stage 共享, 集中管理, 可版本化 |
| 两级加载 (builtin + workspace) | 默认跟代码走, 用户可覆盖 |
| Jinja2 + YAML 模板 | 表达力强, 标准库, 易 diff |
| 文件路径 + semver | 直观, git 友好, 易于切换 |
| Stage 薄包装, 业务逻辑全部在子包 | 子包自包含, Stage 只调不写 |
| Prompt 依赖声明在 `__init__.py` | 静态可见, 启动时验证 |
| 不做 Prompt A/B 测试 (本期) | YAGNI, 后续可加 experiments/ |
| Level 3 ReAct 在 pipeline/ 内实现 | 跨 stage/alpha 的编排属于 pipeline 职责 |
| scripts/ 目录消失 | test_one_factor_llm_code.py 删除 |
| 旧 5-Phase run.py 保留在 persist/ | 标记 deprecated, 后续删除 |
| factor_extractor.py 归 codegen/metadata.py | LLM 解析代码, 与 codegen 同质 |
| l5_orchestrator.py / l5_validation.py 归 backtest/ | 本质是回测后分析 |

## 12. 实施步骤

| 阶段 | 任务 | 验证 |
|------|------|------|
| 1 | 创建 7 个新子包目录 (common, prompts, data_source, paper_understanding, codegen, backtest, persist) | 目录结构 |
| 2 | 创建 `prompts/` 子系统 (registry, group, loader, renderer, version, store) | 单元测试 |
| 3 | 把现有硬编码 prompt 字符串迁移到 `prompts/builtin/*/v*.yaml` | 文件存在 |
| 4 | 把 41 个 .py 文件按归属搬入子包, git mv 保留 blame | import 通过 |
| 5 | 子包 `__init__.py` 透传公共 API + 声明 REQUIRED_PROMPTS | 旧 import 可用 |
| 6 | `reproduction/__init__.py` 顶层透传 (兼容旧 import) | 旧代码不破坏 |
| 7 | 实现 `pipeline/PipelineRunner` + `WorkspaceConfig` + `PromptRegistry.from_config` | 加载成功 |
| 8 | 实现 4 个 Stage (paper_understanding/codegen/backtest/persist) | 跑 101_alphas |
| 9 | 实现三层 ReAct (stage/pipeline/workspace) | 注入故障验证 |
| 10 | 删除 `scripts/test_one_factor_llm_code.py` 和 `scripts/run_101_alphas.py` | 不再被引用 |
| 11 | 全量回归 101 alphas | 99/99 success |
| 12 | 写 `quant/factors/101_alphas/config.yaml` + `prompts/` | 配置文件齐全 |

## 13. 开放问题

1. Stage 0 已有实现位置 `llm_extraction/`, 搬入 paper_understanding 是物理搬移还是逻辑包装?
2. Level 3 ReAct 触发时机: 跑完全部 alpha 后? 还是每 N 个 alpha 后?
3. WebUI 论文页面是否需要新增"重跑失败"按钮 (需要 API 端点)?
4. Pipeline 日志格式: 简单 print 还是结构化 (JSON) 日志?
5. 多 workspace 并行: 是否支持 `python -m ... run 101_alphas 12_factors --parallel`?
6. 旧 5-Phase run.py 是删除还是保留 1-2 个版本作为过渡?
7. PromptGroup 是否需要支持跨 workspace 引用 (如 `./shared_prompts`)?

---

# 第二部分: 实施评估与决策

> 章节 14-17 是 2026-06-23 实施评估讨论的记录。

## 14. 实施风险评估

### 14.1 风险等级图例

| 等级 | 含义 |
|------|------|
| 🔴 P0 | 阻塞, 必须先解决 |
| 🟠 P1 | 高风险, 需要明确方案 |
| 🟡 P2 | 中风险, 有 workaround |
| 🟢 P3 | 低风险, 不影响核心交付 |

### 14.2 范围与影响 (基于 grep 实证)

| 事实 | 数据 | 影响 |
|------|------|------|
| 外部 import `reproduction` 的位置 | **20+ 处** in `interfaces/server/http/*.py` | 改动必须保持 API 兼容 |
| `paper.py` 单文件 import 数 | **15+ 处** 涉及 7 个模块 | 是最大的兼容风险点 |
| `interfaces/cli/commands/reproduce_cmd.py` | 用 `llm_extraction.run_one_paper` | Stage 0 物理搬移会破坏 |
| `interfaces/server/http/reproduction.py` | 用 `reproduction.run.RunContext` | persist/run.py 删除风险 |
| scripts/ 总数 | **23 个** .py 文件, 仅 4-5 个真的活跃 | 大量死代码可一起清理 |
| `factor_compiler.py` (AST 路径) | 仍被 `stage_c_debug_llm.py` + `stage_c_e2e_smoke.py` 用 | 用户说已弃, 但脚本未删 |

### 14.3 P0 阻塞风险

#### 🟠 R1. 41 个文件, ~15K 行同时搬迁, 风险太高

**问题**: 一次搬迁 41 个 .py 文件, 等同于重写整个 reproduction/。

**风险**:
- 内部 import 链复杂 (例如 `llm_extraction/track_b.py` 引用 `paper_understanding` 其他文件)
- 跨包循环依赖容易出现
- git mv 批次多, 冲突难解

**建议方案**:
```
P0-A: 分阶段搬迁, 不要一次到位
  Phase 1: 搬迁 prompts/ + common/ + data_source/ (基础层, 无依赖)
  Phase 2: 搬迁 paper_understanding/ (含 llm_extraction/)
  Phase 3: 搬迁 codegen/ (含 ast/ 子包)
  Phase 4: 搬迁 backtest/ + persist/
  Phase 5: 实施 pipeline/ 编排
P0-B: 每个 Phase 内, 先用符号链接 (symlink) 过渡, 验证后再 git mv
```

#### 🔴 R2. `__init__.py` 兼容层是必须的, 不是可选的

**问题**: 20+ 处外部 import 必须保持工作。

**验证依据**:
```
interfaces/server/http/paper.py: 15+ imports
interfaces/server/http/strategy.py: imports reproduction.backtest
interfaces/server/http/reproduction.py: imports reproduction.run, sessions
interfaces/server/http/routes.py: imports sessions
interfaces/cli/commands/reproduce_cmd.py: imports llm_extraction
```

**结论**: `reproduction/__init__.py` 必须做大量 re-export, 否则 WebUI 立即崩溃。

**建议方案**:
```python
# reproduction/__init__.py 兼容层 (约 50-80 行)
from .paper_understanding.extract_paper import extract_paper
from .persist.factor_library import read_factor_yaml, write_factor_yaml
from .persist.sessions import ReproductionDatabase
# ... 全部公共 API
```

**风险**:
- 循环 import (例如 `reproduction/__init__.py` 同时导入 paper_understanding 和 codegen)
- 需要仔细安排导入顺序

#### 🔴 R3. `llm_extraction` 物理搬入 `paper_understanding` 是高风险

**问题**: `llm_extraction/` 内部 16 个文件互相依赖, 整体搬入需要改 16 个文件的内部 import。

**建议方案**:
```
P0-C: 不要物理搬移, 用 re-export 或 symlink
  方案 1: paper_understanding/llm_extraction.py (单文件 re-export)
  方案 2: 软链接 (symlink) - 最简单
```

### 14.4 P1 高风险

#### 🟠 R4. AST 路径是"半弃用"状态, 处理很尴尬

**现状**:
- `codegen_utils.py` + `factor_compiler_react.py` 是当前生产路径
- `factor_compiler.py` (AST) + `ast_compiler.py` + `ast_nodes.py` + `ast_extractor.py` + `ast_complexity.py` + `self_repairing.py` 是"已弃但脚本还在用"
- `semantic_registry.py` (1044 行) 是 AST 路径的一部分

**建议方案**: 全部搬迁不删 (用户决策 2A), 标记 deprecated。

#### 🟠 R5. `interfaces/server/http/paper.py` 强耦合 15+ 个 reproduction 模块

**关键 import 清单** (必须保证):
```python
from llmwikify.reproduction.factor_library import read/write_factor_yaml
from llmwikify.reproduction.sessions import ReproductionDatabase
from llmwikify.reproduction.utils import parse_frontmatter, generate_slug
from llmwikify.reproduction.quant_wiki import get_quant_wiki
from llmwikify.reproduction.extract_paper import extract_paper, _extract_factors_from_list
from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe, run_factor_backtest
from llmwikify.reproduction.router import DataRouter
from llmwikify.reproduction.universe import resolve_universe
from llmwikify.reproduction.factor_value_store import ...
from llmwikify.reproduction.backtest import run_backtest
from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper
```

#### 🟠 R6. `scripts/` 死代码与 101 alpha 真实代码混在一起

**问题**: scripts/ 里有 23 个 .py 文件, 真正活跃的只有:
- `run_101_alphas.py` ✓
- `test_one_factor_llm_code.py` ✓
- `demo_react_self_repair.py` ✓
- `migrate_factors.py` (迁移用, 完成后可删)

**用户决策 3A**: 全部保留, 不归档不删除。

### 14.5 P2 中风险

#### 🟡 R7. prompts/ 子系统是全新设计, 无现成代码可参照

**问题**: 现存 prompt 全部硬编码在 Python 字符串中, 提取到 YAML 是大工程:
- `codegen_utils.py:35` (SYSTEM_PROMPT_CODE, ~80 行)
- `factor_compiler_react.py:162` (OBSERVE_FEEDBACK_TEMPLATE, ~45 行)
- `factor_extractor.py:41, 101` (METADATA, ~60+60 行)
- `llm_extraction/*.py` 多个 prompt (track_a, track_b, ingest...)
- `l5_orchestrator.py` (hypothesis + risk prompts)
- `extract_paper.py` (repro_extract.yaml)
- `factor_compiler.py` (AST 编译 prompt)

**建议方案**:
```
P2-A: 工具辅助 (写迁移脚本 regex 替换)
P2-B: 灰度策略 (新旧并存 1-2 周)
P2-C: 优先级 (先 code_gen v2 + react_feedback v2, 后其他)
```

#### 🟡 R8. Level 3 Workspace ReAct 的"聚类"逻辑是开放的

**MVP 实现**:
- 最简单: 按 error_type 计数, dominant > 50% 触发
- 不做聚类, 用计数器代替
- 触发时机: 跑完分析, 给出全局报告 (而不是流式)

#### 🟡 R9. `prompts/builtin/` 8 个 PromptGroup 需要逐个验证

**测试策略**:
- 单元测试: 模板渲染 (无需 LLM)
- 集成测试: 跑 3-5 个 alpha (低成本验证)
- 全量回归: 一次性 99 个 alpha (最终验证)

#### 🟡 R10. WorkspaceConfig YAML 解析的兼容性

**路径策略**:
- workspace config 路径全部相对 workspace 根目录
- 支持 `~/` 展开 (用 os.path.expanduser)
- 支持环境变量 `$HOME`, `$LLMWIKIFY_ROOT`
- 启动时验证所有路径存在

### 14.6 P3 低风险

#### 🟢 R11. `pipeline/PipelineRunner` 自身的设计风险低

Stage ABC 简单, Context 字典, 配置加载模式成熟。

#### 🟢 R12. CLI 是薄包装, 风险低

简单 argparse + 委托给 PipelineRunner。

### 14.7 隐性风险

#### 🔴 H1. 测试覆盖率可能不足

**现状**: 41 个 reproduction .py 中, **没有看到 tests/reproduction/ 目录**。

**建议方案**:
```
H1-A: 搬迁前, 写 3-5 个关键 import 的 smoke test
  - test_imports.py: 验证 20+ 关键 import 不报错
  - test_factor_library.py: YAML 读写
  - test_sessions.py: DB 操作
  - test_pipeline_runner_init.py: PipelineRunner 初始化
  - test_prompts.py: PromptRegistry 加载
H1-B: 搬迁后立即跑 smoke test
H1-C: 再跑 1-2 个 alpha 的 e2e
```

#### 🔴 H2. `QuantNodes` 依赖是外部的, 我们的 patch 失效风险

**建议方案**:
```
H2-A: 把 patch 应用放到 PipelineRunner.__init__() 的第一行
H2-B: patch 失败时给出清晰错误信息
H2-C: 考虑把 patch 上游贡献给 QuantNodes
```

#### 🔴 H3. `nanobot` 缺失导致 import 失败 (现有问题) — **待验证**

**状态**: 2026-06-23 文档中标记, **但实际未验证**。

**grep 结果** (2026-06-23 验证):
- 全代码库**无** `import nanobot` 或 `from nanobot`
- 仅 8 处注释: `"# Borrowed from nanobot v0.2.1"` / `"# Vendored from nanobot ..."`
- 这些是 **vendored code** (已复制到本地), 不需要外部 nanobot 依赖

**结论**: H3 假设**可能不成立**。`reproduction/__init__.py` 用 PEP 562 懒加载**仍然必要** (避免循环依赖, 减少启动时间), 但动因不是"nanobot 缺失"。

**待 Phase 1 实施前验证**:
```bash
python -c "from llmwikify.reproduction.factor_library import read_factor_yaml"
# 如果成功 → nanobot 不是问题
# 如果 ModuleNotFoundError: No module named 'nanobot' → 假设成立, 需懒加载
```

**建议方案** (无论假设是否成立):
```
H3-A: 把外部 import 全部延迟 (lazy import) — 防患于未然
  - reproduction/__init__.py 用 __getattr__ 实现 PEP 562 懒加载
H3-B: 调研是否有循环依赖 — 即使无 nanobot, 循环依赖也常出现
```

---

## 15. 用户决策 (2026-06-23)

| # | 决策项 | 选择 | 理由 |
|---|--------|------|------|
| 1 | 实施节奏 | **分 5 个 Phase, 每 Phase 独立可回退** | 41 个文件同时搬迁风险太高 |
| 2 | AST 路径处理 | **A: 全部搬迁不删** | 用户已确认, 保留所有 AST 文件 |
| 3 | scripts/ 处理 | **A: 全部保留** | 用户已确认, 不归档不删除 |
| 4 | 搬迁方式 | **物理搬迁 (git mv)** | 用户已确认, 保留 git blame 历史 |

---

## 16. 实施计划 (5 Phases, 2 周)

### 16.1 总体时间线

```
Week 1
├── Phase 1 (1.5 天) - 基础设施层
├── Phase 2 (1.5 天) - Stage 0
├── Phase 3 (1.5 天) - Stage 1
└── Phase 4 (1.5 天) - Stage 2+3

Week 2
├── Phase 5 (2.0 天) - 编排层
└── 回归 (1.5 天) - 99/99 验证
```

### 16.2 Phase 1: 基础设施层 (1.5 天)

**目标**: 不破坏现有 API, 新增 Layer 1+2 基础

**操作**:
```
1.1 新建 common/ 子包
    git mv:
      config.py → common/config.py
      paths.py → common/paths.py
      run_id.py → common/run_id.py
      telemetry.py → common/telemetry.py
      error_categorizer.py → common/errors.py
      utils.py → common/utils.py
      llm_extraction/llm_factory.py → common/llm_factory.py

1.2 新建 data_source/ 子包
    git mv:
      router.py → data_source/router.py
      akshare_data.py → data_source/akshare.py
      clickhouse_data.py → data_source/clickhouse.py
      ifind_data.py → data_source/ifind.py
      universe.py → data_source/universe.py
      quantnodes_adapter.py → data_source/quantnodes_adapter.py

1.3 新建 prompts/ 子包 (全新)
    创建:
      prompts/__init__.py
      prompts/registry.py
      prompts/group.py
      prompts/loader.py
      prompts/renderer.py (Jinja2)
      prompts/version.py
      prompts/store.py
      prompts/builtin/ 目录

1.4 reproduction/__init__.py 加兼容 re-export
    (用 __getattr__ 懒加载, 避免 nanobot 问题)

验证:
  - python -c "from llmwikify.reproduction.factor_library import read_factor_yaml"
  - python -c "from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper"
  - python -c "from llmwikify.reproduction.quant_wiki import get_quant_wiki"
  - 启动 WebUI (curl http://localhost:8765/api/health)
```

**风险**: 低 (新增包, 不改旧模块)
**回退**: 删除 3 个新目录, 旧文件 git mv 回来

### 16.3 Phase 2: Stage 0 - paper_understanding (1.5 天)

**操作**:
```
2.1 新建 paper_understanding/ 子包
    git mv:
      extract_paper.py → paper_understanding/extract_paper.py
      extract_factors.py → paper_understanding/extract_factors.py
      extract.py → paper_understanding/extract_strategy.py
      quant_wiki.py → paper_understanding/quant_wiki.py
      schemas.py → paper_understanding/schemas.py
      contracts.py → paper_understanding/contracts.py

2.2 整体搬入 llm_extraction/ 子包
    git mv: llm_extraction/ → paper_understanding/llm_extraction/

2.3 修复 paper_understanding/llm_extraction/ 内部 import
    所有 from ..xxx 改为 from ..xxx (新路径)
    所有 from .xxx 保持不变

2.4 修复 paper_understanding/ 各文件的 import
    from .schemas, from .contracts, from .quant_wiki 等

2.5 reproduction/__init__.py 继续加 re-export

验证:
  - paper_understanding/llm_extraction/orchestrator.py 可 import
  - WebUI 论文页面: GET /api/paper/{paper_id} 正常
  - reproduce_cmd.py: 跑 1 个 paper 抽取测试
```

**风险**: 中 (llm_extraction 内部依赖复杂)
**回退**: 反向 git mv

### 16.4 Phase 3: Stage 1 - codegen (1.5 天)

**操作**:
```
3.1 新建 codegen/ 子包
    git mv:
      codegen_utils.py → codegen/llm_code.py
      factor_compiler_react.py → codegen/react_engine.py
      factor_compiler.py → codegen/compiler.py
      self_repairing.py → codegen/repair.py
      semantic_registry.py → codegen/semantic.py
      factor_extractor.py → codegen/metadata.py

3.2 新建 codegen/ast/ 子包
    git mv:
      ast_compiler.py → codegen/ast/compiler.py
      ast_nodes.py → codegen/ast/nodes.py
      ast_complexity.py → codegen/ast/complexity.py
      ast_extractor.py → codegen/ast/extractor.py

3.3 codegen/__init__.py 声明
    REQUIRED_PROMPTS = ["code_gen", "react_feedback"]
    # 兼容旧 import 路径 (codegen_utils, factor_compiler_react)
    from .llm_code import SYSTEM_PROMPT_CODE, generate_factor_code, ...
    from .react_engine import compile_to_code_react, ReactStep, ReactResult

3.4 迁移硬编码 prompt 到 prompts/builtin/
    - codegen/llm_code.py: SYSTEM_PROMPT_CODE → prompts/builtin/code_gen/v2.yaml
    - codegen/react_engine.py: OBSERVE_FEEDBACK_TEMPLATE → prompts/builtin/react_feedback/v2.yaml
    - codegen/metadata.py: SYSTEM_PROMPT_METADATA → prompts/builtin/metadata_extract/v1.yaml
    - codegen/metadata.py: SYSTEM_PROMPT_METADATA_V2 → prompts/builtin/metadata_extract/v2.yaml

3.5 reproduction/__init__.py 加 re-export

验证:
  - python -c "from llmwikify.reproduction.codegen_utils import generate_factor_code"
  - 跑 1 个 alpha-001 codegen 步骤 (无 LLM, 用 mock)
  - AST 路径脚本 stage_c_debug_llm.py 仍可 import
```

**风险**: 中-高 (prompt 迁移容易引入不一致)
**回退**: 反向 git mv, 保留 hardcoded prompt 字符串

### 16.5 Phase 4: Stage 2+3 - backtest + persist (1.5 天)

**操作**:
```
4.1 新建 backtest/ 子包
    git mv:
      quantnodes_repro.py → backtest/runner.py
      factor_backtest.py → backtest/engine.py
      backtest.py → backtest/api.py
      strategies.py → backtest/strategies.py
      metrics.py → backtest/metrics.py
      factor_value_store.py → backtest/value_store.py
      l5_validation.py → backtest/l5_validation.py
      l5_orchestrator.py → backtest/l5_orchestrator.py

4.2 新建 persist/ 子包
    git mv:
      factor_library.py → persist/factor_library.py
      sessions.py → persist/sessions.py
      run.py → persist/run.py (标记 deprecated)

4.3 修复 backtest/, persist/ 内部 import
    跨包引用 (e.g. backtest 用 data_source, persist 用 common)

4.4 reproduction/__init__.py 完整 re-export
    # 全部 20+ 个外部 import 必须可用

验证:
  - 跑 1 个 alpha-001 完整 codegen + backtest + persist
  - factor.yaml 生成正确
  - SQLite 写入正确
  - WebUI 因子页面: GET /api/factor/stk_alpha_001_f9f371 正常
```

**风险**: 中 (backtest 内部依赖多)
**回退**: 反向 git mv

### 16.6 Phase 5: 编排层 pipeline/ (2.0 天)

**操作**:
```
5.1 新建 pipeline/ 子包
    创建:
      pipeline/__init__.py
      pipeline/config.py
      pipeline/runner.py
      pipeline/workspace.py
      pipeline/react.py
      pipeline/data_loader.py
      pipeline/backtest_config.py
      pipeline/backtest_extract.py
      pipeline/score.py
      pipeline/factor_fix.py
      pipeline/quantnodes_patch.py
      pipeline/persist.py
      pipeline/stages/base.py
      pipeline/stages/paper_understanding.py
      pipeline/stages/codegen.py
      pipeline/stages/backtest.py
      pipeline/stages/persist_factor.py
      pipeline/stages/strategy.py (占位)

5.2 把 test_one_factor_llm_code.py 拆分到 pipeline/
    _patch_sample_pool_filter → pipeline/quantnodes_patch.py
    _wide_from_long → pipeline/data_loader.py
    _write_factor_h5 → pipeline/data_loader.py
    _load_market_data → pipeline/data_loader.py
    _build_qn_config → pipeline/backtest_config.py
    _extract_full_backtest_from_ctx → pipeline/backtest_extract.py
    _compute_score + _compute_status → pipeline/score.py
    persist_code_to_yaml → pipeline/persist.py
    save_backtest_to_db → pipeline/persist.py
    _derive_input_columns → pipeline/data_loader.py
    _is_binary + _add_noise → pipeline/factor_fix.py
    _llm_code_react → pipeline/stages/codegen.py
    _llm_code_oneshot → pipeline/stages/codegen.py
    run_one_factor → pipeline/runner.py

5.3 写 reproduction/cli/__main__.py
    python -m llmwikify.reproduction.cli run 101_alphas
    python -m llmwikify.reproduction.cli run 101_alphas --stages codegen
    python -m llmwikify.reproduction.cli prompts list 101_alphas
    ...

5.4 写 quant/factors/101_alphas/config.yaml
    完整的 WorkspaceConfig + prompts 引用

5.5 scripts/ 全部保留 (用户决策 3A), 不删任何文件
    CLI 是新增, scripts/ 是历史, 共存

验证:
  - python -m llmwikify.reproduction.cli run 101_alphas --start 1 --end 3
  - python -m llmwikify.reproduction.cli run 101_alphas --stages codegen
  - python -m llmwikify.reproduction.cli prompts list 101_alphas
```

**风险**: 高 (全新, 无现成)
**回退**: 保留 test_one_factor_llm_code.py 作为 fallback, 不删

### 16.7 回归验证 (1.5 天)

```
R.1 跑 5 个 alpha e2e (1-5 号)
    验证 codegen + backtest + persist 全通

R.2 跑 99 个 alpha 全量
    验证 99/99 success (与迁移前对比)

R.3 启动 WebUI
    验证论文页面 + 因子页面 + 策略页面正常

R.4 验证 20+ 外部 import
    写 test_imports.py, 全自动跑

R.5 验证 scripts/ 全部仍可执行
    跑 4-5 个活跃脚本, 确认无破坏

R.6 数据一致性
    跑前: factor.yaml 99 个, DB 99 条
    跑后: 因子目录相同, DB 行数相同
```

---

## 17. 关键实施细节

### 17.1 reproduction/__init__.py 兼容层 (核心)

```python
# src/llmwikify/reproduction/__init__.py
"""Public API for paper/strategy reproduction module.
Uses PEP 562 lazy loading to avoid nanobot import issues.
"""

# 主动 re-export (不会触发 nanobot 的)
from .backtest import run_backtest
from .schemas import BacktestResult, WikiFactor, WikiStrategy, FactorBacktestResult

# 用 __getattr__ 处理其他可能的引用
_LAZY_IMPORTS = {
    "factor_library": ".persist.factor_library",
    "sessions": ".persist.sessions",
    "codegen_utils": ".codegen.llm_code",  # 兼容旧名
    "factor_compiler_react": ".codegen.react_engine",  # 兼容旧名
    "factor_compiler": ".codegen.compiler",
    "factor_extractor": ".codegen.metadata",
    "factor_backtest": ".backtest.engine",
    "factor_value_store": ".backtest.value_store",
    "quantnodes_repro": ".backtest.runner",
    "quantnodes_adapter": ".data_source.quantnodes_adapter",
    "extract_paper": ".paper_understanding.extract_paper",
    "extract_factors": ".paper_understanding.extract_factors",
    "extract": ".paper_understanding.extract_strategy",
    "quant_wiki": ".paper_understanding.quant_wiki",
    "router": ".data_source.router",
    "universe": ".data_source.universe",
    "utils": ".common.utils",
    "config": ".common.config",
    "paths": ".common.paths",
    "run_id": ".common.run_id",
    "telemetry": ".common.telemetry",
    "error_categorizer": ".common.errors",
    "llm_factory": ".common.llm_factory",
    "akshare_data": ".data_source.akshare",
    "clickhouse_data": ".data_source.clickhouse",
    "ifind_data": ".data_source.ifind",
    "llm_extraction": ".paper_understanding.llm_extraction",
    "run": ".persist.run",  # 旧 5-Phase
    "ast_compiler": ".codegen.ast.compiler",
    "ast_nodes": ".codegen.ast.nodes",
    "ast_complexity": ".codegen.ast.complexity",
    "ast_extractor": ".codegen.ast.extractor",
    "self_repairing": ".codegen.repair",
    "semantic_registry": ".codegen.semantic",
    "l5_orchestrator": ".backtest.l5_orchestrator",
    "l5_validation": ".backtest.l5_validation",
    "strategies": ".backtest.strategies",
    "metrics": ".backtest.metrics",
}

def __getattr__(name):
    if name in _LAZY_IMPORTS:
        import importlib
        module = importlib.import_module(_LAZY_IMPORTS[name], __name__)
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = ["run_backtest", "BacktestResult", "WikiFactor", "WikiStrategy", "FactorBacktestResult"]
```

### 17.2 prompts/builtin/code_gen/v2.yaml 完整结构

```yaml
name: code_gen
version: 2.0.0
description: "LLM code generation for compute_factor()"

system: |
  You are a quant factor code generator.

  DO NOT:
  {% for rule in rules.do_not %}
  - {{ rule }}
  {% endfor %}

  DO:
  {% for rule in rules.do %}
  - {{ rule }}
  {% endfor %}

user_template: |
  Factor: {{ factor_name }}
  Formula (pseudo-code): {{ formula_brief }}

  Available data: {{ available_columns | join(', ') }}

  Output ONLY the python code block.

metadata:
  author: "llmwikify"
  created_at: 2026-06-23
  expected_success_rate: 0.95

required_vars:
  user: [factor_name, formula_brief, available_columns]
```

**配套 Python 端常量** (作为硬编码 fallback):
```python
# codegen/llm_code.py 顶部
_HARDCODED_SYSTEM_PROMPT_CODE = """...原字符串..."""
_HARDCODED_RULES = {
    "do_not": ["if/and/or on polars Expr", ...],
    "do": ["function form", ...],
}
```

### 17.3 验证清单 (每次 Phase 完成后跑)

```python
# tests/test_imports.py
import pytest

CRITICAL_IMPORTS = [
    "from llmwikify.reproduction.factor_library import read_factor_yaml, write_factor_yaml",
    "from llmwikify.reproduction.sessions import ReproductionDatabase",
    "from llmwikify.reproduction.quant_wiki import get_quant_wiki",
    "from llmwikify.reproduction.utils import parse_frontmatter, generate_slug",
    "from llmwikify.reproduction.extract_paper import extract_paper",
    "from llmwikify.reproduction.factor_backtest import run_factor_backtest",
    "from llmwikify.reproduction.router import DataRouter",
    "from llmwikify.reproduction.universe import resolve_universe",
    "from llmwikify.reproduction.backtest import run_backtest",
    "from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper",
    "from llmwikify.reproduction.codegen_utils import generate_factor_code",
    "from llmwikify.reproduction.factor_compiler_react import compile_to_code_react",
    "from llmwikify.reproduction.ast_compiler import compile_ast",
    "from llmwikify.reproduction.factor_compiler import FactorCompiler",
    "from llmwikify.reproduction.semantic_registry import get_template",
    "from llmwikify.reproduction.l5_orchestrator import run_l5",
    "from llmwikify.reproduction.metrics import evaluation",
    "from llmwikify.reproduction.quantnodes_repro import run_factor_backtest",
    "from llmwikify.reproduction.factor_value_store import get_factor_values",
    "from llmwikify.reproduction.run import run_reproduction",
]

@pytest.mark.parametrize("import_stmt", CRITICAL_IMPORTS)
def test_import(import_stmt):
    exec(import_stmt)
```

### 17.4 验证节点 (Gate)

> **本节已废弃** — Phase 5 已演进到 14 → 20 阶段, 详细 Gate 验证节点见 **Section 21.4 (新版, 20 阶段对应 Gate)**。
> 保留本节仅为历史参考, 实施时**以 Section 21.4 为准**。

### 17.5 文档同步

每个 Phase 完成后更新:
- `docs/designs/pipeline_framework.md` - 标注"Phase N 已完成"
- `docs/migrations/2026-06-23-pipeline-refactor.md` - 迁移记录
- 提交时 git log 风格: `refactor(repro): Phase N - xxx`

### 17.6 关键风险点 (回退预案)

| 风险 | 触发条件 | 回退方案 |
|------|----------|----------|
| 20+ 外部 import 破坏 | WebUI 启动报错 | git revert Phase commit |
| 论文页面功能异常 | paper.py 报错 | 验证 reproduction/__init__.py 兼容层 |
| Stage 1 跑失败 | codegen 不可用 | 保留 test_one_factor_llm_code.py 作为回退 |
| 99/99 不达标 | Phase 5 失败 | 继续用 run_101_alphas.py, 不强制替换 |
| prompt 迁移引入 bug | LLM 输出异常 | 保留 hardcoded 字符串作为 fallback |

### 17.7 立即可动手的 (Build Mode 启动后)

1. 写 `tests/test_imports.py` 保护现状
2. 验证 `paper.py` 的 15+ import 列表
3. 列出 41 个文件的搬移顺序 (按依赖关系)
4. 写 `reproduction/__init__.py` 兼容层骨架

---

## 18. 时间估算总结

| 阶段 | 工作量 | 风险 | 备注 |
|------|--------|------|------|
| Phase 1: 基础设施 | 1.5 天 | 中 | 全新 prompts/ 设计, 但代码少 |
| Phase 2: Stage 0 | 1.5 天 | 中 | 物理搬移 + 兼容层 |
| Phase 3: Stage 1 | 1.5 天 | 中-高 | 涉及 AST 路径决策 |
| Phase 4: Stage 2+3 | 1.5 天 | 中 | 模块多, 接口多 |
| Phase 5: 编排层 | 2.0 天 | 高 | 全新, 无现成 |
| 回归测试 | 1.5 天 | - | 95% 改完才暴露 |
| **总计** | **9-10 天** | - | 2 周可完成 |

---

## 19. 关键结论

- 风险最大的是 **20+ 外部 import 的兼容性** (R2, R5)
- 最容易踩坑的是 **`scripts/` 死代码误删** (R6, H2) — 用户决策保留
- 最耗时的是 **prompts/ 模板迁移** (R7)
- 推荐**分 5 Phase**, 每 Phase 独立可回退
- 物理搬迁 (git mv) 保留 blame, 是正确选择
- AST 路径全部搬迁不删, 避免破坏 stage_c_* 脚本
- scripts/ 全部保留, 100% 兼容历史

---

# 第三部分: 14 → 20 阶段细化 + 单元测试

> 章节 20-26 是 2026-06-23 关于阶段拆解、依赖关系、单元测试要求的讨论记录。

## 20. 从 7 阶段到 14 阶段的演进

### 20.1 第一轮细化: 5 Phases → 7 Phases

**触发**: 用户提出 prompts/ 子系统是全新设计, 不能与 stage 搬迁混在一起。

**核心调整**: 把 llm_extraction 暂缓, 等 prompts/ 子系统就绪后再搬。

**新结构**:
```
Phase 1: 基础设施层 (1.5 天)
Phase 2: Stage 0 paper_understanding/ (1.0 天) ← 拆出 llm_extraction
Phase 3: Stage 1 codegen/ (1.5 天)
Phase 4: Stage 2+3 backtest + persist (1.5 天)
Phase 5: prompts/ 子系统 + builtin/ 完整填充 (2.0 天) ★
Phase 6: llm_extraction/ 物理搬入 (0.5 天)
Phase 7: pipeline/ 编排 + 三层 ReAct (2.0 天)
```

**关键决策** (用户选择):
1. **同步迁移 prompt**: Phase 6 搬 llm_extraction 时, 同步将 track_a/b 硬编码 prompt 迁到 prompts/builtin/
2. **暂不创建 paper_understanding (Phase 2)**: 跳过 Phase 2, 在 Phase 6 一次性把 paper_understanding/ + llm_extraction/ 全部建好
3. **prompts 先核心后边缘**: code_gen → react_feedback → metadata → track_a/b → hypothesis/risk

### 20.2 第二轮细化: 7 Phases → 14 Phases

**触发**: 用户要求"工时超过 1 天的内容继续拆解"。

**核心原则**:
| 规则 | 阈值 |
|------|------|
| 单阶段最大工时 | **0.75 天** (1.0 天视为临界, 必须拆) |
| 拆分依据 | 工作量, 文件数, 风险隔离 |
| 命名 | 父阶段号 + 字母后缀 (12A, 14F1) |

**14 阶段结构**:
| Phase | 工时 | 备注 |
|-------|------|------|
| 1: common/ | 0.5 | |
| 2: data_source/ | 0.5 | |
| 3: 兼容层 | 0.5 | G1 |
| 4: prompts/ 骨架 | 0.5 | |
| 5: codegen/ 主包 | 0.5 | |
| 6: codegen/ast/ | 0.5 | 全部保留 (决策 2a) |
| 7: backtest/ | 0.75 | |
| 8: persist/ | 0.5 | run.py deprecated |
| 9: prompts/builtin/ 核心 | 0.75 | code_gen + react_feedback |
| 10: codegen/ 接入 | 0.5 | 用 PromptRegistry |
| 11: metadata_extract + 接入 | 0.5 | |
| 12: paper_understanding + llm_extraction | 1.0 | ⚠ 临界 |
| 13: prompts/builtin/ 边缘 | 0.5 | track + L5 |
| 14: pipeline + CLI + 回归 | 3.5 | ⚠ 必须拆 |

**总工时**: 10.5 天

### 20.3 第三轮细化: 14 Phases → 20 Phases

**触发**: Phase 12 (1.0 天) 和 Phase 14 (3.5 天) 超过 1 天阈值, 必须拆解。

**拆解结果**:

| 原 Phase | 拆解后 | 工时变化 |
|----------|--------|----------|
| 12 (1.0) | 12A + 12B | 1.0 → 0.5 + 0.5 |
| 14 (3.5) | 14A + 14B + 14C + 14D + 14E + 14F1 + 14F2 | 3.5 → 7 × 0.5 |

**完整 20 阶段总表**:

| # | Phase | Time | Gate | 关键交付 |
|---|-------|------|------|----------|
| 1 | common/ 子包 | 0.5 | - | 7 文件 git mv |
| 2 | data_source/ 子包 | 0.5 | - | 6 文件 git mv |
| 3 | 兼容层 | 0.5 | **G1** | `reproduction/__init__.py` 用 PEP 562 |
| 4 | prompts/ 骨架 | 0.5 | - | registry/group/loader/renderer/store |
| 5 | codegen/ 主包 | 0.5 | - | 6 文件 git mv + 改名 |
| 6 | codegen/ast/ 子包 | 0.5 | - | 4 文件 git mv (全部保留) |
| 7 | backtest/ 子包 | 0.75 | - | 8 文件 git mv |
| 8 | persist/ 子包 | 0.5 | - | 3 文件 git mv + run.py 标 deprecated |
| 9 | prompts/builtin/ 核心 | 0.75 | - | code_gen/v1,v2 + react_feedback/v1 |
| 10 | codegen/ 接入 | 0.5 | - | llm_code.py + react_engine.py 用 PromptRegistry |
| 11 | metadata_extract + 接入 | 0.5 | - | v1,v2 yaml + codegen/metadata.py |
| 12A | paper_understanding/ 6 文件 | 0.5 | - | 顶层 6 文件 git mv |
| 12B | llm_extraction/ 16 文件 | 0.5 | **G4** | 整体 git mv + 16 文件 import 修复 |
| 13 | prompts/builtin/ 边缘 | 0.75 | - | track_a/b + hypothesis/risk + 接入 |
| 14A | pipeline/ 框架骨架 | 0.5 | - | config, runner, stages/base |
| 14B | pipeline/ 三层 ReAct | 0.5 | - | react.py + workspace.py |
| 14C | pipeline/ 业务模块 | 0.75 | - | 7 文件从 test_one_factor 拆分 |
| 14D | 4 个 Stage | 0.5 | - | paper_understanding/codegen/backtest/persist |
| 14E | CLI + config.yaml | 0.5 | - | `reproduction/cli/__main__.py` + workspace config |
| 14F1 | 5 alpha e2e + WebUI | 0.5 | - | 跑 5 个 alpha + WebUI API 验证 |
| 14F2 | 99 alpha + 一致性 | 0.5 | **G5** | 99/99 验证 + 数据对比 |
| | **总计** | **10.0 天** | 5 个 Gate | |

---

## 21. 依赖关系分析

### 21.1 依赖图

```
                              ┌─── Phase 1 (common/) ────┐
                              │                            │
                              ├─── Phase 2 (data_source/) ┤
                              │                            │
                              │                            ▼
                              │                   Phase 3 (兼容层) [G1]
                              │                            │
                              │                            │
                              ▼                            │
                       Phase 6 (codegen/ast/)              │
                              │                            │
                              ▼                            │
              ┌─── Phase 5 (codegen/) ───┐                │
              │                          │                │
              │                          ▼                │
              │              Phase 9 (prompts 核心)        │
              │                          │                │
              │                          ▼                │
              │              Phase 10 (codegen 接入)       │
              │                          │                │
              │                          ▼                │
              │              Phase 11 (metadata 接入)     │
              │                          │                │
              │                          │                │
              ▼                          ▼                │
       Phase 7 (backtest/) ───> Phase 12A (paper 6 文件)  │
              │                          │                │
              │                          ▼                │
              │                  Phase 12B (llm_ext 16) [G4]
              │                          │                │
              │                          ▼                │
              │                  Phase 13 (prompts 边缘)  │
              │                          │                │
              │                          │                │
       Phase 8 (persist/) ────────────────┤                │
                                          │                │
                                          ▼                │
                                  Phase 14A (框架骨架) ───┘
                                          │
                                          ▼
                                  Phase 14B (三层 ReAct)
                                          │
                                          ▼
                                  Phase 14C (业务模块)
                                          │
                                          ▼
                                  Phase 14D (4 Stages)
                                          │
                                          ▼
                                  Phase 14E (CLI + config)
                                          │
                                          ▼
                                  Phase 14F1 (5 alpha e2e)
                                          │
                                          ▼
                                  Phase 14F2 (99 alpha) [G5]
```

### 21.2 关键路径 (Critical Path)

```
Phase 1 → Phase 6 → Phase 5 → Phase 9 → Phase 10 → Phase 14A
  → Phase 14B → Phase 14C → Phase 14D → Phase 14E → Phase 14F1 → Phase 14F2
```

**工时**: 0.5 + 0.5 + 0.5 + 0.75 + 0.5 + 0.5 + 0.5 + 0.75 + 0.5 + 0.5 + 0.5 + 0.5 = **6.5 天**

### 21.3 可并行的 Phase (未采用)

| 并行组 | Phase | 总工时 |
|--------|-------|--------|
| 组 A (无依赖) | 1 + 2 + 4 | 1.5 天 (并行) |
| 组 B (组 A 后) | 6 + 7 + 8 | 1.75 天 (并行) |

按用户决策"Verify-Then-Proceed"原则, **强制串行**, 不并行。

### 21.4 Gate 验证节点

| Gate | 触发 | 验证项 | 不通过时 |
|------|------|--------|----------|
| **G1** | Phase 3 后 | 20+ import + WebUI /api/health | 修复兼容层 |
| **G2** | Phase 8 后 | 1 个 alpha e2e (旧 scripts/) | 修复 Stage 1-3 |
| **G3** | Phase 11 后 | codegen + metadata 用 PromptRegistry | 修复 prompt 渲染 |
| **G4** | Phase 12B 后 | paper_understanding + llm_extraction | 修复 import 链 |
| **G5** | Phase 14F2 后 | 99/99 + 数据一致 | 修复 pipeline/CLI |

---

## 22. 单元测试要求 (强制纪律)

### 22.1 总体规则

| 时机 | 操作 | 不允许 |
|------|------|--------|
| **执行前** | 写完整单元测试, 跑通当前代码 | "边写代码边补测试" |
| **执行中** | git mv + 改 import (仅) | 改函数实现, 改函数签名 |
| **执行后** | 改测试的 import (仅) | 改测试逻辑, 跳过测试 |
| **回归** | 跑全部测试, 0 失败 | "就差一点" |

### 22.2 测试层级

| 层级 | 工具 | 覆盖 |
|------|------|------|
| **L1 单元** | pytest | 函数级, 无 IO |
| **L2 集成** | pytest + 临时文件 | 跨函数, 有文件系统 |
| **L3 mock** | unittest.mock | 替代 LLM/H5/DB |
| **L4 e2e** | 跑实际 alpha | 仅 Phase 14F1/F2 |

### 22.3 LLM 依赖测试策略

| 场景 | 策略 |
|------|------|
| 函数内部用 LLM | 用 `Mock(spec=StreamableLLMClient)` 替代 |
| 需要 LLM 输出 | 准备固定的 mock response fixture |
| 实际 LLM 验证 | 推迟到 Phase 14F1 (5 alpha e2e) |
| ReAct 反馈测试 | 注入"已知错误"fixture, 验证反馈格式 |

### 22.4 测试文件组织

```
tests/
├── test_imports.py              # Phase 3 创建, 持续维护 (33 parametrized)
├── test_common.py               # Phase 1 (8 测试)
├── test_data_source.py          # Phase 2 (4 测试)
├── test_prompts.py              # Phase 4 (9 测试)
├── test_codegen.py              # Phase 5 (7 测试)
├── test_codegen_ast.py          # Phase 6 (5 测试)
├── test_backtest.py             # Phase 7 (6 测试)
├── test_persist.py              # Phase 8 (5 测试)
├── test_prompts_builtin.py      # Phase 9 (3+4 测试)
├── test_codegen_with_prompts.py # Phase 10 (3 测试, 行为等价)
├── test_metadata_extract.py     # Phase 11 (2 测试, 行为等价)
├── test_paper_understanding.py  # Phase 12A (6 测试)
├── test_llm_extraction.py       # Phase 12B (16 测试)
├── test_prompts_edge.py         # Phase 13 (6 测试)
├── test_pipeline_framework.py   # Phase 14A (4 测试)
├── test_react.py                # Phase 14B (9 测试)
├── test_pipeline_modules.py     # Phase 14C (6 测试, 行为等价)
├── test_stages.py               # Phase 14D (6 测试)
├── test_cli.py                  # Phase 14E (4 测试)
├── test_e2e_5alpha.py           # Phase 14F1 (5 测试)
└── test_e2e_99alpha.py          # Phase 14F2 (3 测试)
```

### 22.5 行为等价性测试 (最关键)

对于"从 test_one_factor 拆分到 pipeline/"这种重构, 必须保证**逐函数对比**:

```python
# tests/test_pipeline_modules.py
def test_wide_from_long_equivalent():
    """与 test_one_factor_llm_code.py 输出一致"""
    from llmwikify.reproduction.test_one_factor_llm_code import _wide_from_long as old
    from llmwikify.reproduction.pipeline.data_loader import wide_from_long as new
    
    df = pl.DataFrame({...})
    series = pl.Series("x", [...])
    
    wide_old = old(df, series)
    wide_new = new(df, series)
    
    pd.testing.assert_frame_equal(wide_old, wide_new)
```

### 22.6 测试纪律红线

| 红线 | 后果 |
|------|------|
| ❌ 边写代码边补测试 | 测试失去保护作用 |
| ❌ 跳过失败测试 (用 @pytest.skip) | 掩盖问题 |
| ❌ 改测试逻辑 (除 import) | 失去回归保护 |
| ❌ 删测试 (除移到更合适文件) | 失去回归保护 |
| ❌ "差不多"通过 | 累积债务 |
| ✅ 失败立即修 | 保持零回归 |
| ✅ 关键测试 (等价性) 必须真测 | 拆分的正确性 |

---

## 23. 20 阶段详细操作 + 单元测试

### Phase 1: common/ 子包 (0.5 天)

**测试 (前)** — `tests/test_common.py` (8 个):
```python
def test_config_singleton():
    from llmwikify.reproduction.config import config
    assert config is not None

def test_paths_module():
    from llmwikify.reproduction import paths
    assert hasattr(paths, "QUANT_ROOT")

def test_run_id_format():
    from llmwikify.reproduction.run_id import generate_run_id
    rid = generate_run_id()
    assert isinstance(rid, str) and len(rid) > 0

def test_telemetry_singleton():
    from llmwikify.reproduction.telemetry import get_telemetry
    assert get_telemetry() is get_telemetry()

def test_categorize_error():
    from llmwikify.reproduction.error_categorizer import categorize_error
    assert categorize_error(ValueError("test")) is not None

def test_parse_frontmatter():
    from llmwikify.reproduction.utils import parse_frontmatter
    meta, body = parse_frontmatter("---\ntitle: t\n---\nbody")
    assert meta["title"] == "t"

def test_generate_slug():
    from llmwikify.reproduction.utils import generate_slug
    assert generate_slug("Hello World") == "hello-world"

def test_build_default_client():
    from llmwikify.reproduction.paper_understanding.llm_extraction.llm_factory import build_default_client
    client = build_default_client()
    assert client is not None
```

**操作**:
```
git mv 7 文件 → common/
修复 import (common/ 内部)
不改函数实现
不改函数签名
```

**测试 (后, 仅改 import)**:
```python
from llmwikify.reproduction.common.config import config
from llmwikify.reproduction.common import paths
# ... 全部改为新路径
```

**验证**: `pytest tests/test_common.py -v` (8/8 通过)
**回退**: 反向 git mv

---

### Phase 2: data_source/ 子包 (0.5 天)

**测试 (前)** — `tests/test_data_source.py` (4 个):
```python
def test_data_router_init():
    from llmwikify.reproduction.router import DataRouter
    r = DataRouter(use_cache=False)
    assert r is not None

def test_resolve_universe():
    from llmwikify.reproduction.universe import resolve_universe
    result = resolve_universe("all")
    assert result is not None

def test_quantnodes_adapter():
    from llmwikify.reproduction.quantnodes_adapter import to_qn_context
    import polars as pl
    df = pl.DataFrame({"date": [20200101], "code": [1], "close": [10.0]})
    ctx = to_qn_context(df)
    assert ctx is not None

def test_akshare_source_import():
    from llmwikify.reproduction.akshare_data import AKShareDataSource
    assert AKShareDataSource is not None
```

**操作**: git mv 6 文件 → data_source/, 修复 import
**验证**: `pytest tests/test_data_source.py -v`

---

### Phase 3: 兼容层 (0.5 天) [G1] ★

**测试 (前)** — `tests/test_imports.py` (33 个 parametrized, 关键):
```python
CRITICAL_IMPORTS = [
    "from llmwikify.reproduction.factor_library import read_factor_yaml, write_factor_yaml",
    "from llmwikify.reproduction.sessions import ReproductionDatabase",
    "from llmwikify.reproduction.quant_wiki import get_quant_wiki",
    "from llmwikify.reproduction.utils import parse_frontmatter, generate_slug",
    "from llmwikify.reproduction.extract_paper import extract_paper, _extract_factors_from_list",
    "from llmwikify.reproduction.factor_backtest import run_factor_backtest, run_factor_backtest_universe",
    "from llmwikify.reproduction.router import DataRouter",
    "from llmwikify.reproduction.universe import resolve_universe",
    "from llmwikify.reproduction.backtest import run_backtest",
    "from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper",
    "from llmwikify.reproduction.codegen_utils import generate_factor_code, SYSTEM_PROMPT_CODE",
    "from llmwikify.reproduction.factor_compiler_react import compile_to_code_react, ReactStep, ReactResult",
    "from llmwikify.reproduction.factor_compiler import FactorCompiler",
    "from llmwikify.reproduction.ast_compiler import compile_ast, CompileError",
    "from llmwikify.reproduction.ast_nodes import ASTNode, get_op_spec",
    "from llmwikify.reproduction.ast_extractor import extract_ast",
    "from llmwikify.reproduction.semantic_registry import get_template, list_templates",
    "from llmwikify.reproduction.l5_orchestrator import run_l5, L5Orchestrator",
    "from llmwikify.reproduction.l5_validation import run_l5_validation",
    "from llmwikify.reproduction.metrics import evaluation",
    "from llmwikify.reproduction.quantnodes_repro import run_factor_backtest",
    "from llmwikify.reproduction.factor_value_store import get_factor_values, store_factor_values",
    "from llmwikify.reproduction.run import run_reproduction, RunContext",
    "from llmwikify.reproduction.config import config",
    "from llmwikify.reproduction.paths import QUANT_ROOT",
    "from llmwikify.reproduction.error_categorizer import categorize_error",
    "from llmwikify.reproduction.schemas import BacktestResult, WikiFactor, FactorBacktestResult",
    "from llmwikify.reproduction.contracts import FactorPage",
    "from llmwikify.reproduction.akshare_data import AKShareDataSource",
    "from llmwikify.reproduction.clickhouse_data import ClickHouseDataSource",
    "from llmwikify.reproduction.ifind_data import IFindDataSource",
    "from llmwikify.reproduction.telemetry import get_telemetry",
]

@pytest.mark.parametrize("import_stmt", CRITICAL_IMPORTS)
def test_critical_import(import_stmt):
    exec(import_stmt)
```

**操作**:
```
写 reproduction/__init__.py 兼容层
用 PEP 562 __getattr__ 实现懒加载
_LAZY_IMPORTS 字典列出全部 30+ 模块
避免 nanobot import 触发
```

**Gate G1 验证**:
```bash
pytest tests/test_imports.py -v
# 期望: 全部 33 个通过
curl http://localhost:8765/api/health
# 期望: 200 OK
curl http://localhost:8765/api/paper/list
# 期望: 论文列表
```

---

### Phase 4: prompts/ 骨架 (0.5 天)

**测试 (前)** — TDD, `tests/test_prompts.py` (9 个):
```python
def test_prompt_group_render_user():
    from llmwikify.reproduction.prompts.group import PromptGroup
    g = PromptGroup(name="test", version="1.0.0", source="builtin",
                    system="...", user_template="Hello {{ name }}!",
                    feedback_template=None, metadata={}, raw={})
    assert g.render_user(name="world") == "Hello world!"

def test_prompt_group_render_feedback():
    # 验证 feedback_template 渲染

def test_prompt_group_feedback_template_required():
    # feedback_template=None 应抛错

def test_prompt_version_compatibility():
    # semver 兼容性检查

def test_prompt_registry_get_latest():
    # "latest" 应返回最新版本

def test_prompt_registry_require_missing():
    # 缺失应抛错

def test_prompt_loader_load_yaml():
    # 从 yaml 加载

def test_prompt_renderer_jinja2():
    # if/for 支持

def test_prompt_store_builtin_path():
    # 路径正确
```

**操作**: 创建 prompts/ 子包 + builtin/ 空目录

**验证**: `pytest tests/test_prompts.py -v` (9/9)

---

### Phase 5: codegen/ 主包 (0.5 天)

**测试 (前)** — `tests/test_codegen.py` (7 个):
```python
def test_extract_python():
    from llmwikify.reproduction.codegen_utils import extract_python
    text = "```python\ndef foo(): pass\n```"
    assert extract_python(text) == "def foo(): pass"

def test_validate_syntax():
    from llmwikify.reproduction.codegen_utils import validate_syntax
    ok, _ = validate_syntax("def foo(): pass")
    assert ok is True
    ok, _ = validate_syntax("def foo(:")
    assert ok is False

def test_validate_safety_rejects_if():
    from llmwikify.reproduction.codegen_utils import validate_safety
    ok, err = validate_safety("if rank(x): pass")
    assert ok is False

def test_execute_code():
    from llmwikify.reproduction.codegen_utils import execute_code
    import polars as pl
    df = pl.DataFrame({"x": [1, 2, 3]})
    code = "def compute_factor(df): return df['x'] * 2"
    series = execute_code(code, df)
    assert series.to_list() == [2, 4, 6]

def test_factor_compiler_init():
    from llmwikify.reproduction.factor_compiler import FactorCompiler
    c = FactorCompiler()
    assert c is not None

def test_extract_factor_metadata_signature():
    from llmwikify.reproduction.factor_extractor import extract_factor_metadata
    import inspect
    sig = inspect.signature(extract_factor_metadata)
    assert "llm" in sig.parameters
    assert "formula_brief" in sig.parameters
    assert "code" in sig.parameters

def test_system_prompt_code_exists():
    from llmwikify.reproduction.codegen_utils import SYSTEM_PROMPT_CODE
    assert "compute_factor" in SYSTEM_PROMPT_CODE
```

**操作**:
```
git mv 6 文件 + 改名:
  codegen_utils.py → codegen/llm_code.py
  factor_compiler_react.py → codegen/react_engine.py
  factor_compiler.py → codegen/compiler.py
  self_repairing.py → codegen/repair.py
  semantic_registry.py → codegen/semantic.py
  factor_extractor.py → codegen/metadata.py
修复 codegen/ 内部 import
不改函数实现/签名
```

**测试 (后)**: 改 import 路径
**验证**: `pytest tests/test_codegen.py tests/test_imports.py -v`

---

### Phase 6: codegen/ast/ 子包 (0.5 天)

**测试 (前)** — `tests/test_codegen_ast.py` (5 个):
```python
def test_compile_ast():
    from llmwikify.reproduction.ast_compiler import compile_ast
    expr = compile_ast({"op": "rank", "args": ["close"]})
    assert expr is not None

def test_ast_node_construction():
    from llmwikify.reproduction.ast_nodes import ASTNode
    node = ASTNode(op="rank", args=["close"])
    assert node.op == "rank"

def test_compute_complexity():
    from llmwikify.reproduction.ast_complexity import compute_complexity
    assert compute_complexity({"op": "rank", "args": ["close"]}) >= 0

def test_extract_ast():
    from llmwikify.reproduction.ast_extractor import extract_ast
    assert extract_ast("df.select(rank('close'))") is not None

def test_get_op_spec():
    from llmwikify.reproduction.ast_nodes import get_op_spec
    assert get_op_spec("rank") is not None
```

**操作**: git mv 4 文件 → codegen/ast/, 修复 import
**验证**: `pytest tests/test_codegen_ast.py -v` + AST 路径脚本可 import

---

### Phase 7: backtest/ 子包 (0.75 天)

**测试 (前)** — `tests/test_backtest.py` (6 个):
```python
def test_data_router_init():
    from llmwikify.reproduction.factor_backtest import run_factor_backtest_universe
    import inspect
    sig = inspect.signature(run_factor_backtest_universe)
    assert "factor_yaml" in sig.parameters

def test_metrics_evaluation():
    from llmwikify.reproduction.metrics import evaluation
    result = evaluation([0.01, -0.02, 0.03, 0.01, -0.01])
    assert result is not None

def test_strategies_import():
    from llmwikify.reproduction import strategies
    assert hasattr(strategies, "SIGNAL_NODE_REGISTRY")

def test_l5_validation_import():
    from llmwikify.reproduction.l5_validation import run_l5_validation
    assert callable(run_l5_validation)

def test_l5_orchestrator_init():
    from llmwikify.reproduction.l5_orchestrator import L5Orchestrator
    o = L5Orchestrator()
    assert o is not None

def test_value_store_init():
    from llmwikify.reproduction.factor_value_store import (
        store_factor_values, get_factor_values
    )
    import inspect
    assert "date" in inspect.signature(store_factor_values).parameters
```

**操作**: git mv 8 文件 → backtest/, 修复 import
**验证**: `pytest tests/test_backtest.py -v` + WebUI 因子页面仍可访问

---

### Phase 8: persist/ 子包 (0.5 天)

**测试 (前)** — `tests/test_persist.py` (5 个):
```python
def test_factor_library_read():
    from llmwikify.reproduction.factor_library import read_factor_yaml
    p = Path("quant/factors/101_alphas/stk_alpha_001_f9f371/factor.yaml")
    if p.exists():
        data = read_factor_yaml("stk_alpha_001_f9f371")
        assert data is not None

def test_factor_library_list():
    from llmwikify.reproduction.factor_library import list_factors
    factors = list_factors()
    assert isinstance(factors, list) and len(factors) >= 90

def test_sessions_db_init():
    from llmwikify.reproduction.sessions import ReproductionDatabase
    db = ReproductionDatabase()
    assert db is not None

def test_sessions_create_session():
    from llmwikify.reproduction.sessions import ReproductionDatabase
    db = ReproductionDatabase()
    sid = db.create_session(
        wiki_id="test", paper_id="test", source_type="test",
        source_ref="ref", symbol="test:all",
        start_date="20200101", end_date="20241231"
    )
    assert isinstance(sid, str) and len(sid) > 0

def test_run_reproduction_signature():
    from llmwikify.reproduction.run import run_reproduction
    import inspect
    assert callable(run_reproduction)
```

**操作**: git mv 3 文件 → persist/, 修复 import, run.py 标 deprecated
**验证**: `pytest tests/test_persist.py -v`

---

### Phase 9: prompts/builtin/ 核心 (0.75 天)

**测试 (前)** — `tests/test_prompts_builtin.py` (3+4 = 7 个):
```python
def test_hardcoded_system_prompt_code():
    from llmwikify.reproduction.codegen_utils import SYSTEM_PROMPT_CODE
    assert "compute_factor" in SYSTEM_PROMPT_CODE

def test_hardcoded_metadata_prompts():
    from llmwikify.reproduction.factor_extractor import (
        SYSTEM_PROMPT_METADATA, SYSTEM_PROMPT_METADATA_V2
    )
    assert SYSTEM_PROMPT_METADATA and SYSTEM_PROMPT_METADATA_V2

def test_hardcoded_react_feedback():
    from llmwikify.reproduction.factor_compiler_react import OBSERVE_FEEDBACK_TEMPLATE
    assert "error_message" in OBSERVE_FEEDBACK_TEMPLATE
```

**操作**:
```
创建 prompts/builtin/code_gen/v1.yaml (原 SYSTEM_PROMPT_CODE)
创建 prompts/builtin/code_gen/v2.yaml (生产版, 加 rules)
创建 prompts/builtin/react_feedback/v1.yaml (原 OBSERVE_FEEDBACK_TEMPLATE)
```

**测试 (后) — 新增 builtin 渲染测试**:
```python
def test_builtin_code_gen_v1_renders():
    from llmwikify.reproduction.prompts import PromptRegistry
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("code_gen", "v1")
    rendered = g.render_user(factor_name="alpha-001", formula_brief="rank(close)")
    assert "alpha-001" in rendered
    assert "rank(close)" in rendered

def test_builtin_react_feedback_v1_renders():
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("react_feedback", "v1")
    rendered = g.render_feedback(
        error_type="EXTRACT_FAILED", error_message="no code fence",
        last_code="def foo(): pass"
    )
    assert "EXTRACT_FAILED" in rendered

def test_code_gen_v2_includes_rules():
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("code_gen", "v2")
    rendered = g.render_user(
        factor_name="x", formula_brief="y", available_columns=["close"],
        rules={"do_not": ["if/and/or on polars Expr"], "do": ["function form"]}
    )
    assert "if/and/or on polars Expr" in rendered
    assert "function form" in rendered
```

**验证**: `pytest tests/test_prompts_builtin.py -v`

---

### Phase 10: codegen/ 接入 PromptRegistry (0.5 天) ★

**测试 (前)** — `tests/test_codegen_with_prompts.py` (3 个, 行为等价):
```python
def test_generate_factor_code_with_prompts_equals_hardcoded():
    """关键: 用 prompts 与不用 prompts 必须输出等价"""
    from llmwikify.reproduction.codegen import generate_factor_code
    from llmwikify.reproduction.prompts import PromptRegistry
    from unittest.mock import Mock
    import polars as pl
    
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0]})
    mock_response = "```python\ndef compute_factor(df): return df['close']\n```"
    
    # Hardcoded 路径
    mock_llm_1 = Mock()
    mock_llm_1.chat = Mock(return_value=mock_response)
    code1, series1, _, _ = generate_factor_code(
        factor_name="test", formula_brief="close", df=df, llm=mock_llm_1
    )
    
    # Prompts 路径
    mock_llm_2 = Mock()
    mock_llm_2.chat = Mock(return_value=mock_response)
    registry = PromptRegistry.from_builtin_only()
    code2, series2, _, _ = generate_factor_code(
        factor_name="test", formula_brief="close", df=df, llm=mock_llm_2, prompts=registry
    )
    
    assert code1 == code2
    assert series1.to_list() == series2.to_list()

def test_generate_factor_code_fallback_when_no_prompts():
    """无 prompts 时必须 fallback 到 hardcoded"""
    from llmwikify.reproduction.codegen import generate_factor_code
    from unittest.mock import Mock
    import polars as pl
    
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0]})
    mock_llm = Mock()
    mock_llm.chat = Mock(return_value="```python\ndef compute_factor(df): return df['close']\n```")
    
    code, series, err, meta = generate_factor_code(
        factor_name="test", formula_brief="close", df=df, llm=mock_llm, prompts=None
    )
    assert code is not None and series is not None

def test_compile_to_code_react_with_prompts():
    from llmwikify.reproduction.codegen import compile_to_code_react
    from llmwikify.reproduction.prompts import PromptRegistry
    from unittest.mock import Mock
    import polars as pl
    
    df = pl.DataFrame({"close": [1.0, 2.0, 3.0]})
    mock_llm = Mock()
    mock_llm.chat = Mock(return_value="```python\ndef compute_factor(df): return df['close']\n```")
    
    registry = PromptRegistry.from_builtin_only()
    result = compile_to_code_react(
        factor_name="test", formula_brief="close",
        system_prompt=registry.get_required("code_gen", "v2").system,
        df=df, llm=mock_llm, max_repair_rounds=1, prompts=registry
    )
    assert result.is_valid
```

**操作**:
```
修改 codegen/llm_code.py: generate_factor_code() 加可选 prompts 参数
修改 codegen/react_engine.py: compile_to_code_react() 加可选 prompts 参数
保留 hardcoded 字符串作为 fallback
不改原有参数
```

**验证**: `pytest tests/test_codegen_with_prompts.py -v`

---

### Phase 11: metadata_extract + 接入 (0.5 天)

**测试 (前)** — `tests/test_metadata_extract.py` (2 个, 行为等价):
```python
def test_extract_factor_metadata_with_prompts_equals_hardcoded():
    from llmwikify.reproduction.codegen import extract_factor_metadata
    from llmwikify.reproduction.prompts import PromptRegistry
    from unittest.mock import Mock
    
    mock_response = '{"l2": {"calculation_steps": []}, "l3": {}, "l4": {}, "l6": {}}'
    mock_llm = Mock()
    mock_llm.chat = Mock(return_value=f"```json\n{mock_response}\n```")
    
    result_hardcoded = extract_factor_metadata(
        llm=mock_llm, formula_brief="rank(close)",
        code="def compute_factor(df): return df['close']"
    )
    
    registry = PromptRegistry.from_builtin_only()
    result_prompts = extract_factor_metadata(
        llm=mock_llm, formula_brief="rank(close)",
        code="def compute_factor(df): return df['close']",
        prompts=registry
    )
    
    assert result_hardcoded.get("l2") == result_prompts.get("l2")

def test_extract_factor_metadata_v2_with_existing():
    # v2 验证已有元数据
    existing = {"l2": {"calculation_steps": [{"step": 1}]}}
    mock_response = '{"l2": {"calculation_steps": [{"step": 1}, {"step": 2}]}, "l3": {}, "l4": {}, "l6": {}, "verified": true}'
    mock_llm = Mock()
    mock_llm.chat = Mock(return_value=f"```json\n{mock_response}\n```")
    
    registry = PromptRegistry.from_builtin_only()
    result = extract_factor_metadata(
        llm=mock_llm, formula_brief="rank(close)",
        code="def compute_factor(df): return df['close']",
        existing_metadata=existing, prompts=registry
    )
    assert "verified" in result
```

**操作**:
```
创建 prompts/builtin/metadata_extract/v1.yaml + v2.yaml
修改 codegen/metadata.py: extract_factor_metadata() 加可选 prompts 参数
```

**验证**: `pytest tests/test_metadata_extract.py -v`

---

### Phase 12A: paper_understanding/ 6 文件 (0.5 天)

**测试 (前)** — `tests/test_paper_understanding.py` (6 个):
```python
def test_extract_paper_import():
    from llmwikify.reproduction.extract_paper import extract_paper, _extract_factors_from_list
    assert callable(extract_paper)
    assert callable(_extract_factors_from_list)

def test_extract_factors_import():
    from llmwikify.reproduction.extract_factors import extract_factors
    assert callable(extract_factors)

def test_extract_strategy_config_import():
    from llmwikify.reproduction.extract import extract_strategy_config
    assert callable(extract_strategy_config)

def test_quant_wiki_get():
    from llmwikify.reproduction.quant_wiki import get_quant_wiki
    assert callable(get_quant_wiki)

def test_schemas_backtest_result():
    from llmwikify.reproduction.schemas import BacktestResult, WikiFactor
    assert BacktestResult is not None and WikiFactor is not None

def test_contracts_factor_page():
    from llmwikify.reproduction.contracts import FactorPage
    assert FactorPage is not None
```

**操作**:
```
git mv 6 文件 → paper_understanding/
修复 paper_understanding/ 内部 import
llm_extraction 引用改为 from ..llm_extraction (临时)
```

**测试 (后)**: 改 import 路径
**验证**: `pytest tests/test_paper_understanding.py tests/test_imports.py -v`

---

### Phase 12B: llm_extraction/ 16 文件 (0.5 天) [G4] ★

**测试 (前)** — `tests/test_llm_extraction.py` (16 个, 覆盖全部 16 文件):
```python
def test_run_one_paper_import():
    from llmwikify.reproduction.paper_understanding.llm_extraction import run_one_paper
    assert callable(run_one_paper)

def test_run_track_a():
    from llmwikify.reproduction.paper_understanding.llm_extraction import run_track_a
    assert callable(run_track_a)

def test_run_track_b():
    from llmwikify.reproduction.paper_understanding.llm_extraction import run_track_b
    assert callable(run_track_b)

def test_stage0_ingest():
    from llmwikify.reproduction.paper_understanding.llm_extraction import run_stage0_ingest
    assert callable(run_stage0_ingest)

def test_orchestrator():
    from llmwikify.reproduction.paper_understanding.llm_extraction.orchestrator import run_one_paper
    assert callable(run_one_paper)

def test_planner():
    from llmwikify.reproduction.paper_understanding.llm_extraction.planner import plan_paper
    assert callable(plan_paper)

def test_track_a_internal():
    from llmwikify.reproduction.paper_understanding.llm_extraction.track_a import run_track_a
    assert callable(run_track_a)

def test_track_b_internal():
    from llmwikify.reproduction.paper_understanding.llm_extraction.track_b import run_track_b
    assert callable(run_track_b)

def test_validator():
    from llmwikify.reproduction.paper_understanding.llm_extraction.validator import validate_paper_outputs
    assert callable(validate_paper_outputs)

def test_runlog():
    from llmwikify.reproduction.paper_understanding.llm_extraction.runlog import RunLogger
    assert RunLogger is not None

def test_section_detector():
    from llmwikify.reproduction.paper_understanding.llm_extraction.section_detector import detect_sections
    assert callable(detect_sections)

def test_plan_saver():
    from llmwikify.reproduction.paper_understanding.llm_extraction.plan_saver import save_plan
    assert callable(save_plan)

def test_retry():
    from llmwikify.reproduction.paper_understanding.llm_extraction.retry import with_retry
    assert callable(with_retry)

def test_defer():
    from llmwikify.reproduction.paper_understanding.llm_extraction.defer import DeferredQueue
    assert DeferredQueue is not None

def test_preview():
    from llmwikify.reproduction.paper_understanding.llm_extraction.preview import generate_preview
    assert callable(generate_preview)

def test_log_decorator():
    from llmwikify.reproduction.paper_understanding.llm_extraction.log_decorator import with_logging
    assert callable(with_logging)
```

**操作**:
```
git mv llm_extraction/ → paper_understanding/llm_extraction/
修复 16 个文件内部 import (主要是 llm_factory 跨包)
修复 paper_understanding/*.py 引用 (从 .. 改为 .)
更新 reproduction/__init__.py 兼容层
```

**Gate G4 验证**:
```bash
pytest tests/test_llm_extraction.py -v
pytest tests/test_imports.py -v
python -m llmwikify.reproduction.cli reproduce 101_alphas_minimal
curl http://localhost:8765/api/paper/list
```

---

### Phase 13: prompts/builtin/ 边缘 (0.75 天)

**测试 (前)** — `tests/test_prompts_edge.py` (6 个):
```python
def test_builtin_track_a_renders():
    from llmwikify.reproduction.prompts import PromptRegistry
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("track_a", "v1")
    rendered = g.render_user(paper_content="abstract...")
    assert "abstract" in rendered

def test_builtin_track_b_renders():
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("track_b", "v1")
    rendered = g.render_user(paper_content="formula table...")
    assert "formula" in rendered

def test_builtin_hypothesis_renders():
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("hypothesis_test", "v1")
    rendered = g.render_user(factor_name="alpha-001", backtest_metrics={"icir": 0.15})
    assert "alpha-001" in rendered and "0.15" in rendered

def test_builtin_risk_renders():
    registry = PromptRegistry.from_builtin_only()
    g = registry.get_required("risk_analyze", "v1")
    rendered = g.render_user(factor_name="alpha-001")
    assert "alpha-001" in rendered

def test_run_track_a_with_prompts():
    """run_track_a 接入 prompts 后行为不变"""
    from llmwikify.reproduction.paper_understanding.llm_extraction.track_a import run_track_a
    from llmwikify.reproduction.prompts import PromptRegistry
    from unittest.mock import Mock
    
    mock_response = '{"paper_metadata": {}, "abstract_summary": {}}'
    mock_llm = Mock()
    mock_llm.chat = Mock(return_value=f"```json\n{mock_response}\n```")
    
    registry = PromptRegistry.from_builtin_only()
    result = run_track_a(llm=mock_llm, paper="test paper", prompts=registry)
    assert result is not None

def test_l5_with_prompts():
    # 占位, 实际需要 fixture
    pass
```

**操作**:
```
创建 prompts/builtin/track_a/v1.yaml + v2.yaml
创建 prompts/builtin/track_b/v1.yaml + v2.yaml
创建 prompts/builtin/hypothesis_test/v1.yaml
创建 prompts/builtin/risk_analyze/v1.yaml
修改 llm_extraction/track_a.py + track_b.py (加 prompts 参数)
修改 l5_orchestrator.py (hypothesis + risk 接 prompts)
```

**验证**: `pytest tests/test_prompts_edge.py -v`

---

### Phase 14A: pipeline/ 框架骨架 (0.5 天)

**测试 (前)** — TDD, `tests/test_pipeline_framework.py` (4 个):
```python
def test_workspace_config_from_yaml():
    from llmwikify.reproduction.pipeline.config import WorkspaceConfig
    # 临时文件, from_yaml 解析
    # 验证关键字段

def test_pipeline_runner_init():
    from llmwikify.reproduction.pipeline.runner import PipelineRunner
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = PipelineRunner(workspace=Path(tmpdir))
        assert runner is not None

def test_stage_abstract():
    from llmwikify.reproduction.pipeline.stages.base import Stage
    with pytest.raises(TypeError):
        Stage()  # 抽象, 不能实例化

def test_workspace_get_stage():
    from llmwikify.reproduction.pipeline.workspace import Workspace
    # get_stage() 在未注册时应抛错
```

**操作**: 创建 pipeline/ 框架
**验证**: `pytest tests/test_pipeline_framework.py -v`

---

### Phase 14B: pipeline/ 三层 ReAct (0.5 天)

**测试 (前)** — TDD, `tests/test_react.py` (9 个):
```python
def test_failure_classifier_dangerous_code():
    from llmwikify.reproduction.pipeline.react import FailureClassifier
    err = Exception("DangerousCodeError: if/and/or detected")
    assert FailureClassifier().classify(err) == "LLM_PERSISTENT"

def test_failure_classifier_qn_bug():
    err = Exception("AttributeError: QuantNodes.SamplePoolFilter.shape mismatch")
    assert FailureClassifier().classify(err) == "QN_BUG"

def test_failure_classifier_io_error():
    err = OSError("DiskFull")
    assert FailureClassifier().classify(err) == "IO_ERROR"

def test_failure_classifier_data_missing():
    err = KeyError("close not in store")
    assert FailureClassifier().classify(err) == "DATA_MISSING"

def test_failure_classifier_unknown():
    err = Exception("something weird")
    assert FailureClassifier().classify(err) == "UNKNOWN"

def test_pipeline_react_decide_llm_persistent():
    from llmwikify.reproduction.pipeline.react import PipelineReAct, StageFailure, Decision
    failure = StageFailure(stage="codegen", alpha_index=1, error_type="LLM_PERSISTENT",
                          error_message="...", retry_count=3, intermediate_outputs={})
    decider = PipelineReAct(available_prompt_versions=["v1", "v2", "v3"])
    assert decider.decide(failure).action in (Decision.SWITCH_PROMPT, Decision.SKIP)

def test_pipeline_react_decide_qn_bug():
    failure = StageFailure(stage="backtest", alpha_index=1, error_type="QN_BUG",
                          error_message="...", retry_count=0, intermediate_outputs={})
    decider = PipelineReAct(available_prompt_versions=[])
    assert decider.decide(failure).action == Decision.SKIP

def test_workspace_react_decide_dominant_pattern():
    # 失败率 > 50% 且同类错误主导 → SWITCH_PROMPT_AND_RETRY_BATCH

def test_workspace_react_decide_no_dominant():
    # 失败分散 → CONTINUE_WITH_FAILURES
```

**操作**: 实现 pipeline/react.py
**验证**: `pytest tests/test_react.py -v`

---

### Phase 14C: pipeline/ 业务模块 (0.75 天) ★ 关键

**测试 (前)** — `tests/test_pipeline_modules.py` (6 个, 行为等价, 关键):
```python
def test_load_market_data_equivalent():
    """与 test_one_factor_llm_code.py 输出一致"""
    from llmwikify.reproduction.test_one_factor_llm_code import _load_market_data as old
    from llmwikify.reproduction.pipeline.data_loader import load_market_data as new
    
    h5_path = Path("/home/ll/.llmwikify/akshare_cache/quantnodes_h5_long")
    if not h5_path.exists():
        pytest.skip("H5 data not available")
    
    df_old = old(h5_path, 20200101, 20241231)
    df_new = new(h5_path, date_range=(20200101, 20241231))
    
    assert df_old.shape == df_new.shape
    assert df_old.columns == df_new.columns

def test_wide_from_long_equivalent():
    from llmwikify.reproduction.test_one_factor_llm_code import _wide_from_long as old
    from llmwikify.reproduction.pipeline.data_loader import wide_from_long as new
    
    df = pl.DataFrame({
        "date": [20200101, 20200101, 20200102, 20200102],
        "code": [1, 2, 1, 2],
        "close": [10.0, 11.0, 10.5, 11.5],
    })
    series = pl.Series("x", [0.1, 0.2, 0.3, 0.4])
    
    wide_old = old(df, series)
    wide_new = new(df, series)
    
    pd.testing.assert_frame_equal(wide_old, wide_new)

def test_build_qn_config_equivalent():
    from llmwikify.reproduction.test_one_factor_llm_code import _build_qn_config as old
    from llmwikify.reproduction.pipeline.backtest_config import build_qn_config as new
    
    with tempfile.TemporaryDirectory() as tmpdir:
        h5_path = Path(tmpdir) / "factor.h5"
        h5_path.touch()
        config_old = old("alpha-001", h5_path, "def compute_factor(): pass")
        config_new = new("alpha-001", h5_path, "def compute_factor(): pass")
        assert config_old["factor"]["name"] == config_new["factor"]["name"]
        assert config_old["load_keys"] == config_new["load_keys"]

def test_compute_score_equivalent():
    from llmwikify.reproduction.test_one_factor_llm_code import _compute_score as old
    from llmwikify.reproduction.pipeline.score import compute_score as new
    assert old(0.15, 0.6) == new(0.15, 0.6)

def test_detect_binary():
    from llmwikify.reproduction.pipeline.factor_fix import detect_binary
    assert detect_binary(pl.Series("x", [0.0, 0.0, 0.0])) is True
    assert detect_binary(pl.Series("x", [0.0, 0.1, 0.2])) is False

def test_add_noise_preserves_length():
    from llmwikify.reproduction.pipeline.factor_fix import add_noise
    s = pl.Series("x", [0.0, 0.0, 0.0, 0.0])
    s2 = add_noise(s)
    assert len(s) == len(s2) and s2.to_list() != s.to_list()
```

**操作**:
```
从 test_one_factor_llm_code.py 拆分 7 个函数到 pipeline/:
  _patch_sample_pool_filter → pipeline/quantnodes_patch.py
  _wide_from_long → pipeline/data_loader.py
  _write_factor_h5 → pipeline/data_loader.py
  _load_market_data → pipeline/data_loader.py
  _build_qn_config → pipeline/backtest_config.py
  _extract_full_backtest_from_ctx → pipeline/backtest_extract.py
  _compute_score + _compute_status → pipeline/score.py
  persist_code_to_yaml → pipeline/persist.py
  save_backtest_to_db → pipeline/persist.py
  _derive_input_columns → pipeline/data_loader.py
  _is_binary + _add_noise → pipeline/factor_fix.py
  run_one_factor → pipeline/runner.py (Phase 14D 拆)
保留函数签名, 函数体基本一致
```

**验证**: `pytest tests/test_pipeline_modules.py -v` (行为等价, 拆分正确性)

---

### Phase 14D: 4 个 Stage (0.5 天)

**测试 (前)** — `tests/test_stages.py` (6 个):
```python
def test_paper_understanding_stage_attrs():
    from llmwikify.reproduction.pipeline.stages.paper_understanding import PaperUnderstandingStage
    s = PaperUnderstandingStage()
    assert s.name == "paper_understanding"
    assert "track_a" in s.required_prompts

def test_codegen_stage_attrs():
    from llmwikify.reproduction.pipeline.stages.codegen import CodegenStage
    s = CodegenStage()
    assert s.name == "codegen"
    assert "code_gen" in s.required_prompts

def test_backtest_stage_attrs():
    from llmwikify.reproduction.pipeline.stages.backtest import BacktestStage
    s = BacktestStage()
    assert s.name == "backtest"

def test_persist_factor_stage_attrs():
    from llmwikify.reproduction.pipeline.stages.persist_factor import PersistFactorStage
    s = PersistFactorStage()
    assert s.name == "persist_factor"

def test_codegen_stage_run_with_mock():
    from llmwikify.reproduction.pipeline.stages.codegen import CodegenStage
    from unittest.mock import patch
    
    stage = CodegenStage()
    ctx = {"formula_brief": "rank(close)", "df": None, "factor_name": "test"}
    
    with patch("llmwikify.reproduction.codegen.generate_factor_code") as mock_gen:
        mock_gen.return_value = ("def foo(): pass", None, None, {})
        ctx = stage.run(ctx, config=None, prompts=None)
    
    assert "code" in ctx

def test_pipeline_runner_run_one():
    from llmwikify.reproduction.pipeline.runner import PipelineRunner
    from unittest.mock import patch
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        (workspace / "config.yaml").write_text("workspace:\n  name: test\nstages:\n  - codegen\n")
        runner = PipelineRunner(workspace=workspace)
        
        with patch.object(runner, "_run_stage") as mock_run:
            mock_run.return_value = {"code": "x", "factor_name": "test"}
            ctx = runner.run_one({"index": 1})
            assert "code" in ctx
```

**操作**: 实现 4 个 Stage + PipelineRunner.run_one/run_all
**验证**: `pytest tests/test_stages.py -v`

---

### Phase 14E: CLI + config.yaml (0.5 天)

**测试 (前)** — `tests/test_cli.py` (4 个):
```python
def test_cli_parser_run():
    from llmwikify.reproduction.cli.__main__ import build_parser
    parser = build_parser()
    args = parser.parse_args(["run", "101_alphas", "--start", "1", "--end", "5"])
    assert args.command == "run" and args.workspace == "101_alphas"

def test_cli_parser_prompts_list():
    parser = build_parser()
    args = parser.parse_args(["prompts", "list", "101_alphas"])
    assert args.command == "prompts"

def test_cli_list_workspaces(tmp_path):
    # 创建模拟 quant/factors/ 目录
    # 验证 list 命令能找到

def test_cli_prompts_list_with_workspace(tmp_path):
    # 创建 workspace + config + prompts/
    # 验证 prompts list 命令
```

**操作**: 实现 `reproduction/cli/__main__.py` + 写 101_alphas/config.yaml
**验证**:
```bash
pytest tests/test_cli.py -v
python -m llmwikify.reproduction.cli list
python -m llmwikify.reproduction.cli prompts list 101_alphas
```

---

### Phase 14F1: 5 alpha e2e + WebUI (0.5 天)

**测试 (前)** — `tests/test_e2e_5alpha.py` (5 个):
```python
def test_run_5_alphas_e2e():
    import subprocess
    result = subprocess.run(
        ["python", "-m", "llmwikify.reproduction.cli", "run", "101_alphas",
         "--start", "1", "--end", "5"],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0
    for i in range(1, 6):
        paths = list(Path("quant/factors/101_alphas").glob(f"stk_alpha_{i:03d}_*/"))
        assert len(paths) >= 1, f"alpha-{i:03d} factor dir not found"

def test_webui_health():
    import urllib.request
    response = urllib.request.urlopen("http://localhost:8765/api/health", timeout=5)
    assert response.status == 200

def test_webui_paper_list():
    import urllib.request, json
    response = urllib.request.urlopen("http://localhost:8765/api/paper/list", timeout=5)
    data = json.loads(response.read())
    assert isinstance(data, list)

def test_webui_factor_detail():
    import urllib.request, json
    response = urllib.request.urlopen(
        "http://localhost:8765/api/factor/stk_alpha_001_f9f371", timeout=5
    )
    data = json.loads(response.read())
    assert "l1" in data or "factor" in data

def test_old_scripts_still_work():
    import subprocess
    result = subprocess.run(
        ["python", "-c", "from scripts.test_one_factor_llm_code import run_one_factor"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0
```

**操作**: 跑 5 个 alpha + 启动 WebUI
**验证**: `pytest tests/test_e2e_5alpha.py -v` (5/5)

---

### Phase 14F2: 99 alpha + 一致性 (0.5 天) [G5] ★

**测试 (前)** — `tests/test_e2e_99alpha.py` (3 个):
```python
def test_run_99_alphas():
    import subprocess, json
    from pathlib import Path
    result = subprocess.run(
        ["python", "-m", "llmwikify.reproduction.cli", "run", "101_alphas",
         "--start", "1", "--end", "101", "--skip-existing"],
        capture_output=True, text=True, timeout=3600,
    )
    output_path = Path("scripts/output/multi_alpha_001_to_101.json")
    if output_path.exists():
        data = json.loads(output_path.read_text())
        assert data["success_count"] >= 90

def test_factor_count_unchanged():
    from pathlib import Path
    factors_dir = Path("quant/factors/101_alphas")
    factor_dirs = [d for d in factors_dir.iterdir() if d.name.startswith("stk_alpha_")]
    assert len(factor_dirs) >= 95

def test_db_row_count_unchanged():
    import sqlite3
    from pathlib import Path
    db_path = Path.home() / ".llmwikify" / "agent" / "reproduction.db"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM reproduction_results").fetchone()[0]
        conn.close()
        assert count >= 90
```

**Gate G5 验证**:
```bash
pytest tests/test_e2e_99alpha.py -v
# 期望: 99/99 success, 因子数量不变, DB 行数不变
```

---

## 24. 单元测试运行总表

| 阶段 | 测试文件 | 测试数 | 验证 |
|------|----------|--------|------|
| 1 | test_common.py | 8 | 旧路径 → 新路径 |
| 2 | test_data_source.py | 4 | 同上 |
| 3 | test_imports.py | 33 (parametrized) | 兼容层 [G1] |
| 4 | test_prompts.py | 9 | 新建 |
| 5 | test_codegen.py | 7 | 旧路径 → 新路径 |
| 6 | test_codegen_ast.py | 5 | 同上 |
| 7 | test_backtest.py | 6 | 同上 |
| 8 | test_persist.py | 5 | 同上 |
| 9 | test_prompts_builtin.py | 7 (3+4 新增) | 新建 |
| 10 | test_codegen_with_prompts.py | 3 | 行为等价 |
| 11 | test_metadata_extract.py | 2 | 行为等价 |
| 12A | test_paper_understanding.py | 6 | 旧路径 → 新路径 |
| 12B | test_llm_extraction.py | 16 | 内部 16 文件 [G4] |
| 13 | test_prompts_edge.py | 6 | 新建 |
| 14A | test_pipeline_framework.py | 4 | 新建 |
| 14B | test_react.py | 9 | 新建 |
| 14C | test_pipeline_modules.py | 6 | 行为等价 (关键) |
| 14D | test_stages.py | 6 | 新建 |
| 14E | test_cli.py | 4 | 新建 |
| 14F1 | test_e2e_5alpha.py | 5 | e2e 验证 |
| 14F2 | test_e2e_99alpha.py | 3 | [G5] |
| | **总计** | **~150 个测试** | |

---

## 25. 用户决策的全部体现

| # | 决策 | 体现阶段 | 说明 |
|---|------|----------|------|
| 1 | 分阶段实施 | 20 Phases | 全部 ≤ 0.75 天 |
| 2a | AST 全部搬迁不删 | Phase 6 | 完整 codegen/ast/ |
| 3a | scripts/ 全部保留 | 全部 Phase | 不删任何 scripts/ 文件 |
| 4 | 物理搬迁 (git mv) | Phase 1-13 | 保留 blame |
| 5 | llm_extraction 暂缓 | Phase 12A/12B | prompts 后再搬 |
| 6 | 同步迁移 prompt | Phase 12B + 13 | track_a/b 一并迁 |
| 7 | 暂不创建 paper_understanding (Phase 2) | Phase 12A | 12A 一次性建完整 |
| 8 | prompts 先核心后边缘 | Phase 9 → 11 → 13 | code_gen → metadata → track |
| 9 | 工时 > 1 天必须拆 | Phase 12, 14 拆分 | 14 → 20 Phases |
| 10 | 每步前写完整测试 | 所有 Phase 都有 "测试 (前)" | 22 个测试文件, ~150 个测试 |
| 11 | 测试不回归 (仅改 import) | 所有 Phase 都有 "测试 (后)" | 行为等价性测试是核心 |
| 12 | 串行执行 (不并行) | 全程串行 | Verify-Then-Proceed 原则 |

---

## 26. 最终汇总

| 维度 | 数值 |
|------|------|
| **阶段数** | **20** (全部 ≤ 0.75 天) |
| **总工时** | **10.0 天** |
| **关键路径** | 6.5 天 (Phase 1→6→5→9→10→14A→14B→14C→14D→14E→14F1→14F2) |
| **测试文件** | **22 个** |
| **测试用例** | **~150 个** |
| **Gate 数** | 5 (G1, G2, G3, G4, G5) |
| **最长单阶段** | 0.75 天 (Phase 7, 9, 13, 14C) |
| **风险** | 中 (20 阶段串行, 每阶段有测试保护) |
| **回退成本** | 低 (每阶段独立可 git revert) |
| **执行模式** | 串行 (不并行) |

### 26.1 实施前必做

1. **建立测试基础设施**:
   ```
   tests/__init__.py
   tests/conftest.py        # 公用 fixture
   tests/test_imports.py    # 33 parametrized (保护 WebUI)
   ```

2. **写测试基线**:
   ```bash
   pytest tests/ -v
   # 期望: 33 个 import 测试通过 (这是迁移前的快照)
   ```

3. **验证现有数据完整性**:
   ```bash
   ls quant/factors/101_alphas/ | wc -l   # 99 个因子目录
   sqlite3 ~/.llmwikify/agent/reproduction.db "SELECT COUNT(*) FROM reproduction_results"
   # 期望: 99 条记录
   ```

### 26.2 验证节奏 (每 Phase)

| 时机 | 命令 | 期望 |
|------|------|------|
| 执行前 | `pytest tests/test_<phase>.py -v` | 全部通过 (旧代码) |
| 执行中 | `git mv` + 改 import (仅) | 无 diff 在函数体 |
| 执行后 | `pytest tests/test_<phase>.py -v` | 全部通过 (新代码) |
| 全量回归 | `pytest tests/ -v` | 0 失败 |
| Gate | `curl /api/health` + `pytest tests/test_imports.py -v` | 通过 |

### 26.3 应急回退

任何 Phase 失败:
```bash
# 1. 找到该 Phase 的 commit
git log --oneline -n 20

# 2. revert 该 commit
git revert <commit-hash>

# 3. 验证测试通过
pytest tests/ -v

# 4. 修复问题后重新执行
```

---

## 27. 文档版本

| 版本 | 日期 | 内容 |
|------|------|------|
| v1.0 | 2026-06-23 | 初版设计 (Section 1-13) |
| v1.1 | 2026-06-23 | 加入实施风险评估 (Section 14-19) |
| v1.2 | 2026-06-23 | 加入 14 → 20 阶段细化 + 单元测试要求 (Section 20-27) |
| v1.3 | 2026-06-23 | 加入 AI 执行原则 (Section 28) — **G5 前不主动暂停** |
| v1.4 | 2026-06-23 | 加入单元测试完整规划 (Section 29) — **5 阶段, 13 天, ~300 新测试** |
| v1.5 | 2026-06-23 | 加入 Python 设计模式评估 (Section 30) — **7 类模式集成, +2.5d** |
| **v1.6** | 2026-06-23 | **修复 5 个内部矛盾 + 加部署与运维 (Section 31)** — Stage ABC 用 StageContext dataclass / metadata_extract 改 Stage 1 / CLI 双入口 / 删除旧 5-Phase Gate 表 / Strategy for FactorCompiler 改为配置选择 / 加 nanobot 待验证 / 加 Section 31 部署与运维 |

---

# 第四部分: AI 执行原则

> Section 28 是 2026-06-23 关于 AI 如何执行 20 阶段任务的讨论记录。

## 28. AI 执行原则 (修订版)

### 28.1 核心原则总览

针对 20 阶段 refactoring 任务, 提出 6 类 30 条原则, 帮助 AI 高质量完成。

**关键设计**: 仅 G5 是硬暂停点, G1-G4 是自动验证点 (AI 不主动暂停)。

### 28.2 A. 阶段执行原则 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| **A1** | **一次只做一个阶段** | 不跨阶段, 不并行, 不跳跃 |
| **A2** | **仅 G5 是硬暂停点** | G1-G4 是自动验证点 (失败按 D5 重试), **仅 G5 后等用户最终确认** |
| A3 | 每阶段独立可回退 | 每个 phase 是一个独立 git commit, 失败可 revert |
| A4 | 执行前先读设计文档对应章节 | 文档即 spec, 避免偏离设计 |
| A5 | 阶段结束输出 L1 详细报告 | 每阶段都输出, 不论 Gate 或非 Gate |

### 28.3 B. 测试纪律 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| B1 | 测试先于代码 (TDD) | 先写测试 → 跑通当前代码 → 实施阶段 → 测试仍通过 |
| B2 | 零回归, 只允许改 import | 严禁改测试逻辑/函数实现 |
| B3 | 行为等价性测试是核心 | Phase 14C 等重构类必须做"新旧实现对比" |
| B4 | 不跳过, 不删除, 不 `@pytest.skip` | 红线 (Section 22.6) |
| B5 | 关键 import 始终保护 | `test_imports.py` 33 个 parametrized 是 WebUI 不破的基石 |

### 28.4 C. 变更纪律 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| C1 | 最小 diff | 只动该动的, 每一行 diff 可追溯到用户请求 |
| C2 | 保留 git blame | 用 `git mv` 不用 `cp + rm`, 不重写历史 |
| C3 | 不"顺手"重构 | 看到不顺眼的代码不主动改, 列 TODO 后续处理 |
| C4 | 不改函数签名 | 旧 API 必须向后兼容, 新参数用 default value |
| C5 | 不删代码除非必要 | scripts/ 全保留, deprecated 用 docstring 标记 |

### 28.5 D. 决策原则 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| D1 | 困惑就停下问 | 不假设, 多解就列出, 资深工程师会嫌复杂就重写 |
| D2 | 不做超出范围的决策 | 当前阶段解决当前问题, 不提前优化 |
| D3 | 遵循 AGENTS.md | Simplicity First, Surgical Changes, Verify-Then-Proceed |
| **D4** | **仅 G5 后等待用户最终确认** | G1-G4 阶段 AI 自动推进, 不主动暂停 |
| **D5** | **硬限重试 3 次** | 遇 blocker 重试 3 次, 仍失败主动停下报告, 等待用户决策 |

### 28.6 E. 知识连续性 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| E1 | commit message 中文, 风格 `fix(scope): 说明` | 符合用户偏好 |
| E2 | commit 前 `git status` + `git diff --stat` | 确认改动范围 |
| E3 | 写迁移记录 | `docs/migrations/2026-06-23-pipeline-refactor.md` 记录每阶段 |
| E4 | 更新设计文档 | 每阶段完成后, 文档标注"Phase N 已完成" |
| E5 | 不留 stash 遗留 | 阶段性 commit 前主动提醒用户处理 stash |

### 28.7 F. 沟通原则 (5 条)

| # | 原则 | 说明 |
|---|------|------|
| F1 | 每阶段输出 L1 详细报告 | 不论 Gate 或非 Gate |
| F2 | 遇 blocker 立即报告 | 不尝试绕过, 主动暴露 |
| F3 | 测试结果要可见 | 输出 pass/fail 数, 不只说"通过了" |
| F4 | 每个 Gate 单独报告 | G1-G4 自动验证也要报告, G5 详细报告 |
| F5 | 最终报告完整 (L2) | 全部 20 阶段完成后输出 L2 |

### 28.8 Gate 角色重新定义

| Gate | 阶段 | 角色 | AI 行为 |
|------|------|------|---------|
| **G1** | Phase 3 后 | **自动验证点** | 跑测试, 输出 L1 报告; 失败按 D5 重试, 仍失败停下 |
| **G2** | Phase 8 后 | **自动验证点** | 同 G1 |
| **G3** | Phase 11 后 | **自动验证点** | 同 G1 |
| **G4** | Phase 12B 后 | **自动验证点** | 同 G1 |
| **G5** | Phase 14F2 后 | **硬暂停点** | ⏸ 强制暂停, 输出 L2 最终报告, 等用户最终确认 |

**关键区别**:
- G1-G4: AI 自动推进, 仅报告验证结果
- G5: AI 强制停止, 等待用户最终验收

### 28.9 执行节奏示意

```
Phase 1   ──┐
Phase 2   ──┤
Phase 3 [G1]─┤ 自动验证 (L1 报告)
Phase 4   ──┤
Phase 5   ──┤
Phase 6   ──┤
Phase 7   ──┤ 自动推进 (每阶段 L1 报告)
Phase 8 [G2]─┤ 自动验证 (L1 报告)
Phase 9   ──┤
Phase 10  ──┤
Phase 11[G3]─┤ 自动验证 (L1 报告)
Phase 12A ──┤
Phase 12B[G4]┤ 自动验证 (L1 报告)
Phase 13  ──┤
Phase 14A ──┤
Phase 14B ──┤
Phase 14C ──┤
Phase 14D ──┤ 自动推进 (每阶段 L1 报告)
Phase 14E ──┤
Phase 14F1 ──┤
Phase 14F2[G5]┘ ⏸ 硬暂停 (L2 最终报告 + 等待用户最终确认)
```

**总暂停次数**: 1 次 (G5)
**自动验证点**: 4 个 (G1, G2, G3, G4)
**自动推进阶段**: 15 个

### 28.10 20 阶段 + Gate 类型总表

| # | Phase | Time | Gate | AI 行为 |
|---|-------|------|------|---------|
| 1 | common/ | 0.5 | - | 自动 + L1 |
| 2 | data_source/ | 0.5 | - | 自动 + L1 |
| 3 | 兼容层 | 0.5 | **G1 (自动验证)** | 跑测试, L1 报告, 失败按 D5 重试 |
| 4 | prompts/ 骨架 | 0.5 | - | 自动 + L1 |
| 5 | codegen/ | 0.5 | - | 自动 + L1 |
| 6 | codegen/ast/ | 0.5 | - | 自动 + L1 |
| 7 | backtest/ | 0.75 | - | 自动 + L1 |
| 8 | persist/ | 0.5 | **G2 (自动验证)** | 跑测试, L1 报告, 失败按 D5 重试 |
| 9 | prompts/builtin/ 核心 | 0.75 | - | 自动 + L1 |
| 10 | codegen/ 接入 | 0.5 | - | 自动 + L1 |
| 11 | metadata_extract + 接入 | 0.5 | **G3 (自动验证)** | 跑测试, L1 报告, 失败按 D5 重试 |
| 12A | paper_understanding/ 6 文件 | 0.5 | - | 自动 + L1 |
| 12B | llm_extraction/ 16 文件 | 0.5 | **G4 (自动验证)** | 跑测试, L1 报告, 失败按 D5 重试 |
| 13 | prompts/builtin/ 边缘 | 0.75 | - | 自动 + L1 |
| 14A | pipeline/ 框架骨架 | 0.5 | - | 自动 + L1 |
| 14B | pipeline/ 三层 ReAct | 0.5 | - | 自动 + L1 |
| 14C | pipeline/ 业务模块 | 0.75 | - | 自动 + L1 |
| 14D | 4 个 Stage | 0.5 | - | 自动 + L1 |
| 14E | CLI + config.yaml | 0.5 | - | 自动 + L1 |
| 14F1 | 5 alpha e2e + WebUI | 0.5 | - | 自动 + L1 |
| 14F2 | 99 alpha + 一致性 | 0.5 | **G5 (硬暂停)** | ⏸ 强制暂停, L2 最终报告, 等用户确认 |

### 28.11 D5 硬限重试机制

```
遇 blocker (Gate 验证失败):
  ├─ 轮次 1: 修复并重试
  ├─ 轮次 2: 修复并重试
  ├─ 轮次 3: 修复并重试
  └─ 仍失败: 主动停下来报告
              ├── 描述 blocker 详情
              ├── 列出已尝试的修复
              ├── 给出建议方案 (1-3 个选项)
              └── 等待用户决策
```

**关键**:
- 不连续重试超过 3 次
- 不带病前进 (D5 vs A2)
- 报告内容要清晰可决策

### 28.12 L1 阶段报告模板

```markdown
## [Phase N/20] {Phase 名称} 完成

**耗时**: {实际} (估算 X 天)
**类型**: {自动 / Gate 验证点 / 硬暂停点}
**Gate 编号**: {G1/G2/G3/G4/G5 或 无}

### 改动
- {文件 1}: {改动描述}
- {文件 2}: {改动描述}

### 测试
- tests/test_{phase}.py: X/X 通过
- tests/test_imports.py: 33/33 通过 (兼容层)
- 行为等价性: ✅/⚠️/❌

### Gate 验证 (仅 Gate 阶段)
- {验证项 1}: ✅
- {验证项 2}: ✅
- WebUI /api/health (如适用): ✅
- Gate G{X} (如适用): ✅

### Git
- commit: {hash} - {message}

### 遗留
- {TODO 1}
- {known issue 1}

### 下一步
{硬暂停 G5: 等待用户最终确认. / 其他: 进入 Phase {N+1} ({名称}), 自动推进.}
```

### 28.13 L2 最终报告模板

```markdown
## 20 阶段 Refactor 完成报告 (G5 硬暂停)

**总耗时**: X 天 (估算 10 天)
**Git 提交**: {N} 个 commit
**测试用例**: X 个 (迁移前 X, 迁移后 X, 差异 0)

### 核心指标
- 99/99 alpha success: ✅
- WebUI /api/health 200 OK: ✅
- 20+ 外部 import 全部可用: ✅
- 因子目录 99 个, DB 99 条: ✅
- 旧 scripts/ 仍可执行: ✅

### 用户决策执行 (12 条)
- 决策 1-12: 全部 ✅

### 已知遗留
- {issue 1}
- {issue 2}

### 建议后续
- {建议 1}
- {建议 2}

### 等待用户最终确认
```

### 28.14 与 AGENTS.md 关系

| AGENTS.md 原则 | 强化/补充 |
|----------------|----------|
| 1. Think Before Coding | D1 (困惑就停下问) |
| 2. Simplicity First | C1 (最小 diff), D2 (不做超出范围) |
| 3. Surgical Changes | C1, C2, C3 |
| 4. Goal-Driven Execution | A1, A2, A3 |
| 5. Context First | A4 (读设计文档) |
| 6. Verify-Then-Proceed | A2, B1, B2, B3 |
| 7. Loop Until Done | A2, D5 (失败不前进) |
| 8. Memory Hygiene | E1, E2, E3, E4, E5 |

这些原则与 AGENTS.md 兼容, **不冲突**, 是具体到这个 20 阶段任务的应用层细化。

### 28.15 原则总结表

| 类别 | 原则数 | 范围 |
|------|--------|------|
| A. 阶段执行 | 5 | A1-A5 |
| B. 测试纪律 | 5 | B1-B5 |
| C. 变更纪律 | 5 | C1-C5 |
| D. 决策原则 | 5 | D1-D5 |
| E. 知识连续性 | 5 | E1-E5 |
| F. 沟通原则 | 5 | F1-F5 |
| **总计** | **30 条** | |
| 报告模板 | 2 | L1 阶段, L2 最终 |
| 应急机制 | 1 | D5 硬限重试 3 次 |

### 28.16 修订历史 (本节)

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.2 原则版 | 2026-06-23 | 5 Gate 全部硬暂停, 遇 blocker 不限重试 |
| **v1.3 修订版 (当前)** | 2026-06-23 | **仅 G5 硬暂停**, G1-G4 自动验证, **硬限重试 3 次** |

---

# 第五部分: 单元测试规划

> Section 29 是 2026-06-23 关于 reproduction/ 56 个模块的完整测试规划。

## 29. 单元测试完整规划

### 29.1 用户决策 (6/6)

| # | 决策 | 内容 |
|---|------|------|
| 1 | **a** 范围 | 顶层 40 + llm_extraction 16 = **56 个文件** |
| 2 | **a** 策略 | 完整 5 阶段, 13 天 |
| 3 | **a** 风格 | **严格 0 回归**: 只新增文件, 不动旧测试 |
| 4 | **b** 时机 | **测试与 refactor 并行**: refactor 阶段必先有测试 |
| 5 | **a** CI | **立即接入 GHA** |
| 6 | **b** 数据源 | **mock 优先 + 1 个真实冒烟** (GHA secret gating) |

### 29.2 现状基线

| 指标 | 当前值 |
|------|--------|
| Python | 3.10.12 (CI 3.10/3.11/3.12) |
| 现有 tests | **784 collected**, 抽样 67/67 通过 |
| pytest 配置 | `[tool.pytest.ini_options]` 已含 `addopts=-v --tb=short`, markers=e2e |
| coverage 配置 | `[tool.coverage]` 已含 `branch=true`, `source=["src/llmwikify"]` |
| GHA | `tests.yml` + `lint.yml` 已有 (基础跑 pytest) |
| pyproject extras | dev: pytest/pytest-cov/black/ruff/mypy |
| **目标覆盖率** | **80% line** (fail_under) |

### 29.3 测试覆盖矩阵 (56 个模块)

| 类别 | 数量 | 模块 |
|------|------|------|
| **完全覆盖** ✅ | 19 | defer, extract, extract_factors, extract_paper, factor_backtest, factor_compiler_react, llm_extraction/orchestrator, llm_extraction/plan_saver, llm_extraction/retry, llm_extraction/runlog, llm_extraction/stage0_ingest, llm_extraction/track_b, llm_extraction/validator, sessions, router, run, universe, utils, llm_extraction/section_detector(部分) |
| **零覆盖** ❌ | **15** | akshare_data, ast_compiler, ast_complexity, ast_extractor, clickhouse_data, config, contracts, error_categorizer, factor_library, ifind_data, paths, run_id, telemetry, llm_extraction/config, llm_extraction/llm_factory |
| **部分覆盖** ⚠️ | **18** | ast_nodes, backtest, codegen_utils, factor_compiler, factor_extractor, factor_value_store, l5_validation, metrics, quant_wiki, quantnodes_adapter, quantnodes_repro, schemas, self_repairing, strategies, llm_extraction/planner, llm_extraction/preview, llm_extraction/section_detector, llm_extraction/track_a |

### 29.4 五阶段总览

| 阶段 | 内容 | 文件数 | 新测试 | 时间 | 累计 |
|------|------|--------|--------|------|------|
| **0** | 基础设施 (imports/inventory/smoke) | 3 | 87+ | 1d | 1d |
| **1** | 零覆盖模块 | 15 | ~120 | 5d | 6d |
| **2** | 部分覆盖补充 | 18 | ~180 | 4d | 10d |
| **3** | 集成 + 行为等价性 | 6 | ~40 | 3d | 13d |
| **4** | 覆盖率报告 + CI 完善 | 2 | - | 1d | 14d |
| **总计** | | **44** | **~430** | **14d** | |

### 29.5 阶段 0: 基础设施 (D1, 1 天)

**目标**: 建立"全模块可导入 + 全模块有基本测试"的最低基线。

#### 29.5.1 `tests/reproduction/test_imports.py` (新)

```python
ALL_MODULES = [
    # 40 顶层模块
    "akshare_data", "ast_compiler", "ast_complexity", "ast_extractor",
    "ast_nodes", "backtest", "clickhouse_data", "codegen_utils",
    "config", "contracts", "error_categorizer", "extract",
    "extract_factors", "extract_paper", "factor_backtest",
    "factor_compiler", "factor_compiler_react", "factor_extractor",
    "factor_library", "factor_value_store", "ifind_data",
    "l5_orchestrator", "l5_validation", "metrics", "paths",
    "quant_wiki", "quantnodes_adapter", "quantnodes_repro",
    "router", "run", "run_id", "schemas", "self_repairing",
    "sessions", "strategies", "telemetry", "universe", "utils",
    # 16 llm_extraction/ 模块
    "llm_extraction.config", "llm_extraction.defer",
    "llm_extraction.llm_factory", "llm_extraction.log_decorator",
    "llm_extraction.orchestrator", "llm_extraction.plan_saver",
    "llm_extraction.planner", "llm_extraction.preview",
    "llm_extraction.retry", "llm_extraction.runlog",
    "llm_extraction.section_detector", "llm_extraction.stage0_ingest",
    "llm_extraction.track_a", "llm_extraction.track_b",
    "llm_extraction.validator",
]

@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports(module_name):
    __import__(f"llmwikify.reproduction.{module_name}")
```

**测试数**: 56 (parametrized)

#### 29.5.2 `tests/reproduction/test_module_inventory.py` (新)

锁定每个模块的公共 API, 防止重构时意外破坏。

```python
EXPECTED_PUBLIC_API = {
    "factor_library": ["read_factor_yaml", "write_factor_yaml",
                        "list_factors", "update_index", ...],
    # ... 56 个模块
}
```

**测试数**: ~30 (parametrized)

#### 29.5.3 `tests/reproduction/test_no_uncovered_smoke.py` (新)

```python
# 列出所有 reproduction/ 下的模块
# 检查每个模块是否在 tests/ 中有对应测试文件
# 无测试文件的: fail
```

**测试数**: 1 (skipif override)

**阶段 0 产出**: 3 个新文件, 87+ 测试, **1 天完成**

---

### 29.6 阶段 1: 零覆盖模块 (D2-D6, 5 天)

#### 29.6.1 测试规格 (按优先级)

| 序号 | 模块 | 行数 | 测试文件 | 测试数 | 估算 |
|------|------|------|---------|--------|------|
| **P0 (立即)** | | | | | |
| 1 | `factor_library.py` | 314 | `test_factor_library.py` | 25 | 0.5d |
| **P1 (核心)** | | | | | |
| 2 | `paths.py` | 187 | `test_paths.py` | 12 | 0.25d |
| 3 | `run_id.py` | 70 | `test_run_id.py` | 5 | 0.1d |
| 4 | `telemetry.py` | 80 | `test_telemetry.py` | 8 | 0.15d |
| 5 | `error_categorizer.py` | 156 | `test_error_categorizer.py` | 10 | 0.25d |
| 6 | `config.py` | 250 | `test_repro_config.py` | 12 | 0.3d |
| 7 | `contracts.py` | 468 | `test_contracts.py` | 18 | 0.5d |
| **P2 (AST)** | | | | | |
| 8 | `ast_extractor.py` | 98 | `test_ast_extractor.py` | 10 | 0.25d |
| 9 | `ast_complexity.py` | 113 | `test_ast_complexity.py` | 8 | 0.2d |
| 10 | `ast_compiler.py` | 192 | `test_ast_compiler.py` | 12 | 0.4d |
| **P3 (LLM 子包)** | | | | | |
| 11 | `llm_extraction/config.py` | 245 | `test_llm_extraction_config.py` | 10 | 0.3d |
| 12 | `llm_extraction/llm_factory.py` | 82 | `test_llm_factory.py` | 8 | 0.2d |
| **P4 (数据源)** | | | | | |
| 13 | `akshare_data.py` | 212 | `test_akshare_data.py` | 10 | 0.4d |
| 14 | `clickhouse_data.py` | 209 | `test_clickhouse_data.py` | 8 | 0.4d |
| 15 | `ifind_data.py` | 685 | `test_ifind_data.py` | 14 | 0.5d |

**小计**: ~4.25 天, **15 个新文件**, **~170 测试**

#### 29.6.2 factor_library.py 详细测试设计 (示例, 最重要)

```python
# test_factor_library.py

class TestReadFactorYaml:
    def test_new_dir_format(self, tmp_path):         # 101_alphas/.../factor.yaml
    def test_old_single_file_format(self, tmp_path): # 旧 *.yaml 平铺
    def test_missing_file_returns_none(self, tmp_path):
    def test_invalid_yaml_returns_none(self, tmp_path):
    def test_loads_code_py(self, tmp_path):         # 单独 code.py
    def test_loads_backtest_latest(self, tmp_path):  # backtest/latest.json
    def test_loads_meta_json(self, tmp_path):
    def test_handles_unicode(self, tmp_path):

class TestWriteFactorYaml:
    def test_writes_factor_yaml(self, tmp_path):
    def test_writes_code_py(self, tmp_path):
    def test_writes_backtest(self, tmp_path):
    def test_atomic_write(self, tmp_path):          # 防止半成品

class TestListFactors:
    def test_empty_dir(self, tmp_path):
    def test_lists_all_factors(self, tmp_path):
    def test_filters_by_category(self, tmp_path):

class TestUpdateIndex:
    def test_creates_index_if_missing(self, tmp_path):
    def test_appends_new_factor(self, tmp_path):
    def test_idempotent(self, tmp_path):

# 约 25 个测试
```

---

### 29.7 阶段 2: 部分覆盖补充 (D7-D10, 4 天)

#### 29.7.1 重点补充方向 (不修改旧测试, 全部新文件)

| 模块 | 已有测试 | 补充方向 | 估算 |
|------|---------|---------|------|
| `ast_nodes.py` | - | AST 节点构造/序列化/深拷贝 | 0.3d |
| `backtest.py` | factor_api, p0_fixes | 与 factor_backtest 差异 + run_backtest 主流程 | 0.3d |
| `codegen_utils.py` | factor_compiler_react | extract_python/validate_safety/execute_code 完整路径 | 0.4d |
| `factor_compiler.py` | loop_v4 | AST 路径 + L5 fallback + 错误 | 0.4d |
| `factor_extractor.py` | extract_factor_metadata, multi | existing_metadata merge + batch_size | 0.4d |
| `factor_value_store.py` | parquet_and_formula | H5/Parquet 读写 + Polars 兼容 | 0.3d |
| `l5_validation.py` | l4_sync, l5_* | hypothesis sync + 风险校验 | 0.4d |
| `metrics.py` | quant | IC/ICIR/winrate 计算 | 0.3d |
| `quant_wiki.py` | paper_api | Wiki 写入 + Markdown 转换 | 0.3d |
| `quantnodes_adapter.py` | quant, cross_section | PipelineRunner 12 节点 | 0.4d |
| `quantnodes_repro.py` | factor_backtest, quant | Reproduce 端到端 | 0.4d |
| `schemas.py` | routes | Schema 验证 + 序列化 | 0.3d |
| `self_repairing.py` | factor_compiler_react | 自动修复错误分类 + 重试 | 0.3d |
| `strategies.py` | strategy_api, loop_v4 | 策略组合 + 资金曲线 | 0.3d |
| `llm_extraction/planner.py` | planner_helpers | Plan 生成 + token budget | 0.3d |
| `llm_extraction/preview.py` | validator_preview | 预览生成 + 校验 | 0.3d |
| `llm_extraction/section_detector.py` | section_detector_helpers | 16-section typology | 0.3d |
| `llm_extraction/track_a.py` | - (缺) | Tier 1/2 metadata 提取 | 0.3d |

**小计**: ~5.6 天, **18 个新文件**, **~180 测试**

---

### 29.8 阶段 3: 集成 + 行为等价性 (D11-D12, 3 天)

#### 29.8.1 文件清单

| 文件 | 内容 | 测试数 | 估算 |
|------|------|--------|------|
| `test_pipeline_equivalence.py` | 旧 reproduction/ 实现 vs 新 pipeline/ 实现的输出对比 (refactor 时使用) | 6 | 0.5d |
| `test_pipeline_e2e_5alphas.py` | alpha-001/002/003/004/005 端到端 (~10min, gated) | 5 | 0.5d |
| `test_pipeline_99alphas.py` | 99 alpha 完整 (~60min, CI nightly only) | 1 | 0.5d |
| `test_webui_factor_pages.py` | WebUI /factor/{id} 路由 + 渲染 (FastAPI TestClient) | 12 | 0.5d |
| `test_data_source_integration.py` | akshare/clickhouse/ifind 切换 + 数据一致性 | 10 | 0.5d |
| `test_react_self_repair_e2e.py` | ReAct 主循环 + 自动修复完整流程 | 6 | 0.5d |

**小计**: ~3 天, **6 个新文件**, **~40 测试**

#### 29.8.2 行为等价性测试模板

```python
# test_pipeline_equivalence.py

def test_factor_library_read_old_vs_new_format():
    """旧 *.yaml 与新 {name}/factor.yaml 行为等价."""
    old_result = read_factor_yaml_old("stock/price/momentum")
    new_result = read_factor_yaml_new("stock/price/momentum")
    assert new_result["name"] == old_result["name"]
    assert new_result["l5"]["ast"] == old_result["l5"]["ast"]
```

---

### 29.9 阶段 4: 覆盖率报告 (D13, 1 天)

#### 29.9.1 pyproject 门槛

```toml
[tool.coverage.report]
fail_under = 80
show_missing = true
exclude_lines = [...]
```

#### 29.9.2 CI 集成

- codecov.io 接入
- PR 评论显示覆盖率 diff
- main 分支覆盖率追踪

#### 29.9.3 HTML 报告

- 保留本地生成 (`htmlcov/`)
- 加 .gitignore

---

### 29.10 CI 增强 (1 天)

#### 29.10.1 修改 `.github/workflows/tests.yml`

```yaml
name: Tests
on: [push, pull_request]
jobs:
  unit:               # 快, < 2min, 必跑
  unit-mock-only:     # 不连真实, 默认 gating
  integration:        # DB/H5, ~10min
  llm-smoke:          # 真实 LLM, GHA secret gating
  coverage:           # codecov 上传
```

**关键设计**:
- `unit` job: 全 mock, 默认触发, ~30s
- `integration` job: 真实 DB/H5, ~5min, push to main + PR
- `llm-smoke` job: 真实 LLM, `if: github.event_name == 'push' && github.ref == 'refs/heads/main' && env.LLM_API_KEY` gating
- `coverage`: codecov 上传, 门槛 80% line

#### 29.10.2 新增 GHA secrets

- `LLM_API_KEY` (minimax)
- `LLM_BASE_URL`
- `CODECOV_TOKEN`

#### 29.10.3 修改 pyproject.toml

- 新增 marker: `mock` (默认) / `integration` (push to main) / `llm` (gated)
- `addopts` 增加 `--strict-markers`

---

### 29.11 测试模板

#### 29.11.1 通用测试文件模板

```python
"""Tests for {module_name}.

覆盖:
  - 公开 API 主要路径
  - 边界 (空/None/Unicode)
  - 错误处理 (异常路径)
  - 性能 (大输入不超 2x)
"""
from __future__ import annotations

import pytest
from llmwikify.reproduction.{module_name} import (
    public_function_1, public_function_2, ...
)


class TestPublicFunction1:
    def test_basic(self):
        ...

    def test_edge_case_empty(self):
        ...

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            ...


class TestPublicFunction2:
    ...
```

#### 29.11.2 fixture 复用

复用 `tests/reproduction/conftest.py` 已有的:
- `FakeWiki` (in-memory wiki mock)
- `FakeRegistry`
- `FakeLLMClient`
- `paper_client`, `repro_client`, `factor_client`, `strategy_client`
- `tmp_path` (pytest built-in)

---

### 29.12 时间表 (Gantt)

```
D1   ┃ ████ 阶段 0 (基础设施)               ████
     ┃   test_imports.py (56)
     ┃   test_module_inventory.py (30)
     ┃   test_no_uncovered_smoke.py (1)
D2-3 ┃ ████ 阶段 1.1-1.2 factor_library + paths/run_id/telemetry
D4   ┃ ████ 阶段 1.3-1.4 error_categorizer/config/contracts
D5   ┃ ████ 阶段 1.5-1.7 ast 4 + llm_extraction 2
D6   ┃ ████ 阶段 1.8 数据源 3 (mock 优先)
D7-9 ┃ ████ 阶段 2 补充 18 文件 (重点)
D10  ┃ ████ 阶段 2 补充 (剩余)
D11  ┃ ████ 阶段 3.1-3.2 集成 + 等价性
D12  ┃ ████ 阶段 3.3-3.4 e2e + WebUI
D13  ┃ ████ 阶段 4 覆盖率报告 + CI
```

---

### 29.13 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| iFinD/ClickHouse mock 复杂 | 高 | 测试慢 | 写接口契约测试, 真实调用仅 1 个冒烟 |
| Polars 兼容性差异 | 中 | 断言 flaky | tolerance + 业务结果对比, 不比 bit-level |
| LLM 真实测试不稳定 | 中 | CI 失败 | 严格 gating, 仅 nightly + main |
| 文档未与代码同步 | 中 | 信任降低 | 阶段 0 test_module_inventory 锁定 API |
| 18 个部分覆盖补充慢 | 中 | 进度推迟 | P0 优先, P1+ 可后续 |
| 20 阶段 refactor 冲突 | 中 | 工作量翻倍 | 阶段 0 严格 smoke test 先建立, refactor 必先有测试 |

---

### 29.14 验证清单 (Definition of Done)

每个阶段必须满足:

- [ ] 所有新测试通过 (`pytest -m mock`)
- [ ] 已有 784 测试**全部仍然通过** (0 回归)
- [ ] 阶段报告中说明: 文件数 / 新增测试数 / 覆盖率
- [ ] 旧测试**完全未修改** (用 `git diff tests/reproduction/`)
- [ ] 新增文件命名遵循 `test_<module>_<aspect>.py` 规范
- [ ] 中文 commit message 风格 `test(repro): 阶段 X.Y <说明>`
- [ ] GHA unit job 跑通 (5min 内)

**最终交付物** (D13):
- 56 个模块全部有测试
- 零覆盖模块: 0
- 部分覆盖模块: ≤ 5 (剩 13 个有完整覆盖)
- 总测试数: ~1300+ (从 784 → 1300+)
- Coverage ≥ 80% line
- GHA 5 jobs 全部跑通
- 20 阶段 refactor 可安全进行

---

### 29.15 与 20 阶段 refactor 关系 (决策 4.b)

按决策 4.b (**测试与 refactor 并行**), 实施时序:

| refactor 阶段 | 前置测试 | 并行 |
|--------------|---------|------|
| Phase 1 (common/) | test_common.py | 阶段 0-1 |
| Phase 2 (data_source/) | test_data_source.py | 阶段 1.13-1.15 |
| Phase 3 (兼容层) | test_imports.py (33 parametrized) | 阶段 0 |
| Phase 5 (codegen/) | test_codegen.py | 阶段 1.4 (codegen_utils) + 阶段 2.3 |
| Phase 7 (backtest/) | test_backtest.py | 阶段 2.2 |
| Phase 8 (persist/) | test_persist.py | 阶段 2.x |
| Phase 11 (metadata_extract) | test_metadata.py | 阶段 2.5 |
| Phase 14C (pipeline/ 业务) | test_pipeline_equivalence.py | 阶段 3.1 |

**强约束**: refactor 一个模块前, 该模块必须有完整测试。

---

### 29.16 立即执行清单 (退出 Plan Mode 后)

| 步骤 | 操作 | 时间 |
|------|------|------|
| **1** | 修改 `pyproject.toml` (新 marker, fail_under) | 5min |
| **2** | 改写 `.github/workflows/tests.yml` (5 jobs) | 30min |
| **3** | 创建 `tests/reproduction/test_imports.py` (56 测试) | 1h |
| **4** | 创建 `tests/reproduction/test_module_inventory.py` (30 测试) | 1h |
| **5** | 创建 `tests/reproduction/test_no_uncovered_smoke.py` (1 测试) | 15min |
| **6** | 跑 `pytest -m mock` 验证基线 | 5min |
| **7** | commit: "test(repro): 阶段 0 基础设施 — 56 模块 import + 公共 API 锁定" | 5min |
| **8** | 进入阶段 1, 按 4.25 天分批 | ... |

**Day 1 总计**: ~3.5h, 产出 87+ 测试, CI 跑通

---

### 29.17 原则总结

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 测试范围 | 56 个文件 | 全面, 避免盲点 |
| 执行策略 | 5 阶段, 13 天 | 渐进, 风险可控 |
| 测试风格 | 严格 0 回归 | 保护现有 784 测试 |
| refactor 时机 | 测试先行 | 安全 refactor, 不破 |
| CI 集成 | 立即 GHA | 5 jobs, 早发现早修复 |
| 数据源 | mock 优先 + 1 冒烟 | 稳定 + 真实覆盖 |

---

**Section 29 完成**. 涵盖 56 个模块的完整单元测试规划: 5 阶段, 13 天, 44 个新文件, ~430 个新测试, 80% 覆盖率门槛, 决策记录.

---

# 第六部分: Python 设计模式集成

> Section 30 是 2026-06-23 关于 reproduction/ 56 个模块的设计模式评估与重构建议。

## 30. Python 设计模式评估

### 30.1 用户决策 (5/5)

| # | 决策点 | 决策 |
|---|--------|------|
| 1 | 模式范围 | **(a) 必用 3 类 + (b) 推荐 4 类** = 7 类集成 |
| 2 | 引入顺序 | **(b) refactor 时引入** (与决策 4.b 一致) |
| 3 | ABC vs Protocol | **(b) ABC + Protocol 混用** (Pythonic) |
| 4 | 何时开始 | **(b) 先完成 Phase 0 测试** (安全) |
| 5 | Pydantic | **(a) 不引入** (overkill) |

### 30.2 现状勘察

| 维度 | 现状 | 评估 |
|------|------|------|
| **ABC/抽象基类** | 0 文件使用 | ⚠️ 重大空白 |
| **Protocol** | 1 个 (router.py:27 DataSource) | 🟡 仅 1 个, 远不够 |
| **@dataclass** | 18 文件 | ✅ 已成熟 |
| **Enum** | 0 个 (状态用 string) | ⚠️ 重复定义 3+ 次 |
| **Context Manager** | 0 个 | 🟡 缺 |
| **Factory** | llm_factory.py 已有 | ✅ 局部 |
| **Registry** | 0 个 | 🟡 缺 |
| **Builder** | 0 | 🟡 缺 |
| **Singleton** | 0 (依赖 module-level globals) | 🟢 Python 推荐 |
| **frozen=True** | 0 个 @dataclass | 🟡 18 个文件可加 |

### 30.3 代码异味 (Code Smells)

| 异味 | 位置 | 重复 | 影响 |
|------|------|------|------|
| **read_factor_yaml 散布 3 文件** | factor_library / quant_wiki / quantnodes_repro | 3× | 维护成本 |
| **Config 双份** | config.py (250) + llm_extraction/config.py (245) | 2× | 概念分裂 |
| **VALID_STATUSES 硬编码** | sessions.py:54 | 1× | 散落难改 |
| **DataSource 签名不一致** | akshare/clickhouse/ifind 3 文件 | 3× 接口不同 | 替换困难 |
| **3 个数据源** | akshare/clickhouse/ifind 不走 DataSource Protocol | 3× | 未统一 |
| **module logger 散落 29 文件** | 全部 | 29× | 风格不一致 |
| **@dataclass 无 frozen** | 18 文件 | 18× | 不可变数据保护 |

### 30.4 候选模式 × 适用场景矩阵

| 模式 | 适用模块 | 价值 | 成本 | 当前状态 | 建议 |
|------|---------|------|------|---------|------|
| **ABC (抽象基类)** | `Stage` (7 子包) | 🟢 高 | 🟢 低 | 未应用 | **必用** (Phase 14D) |
| **ABC** | `DataSource` | 🟢 高 | 🟡 中 | 已有 Protocol | **升级为 ABC** (Phase 2) |
| **ABC** | `LLMClient` | 🟡 中 | 🟢 低 | 未应用 | **Phase 11** (llm_factory) |
| **ABC** | `CodeValidator` | 🟡 中 | 🟢 低 | 未应用 | **Phase 5** (codegen) |
| **Strategy** | `DataSource` (3 impl) | 🟢 高 | 🟡 中 | 散落 | **Phase 2** |
| **Strategy** | `LLMProvider` (minimax/openai) | 🟡 中 | 🟡 中 | 部分 | **Phase 11** |
| **Strategy** | `FactorCompiler` (AST vs ReAct) | 🟡 中 | 🟡 中 | 并存 | **Phase 5** 统一接口 |
| **Factory** | `LLMClient.create()` | 🟡 中 | 🟢 低 | 已有 | **保留** |
| **Factory** | `Stage.create(name)` | 🟢 高 | 🟢 低 | 未应用 | **Phase 14D** |
| **Factory** | `DataSource.create(name)` | 🟡 中 | 🟢 低 | 部分 | **Phase 2** |
| **Registry** | `Stage` 注册表 | 🟢 高 | 🟢 低 | 未应用 | **Phase 14A** (planned) |
| **Registry** | `PromptTemplate` | 🟢 高 | 🟢 低 | 未应用 | **Phase 4** (planned) |
| **Builder** | `WorkspaceConfig` | 🟡 中 | 🟢 低 | 未应用 | **Phase 14A** (planned) |
| **Builder** | `PaperBacktestReport` | 🟡 中 | 🟢 低 | 未应用 | **Phase 7** |
| **Context Manager** | `pipeline.run()` (start/end) | 🟡 中 | 🟢 低 | 未应用 | **Phase 14A** |
| **Context Manager** | `Config.override()` (temp) | 🟡 中 | 🟢 低 | 未应用 | **可选** |
| **Enum** | `SessionStatus` (替代 VALID_STATUSES) | 🟢 高 | 🟢 低 | 字符串 | **Phase 1** (common/) |
| **Enum** | `ReactErrorKind` | 🟢 高 | 🟢 低 | 已有 | **保留** |
| **frozen=True** | `BacktestConfig` / `FactorMetadata` | 🟡 中 | 🟢 低 | 未用 | **Phase 1** (common/) |
| **Pydantic** | configs, contracts | 🟡 中 | 🟡 中 (新依赖) | 未用 | **不推荐** (overkill) |
| **Singleton** | `Config`, `LLMClient` | 🟡 中 | 🟢 低 | module-level | **不推荐** (Pythonic: globals) |
| **Template Method** | Stage.run() | 🟡 中 | 🟡 中 | 未用 | **不推荐** (过度抽象) |
| **Observer** | Telemetry events | 🟢 高 | 🟡 中 | 未用 | **可选** (Phase 14A) |
| **Chain of Responsibility** | Stage pipeline | 🟡 中 | 🟡 中 | 部分 (3 层 ReAct) | **保留** |
| **Memento/State** | Session.status 转移 | 🟡 中 | 🟡 中 | 字符串 | **可选** (Phase 1) |

### 30.5 强烈推荐 (3 类)

#### 30.5.1 🟢 ABC + Registry for Stages (Phase 14A/14D)

**现有问题**: 7 子包无统一接口 (paper_understanding/codegen/backtest/persist/strategy 各有 run() 但签名不同)

```python
# 方案: pipeline/stages/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class StageContext:
    """累积 14 字段的 ctx, 替代纯 dict 提供类型标注 (Section 3.1)"""
    paper_dir: Path | None = None
    formula: str | None = None
    code: str | None = None
    # ... 14 字段 (详见 Section 3.1)
    error: str | None = None
    alpha_index: int | None = None


class Stage(ABC):
    """Stage 是 pipeline 编排的最小单元, 薄包装.

    选择 ctx 字典 (StageContext dataclass) 而非 Generic[IT, OT]:
      - 14 字段累积, Generic 难以表达
      - 各 Stage 输出类型多样
      - 类型安全靠内部方法签名
    """
    name: str
    required_prompts: list[str] = []

    def __init__(self, workspace: "Workspace"):
        self.workspace = workspace

    @abstractmethod
    def run(self, ctx: StageContext, config: WorkspaceConfig, prompts: PromptRegistry) -> StageContext: ...
    def load(self, ctx: StageContext) -> StageContext: ...  # 默认 noop
    def exists(self, ctx: StageContext) -> bool: ...  # 默认 False


# 5 个 Stage 实现
class PaperUnderstandingStage(Stage):
    name = "paper_understanding"
    required_prompts = ["track_a", "track_b", "paper_ingest"]


class CodegenStage(Stage):
    name = "codegen"
    required_prompts = ["code_gen", "react_feedback", "metadata_extract"]


class BacktestStage(Stage):
    name = "backtest"
    required_prompts = ["hypothesis_test", "risk_analyze"]


class PersistFactorStage(Stage):
    name = "persist_factor"
    required_prompts = []  # 不需 LLM


class StrategyStage(Stage):
    name = "strategy"  # 占位
    required_prompts = ["strategy_compose"]


# Registry
class StageRegistry:
    _stages: dict[str, type[Stage]] = {}
    @classmethod
    def register(cls, name: str, stage_cls: type[Stage]): ...
    @classmethod
    def create(cls, name: str, workspace: "Workspace") -> Stage: ...
    @classmethod
    def all_stages(cls) -> list[type[Stage]]: ...
```

**位置**: `pipeline/stages/base.py` (与具体 stages 同包, 不放 common/)
**理由**: ABC 与具体 stage 紧耦合, 放 pipeline/stages/ 方便查找; common/ 只放**与 stage 无关的横切关注点** (config, paths, errors)。

**收益**:
- 5 个 Stage 统一契约 (Section 3.1 详细设计)
- pipeline/ 编排不再 if/elif
- 单元测试 mock 简化
- 新增 stage 自动注册 (Registry 模式)

**成本**: ~150 行代码, Phase 14A + 14D 各 0.5d

#### 30.5.2 🟢 ABC + Strategy for DataSource (Phase 2)

**现有问题**: 3 个数据源签名不一致
- `akshare_data.py`: `fetch_hs300_constituents()` / `fetch_close_panel()`
- `clickhouse_data.py`: `fetch_hs300_constituents()` / `fetch_close_panel()`
- `ifind_data.py`: `fetch_tradability_batch()` / `fetch_ipo_dates()` / ...

```python
# 方案: data_source/base.py
from abc import ABC, abstractmethod
import pandas as pd

class DataSource(ABC):
    name: str
    @abstractmethod
    def fetch_universe(self, date: str) -> list[str]: ...
    @abstractmethod
    def fetch_panel(self, field: str, start: str, end: str) -> pd.DataFrame: ...
    @abstractmethod
    def fetch_tradable_matrix(self, date: str) -> pd.DataFrame: ...

class AkShareDataSource(DataSource):
    name = "akshare"
    def fetch_universe(self, date: str) -> list[str]:
        return fetch_hs300_constituents()  # 内部委托现有函数
```

**收益**:
- 3 数据源统一接口
- router.py 简化
- 新增数据源 (Tushare/JoinQuant) 模板化
- 单元测试 mock 更简单

**成本**: ~200 行代码, Phase 2 (0.5d)

#### 30.5.3 🟢 Enum for SessionStatus (Phase 1)

**现有问题**: `sessions.py:54` 散落字符串
```python
VALID_STATUSES = {"pending", "extracting", "backtesting", "analyzing", "done", "error"}
TERMINAL_STATUSES = {"done", "error"}
```

```python
# 方案: common/enums.py
from enum import Enum

class SessionStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    BACKTESTING = "backtesting"
    ANALYZING = "analyzing"
    DONE = "done"
    ERROR = "error"

    @property
    def is_terminal(self) -> bool:
        return self in {SessionStatus.DONE, SessionStatus.ERROR}

# 配合 dataclass
@dataclass(frozen=True)
class Session:
    status: SessionStatus = SessionStatus.PENDING
```

**收益**:
- 类型安全 (mypy 友好)
- IDE 自动补全
- 状态机可序列化
- 拼写错误编译期发现

**成本**: ~30 行, Phase 1 顺手做

### 30.6 推荐 (4 类)

#### 30.6.1 🟡 Context Manager for Pipeline Run (Phase 14A)

**现有问题**: 21 文件有 with/CM (5 文件) 但无 pipeline 级别

```python
# 方案: pipeline/runner.py
from contextlib import contextmanager
import time

@contextmanager
def pipeline_run(name: str, ctx: PipelineContext):
    start = time.time()
    log.info(f"pipeline {name} start")
    try:
        yield ctx
        log.info(f"pipeline {name} done ({time.time()-start:.1f}s)")
    except Exception as exc:
        log.exception(f"pipeline {name} failed")
        ctx.record_error(exc)
        raise

# 用法
with pipeline_run("alpha-001", ctx) as run:
    for stage in stages:
        run(stage)
```

**收益**: 自动异常捕获 + 时长记录 + 统一入口
**成本**: ~50 行

#### 30.6.2 🟡 Builder for WorkspaceConfig (Phase 14A, planned)

```python
@dataclass
class WorkspaceConfig:
    name: str
    data_source: str
    l5_provider: str
    # ... ~18 字段

class WorkspaceConfigBuilder:
    def with_name(self, name): ...
    def with_data_source(self, name): ...
    def with_l5(self, provider): ...
    def build(self) -> WorkspaceConfig: ...

# 用法
ws = (WorkspaceConfigBuilder()
      .with_name("101_alphas")
      .with_data_source("quantnodes_h5_long")
      .with_l5("minimax")
      .build())
```

**收益**: 可选字段不传 None, 必填字段强制
**成本**: ~80 行

#### 30.6.3 🟡 frozen=True for Config Dataclasses (Phase 1)

**现有问题**: 18 个 @dataclass 全部无 frozen, 可被无意修改

```python
# 现状
@dataclass
class BacktestConfig:
    start: str
    end: str
    universe: str = "HS300"

# 方案
@dataclass(frozen=True)
class BacktestConfig:  # 不可变
    start: str
    end: str
    universe: str = "HS300"
```

**收益**: 防止意外修改, 线程安全, 哈希可用
**成本**: 0 (只改装饰器), 需扫描现有 18 个 @dataclass

#### 30.6.4 🟡 Strategy for FactorCompiler (Phase 5)

**现有问题**: `factor_compiler.py::FactorCompiler` (AST + LLM 多样本 Loop v4) + `factor_compiler_react.py::compile_to_code_react` (ReAct 状态机) 并存, **两个接口不兼容**:

| 维度 | FactorCompiler (AST Loop v4) | compile_to_code_react (ReAct) |
|------|---------------------------|------------------------------|
| 输入 | `formula_brief, llm_client, max_iterations=2, n_samples=3` | `formula_brief, system_prompt, llm, max_repair_rounds=3, df` |
| 输出 | `(code: str, valid: bool, ast: dict, errors: list)` | `ReactResult (steps, is_valid, code, feedback)` |
| LLM 调用 | 多样本 K=3 + 迭代 | 串行 4 轮 ReAct |
| 状态 | 无 (无状态函数) | 有 (ReactState 累积) |

**强行套用 Strategy 模式需要大量适配层** (~200 行而非 60 行), 实际可能得不偿失。

**替代方案** (推荐):

```python
# 方案 A: 不统一接口, 保留两个独立函数 (现状)
# codegen/llm_code.py
def generate_factor_code(formula_brief, df, llm, ...) -> tuple[str, pl.Series, ...]: ...
# codegen/react_engine.py
def compile_to_code_react(formula_brief, system_prompt, llm, max_repair_rounds, df, ...) -> ReactResult: ...

# PipelineRunner 内部根据配置选择
if config.codegen.strategy == "react":
    result = compile_to_code_react(...)
else:  # 默认 "ast" 路径
    code, series, _, _ = generate_factor_code(...)
```

**最终选择**: **不强行 Strategy**, 用**配置切换**。理由:
1. 两接口差异大, 适配层成本 > 收益
2. 实际只用 ReAct 路径 (Loop v4 是已弃用路径)
3. 适配层 = 隐藏实际差异, 增加维护成本
4. Pythonic: 配置选择 > 多态

**实施**: Phase 5 创建 `codegen/strategies.py` 仅作为**选择器**, 不创建统一接口:
```python
# codegen/strategies.py
def select_compiler(config: WorkspaceConfig) -> str:
    """根据 config 返回编译器名, 由 PipelineRunner 决定调哪个函数."""
    return config.codegen.strategy  # "react" / "ast"
```

**收益**:
- 0 适配层代码
- 保持两函数独立
- 配置切换透明

**成本**: ~20 行, Phase 5 顺手做

**若坚持 Strategy 模式**: 预估 200+ 行适配层, Phase 5 0.5d → 1.0d, 不推荐。

### 30.7 不推荐 (4 类)

| 模式 | 原因 |
|------|------|
| **Singleton** | Python module-level globals 已足够, Singleton 是 Java/C++ 思维 |
| **Template Method** | 过度抽象, Python duck typing 更灵活 |
| **Pydantic** | 项目用 dataclass, 新增依赖不值得, 性能差异不大 |
| **Observer (telemetry)** | 当前 logger 够用, 事件总线增加复杂度 |

### 30.8 与 20 阶段 refactor 整合

| Refactor 阶段 | 引入模式 | 优先级 |
|--------------|---------|--------|
| **Phase 1** (common/) | Enum (SessionStatus) + frozen=True + ABC 基类 | 🟢 |
| **Phase 2** (data_source/) | ABC (DataSource) + Strategy (3 impl) | 🟢 |
| **Phase 4** (prompts/) | Registry (PromptTemplate) (planned) | 🟢 |
| **Phase 5** (codegen/) | ABC (CodeValidator) + Strategy (FactorCompiler) | 🟡 |
| **Phase 7** (backtest/) | frozen=True (BacktestConfig) + Builder (Report) | 🟡 |
| **Phase 11** (metadata_extract) | ABC (LLMClient) + Factory 增强 | 🟡 |
| **Phase 14A** (pipeline/ 框架) | ABC (Stage) + Registry + Context Manager + Builder | 🟢 |
| **Phase 14D** (4 stages) | 4 个 Stage ABC 实现 + 自动注册 | 🟢 |
| **Phase 14C** (pipeline/ 业务) | 保留 3 层 ReAct (Chain of Responsibility) | 🟢 |

### 30.9 风险评估

| 风险 | 概率 | 缓解 |
|------|------|------|
| ABC 过度约束 (新需求难加方法) | 中 | 文档化契约, 留出 `*args, **kwargs` 逃生口 |
| Registry 隐式导入 (难调试) | 中 | 注册时显式日志, 启动时打印已注册 stage |
| Enum 兼容 (旧字符串数据迁移) | 中 | `str, Enum` 兼容序列化, dataclass 双向转换 |
| Strategy 模式增加间接性 | 低 | 简单场景不用, 仅复杂切换才用 |
| Builder 字段爆炸 | 低 | 必填字段在 `__post_init__` 校验 |

### 30.10 工作量估算

| 类别 | 数量 | 时间 |
|------|------|------|
| 必用 (🟢) | 3 类 | +1.5d (总 refactor 14d → 15.5d) |
| 推荐 (🟡) | 4 类 | +1.0d (16.5d) |
| 不推荐 | 4 类 | 0d |
| **总计** | **7 类新模式** | **+2.5d** (从 13d → 15.5d) |

**单模式平均成本**:
- ABC: 50-200 行, 0.25-0.5d
- Strategy: 60-150 行, 0.25-0.5d
- Registry: 50-100 行, 0.25d
- Builder: 60-100 行, 0.25-0.4d
- Context Manager: 30-50 行, 0.1-0.2d
- Enum: 20-50 行, 0.1d
- frozen=True: 0 行 (1 行装饰器)

### 30.11 与 13d 单元测试 + 20 阶段总时长

| 项目 | 估算 |
|------|------|
| 20 阶段 refactor | 10d |
| 单元测试 5 阶段 | 13d |
| 7 类新模式集成 | +2.5d (含在 refactor 中, 不增加) |
| **总工作量** | **23d** (refactor + 测试并行) |

注: 模式引入**已经在 20 阶段计划中预留时间**, 不额外增加总时长。

### 30.12 立即可执行 (3 步, 等待用户放行)

按决策 1.a + 4.b (测试先行 + 与 refactor 并行), 立即可做:

1. **Phase 0 单元测试基础设施** (1d) — 不动设计模式
2. **Phase 1 common/** (0.5d) — 引入 Enum + frozen=True + ABC 基类
3. **Stage ABC 接口测试** (0.25d) — 在 Phase 0 加 test_stage_abc.py 占位

### 30.13 7 类模式引入顺序 (推荐)

| 顺序 | 模式 | 阶段 | 风险 |
|------|------|------|------|
| 1 | **Enum** (SessionStatus) | Phase 1 | 极低 |
| 2 | **frozen=True** (Config) | Phase 1 | 极低 |
| 3 | **ABC** (DataSource) | Phase 2 | 中 (有 3 个 impl 需改) |
| 4 | **Strategy** (DataSource 3 impl) | Phase 2 | 中 |
| 5 | **ABC** (Stage) | Phase 14A | 高 (7 子包依赖) |
| 6 | **Registry** (Stage + Prompt) | Phase 14A + 4 | 中 |
| 7 | **Context Manager** (pipeline.run) | Phase 14A | 低 |
| 8 | **Builder** (WorkspaceConfig) | Phase 14A | 中 |
| 9 | **ABC + Strategy** (FactorCompiler) | Phase 5 | 中 |
| 10 | **ABC** (LLMClient) | Phase 11 | 中 |
| 11 | **Builder** (PaperBacktestReport) | Phase 7 | 低 |

### 30.14 与 AGENTS.md 关系

| AGENTS.md 原则 | 强化/补充 |
|----------------|----------|
| 2. Simplicity First | **不推荐 4 类** (避免过度抽象) |
| 3. Surgical Changes | C1 (最小 diff), ABC 强制接口降低长期维护成本 |
| 5. Context First | A4 (读设计文档), Enum/frozen 提供类型安全 |
| 7. Loop Until Done | A2, D5, refactor 时引入模式分批验证 |

### 30.15 修订历史 (本节)

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.4 测试规划版 | 2026-06-23 | 5 阶段, 13 天, ~430 新测试 |
| **v1.5 设计模式版 (当前)** | 2026-06-23 | **7 类模式集成, +2.5d**, 含必用 3 + 推荐 4, 不推荐 4 类已记录理由 |
| v1.6 修复版 | 2026-06-23 | 修复 5 个内部矛盾 + 加部署与运维章节 |

---

# 第七部分: 部署与运维

> Section 31 是 2026-06-23 关于 20 阶段 refactor 实施时的非功能性需求。

## 31. 部署与运维 (1 页)

### 31.1 用户与并发

| 维度 | 本期方案 | 未来 |
|------|---------|------|
| **用户数** | **单用户, 单进程** | 多用户 (Phase 15+) |
| **并发安全** | 写文件用 `tmp + rename` 原子操作 | `Workspace.lock` 文件锁 |
| **多 workspace 并行** | 不支持 (默认串行) | 支持 (Phase 15+) |

**原因**: 本期是 dev/research 阶段, 单用户足够。多用户需求待 Phase 14F2 验证后再评估。

**原子写示例** (各 Stage 产物保存):
```python
def atomic_write(path: Path, content: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.rename(path)  # 原子 rename
```

### 31.2 Secrets 管理

**LLM API key 来源**: 环境变量 `LLMWIKIFY_API_KEY` (必须)

**读取方式**:
```python
api_key = os.environ["LLMWIKIFY_API_KEY"]  # 缺失时 KeyError
base_url = os.environ.get("LLMWIKIFY_BASE_URL", "https://api.minimaxi.com")
```

**优先级**: env (最高) > config.yaml (中) > 硬编码默认 (最低)

**错误处理**: 缺失时**立即 raise**, 不 fallback 到 dummy
```python
if not os.environ.get("LLMWIKIFY_API_KEY"):
    raise EnvironmentError("LLMWIKIFY_API_KEY not set. See docs/setup.md")
```

**git 保护**: `config.yaml` 永远**不含 API key**, 只引用 env var 名字。

### 31.3 性能目标

| 任务 | 目标 | 备注 |
|------|------|------|
| 99 alpha 全量 | **< 2 小时** | 含 LLM 调用 |
| 单 alpha codegen | < 30s | mock LLM |
| 单 alpha backtest | < 60s | QuantNodes PipelineRunner |
| WebUI `/api/health` | < 100ms | FastAPI |

**性能瓶颈**: LLM 响应 (~80% 时间), 不是代码。优化 LLM 调用的 ROI 最高。

### 31.4 成本估算 (脚本, 不进 doc)

**详细估算见**: `scripts/estimate_llm_cost.py` (Phase 0 创建)

**粗估** (minimax M3, ~¥0.001/call):
- 99 alpha × 4 轮 ReAct × 1 LLM call = ~400 calls
- 99 alpha 总成本: **~¥0.4** (可忽略)
- 调试期 (重试): ×3 = ~¥1.2
- 全量回归 (3 轮): ~¥3.6

### 31.5 环境区分

| 环境 | 用途 | LLM | 数据 |
|------|------|-----|------|
| **dev** | 本地开发 | minimax API (env) | sample H5 |
| **prod** | 暂不实现 (Phase 15+) | 待评估 | 待评估 |

本期**只有 dev 环境**, 单一配置。

### 31.6 部署与运维检查清单

- [ ] `LLMWIKIFY_API_KEY` env var 已设置
- [ ] `LLMWIKIFY_BASE_URL` 已设置 (默认 minimax)
- [ ] `quant/factors/<workspace>/` 目录权限可写
- [ ] `~/.llmwikify/akshare_cache/quantnodes_h5_long/` H5 数据存在 (~2GB)
- [ ] 99 alpha 单次跑 < 2h
- [ ] WebUI `/api/health` 200 OK
- [ ] `git status` 无未提交改动 (避免半成品)

---

# 第八部分: 实施总结

> 2026-06-24: 20 阶段 refactor 全部完成.

## 32. 实施总结

### 32.1 完成状态

| Gate | Phase | 状态 | 验证 |
|------|-------|------|------|
| G1 | Phase 3 | ✅ | 91/91 import 兼容性测试 |
| G4 | Phase 12B | ✅ | 16 文件搬迁, 内部 import 全部通过 |
| **G5** | **Phase 14F2** | ✅ | **99/99 alpha e2e, 1313 单元测试** |

### 32.2 最终模块结构

```
reproduction/
├── common/              (7) 基础设施
│   ├── config.py        # 全局配置
│   ├── paths.py         # 路径常量
│   ├── run_id.py        # run ID 生成
│   ├── telemetry.py     # 遥测
│   ├── errors.py        # 错误处理
│   ├── utils.py         # 工具函数
│   └── llm_factory.py   # LLM 客户端工厂
│
├── data_source/         (6) 数据源
│   ├── router.py        # 数据源路由
│   ├── universe.py      # 股票池管理
│   ├── quantnodes_adapter.py  # QuantNodes 适配
│   ├── akshare.py       # AkShare 数据
│   ├── clickhouse.py    # ClickHouse 数据
│   └── ifind.py         # iFinD 数据
│
├── codegen/             (6) 代码生成
│   ├── llm_code.py      # LLM 代码生成
│   ├── react_engine.py  # ReAct 引擎
│   ├── compiler.py      # 代码编译
│   ├── repair.py        # 代码修复
│   ├── semantic.py      # 语义分析
│   ├── metadata.py      # 元数据提取
│   └── ast/             (4) AST 处理
│       ├── compiler.py  # AST 编译器
│       ├── nodes.py     # AST 节点
│       ├── complexity.py # 复杂度分析
│       └── extractor.py # 代码提取
│
├── prompts/             (6) Prompt 系统
│   ├── group.py         # Prompt 分组
│   ├── registry.py      # Prompt 注册
│   ├── loader.py        # Prompt 加载
│   ├── renderer.py      # Prompt 渲染
│   ├── store.py         # Prompt 存储
│   └── builtin/         (9) 内置模板
│       ├── code_gen/v1.yaml, v2.yaml
│       ├── react_feedback/v1.yaml
│       ├── metadata_extract/v1.yaml, v2.yaml
│       ├── track_a/v1.yaml
│       ├── track_b/v1.yaml
│       ├── hypothesis_test/v1.yaml
│       └── risk_analyze/v1.yaml
│
├── backtest_pkg/        (8) 回测
│   ├── factor_backtest.py
│   ├── run_backtest.py
│   ├── metrics.py
│   ├── strategies.py
│   ├── l5_validation.py
│   ├── l5_orchestrator.py
│   ├── factor_value_store.py
│   └── quantnodes_repro.py
│
├── persist/             (3) 持久化
│   ├── factor_library.py
│   ├── sessions.py
│   └── run.py
│
├── paper_understanding/ (6) 论文理解
│   ├── extract_paper.py
│   ├── extract_factors.py
│   ├── extract_strategy.py
│   ├── quant_wiki.py
│   ├── schemas.py
│   ├── contracts.py
│   └── llm_extraction/  (15) LLM 提取
│       ├── orchestrator.py
│       ├── planner.py
│       ├── track_a.py
│       ├── track_b.py
│       ├── validator.py
│       └── ... (11 more)
│
└── pipeline/            (5) 流水线框架
    ├── config.py        # WorkspaceConfig
    ├── runner.py        # PipelineRunner
    ├── workspace.py     # Workspace 管理
    ├── react.py         # FailureClassifier + PipelineReAct
    ├── stages/          (5) Stage 实现
    │   ├── base.py      # Stage 抽象基类
    │   ├── paper_understanding.py
    │   ├── codegen.py
    │   ├── backtest.py
    │   └── persist_factor.py
    ├── data_loader.py   # 数据加载
    ├── backtest_config.py # 回测配置
    ├── backtest_extract.py # 回测结果提取
    ├── score.py         # 评分计算
    ├── persist.py       # 持久化
    ├── factor_fix.py    # 因子修复
    └── quantnodes_patch.py # QuantNodes 修复
```

### 32.3 Commits 记录

| Phase | Commit | 说明 |
|-------|--------|------|
| 1 | `936e1cb` | common/ 基础设施 |
| 2 | `e5f335f` | data_source/ 数据源 |
| 3 | `e2fc83d` | PEP 562 兼容层 [G1] |
| 4 | `b48091b` | prompts/ 骨架 |
| 5 | `02edc11` | codegen/ 主包 |
| 6 | `e7ae49b` | codegen/ast/ 子包 |
| 7 | `dccd381` | backtest_pkg/ 子包 |
| 8 | `b10cd86` | persist/ 子包 |
| 9 | `c4a9f62` | prompts/builtin/ 核心 |
| 10 | `65ace89` | codegen/ 接入 PromptRegistry |
| 11 | `2582b0b` | metadata_extract + 接入 |
| 12A | `ea6dfef` | paper_understanding/ |
| 12B | `21a54df` | llm_extraction/ 搬入 [G4] |
| 13 | `ef8b145` | prompts/builtin/ 边缘 |
| 14A-B | `7588f59` | pipeline/ 框架 + ReAct |
| 14C-E | `9bd79b4` | 业务模块 + Stage + CLI |
| 14F1 | `5a4742d` | import 修复 + 5 alpha e2e |

### 32.4 测试统计

| 类型 | 数量 | 说明 |
|------|------|------|
| 单元测试 | 1313 passed | 0 failed, 13 skipped |
| E2E (5 alpha) | 5/5 | avg ICIR=0.0507 |
| E2E (99 alpha) | 99/99 | 全部完成 |
| 测试文件 | 89+ | 覆盖所有子包 |

### 32.5 Gate 验证结果

**G1 [Phase 3] - Import 兼容性**:
- 33 项 import 路径测试全部通过
- 旧路径 `reproduction.X` 自动重定向到新子包
- 无破坏性变更

**G4 [Phase 12B] - 内部搬迁**:
- llm_extraction/ 16 文件全部搬迁
- 内部 import 使用 `...X` (3 层相对路径)
- 所有内部测试通过

**G5 [Phase 14F2] - 全量验证**:
- 99 alpha 全部完成 LLM 代码生成 + 回测 + 持久化
- 因子目录数量不变 (99)
- 无回归 (1313 单元测试全过)

### 32.6 下一步

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | `git push` | 推送到远端 |
| P0 | 创建 PR | refactor/pass2-config-v4 → main |
| P1 | 代码审查 | 检查每个 commit |
| P2 | 文档更新 | 更新 README.md |
| P3 | 清理旧文件 | 删除 scripts/test_one_factor_llm_code.py |

---

**文档完成**. 涵盖 101 alpha 端到端设计 + 4 层架构 + prompts/ 子系统 + 三层 ReAct + 7 子包拆分 + 20 阶段实施计划 + 单元测试纪律 + 5 个 Gate 验证 + 风险评估 + 决策记录 + AI 执行原则 + 单元测试完整规划 + Python 设计模式集成 + 部署与运维 + 实施总结.

**下一步**: 见 [workflow-pipeline-separation.md](workflow-pipeline-separation.md) — pipeline (通用工具) + workflow (任务编排) + paper.py (HTTP 薄包装) 三层分离设计.
