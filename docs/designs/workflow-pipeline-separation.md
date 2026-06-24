# Workflow-Pipeline 分离设计文档

> 最后更新: 2026-06-24
> 状态: 设计确认，待实施

## 1. 设计目标

将 `paper.py` 中混合的 HTTP + 提取 + 回测 + 持久化逻辑拆分为三层：

| 层 | 模块 | 职责 |
|----|------|------|
| L1 | `pipeline/` | 通用工具箱：无状态函数，不管谁调用 |
| L2 | `workflow.py` | 任务编排：论文→因子，调用 pipeline 工具 |
| L3 | `paper.py` | HTTP 薄包装：只管 DB 会话 + 端点 + 前端轮询 |

**核心原则**：
- pipeline/ 是纯函数，不关心数据从哪来
- workflow.py 只做编排，不实现具体工具
- paper.py 不包含业务逻辑

## 2. 架构总览

```
┌──────────────┐      ┌──────────────────┐      ┌──────────────┐
│   paper.py   │─────▶│  workflow.py     │─────▶│  pipeline/   │
│   (HTTP)     │      │  UnifiedWorkflow │      │  (工具集)    │
│              │      │                  │      │              │
│ 管 DB 会话    │      │ _stage1() ───────────▶ orchestrator   │
│ 管 HTTP 端点  │      │ _stage2() ───────────▶ react_engine  │
│ 管前端轮询    │      │ _stage3() ───────────▶ persist       │
│              │      │ _stage4() ───────────▶ backtest_*    │
│              │      │                  │      │ data_loader  │
│              │      │ return Result    │      │ quantnodes_  │
└──────────────┘      └──────────────────┘      │ patch        │
                              │                 └──────────────┘
                              ▼
                      ┌──────────────────┐
                      │  CLI 入口         │
                      │  python -m       │
                      │  pipeline        │
                      └──────────────────┘
```

### 2.1 调用链

```
用户 POST /api/paper/start
  → paper.py: DB.create_session()
  → asyncio.create_task(_run_paper_extraction())
    → workflow.py: UnifiedWorkflow(config).run()
      → Stage 1: orchestrator.run_track_b()     ← paper_understanding/
      → Stage 2: react_engine.compile_to_code()  ← codegen/
      → Stage 3: persist.write_factor_yaml()     ← pipeline/persist.py
      → Stage 4: PipelineRunner.run()            ← QuantNodes
    → return WorkflowResult
  → paper.py: DB.create_artifact() + DB.record_event()
  → 前端 GET /api/paper/{sid}/status 轮询
```

## 3. pipeline/ — 通用工具箱

### 3.1 现有工具（已完成迁移）

| 文件 | 函数 | 用途 |
|------|------|------|
| `data_loader.py` | `wide_from_long()` | Polars 长表 → Pandas 宽表 |
| `data_loader.py` | `write_factor_h5()` | 写 QuantNodes H5 文件 |
| `data_loader.py` | `derive_input_columns()` | 从公式提取输入列名 |
| `backtest_config.py` | `build_qn_config()` | 构建 PipelineRunner 配置 |
| `backtest_extract.py` | `extract_full_backtest_from_ctx()` | 从 QN ctx 提取 IC/分层/多空 |
| `backtest_extract.py` | `safe_float()` | 安全类型转换 |
| `score.py` | `compute_score()` | ICIR + 胜率 → 0-100 分 |
| `score.py` | `compute_status()` | ICIR → 状态字符串 |
| `persist.py` | `persist_code_to_yaml()` | 写 6 层因子 YAML |
| `persist.py` | `save_backtest_to_db()` | 回测结果入 SQLite |
| `quantnodes_patch.py` | `patch_sample_pool_filter()` | QN bug workaround |
| `react.py` | `PipelineReAct` | 失败恢复引擎 |
| `factor_fix.py` | `detect_binary()` / `add_noise()` | 退化因子修复 |

### 3.2 本次需要接线的工具（在 workflow.py 中调用）

| 来源模块 | 函数 | 调用位置 |
|----------|------|----------|
| `paper_understanding/llm_extraction/orchestrator.py` | `run_one_paper()` | Stage 1 |
| `paper_understanding/llm_extraction/track_b.py` | `run_track_b()` | Stage 1 |
| `paper_understanding/llm_extraction/planner.py` | `plan_paper()` | Stage 1 |
| `paper_understanding/llm_extraction/section_detector.py` | `detect_sections()` | Stage 1 |
| `paper_understanding/extract_paper.py` | `_fetch_content()` | Stage 1 |
| `codegen/react_engine.py` | `compile_to_code_react()` | Stage 2 |
| `codegen/llm_code.py` | `execute_code()` | Stage 2 |
| `codegen/llm_code.py` | `SYSTEM_PROMPT_CODE` | Stage 2 |
| `data_source/router.py` | `DataRouter.get()` | Stage 2/4 |

### 3.3 不需要迁移的模块

| 模块 | 原因 |
|------|------|
| `codegen/react_engine.py` | 保持原位，workflow.py 直接 import |
| `codegen/llm_code.py` | 保持原位，workflow.py 直接 import |
| `paper_understanding/llm_extraction/` | 保持原位，workflow.py 直接 import |
| `data_source/router.py` | 保持原位，workflow.py 直接 import |

**关键决策：不迁移代码，只接线。** 现有模块位置不变，workflow.py 通过 import 调用。

## 4. workflow.py — 任务编排

### 4.1 数据结构

```python
@dataclass
class WorkflowConfig:
    """流水线配置"""
    paper_id: str
    source_type: str              # pdf / url / raw
    source_ref: str
    paper_content: str = ""
    # 回测参数
    symbol: str = "000300.SH"
    start_date: str = "2023-01-01"
    end_date: str = "2025-12-31"
    # LLM
    llm_client: Any = None
    # 控制
    use_react: bool = True
    skip_codegen: bool = False
    skip_backtest: bool = False

@dataclass
class WorkflowResult:
    """流水线结果"""
    paper_id: str
    success: bool
    # Stage 1
    n_signals: int = 0
    pass2_details: list[dict]     # SignalDetail.to_dict() 列表
    # Stage 2
    n_coded: int = 0
    code_results: list[dict]      # [{name, code, formula_brief}]
    # Stage 3
    written_factors: list[str]    # factor slug 列表
    # Stage 4
    backtest_results: list[dict]  # [{name, ic_mean, icir, ...}]
    # 元数据
    total_latency_ms: int = 0
    llm_calls: int = 0
    error: str | None = None
```

### 4.2 类结构

```python
class UnifiedWorkflow:
    """论文→因子 完整流水线: 提取(B) → 代码生成(C) → 持久化 → 回测(C)"""

    def __init__(self, config: WorkflowConfig): ...

    def run(self) -> WorkflowResult:
        """执行完整流水线"""
        t0 = time.monotonic()
        try:
            self._stage1_extraction()
            if not self.config.skip_codegen:
                self._stage2_codegen()
            self._stage3_persist()
            if not self.config.skip_backtest:
                self._stage4_backtest()
            self.result.success = True
        except Exception as exc:
            self.result.error = str(exc)
        self.result.total_latency_ms = int((time.monotonic() - t0) * 1000)
        return self.result

    def load_checkpoint(self, path: str) -> None:
        """从 track_b_checkpoint.json 加载, 跳过 Stage 1"""

    def _fetch_content(self) -> str:
        """读取 PDF/URL/raw 文件内容"""

    def _load_market_data(self) -> pl.DataFrame:
        """加载行情数据为 Polars DataFrame"""

    def _stage1_extraction(self) -> None:
        """Flow B: 多阶段 LLM 提取"""

    def _stage2_codegen(self) -> None:
        """Flow C: ReAct 代码生成"""

    def _stage3_persist(self) -> None:
        """写 YAML 因子定义"""

    def _stage4_backtest(self) -> None:
        """Flow C: QuantNodes PipelineRunner 回测"""
```

### 4.3 Stage 实现细节

#### Stage 1: `_stage1_extraction()`

**调用链**:
```
_fetch_content()
  → detect_sections(paper_id, content, llm_client)
  → plan_paper(paper_id, title, content, sections, llm_client)
  → run_track_b(paper_id, plan, content, sections, llm_client)
  → TrackBResult.pass2_details[]
```

**输入**: PDF/URL/raw 文件 → paper_content 字符串
**输出**: `result.pass2_details[]` = [{name, formula_brief, l1, l2, l3, l4, success}]

**依赖**:
- `paper_understanding/extract_paper.py:_fetch_content()` — 读取文件
- `paper_understanding/llm_extraction/section_detector.py:detect_sections()` — LLM 章节检测
- `paper_understanding/llm_extraction/planner.py:plan_paper()` — LLM 规划
- `paper_understanding/llm_extraction/track_b.py:run_track_b()` — 多阶段提取

#### Stage 2: `_stage2_codegen()`

**调用链**:
```
DataRouter.get(symbol, start, end) → df_pd
pl.from_pandas(df_pd) → df_pl
FOR EACH detail in pass2_details:
  compile_to_code_react(name, formula_brief, SYSTEM_PROMPT_CODE, df=df_pl, llm=client)
  → ReactResult.code + execute_code(code, df_pl) → series
  → code_results.append({name, code, formula_brief})
```

**输入**: `result.pass2_details[]` + 行情数据
**输出**: `result.code_results[]` = [{name, code, formula_brief}]

**依赖**:
- `codegen/react_engine.py:compile_to_code_react()` — ReAct 代码生成
- `codegen/llm_code.py:execute_code()` — 执行生成的代码
- `codegen/llm_code.py:SYSTEM_PROMPT_CODE` — 系统提示词
- `data_source/router.py:DataRouter.get()` — 行情数据

#### Stage 3: `_stage3_persist()`

**调用链**:
```
FOR EACH detail in pass2_details:
  _track_b_to_factor(detail, paper_id) → factor_data
  注入 code (如果有)
  write_factor_yaml(factor_data["name"], factor_data)
  → written_factors.append(slug)
```

**输入**: `result.pass2_details[]` + `result.code_results[]`
**输出**: `result.written_factors[]` = [slug, slug, ...]

**依赖**:
- `pipeline/persist.py:write_factor_yaml()` — 写 YAML 文件
- 内部适配器 `_track_b_to_factor()` — SignalDetail → YAML 格式

#### Stage 4: `_stage4_backtest()`

**调用链**:
```
patch_sample_pool_filter()
FOR EACH code_result:
  execute_code(code, df_pl) → series
  wide_from_long(df_pl, series) → wide
  write_factor_h5(wide, name) → h5_path
  build_qn_config(name, h5_path, code) → config
  PipelineRunner.from_dict(config).run() → ctx
  extract_full_backtest_from_ctx(ctx) → backtest
  persist_code_to_yaml(name, code, formula_brief, backtest, h5_path, code_chars)
  save_backtest_to_db(slug, alpha_index, backtest)
  → backtest_results.append({name, ...})
```

**输入**: `result.code_results[]` + 行情数据
**输出**: `result.backtest_results[]` = [{name, ic_mean, icir, ...}]

**依赖**:
- `pipeline/quantnodes_patch.py:patch_sample_pool_filter()` — QN bug 修复
- `pipeline/data_loader.py:wide_from_long()` — 数据格式转换
- `pipeline/data_loader.py:write_factor_h5()` — 写 H5 文件
- `pipeline/backtest_config.py:build_qn_config()` — 构建配置
- `QuantNodes.PipelineRunner` — 回测执行
- `pipeline/backtest_extract.py:extract_full_backtest_from_ctx()` — 提取指标
- `pipeline/persist.py:persist_code_to_yaml()` — 写回 YAML
- `pipeline/persist.py:save_backtest_to_db()` — 入库

### 4.4 适配器函数

```python
def _track_b_to_factor(detail: dict, paper_id: str) -> dict:
    """SignalDetail.to_dict() → write_factor_yaml 兼容格式"""
    from ..common.utils import generate_slug
    slug = generate_slug(detail["name"])
    return {
        "name": slug,
        "factor": {
            "name": slug,
            "name_cn": (detail.get("description") or detail["name"])[:50],
            "asset_type": "stock",
            "category": "alpha",
            "subcategory": "paper_derived",
            "version": 1,
            "source_paper": paper_id,
            "status": "draft",
            "l1": detail.get("l1", {}),
            "l2": detail.get("l2", {}),
            "l3": detail.get("l3", {}),
            "l4": detail.get("l4", {}),
        },
    }
```

## 5. paper.py — HTTP 薄包装

### 5.1 删除的代码

| 代码块 | 行数 | 说明 |
|--------|------|------|
| `_extract_factor_from_page()` | 41-199 | 单因子 legacy 函数 |
| `_run_paper_extraction()` 内部逻辑 | 286-651 | 提取+回测逻辑 |

### 5.2 重写的 `_run_paper_extraction()`

```python
async def _run_paper_extraction(
    session_id, paper_id, source_type, source_ref,
    paper_content, wiki_id, symbol, start_date, end_date,
) -> None:
    """Background task: 调用 UnifiedWorkflow"""
    from llmwikify.reproduction.pipeline.workflow import (
        UnifiedWorkflow, WorkflowConfig,
    )
    try:
        _DB.update_status(session_id, "extracting")
        config = WorkflowConfig(
            paper_id=paper_id, source_type=source_type,
            source_ref=source_ref, paper_content=paper_content,
            symbol=symbol, start_date=start_date, end_date=end_date,
            llm_client=_LLM_CLIENT,
        )
        workflow = UnifiedWorkflow(config)
        result = await asyncio.to_thread(workflow.run)
        # DB 更新
        for name in result.written_factors:
            _DB.create_artifact(session_id, kind="Factor", wiki_page=f"factor-{name}")
        _DB.record_event(session_id, "backtest.done", results=result.backtest_results)
        _DB.update_status(session_id, "done" if result.success else "error")
    except Exception as exc:
        _DB.update_status(session_id, "error", error=str(exc))
```

### 5.3 保留不变的端点

| 端点 | 说明 |
|------|------|
| `POST /api/paper/start` | 启动提取 |
| `GET /api/paper/list` | 列出会话 |
| `GET /api/paper/list-raw` | 列出 PDF 文件 |
| `POST /api/paper/upload` | 上传 PDF |
| `GET /api/paper/{sid}/status` | 前端轮询 |
| `GET /api/paper/{paper_id}` | Legacy 端点 |
| `GET /api/paper/{paper_id}/artifacts` | Legacy 端点 |
| `DELETE /api/paper/{sid}` | 删除会话 |

## 6. CLI 入口

```bash
# 完整流水线
python -m llmwikify.reproduction.pipeline \
    --paper-id 101_alphas_minimal \
    --source-type raw \
    --source-ref 101_alphas_minimal.pdf

# 从 checkpoint 运行 (跳过提取)
python -m llmwikify.reproduction.pipeline \
    --paper-id 101_alphas_minimal \
    --checkpoint quant/papers/101_alphas_minimal/track_b_checkpoint.json

# 只提取不回测
python -m llmwikify.reproduction.pipeline \
    --paper-id 101_alphas_minimal \
    --source-type raw \
    --source-ref 101_alphas_minimal.pdf \
    --skip-backtest
```

## 7. 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `pipeline/workflow.py` | **新增** | UnifiedWorkflow 核心类 (~250行) |
| `pipeline/cli/__main__.py` | **重写** | CLI 独立入口 (~60行) |
| `interfaces/server/http/paper.py` | **重构** | 改为调用 UnifiedWorkflow (-400, +50行) |
| `paper_understanding/extract_paper.py` | **删除** | 被 Flow B 替代 |
| `paper_understanding/extract_factors.py` | **删除** | 无生产代码引用 |
| `tests/reproduction/test_extract_paper.py` | **迁移** | 用例迁移到 test_workflow.py |
| `tests/reproduction/test_multi_factor_extraction.py` | **迁移** | 用例迁移到 test_workflow.py |
| `tests/reproduction/test_extract_factors.py` | **迁移** | 用例迁移到 test_workflow.py |
| `tests/test_workflow.py` | **新增** | workflow 单元测试 |

## 8. 执行步骤

| 步骤 | 内容 | 验证 |
|------|------|------|
| 1 | 新增 `pipeline/workflow.py` | 单元测试通过 |
| 2 | 重写 `pipeline/cli/__main__.py` | `--help` 输出正常 |
| 3 | 重构 `paper.py` | HTTP 端点正常 |
| 4 | 迁移测试 → `tests/test_workflow.py` | 所有测试通过 |
| 5 | 删除 `extract_paper.py` + `extract_factors.py` | import 检查通过 |
| 6 | 删除旧测试文件 | 测试全过 |
| 7 | 回归测试 `pytest tests/ -x -q` | 无新增失败 |

## 9. 风险评估

| 风险 | 缓解 |
|------|------|
| Flow B LLM 调用次数多，速度慢 | 保留 async，后台执行 |
| Flow C 代码生成可能失败 | 保留 fallback 到 formula |
| QuantNodes bug | 保留 `patch_sample_pool_filter()` |
| 测试迁移遗漏 | 逐个对比测试用例 |
| extract_paper.py 删除后 import 断裂 | paper.py 重构后不再依赖 |
