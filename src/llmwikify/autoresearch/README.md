# AutoResearch: 6 步逻辑框架研究引擎

> 独立顶级子项目 — 概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单

![Tests](https://img.shields.io/badge/tests-89%20passing-brightgreen)
![Independent DB](https://img.shields.io/badge/DB-autoresearch.db-blue)
![Zero Coupling](https://img.shields.io/badge/coupling-zero%20to%20research-success)
![Python](https://img.shields.io/badge/python-3.10+-blue)

---

## 目录

- [概览](#概览)
- [6 步框架](#6-步框架)
- [8 门禁（4 基础 + 4 六步）](#8-门禁4-基础--4-六步)
- [数据存储](#数据存储)
- [快速开始](#快速开始)
- [使用方式](#使用方式)
- [配置参考](#配置参考)
- [公开 API](#公开-api)
- [重试机制](#重试机制)
- [与 research 的区别](#与-research-的区别)
- [文件结构](#文件结构)
- [测试](#测试)
- [设计文档](#设计文档)
- [License](#license)

---

## 概览

**AutoResearch** 是 llmwikify 的一个**独立顶级子项目**，集成了结构化推理的 6 步逻辑框架（基于 TradingAgent 等多 Agent 框架的架构思想，但完全独立实现）。它将传统的「ReAct 循环」升级为「6 步框架 + ReAct」的混合范式：

- **第 1 步（概念澄清）**：在研究开始前明确研究边界、前提、视角
- **第 2 步（建立依据）**：评估每个 source 的证据质量（不只看长度/域名，加入可追溯性 + 权威性维度）
- **第 3 步（推理严密）**：综合后用 6 维评分卡（结论-证据对齐 / 逻辑矛盾 / 因果覆盖 / 前提-证据对齐 / 假设显式性 / 不确定性量化）检查推理链
- **第 4 步（稳固结构）**：报告完成后用 3 层评分（层级支撑 / 章节完整性 / 内部一致性）验证结构
- **第 5 步（结论输出）**：报告生成时自动注入 6 步框架上下文（不再孤立）
- **第 6 步（检查清单）**：reviewing 阶段自动跑 `framework_compliance` 门禁

**关键设计决策**（已确认）：

| 决策 | 内容 |
|------|------|
| **独立顶级** | `src/llmwikify/autoresearch/` 与 `strategy/` 并列，不是 `agent.backend.research.*` 的子目录 |
| **零耦合** | 不 import `llmwikify.agent.backend.research.*` 任何符号 |
| **独立 DB** | `~/.llmwikify/agent/autoresearch.db`（不共享 `.llmwiki_agent.db`） |
| **6 步字段内置** | 6 步 JSON 字段（clarification / reasoning / structure / self_loop_* / evidence_scores）在 schema 创建时内置，不通过 `ALTER TABLE` |
| **旧数据不迁移** | 提供可选 `migrate_research_six_step_columns()` 工具，**不**自动迁移 |
| **公开 API 同形** | `create_research_session` / `get_research_session` / `save_sub_query` / `save_source` 等方法名与旧 DB 兼容 |
| **自我循环必启用** | 自我循环无关闭开关（仅限关键步骤：clarify + evidence），最多重试 2 次，占 30% 预算 |
| **门禁失败行为** | 6 步门禁失败 → 强制返回 plan 重新规划（受 `_max_replan=2` 限制） |

---

## 6 步框架

```
概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单
   │          │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼          ▼
clarifier  SourceFilter  ReasoningChecker  StructureValidator  ReportGenerator  framework
.py        .compute_evidence_score  (6 维)  (3 层)        + 6 步 system 注入  _compliance
```

### Step 1 — 概念澄清（ResearchClarifier）

**目的**：在研究开始前明确研究边界、前提、视角，避免无目的检索。

**实现**：`src/llmwikify/autoresearch/clarifier.py:ResearchClarifier`

**输入**：研究 query

**输出**（`state.clarification`）：
```json
{
  "context": "研究主题'X'指... 适用范围是..., 边界条件是...",
  "boundaries": "利益相关方: A, B, C; 假设: ...",
  "position": "研究者视角 / 实践者视角 / 决策者视角",
  "premises": ["前提1", "前提2", "..."],
  "scope_check": true
}
```

**自我循环**：最多 2 次重试，最多占用 30% 预算。失败时使用 fallback（context="未澄清..."，scope_check=true 不强制）。

### Step 2 — 建立依据（SourceFilter.compute_evidence_score）

**目的**：评估每个 source 的证据质量，**超越传统长度/域名检查**。

**实现**：`src/llmwikify/autoresearch/source_filter.py:SourceFilter`

**评分维度**（0.0-1.0）：

| 维度 | 含义 | 信号 |
|------|------|------|
| **length** | 内容长度 | `len(content)` |
| **domain** | 域名权威性 | arxiv.org / ieee.org / nature.com 加分，spammy 减分 |
| **traceability** | 可追溯性 | URL 完整 / 有 author / 有 DOI / 有 arxiv ID |
| **authority** | 权威性 | source_type=arxiv/pdf/wiki 强信号，youtube 弱信号 |
| **type_consistency** | 类型一致性 | 与声明的 source_type 匹配 |

**使用**：
```python
sf = SourceFilter(config)
score = sf.compute_evidence_score({
    "url": "https://arxiv.org/abs/2401.00001",
    "title": "Attention Is All You Need",
    "author": "Vaswani et al.",
    "source_type": "arxiv",
    "content": "..." * 2000,
})
# → 0.85 (高质量)
```

### Step 3 — 推理严密（ReasoningChecker）

**目的**：综合后用 **6 维评分卡**检查推理链。

**实现**：`src/llmwikify/autoresearch/reasoning_checker.py:ReasoningChecker`

**6 维度**（每维 0.0-1.0）：

| # | 维度 | 检查内容 |
|---|------|---------|
| 1 | **conclusion_evidence_alignment** | 每个结论是否引用证据？ |
| 2 | **logical_contradiction** | 是否有互斥主张？ |
| 3 | **causal_coverage** | 是否解释 cause→effect？ |
| 4 | **premise_evidence_alignment** | 声明的前提是否有支撑？ |
| 5 | **assumption_visibility** | 未声明假设是否显式标注？ |
| 6 | **uncertainty_quantification** | 不确定性是否量化？ |

**输出**：
```python
{
  "aggregate_score": 0.65,           # 6 维平均
  "scores": {"conclusion_evidence_alignment": 0.8, ...},
  "issues": [
    {"dimension": "causal_coverage", "severity": "info", "message": "未检测到因果连接词"},
    ...
  ],
  "method": "rule_based"             # 或 "llm_judge" (future)
}
```

### Step 4 — 稳固结构（StructureValidator）

**目的**：报告完成后用 **3 层评分**验证结构。

**实现**：`src/llmwikify/autoresearch/structure_validator.py:StructureValidator`

**3 维度**：

| # | 层 | 检查内容 |
|---|------|---------|
| 1 | **hierarchical_support** | 顶层声明是否有 ≥2 子声明支撑？子声明是否有 ≥1 证据引用？ |
| 2 | **section_completeness** | 必含章节（背景 / 分析 / 证据 / 结论）是否齐全？ |
| 3 | **internal_consistency** | 关键术语是否在多段重复出现？ |

**4 期望章节**（多语言）：`# Background / # Analysis / # Evidence / # Conclusion`

### Step 5 — 结论输出（ReportGenerator + 6 步 system 注入）

**目的**：报告生成时自动注入 6 步框架上下文，使 LLM 在写报告时"知道"前 4 步的产出。

**实现**：`src/llmwikify/autoresearch/report.py:ReportGenerator`

**`six_step_context` 构造**（`engine.py:_build_six_step_context`）：
```python
{
  "clarification": state.clarification,
  "reasoning_check": state.reasoning_check,   # Step 3 结果
  "structure_check": state.structure_check,   # Step 4 结果（写入后立即可用）
  "evidence_scores": dict(state.evidence_scores),  # Step 2 结果
}
```

**渲染**：`_render_framework_block()` 在 system prompt 中追加：
```
# 6-step Framework Guidance (this report should reflect all 6 steps)
- Clarification: ... (context, boundaries, position, premises)
- Evidence: 12 sources scored; avg 0.65; min 0.32; max 0.92
- Reasoning: aggregate 0.65, 2 issues to address
- Structure: aggregate 0.72, 1 issue to address
```

**Reviewer 同理**：`ResearchReviewer.review()` 也接收 `six_step_context`。

### Step 6 — 检查清单（framework_compliance gate）

**目的**：在 reviewing 阶段检查前 3 步（clarification / reasoning / structure）是否全部产出，**任一缺失** → 报告"框架不完整"，建议 `replan_framework`。

**实现**：`src/llmwikify/autoresearch/quality_gate.py:check_framework_compliance`

**逻辑**：
```python
issues = []
if not clarification or not clarification.get("context"):
    issues.append("missing clarification step 1 output")
if not reasoning_check or reasoning_check.get("aggregate_score", 0) == 0:
    issues.append("missing reasoning step 3 check")
if not structure_check or structure_check.get("aggregate_score", 0) == 0:
    issues.append("missing structure step 4 check")
passed = len(issues) == 0
```

---

## 8 门禁（4 基础 + 4 六步）

引擎在 4 个 phase 各调 1 个**基础门禁** + 1 个**六步门禁**（叠加，任一失败 → 触发 replan）。

| 阶段 | 基础门禁 | 六步门禁 | 守门 |
|------|---------|---------|------|
| `gathering` | `check_after_gathering`（数量/多样性/长内容） | `check_evidence_quality`（evidence_score 平均） | `evidence_scoring_enabled` |
| `analyzing` | `check_after_analysis`（credibility） | — | — |
| `synthesizing` | `check_after_synthesis`（reinforced_claims/gaps） | `check_reasoning_quality`（6 维 aggregate） | `reasoning_check_enabled` |
| `reporting` | `check_before_report`（synthesis + sources） | `check_structure_quality`（3 层 aggregate） | `structure_check_enabled` |
| `reviewing` | — | `check_framework_compliance`（3 步齐全） | `framework_check_enabled` |

**6 步门禁失败** → 优先级 > 基础门禁失败 → 引擎进入 plan 重规划（受 `max_replan_attempts=2` 限制）。

**自我循环超限** → 用最后结果 + 警告（不强制终止，per 设计约束）。

---

## 数据存储

### 独立数据库

`~/.llmwikify/agent/autoresearch.db`（与 `.llmwiki_agent.db` 同级，**零共享**）

### 3 张表

```sql
-- Session 表（含 6 步 JSON 字段）
CREATE TABLE autoresearch_sessions (
  id TEXT PRIMARY KEY,
  wiki_id TEXT,
  query TEXT,
  status TEXT DEFAULT 'clarifying',  -- v5 默认值（v4 之前是 'planning'）
  current_step TEXT,
  progress REAL,
  result TEXT,
  wiki_page_name TEXT,
  iteration_round INTEGER,
  synthesis_json TEXT,        -- 基础
  review_json TEXT,            -- 基础
  -- 6 步字段（v4 内置）
  clarification_json TEXT,
  reasoning_json TEXT,
  structure_json TEXT,
  self_loop_counts_json TEXT,
  self_loop_history_json TEXT,
  evidence_scores_json TEXT,   -- dict[source_id, float]
  created_at TEXT,
  updated_at TEXT
);

-- Sub-queries
CREATE TABLE autoresearch_sub_queries (...);

-- Sources
CREATE TABLE autoresearch_sources (...);
```

**零共享验证**：
- `autoresearch.db` 不含 `research_sessions` 表
- `.llmwiki_agent.db` 不被 autoresearch 写入
- 启动日志显示两条独立 DB 路径

### 旧数据迁移（可选）

如曾运行过 v1-v3 共享 DB 模式的 autoresearch，可手动清理：

```python
from llmwikify.autoresearch.db_migrations import migrate_research_six_step_columns

count = migrate_research_six_step_columns(
    old_db_path=Path("~/.llmwikify/agent/.llmwiki_agent.db"),
    drop_columns=True,  # False = dry-run
)
# count: 实际删除的列数（0-3：clarification_json / reasoning_json / structure_json）
```

CLI 等价：
```bash
python scripts/migrate_autoresearch_v3_to_v4.py --dry-run  # 检查
python scripts/migrate_autoresearch_v3_to_v4.py --apply    # 执行
```

---

## 快速开始

### 安装

无需额外安装 — 已随 llmwikify 一起安装。

### 启动 server

```bash
# 默认端口
llmwikify serve --web --port 8765 --host 0.0.0.0

# 启动日志应包含：
# AutoResearch database: /home/xxx/.llmwikify/agent/autoresearch.db
# Agent database:       /home/xxx/.llmwikify/agent/.llmwiki_agent.db
```

### 配置 wiki

确保 `~/.llmwikify/llmwikify.json` 中有 wiki 配置。

### 第一次研究

```bash
curl -X POST http://127.0.0.1:8765/api/autoresearch/start \
  -H "Content-Type: application/json" \
  -d '{"query": "2024 年 LLM 推理优化最新进展", "wiki_id": "default"}'

# → {"session_id": "b1aeb31b-...", "status": "running"}
```

实时事件流：

```bash
curl -N http://127.0.0.1:8765/api/autoresearch/b1aeb31b-.../stream
```

查看结果：

```bash
curl http://127.0.0.1:8765/api/autoresearch/b1aeb31b-.../
```

---

## 使用方式

### 方式 1：HTTP API

8 个端点（`/api/autoresearch/*`）：

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/start` | 启动新 session（query + 可选 wiki_id） |
| `GET` | `/{sid}/stream` | SSE 实时事件流 |
| `GET` | `/list` | 列出所有 session（可按 wiki 过滤） |
| `GET` | `/{sid}` | 完整 session 详情（含 6 步字段） |
| `GET` | `/{sid}/clarification` | 仅概念澄清结果 |
| `POST` | `/{sid}/pause` | 暂停 |
| `POST` | `/{sid}/resume` | 恢复 |
| `DELETE` | `/{sid}` | 取消/删除 |

**示例：完整流程**

```bash
# 1. 启动
SID=$(curl -s -X POST http://127.0.0.1:8765/api/autoresearch/start \
  -H "Content-Type: application/json" \
  -d '{"query": "Compare Y and Z"}' | jq -r .session_id)

# 2. 监听事件（带超时）
timeout 120 curl -sN http://127.0.0.1:8765/api/autoresearch/$SID/stream \
  | grep -E "^data: " | head -20

# 3. 查看最终结果（含 6 步字段）
curl -s http://127.0.0.1:8765/api/autoresearch/$SID/ | jq .

# 4. 暂停/恢复
curl -X POST http://127.0.0.1:8765/api/autoresearch/$SID/pause
curl -X POST http://127.0.0.1:8765/api/autoresearch/$SID/resume

# 5. 删除
curl -X DELETE http://127.0.0.1:8765/api/autoresearch/$SID
```

### 方式 2：Python 直接调用

```python
import asyncio
from llmwikify.autoresearch import (
    ResearchEngine, DEFAULT_SIX_STEP_CONFIG, merge_six_step_config
)
from llmwikify.autoresearch.db import AutoResearchDatabase
from llmwikify.autoresearch.session import ResearchSessionManager
from llmwikify.autoresearch.task_manager import get_task_manager

# 1. 准备依赖
wiki = ...           # 你的 Wiki 实例
db = AutoResearchDatabase("~/.llmwikify/agent/")
llm_client = ...      # StreamableLLMClient 实例

# 2. 构造 engine
config = merge_six_step_config({
    "max_react_rounds": 8,
    "planning_model": "claude-sonnet-4.5",
    "report_model": "claude-sonnet-4.5",
})
engine = ResearchEngine(wiki, db, llm_client, config)

# 3. 启动 session
sm = ResearchSessionManager(db)
session_id = sm.create_session("my-wiki", "What is X?")

# 4. 跑
async def run():
    async for event in engine.run(session_id, "What is X?"):
        t = event.get("type")
        if t == "clarification_complete":
            print("CLARIFIED:", event.get("context"))
        elif t == "evidence_scoring_complete":
            print(f"SCORED {event['count']} sources, avg={event['avg_score']}")
        elif t == "reasoning_check_complete":
            print(f"REASONING {event['aggregate_score']:.2f}")
        elif t == "structure_check_complete":
            print(f"STRUCTURE {event['aggregate_score']:.2f}")
        elif t == "review_passed":
            print(f"REVIEW PASSED, score={event['score']}")
        elif t == "done":
            break
        elif t == "error":
            print("ERROR:", event.get("error"))

asyncio.run(run())
```

**后台任务**（生产用法）：

```python
tm = get_task_manager()
tm.start(session_id, "What is X?", engine, resume=False)

# 监听事件流
async for event in tm.get_event_stream(session_id):
    print(event)
```

**读 6 步字段**：

```python
# 读所有 6 步字段（解析后）
fields = db.get_six_step_fields(session_id)
# {
#   "clarification": {...},
#   "reasoning": {"scores": {...}, "aggregate_score": 0.65, "issues": [...]},
#   "structure": {"scores": {...}, "aggregate_score": 0.72, "issues": [...]},
#   "self_loop_counts": {...},
#   "self_loop_history": [...],
#   "evidence_scores": {"src-uuid-1": 0.78, "src-uuid-2": 0.55, ...}
# }

# 写单个字段
db.update_six_step_fields(
    session_id,
    reasoning={"scores": {...}, "aggregate_score": 0.8, "issues": []},
    # 其他可写: clarification, structure, self_loop_counts,
    #          self_loop_history, evidence_scores
)
```

### 方式 3：独立调用 6 步组件

```python
from llmwikify.autoresearch import (
    ResearchClarifier, SourceFilter, ReasoningChecker,
    StructureValidator, QualityGate
)

# 1. 概念澄清
clarifier = ResearchClarifier(llm_client, config)
result = await clarifier.clarify("What is the impact of X?")

# 2. 证据评分
sf = SourceFilter(config)
score = sf.compute_evidence_score(source_dict)

# 3. 推理检查
checker = ReasoningChecker()
result = checker.check(synthesis=text, evidence_sources=sources, clarification=ctx)

# 4. 结构验证
validator = StructureValidator()
result = validator.validate(report=md_text, synthesis=syn, evidence_sources=sources)

# 5. 完整 8 门禁
gate = QualityGate(config)
r1 = gate.check_evidence_quality(sources)
r2 = gate.check_reasoning_quality(text, sources, ctx)
r3 = gate.check_structure_quality(md_text, syn, sources)
r4 = gate.check_framework_compliance(ctx, reasoning, structure)
# 每个返回 GateResult(passed, gate_name, summary, details, suggestion)
```

---

## 配置参考

### 默认配置（`DEFAULT_SIX_STEP_CONFIG`）

```python
DEFAULT_SIX_STEP_CONFIG = {
    # ─── 基础 research 配置（与 llmwikify 一致） ───
    "max_sub_queries": 20,
    "max_source_content_length": 500000,
    "research_timeout_minutes": 30,
    "max_parallel_gathering": 5,
    "web_search_results_per_query": 5,
    "max_retry_attempts": 3,
    "max_review_rounds": 2,
    "planning_model": None,        # 默认用 default_llm
    "report_model": None,
    "llm_call_timeout_seconds": 120,
    "search_provider": "auto",     # auto / searxng / minimax / tavily / duckduckgo
    "max_react_rounds": 10,
    "quality_threshold": 7,
    "max_replan_attempts": 2,      # 门禁失败 → plan 最多重 2 次
    "parallel_wiki_search": True,
    "source_filter_enabled": True,
    "source_min_content_length": 100,
    "source_min_quality_score": 0.3,
    "report_max_per_source": 4000,
    "report_max_total_content": 60000,

    # ─── 4 基础门禁 ───
    "gate_enabled": True,
    "gate_min_sources": 3,
    "gate_min_type_diversity": 2,
    "gate_min_analyzed": 2,
    "gate_min_avg_credibility": 5,
    "gate_max_knowledge_gaps": 3,
    "gate_min_reinforced_claims": 2,

    # ─── 6 步框架开关（默认全开，不可关闭 self-loop） ───
    "clarify_enabled": True,
    "reasoning_check_enabled": True,
    "structure_check_enabled": True,
    "evidence_scoring_enabled": True,
    "framework_check_enabled": True,

    # ─── 6 步门禁阈值 ───
    "gate_min_evidence_score": 0.5,      # 0-1
    "gate_min_traceable_sources": 2,
    "gate_min_reasoning_score": 7,         # 0-10
    "gate_max_reasoning_issues": 3,
    "gate_min_structure_score": 7,         # 0-10
    "gate_min_source_refs": 3,

    # ─── 自我循环（必启用，无关闭） ───
    "clarify_max_retries": 2,
    "evidence_max_retries": 2,
    "self_loop_budget_ratio": 0.3,         # 最多 30% 预算

    # ─── 3 个重试管理器 ───
    "stage_max_retries": 2,
    "stage_retry_base_delay": 2.0,
    "llm_parse_max_retries": 3,
    "db_retry_base_delay": 1.0,
    "db_retry_max_retries": 3,
}
```

### 自定义配置

```python
from llmwikify.autoresearch import merge_six_step_config

config = merge_six_step_config({
    # 覆盖默认值
    "max_react_rounds": 5,
    "gate_min_evidence_score": 0.7,  # 严格要求
    "clarify_max_retries": 1,          # 减少重试
    "planning_model": "claude-sonnet-4.5",
    "report_model": "claude-sonnet-4.5",
})
# 未指定的字段保持默认值
```

---

## 公开 API

从 `llmwikify.autoresearch` 可直接 import 的 14 个符号：

| 符号 | 类型 | 用途 |
|------|------|------|
| `ResearchEngine` | class | ReAct 引擎主类 |
| `ResearchState` | dataclass | ReAct 状态（含 6 步字段） |
| `ResearchClarifier` | class | 概念澄清器（Step 1） |
| `DEFAULT_SIX_STEP_CONFIG` | dict | 默认配置 |
| `merge_six_step_config` | function | 配置覆盖合并 |
| `VALID_TRANSITIONS` | dict | 状态转换表（`None → clarifying → plan → ...`） |
| `GateResult` | dataclass | 门禁结果（含 passed/suggestion） |
| `QualityGate` | class | 8 门禁统一接口 |
| `ReasoningChecker` | class | 6 维推理评分（Step 3） |
| `SourceFilter` | class | 证据评分（Step 2） |
| `StructureValidator` | class | 3 层结构验证（Step 4） |
| `StageRetryManager` | class | Stage 级别重试 |
| `LLMRetryManager` | class | LLM 错误重试（rate limit / 5xx） |
| `DBRetryManager` | class | DB locked 错误重试 |
| `retry_async` | function | 通用 async 重试装饰器 |

### `AutoResearchDatabase` 公共方法

```python
from llmwikify.autoresearch.db import AutoResearchDatabase

db = AutoResearchDatabase("~/.llmwikify/agent/")  # → autoresearch.db

# Sessions
sid = db.create_research_session(wiki_id, query)
session = db.get_research_session(sid)
sessions = db.list_research_sessions(wiki_id=None)
db.update_research_status(sid, status, step, progress=None, ...)
db.update_research_progress(sid, progress)
db.persist_report(sid, result_json)
db.finalize_research(sid, status, result_json, quality_score=None)
deleted = db.delete_research(sid)

# Sub-queries
sq_id = db.save_sub_query(session_id, query, source_type, url=None)
db.update_sub_query(sq_id, status, result=None, error=None)
sqs = db.get_sub_queries(session_id)

# Sources
src_id = db.save_source(session_id, sub_query_id, source_type, url, title,
                        content_length, content_preview=None, content=None)
db.update_source_analysis(src_id, analysis_dict)
sources = db.get_sources(session_id)

# 6 步框架 helpers
db.update_six_step_fields(session_id, clarification=None, reasoning=None,
                          structure=None, self_loop_counts=None,
                          self_loop_history=None, evidence_scores=None)
fields = db.get_six_step_fields(session_id)
# → {"clarification", "reasoning", "structure",
#    "self_loop_counts", "self_loop_history", "evidence_scores"}
```

**方法名与 `AgentDatabase` 同形**（v4 兼容性）— 调用方零业务逻辑改动。

---

## 重试机制

3 个独立的重试管理器（`src/llmwikify/autoresearch/retry_managers.py`）：

### `StageRetryManager`

**用途**：整个 stage（gather / synthesize / report / review）失败时，**部分回退**（不重做整个 stage）。

```python
from llmwikify.autoresearch import StageRetryManager

mgr = StageRetryManager(max_retries=2, base_delay=2.0)
result = mgr.run(
    stage_func=lambda: gather(...),
    fallback=lambda exc: partial_results,  # 失败时的回退
)
# 返回 (success, result, retries_used)
```

### `LLMRetryManager`

**用途**：LLM 调用的瞬时错误（rate limit / 5xx）。

```python
from llmwikify.autoresearch import LLMRetryManager

mgr = LLMRetryManager(max_retries=3, base_delay=1.0)
result = await mgr.call(llm.chat, messages, ...)
# 自动重试：rate limit (429), 5xx, connection error
# 不重试：JSON decode error, validation error, 4xx (except 429)
```

### `DBRetryManager`

**用途**：SQLite `database is locked` 错误（并发写入时）。

```python
from llmwikify.autoresearch import DBRetryManager

mgr = DBRetryManager(max_retries=3, base_delay=1.0)
mgr.execute("INSERT INTO ...", (params,))  # 自动重试 locked 错误
```

### 通用 `retry_async`

```python
from llmwikify.autoresearch import retry_async

@retry_async(max_attempts=3, base_delay=1.0,
             exceptions=(ConnectionError, TimeoutError))
async def fetch_data():
    ...
```

---

## 与 research 的区别

| 维度 | research (`agent.backend.research`) | autoresearch |
|------|--------------------------------------|---------------|
| **位置** | `src/llmwikify/agent/backend/research/` | `src/llmwikify/autoresearch/` |
| **DB** | `~/.llmwikify/agent/.llmwiki_agent.db` | `~/.llmwikify/agent/autoresearch.db` |
| **Session 表** | `research_sessions` | `autoresearch_sessions` |
| **状态起点** | `planning` | `clarifying`（v4+） |
| **结构化推理** | 无 | **6 步框架** |
| **证据评估** | 长度/域名 | **5 维（length/domain/traceability/authority/type_consistency）** |
| **推理检查** | 无 | **6 维（ReasoningChecker）** |
| **结构检查** | 无 | **3 层（StructureValidator）** |
| **报告 prompt 注入** | 无 | **6 步 framework block** |
| **耦合到 `agent.backend.research`** | N/A | **零** |
| **UI 入口** | `/agent/` Quick Research 面板 | `/agent/` AutoResearch 面板（规划中） |
| **默认时间预算** | 30 分钟 | 30 分钟 |
| **门禁数** | 4 基础 | **8（4 基础 + 4 六步）** |

**何时选哪个**：

- **research** — 快速、轻量、不需要严格结构化推理
- **autoresearch** — 严肃研究、对推理链质量有要求、需要审计 6 步

---

## 文件结构

```
src/llmwikify/autoresearch/                # 全新顶级子项目
├── __init__.py                            # 14 个公共 API 重导出
├── engine.py                              # COPY+增强：ReAct 引擎（~1510 行）
├── config.py                              # 独立 6 步配置（~95 行）
├── session.py                             # session 管理（~90 行）
├── source_filter.py                       # SourceFilter + compute_evidence_score（~329 行）
├── gatherer.py                            # SourceGatherer（~426 行）
├── analyzer.py                            # SourceAnalyzer（~93 行）
├── synthesizer.py                         # ResearchSynthesizer（~145 行）
├── web_search.py                          # 多 provider web search（~274 行）
├── quality_gate.py                        # 8 门禁（4 基础 + 4 六步）（~341 行）
├── report.py                              # ReportGenerator + 6 步注入（~307 行）
├── review.py                              # ResearchReviewer + 6 步评审（~210 行）
├── clarifier.py                           # ResearchClarifier（~207 行）
├── reasoning_checker.py                   # 6 维推理评分（~229 行）
├── structure_validator.py                 # 3 层结构验证（~173 行）
├── retry_managers.py                      # 3 个重试管理器（~294 行）
├── db.py                                  # 独立 AutoResearchDatabase（~511 行）
├── db_migrations.py                       # init + 可选 migrate（~96 行）
├── routes.py                              # FastAPI router（~216 行，8 端点）
└── task_manager.py                        # 后台任务管理（~144 行）

tests/test_autoresearch.py                 # 89 测试（82 旧 + 7 e2e v5）
docs/plans/autoresearch-structured-reasoning.md  # 设计文档（含 v5 revision）
```

---

## 测试

89 个测试，全部通过：

```
$ python3 -m pytest tests/test_autoresearch.py
======================== 89 passed, 2 warnings in 0.80s ========================
```

**测试覆盖**：

| TestClass | 测试数 | 覆盖内容 |
|-----------|--------|---------|
| `TestAutoresearchConfig` | 6 | 默认配置字段、merge、未知 key 忽略 |
| `TestDBMigrations` | 6 | init 幂等、migrate 列、dry-run、no-op |
| `TestResearchState` | 2 | 6 步字段、基础字段 |
| `TestValidTransitions` | 3 | `clarifying` 转换、None→clarifying、所有基础转换 |
| `TestResearchClarifier` | 7 | clarify、code_fence、LLM 错误 fallback、scope_check 重试、self-loop 预算、exhausted 警告 |
| `TestEngineInitialization` | 2 | 独立 DB、6 步配置 |
| `TestEngineClarifyIntegration` | 1 | 引擎先 clarify 后 plan |
| `TestSourceFilterEvidence` | 5 | 高/低质量、wiki 完整可追溯、traceability 分解、PDF 权威 |
| `TestReasoningChecker` | 5 | 6 维返回、高质量 pass、空 synthesis 0、premises alignment、issues |
| `TestQualityGateNewGates` | 3 | evidence pass/fail、reasoning aggregate/threshold |
| `TestStructureValidator` | 4 | 3 层、好报告 pass、短报告 fail hierarchy、缺失 section issue |
| `TestStructureAndFrameworkGates` | 5 | structure gate、framework_compliance 3 步齐全 |
| `TestReportAndReviewEnrichment` | 4 | report + review 的 framework block 渲染 |
| `TestRetryAsync` | 3 | 首次成功、重试后 raise、最终成功 |
| `TestStageRetryManager` | 4 | 首次成功、重试成功、部分回退、no partial |
| `TestLLMRetryManager` | 4 | rate limit、5xx、不重试 JSON、不重试 validation |
| `TestDBRetryManager` | 3 | locked 重试、不重试非瞬时、is_retriable |
| `TestAutoResearchDatabase` | 14 | 3 表、2 索引、status=clarifying、6 JSON 字段、round-trip、partial update、cascade delete、零共享、幂等 init、解析 |
| **`TestAutoresearchIntegration`** (v5 新增) | **7** | **完整 ReAct 循环、6 步 events、6 步 fields 持久化、six_step_context 注入、6 步 gates 触发、framework_compliance 行为** |

**全测试套件**：1297 passed, 0 regression（除 3 个 pre-existing e2e failures 无关）。

---

## 设计文档

完整设计 + 决策历史 + 4 次 revision：

- `docs/plans/autoresearch-structured-reasoning.md`（1147 行）
  - v3 — 独立顶级子项目
  - v4 — 独立 `autoresearch.db`（替代共享 `AgentDatabase`）
  - **v5 — 6 步门禁引擎集成 + 报告上下文注入**（2026-06-04 最新）

---

## License

MIT（与 llmwikify 主体一致）

---

## 致谢

- **TradingAgent** 架构思想（[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)）— 团队多角色协作、迭代优化
- **Karpathy's LLM Wiki Principles** — 持久化、可累积的知识库
- **ReAct 范式**（Yao et al. 2022）— Reason → Act → Observe 循环
- **prompt 框架**：6 步结构化推理（基于 [AISafety / v0 framework](https://www.anthropic.com/research/claude-s-character)）
