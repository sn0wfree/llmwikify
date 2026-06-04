# AutoResearch 结构化推理框架集成 — 设计文档

## Overview

将「6 步逻辑框架」（概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单）作为**全新顶级子项目** `src/llmwikify/autoresearch/` 集成到 llmwikify 中。

**关键决策（已确认）**：
- **autoresearch 与 research 是两个完全独立的项目**
- 现有 `src/llmwikify/agent/backend/research/` 100% 保留不动
- autoresearch 通过 **copy**（而非继承/组合）方式从 research 获取初始代码
- autoresearch 内部的 6 步增强独立开发
- 两者共享 `AgentDatabase`（通过幂等 `ALTER TABLE` 扩展 schema）和 `core` 模块（PromptRegistry、Wiki 等）
- 独立路由 `/api/autoresearch/*`，独立测试 `tests/test_autoresearch.py`

## Problem Statement

现有 AutoResearch 引擎（`src/llmwikify/agent/backend/research/`）实现了 ReAct 循环，但缺乏结构化推理约束：

1. **无概念澄清** — 直接进入规划，未明确研究边界和前提
2. **证据评估粗糙** — `source_filter.py` 仅检查内容长度/域名，未评估可追溯性
3. **推理链无校验** — `synthesizer.py` 综合后无推理严密性检查
4. **报告结构无约束** — `report.py` 生成的报告格式依赖 prompt，无结构校验
5. **结论质量无保证** — `review.py` 仅 LLM 评分，无多维度检查
6. **检查清单缺失** — `quality_gate.py` 仅检查数量指标，无逻辑合规性

### 解决方案：全新独立子项目

新建 `src/llmwikify/autoresearch/` 顶级目录：
- **零代码耦合**：不 import `llmwikify.agent.backend.research.*` 任何符号
- **copy 而非继承**：从 research 复制初始代码后独立演进
- **共享基础设施**：仅复用 `AgentDatabase`（DB 共享 + 幂等 schema 迁移）和 `core/` 模块
- **独立测试/路由/配置**：完全可独立运行、测试、部署

## 目标目录结构

```
src/llmwikify/autoresearch/                # 全新顶级子项目
├── __init__.py                            # 公共 API
├── engine.py                              # COPY 自 research + 6 步增强
├── config.py                              # 独立配置
├── session.py                             # COPY + 6 步字段
├── source_filter.py                       # COPY + evidence_score
├── gatherer.py                            # COPY（无修改）
├── analyzer.py                            # COPY（无修改）
├── synthesizer.py                         # COPY（无修改）
├── web_search.py                          # COPY（无修改）
├── quality_gate.py                        # COPY + 4 新门禁
├── report.py                              # COPY + 6 步 system 注入
├── review.py                              # COPY + 6 步 system 注入
├── clarifier.py                           # 新建：概念澄清器
├── reasoning_checker.py                   # 新建：推理链校验器
├── structure_validator.py                 # 新建：结构校验器
├── retry_managers.py                      # 新建：3 个重试管理器
├── db.py                                  # v4 新建：独立 AutoResearchDatabase
├── db_migrations.py                       # v3 新建 → v4 改写：init_autoresearch_db + 可选 migrate_research_six_step_columns
├── routes.py                              # 新建 FastAPI router
└── task_manager.py                        # COPY 自 research

tests/test_autoresearch.py                 # 独立测试
```

## 零耦合约束

`autoresearch/` 中**禁止** import 任何 `llmwikify.agent.backend.research.*` 符号。

只允许 import：
```python
from llmwikify.agent.backend.db import AgentDatabase
from llmwikify.agent.backend.adapters import StreamableLLMClient
from llmwikify.core.prompt_registry import PromptRegistry
from llmwikify.core.synthesis_engine import SynthesisEngine
from llmwikify.core.wiki import Wiki
from llmwikify.extractors.base import ExtractedContent
from llmwikify.extractors.web import extract_url
from llmwikify.extractors.youtube import extract_youtube
```

## TradingAgent 借鉴分析

[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) 是多 Agent 交易框架（82.6k stars），其核心架构可借鉴：

### 借鉴架构

```
TradingAgent 角色分工
├── Analyst Team（分析师团队）
│   ├── Fundamentals Analyst
│   ├── Sentiment Analyst
│   ├── News Analyst
│   └── Technical Analyst
├── Researcher Team（研究员团队）
│   ├── Bullish Researcher
│   └── Bearish Researcher
├── Trader Agent
└── Risk Management & Portfolio Manager
```

### 借鉴特性

| 特性 | TradingAgent | 第一阶段借鉴 |
|------|-------------|------------|
| **多 Agent 辩论** | Bullish vs Bearish | 可选：添加到研究决策 |
| **决策日志** | 持久化到 `~/.tradingagents/memory/` | 可选：研究反思机制 |
| **检查点恢复** | LangGraph checkpoint | 已有：DB 状态 |
| **环境变量配置** | `TRADINGAGENTS_*` | 已有：`~/.llmwikify/llmwikify.json` |

### 借鉴但不依赖

- **借鉴思想**：多 Agent 协作、决策日志、反思机制
- **不复用代码**：保持独立架构，避免耦合
- **统一接口**：研究 API 与策略 API 设计一致

## 并行开发计划

### 开发策略：选项 B（并行独立开发）

两个阶段可并行开发，借鉴架构但不依赖代码：

```
第 1 周：基础模块
├── 第一阶段：DB 迁移 + config + clarifier
└── 第二阶段：data_provider + data_cache

第 2 周：核心模块
├── 第一阶段：reasoning_checker + structure_validator + 自我循环
└── 第二阶段：factor_miner + factor_validator + 策略实现

第 3 周：完善
├── 第一阶段：重试机制 + 集成测试
└── 第二阶段：回测引擎 + 风控模块 + 测试

第 4 周：集成
├── 第一阶段：端到端测试
└── 第二阶段：端到端测试
└── 整体联调
```

### 借鉴点（不依赖）

| 借鉴项 | 应用到 |
|-------|--------|
| 质量门禁架构 | 策略质量校验（第二阶段） |
| 自我循环模式 | 策略优化迭代（第二阶段） |
| DB 迁移模式 | 策略表创建（第二阶段） |
| Prompt 模板结构 | 策略 prompt（第二阶段） |
| 配置系统 | 策略 config（第二阶段） |

## 6 步框架映射

```
概念澄清 → 建立依据 → 推理严密 → 稳固结构 → 结论输出 → 检查清单
   │          │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼          ▼
clarifier  evidence   reasoning  structure  report+    framework
.py        scoring    _checker   _validator  review    _compliance
```

| 框架步骤 | autoresearch 实现 | 触发位置 |
|---------|------------------|---------|
| 1. 概念澄清 | `clarifier.py` + `research_clarify.yaml` | `_action_clarify` (state 阶段: clarifying) |
| 2. 建立依据 | `source_filter.py.compute_evidence_score()` + `quality_gate.check_evidence_quality()` | `_evaluate_gate` (phase: gathering) |
| 3. 推理严密 | `reasoning_checker.py` + `quality_gate.check_reasoning_quality()` | `_evaluate_gate` (phase: synthesizing) |
| 4. 稳固结构 | `structure_validator.py` + `research_structure_check.yaml` + `quality_gate.check_structure_quality()` | `_evaluate_gate` (phase: reporting) |
| 5. 结论输出 | `report.py` + `review.py` 内部注入 6 步 system prompt | `_action_report` + `_action_review` |
| 6. 检查清单 | `quality_gate.check_framework_compliance()` | `_evaluate_gate` (phase: reviewing) |

### 8 门禁独立调度（已确认）

| 门禁 | 类型 | 触发阶段 | 失败动作 |
|------|------|---------|---------|
| `check_after_gathering` | 基础 | gathering | gather_more |
| `check_after_analysis` | 基础 | analyzing | gather_higher_quality |
| `check_after_synthesis` | 基础 | synthesizing | replan_for_gaps |
| `check_before_report` | 基础 | reporting | synthesize_again |
| **`check_evidence_quality`** | 6 步 | gathering | **强制 plan** |
| **`check_reasoning_quality`** | 6 步 | synthesizing | **强制 plan** |
| **`check_structure_quality`** | 6 步 | reporting | **强制 plan** |
| **`check_framework_compliance`** | 6 步 | reviewing | 注入 observation（不强制 plan） |

**调度优先级**（用户已确认）：6 步门禁失败 > 基础门禁失败。6 步门禁失败一律**强制返回 plan** 重新规划（受 `_max_replan` 限制）。

## Architecture

### 1. Research State 扩展

```python
@dataclass
class ResearchState:
    # ... 现有字段 ...

    # 新增：6步框架字段
    clarification: dict | None    # 概念澄清结果
    reasoning_check: dict | None  # 推理链校验结果
    structure_check: dict | None  # 结构校验结果
    evidence_scores: list[float]  # 证据可信度评分
```

### 2. 新模块设计

#### 2.1 ResearchClarifier（概念澄清器）

```python
class ResearchClarifier:
    """概念澄清器 - 锁定研究的语境、边界、立场、前提"""

    async def clarify(self, query: str) -> dict:
        """
        输出：
        {
            "context": "研究语境（适用范围、时间/空间边界）",
            "boundaries": "边界条件（利益相关方、约定条件）",
            "position": "立场（角色视角）",
            "premises": "前提假设（必要条件、假设）",
            "scope_check": "范围是否可研究（true/false）"
        }
        """
```

**触发时机**：ReAct 循环开始时，在 `_action_plan()` 之前调用。

**数据流**：
```
query → ResearchClarifier.clarify() → state.clarification
                                        ↓
                            _llm_reason() 注入澄清上下文
                            _plan_sub_queries() 使用边界约束
```

#### 2.2 ReasoningChecker（推理链校验器）

```python
class ReasoningChecker:
    """推理链校验器 - 确保推理环环相扣"""

    def check_reasoning_chain(self, synthesis: dict, sources: list[dict]) -> dict:
        """
        检查：
        1. 小结论链条：前提→结果，逐步推导
        2. 首尾明确：开头设定，结尾收束
        3. 前提清晰：每一步前提明确
        4. 步骤完整：逻辑不跳跃
        5. 环环相扣：上下支撑，因果清晰
        6. 能自洽：内部逻辑无冲突
        """
```

**触发时机**：`_action_synthesize()` 完成后，作为质量门禁的一部分。

**数据流**：
```
synthesis → ReasoningChecker.check() → state.reasoning_check
                                        ↓
                            质量门禁决策：通过 / 重新综合 / 重新规划
```

#### 2.3 StructureValidator（结构校验器）

```python
class StructureValidator:
    """结构校验器 - 确保报告结构稳固"""

    def validate_structure(self, report_md: str, synthesis: dict) -> dict:
        """
        三层支撑检查：
        1. 上层结论：整体判断
        2. 中层论证：连接上下
        3. 底层支撑：事实与依据

        三个标准：
        1. 无差异：关键判断标准一致
        2. 能自洽：内部逻辑不矛盾
        3. 结构稳固：上下支撑，左右呼应
        """
```

**触发时机**：`_action_report()` 完成后，作为质量门禁的一部分。

**数据流**：
```
report_md → StructureValidator.validate() → state.structure_check
                                             ↓
                                    质量门禁决策：通过 / 重新报告 / 修订
```

### 3. 质量门禁增强

```python
class QualityGate:
    # 现有门禁：
    #   check_after_gathering()
    #   check_after_analysis()
    #   check_after_synthesis()
    #   check_before_report()

    # 新增门禁：
    def check_evidence_quality(self, sources: list[dict]) -> GateResult:
        """证据质量检查（建立依据）"""

    def check_reasoning_quality(self, synthesis: dict) -> GateResult:
        """推理严密性检查（推理严密）"""

    def check_structure_quality(self, report_md: str) -> GateResult:
        """结构稳固性检查（稳固结构）"""

    def check_framework_compliance(self, state: ResearchState) -> GateResult:
        """6步框架合规检查（检查清单）"""
```

### 4. Prompt 模板增强

#### 4.1 research_clarify.yaml（新建）

```yaml
name: research_clarify
description: "Clarify research context, boundaries, position, and premises"

params:
  max_tokens: 1024
  temperature: 0.3
  json_mode: true

system: |
  你是一个研究澄清助手。给定研究主题，你需要：

  1. **语境**：明确在谈什么，适用范围、可改变范围、约定边界
  2. **边界**：识别利益相关方、约定条件
  3. **立场**：明确角色视角
  4. **前提**：区分必要条件、前提假设

  返回 JSON：
  {
    "context": "研究语境描述",
    "boundaries": "边界条件",
    "position": "立场声明",
    "premises": "前提假设列表",
    "scope_check": "范围是否可研究（true/false）"
  }

user: |
  研究主题：{{ query }}
  {% if wiki_context %}
  现有知识库上下文：
  {{ wiki_context }}
  {% endif %}
  请进行概念澄清。
```

#### 4.2 research_structure_check.yaml（新建）

```yaml
name: research_structure_check
description: "Validate report structure against 6-step framework"

params:
  max_tokens: 2048
  temperature: 0.1
  json_mode: true

system: |
  你是一个报告结构校验器。评估报告是否符合以下结构要求：

  **三层支撑：**
  1. 上层结论：整体判断是否清晰
  2. 中层论证：连接上下是否充分
  3. 底层支撑：事实与依据是否可靠

  **三个标准：**
  1. 无差异：关键判断标准是否一致
  2. 能自洽：内部逻辑是否矛盾
  3. 结构稳固：上下支撑是否充分

  返回 JSON：
  {
    "approved": true/false,
    "score": 1-10,
    "structure_score": {
      "top_layer": 1-10,
      "middle_layer": 1-10,
      "bottom_layer": 1-10
    },
    "issues": ["问题1", "问题2"],
    "suggestions": ["建议1", "建议2"]
  }

user: |
  研究主题：{{ query }}
  报告内容：{{ report }}
  合成信息：
  - 强化结论：{{ reinforced_claims }}
  - 矛盾：{{ contradictions }}
  - 知识缺口：{{ knowledge_gaps }}
  请验证报告结构。
```

#### 4.3 现有 Prompt 增强

**research_plan.yaml**：在 system 中增加澄清约束

```yaml
system: |
  ...现有内容...

  IMPORTANT: 在规划前，先进行概念澄清：
  - 明确研究的语境和边界
  - 识别利益相关方
  - 明确立场和前提假设
  - 如果前提不可靠，返回 scope_check: false
```

**research_review.yaml**：增加结论质量标准

```yaml
system: |
  ...现有标准...

  评估标准新增：
  8. 是否有明确的一句话核心结论
  9. 是否解释了原因和结果
  10. 是否提供了可执行的行动建议
  11. 结论是否可被验证
  12. 报告结构是否符合三层支撑
```

### 5. 数据库变更（独立 autoresearch.db）

**设计原则：autoresearch 与 research / chat / ppt 共享进程但使用独立 SQLite 数据库**。

#### 5.1 文件路径

| 数据库 | 路径 | 用途 |
|--------|------|------|
| AgentDatabase | `~/.llmwikify/agent/.llmwiki_agent.db` | chat / tool_calls / research / ppt / notifications |
| **AutoResearchDatabase** | **`~/.llmwikify/agent/autoresearch.db`** | **autoresearch 全部数据** |

两个 DB 在 `~/.llmwikify/agent/` 目录下**同级**，互不引用。Server 启动时各自初始化。

#### 5.2 零共享约束

| 维度 | 现状 | 目标 |
|------|------|------|
| 文件 | `agent_service.db` 共享 | `autoresearch.db` 独立 |
| 表 | `research_sessions` 表加 3 列 | `autoresearch_sessions` 独立表 |
| ALTER 触发 | 每次 `ResearchEngine.__init__` 跑 `ensure_six_step_columns` | 启动时一次性 `CREATE TABLE IF NOT EXISTS` |
| 写路径 | engine.py 第 699 行裸 SQL `UPDATE research_sessions SET clarification_json = ?` | 改用 `update_six_step_fields()` 封装方法 |
| 删除残留 | research_sessions 含 autoresearch 字段 | 可选迁移工具 `migrate_research_six_step_columns()` 显式清理 |

#### 5.3 Schema（幂等 `CREATE TABLE IF NOT EXISTS`）

```sql
-- autoresearch.db 全部表（独立于 .llmwiki_agent.db）

CREATE TABLE autoresearch_sessions (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'clarifying',  -- 默认 'clarifying'，与 research 不同
    current_step TEXT DEFAULT 'clarifying',
    progress REAL DEFAULT 0.0,
    result TEXT,
    wiki_page_name TEXT,
    iteration_round INTEGER DEFAULT 0,
    synthesis_json TEXT,
    review_json TEXT,
    -- ─── 6 步框架字段（schema 内置，无需 ALTER） ─────
    clarification_json TEXT,
    reasoning_json TEXT,
    structure_json TEXT,
    self_loop_counts_json TEXT,
    self_loop_history_json TEXT,
    evidence_scores_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE autoresearch_sub_queries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id)
);

CREATE TABLE autoresearch_sources (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sub_query_id TEXT,
    source_type TEXT NOT NULL,
    url TEXT,
    title TEXT,
    content_length INTEGER,
    content_preview TEXT,
    content TEXT,
    analysis TEXT,
    rating INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES autoresearch_sessions(id),
    FOREIGN KEY (sub_query_id) REFERENCES autoresearch_sub_queries(id)
);

CREATE INDEX idx_ar_sub_queries_session
    ON autoresearch_sub_queries(session_id, status);
CREATE INDEX idx_ar_sources_session
    ON autoresearch_sources(session_id);
```

#### 5.4 AutoResearchDatabase 公共 API

保持方法名同形于 AgentDatabase.research_* 系列，**调用方零改动**：

```python
class AutoResearchDatabase:
    def __init__(self, data_dir: Path | str):
        """data_dir = ~/.llmwikify/agent/ → autoresearch.db"""

    # Session CRUD
    def create_research_session(wiki_id, query) -> str
    def get_research_session(session_id) -> dict | None
    def list_research_sessions(wiki_id=None) -> list[dict]
    def update_research_status(session_id, status, step, iteration_round, synthesis_json, review_json)
    def update_research_progress(session_id, progress, wiki_page_name)
    def delete_research(session_id) -> bool  # cascade sub_queries + sources

    # Sub-queries
    def save_sub_query(session_id, query, source_type, url) -> str
    def update_sub_query(sq_id, status, result, error)
    def get_sub_queries(session_id) -> list[dict]

    # Sources
    def save_source(session_id, sub_query_id, source_type, url, title, content_length, content_preview, content) -> str
    def update_source_analysis(source_id, analysis)
    def get_sources(session_id) -> list[dict]

    # Report
    def persist_report(session_id, result_json)
    def finalize_research(session_id, result_json, wiki_page_name)

    # 6 步框架专用
    def update_six_step_fields(
        session_id,
        clarification=None,
        reasoning=None,
        structure=None,
        self_loop_counts=None,
        self_loop_history=None,
        evidence_scores=None,
    ) -> None
    def get_six_step_fields(session_id) -> dict[str, Any]
```

#### 5.5 db_migrations.py 改写

```python
"""Schema bootstrap for the autoresearch database."""

def init_autoresearch_db(db_path) -> None:
    """幂等创建 autoresearch schema（无操作如果表已存在）"""
    from llmwikify.autoresearch.db import AutoResearchDatabase
    AutoResearchDatabase(Path(db_path).parent)


def migrate_research_six_step_columns(old_db_path, drop_columns=True) -> int:
    """OPTIONAL: 清理旧 .llmwiki_agent.db 中 research_sessions 的
    autoresearch 残留字段 (clarification_json / reasoning_json / structure_json)

    Returns: 已删除的列数
    """
```

#### 5.6 engine.py 关键修改

| 行 | Before | After |
|----|--------|-------|
| 18 | `from llmwikify.agent.backend.db import AgentDatabase` | `from llmwikify.autoresearch.db import AutoResearchDatabase` |
| 164 | `db: AgentDatabase` | `db: AutoResearchDatabase` |
| 188-197 | 8 行 `ensure_six_step_columns(...)` 块 | **删除** |
| 699-704 | 6 行裸 SQL | `self.db.update_six_step_fields(state.session_id, clarification=clarification)` |

#### 5.7 server/http/routes.py 注入

```python
# AutoResearch - independent 6-step framework engine with its own DB.
# No shared schema with research / chat / ppt.
from llmwikify.autoresearch.db import AutoResearchDatabase
autoresearch_db = AutoResearchDatabase(data_dir)
set_autoresearch_deps(
    db=autoresearch_db,  # 独立 DB（非 agent_service.db）
    wiki_registry=registry,
    llm_client=None,  # Will fallback to agent service LLM
    config=research_config,
)
```

#### 5.8 旧数据迁移（可选 / 不强制）

当前不自动迁移。如用户曾运行过旧版 autoresearch（共享 DB 模式），可手动调用：

```python
from llmwikify.autoresearch.db_migrations import migrate_research_six_step_columns
count = migrate_research_six_step_columns(
    old_db_path=Path("~/.llmwikify/agent/.llmwiki_agent.db"),
    drop_columns=True,
)
# count: 实际删除的列数（0-3）
```

### 6. 配置参数

```python
DEFAULT_RESEARCH_CONFIG = {
    # ... 现有参数 ...

    # 6步框架开关
    "clarify_enabled": True,
    "reasoning_check_enabled": True,
    "structure_check_enabled": True,
    "evidence_scoring_enabled": True,

    # 证据质量阈值
    "gate_min_evidence_score": 0.5,
    "gate_min_traceable_sources": 2,

    # 推理严密性阈值
    "gate_min_reasoning_score": 7,
    "gate_max_reasoning_issues": 3,

    # 结构稳固性阈值
    "gate_min_structure_score": 7,
    "gate_min_source_refs": 3,

    # 框架合规性阈值
    "gate_framework_check_enabled": True,
}
```

## File Changes

### autoresearch/ 新建文件

| 文件 | 类型 | 来源 | 行数 | 说明 |
|------|------|------|------|------|
| `autoresearch/__init__.py` | Python | 新建 | ~10 | 公共 API 重导出 |
| `autoresearch/config.py` | Python | 新建 | ~60 | 独立配置 |
| `autoresearch/clarifier.py` | Python | 新建 | ~130 | 概念澄清器 |
| `autoresearch/reasoning_checker.py` | Python | 新建 | ~100 | 推理链校验器 |
| `autoresearch/structure_validator.py` | Python | 新建 | ~150 | 结构校验器 |
| `autoresearch/retry_managers.py` | Python | 新建 | ~150 | 3 个重试管理器 |
| `autoresearch/db.py` | Python | 新建 | ~380 | 独立 AutoResearchDatabase（含 update_six_step_fields / get_six_step_fields） |
| `autoresearch/db_migrations.py` | Python | 改写 | ~50 | init_autoresearch_db() + 可选 migrate_research_six_step_columns() |
| `autoresearch/routes.py` | Python | 新建 | ~120 | FastAPI router |
| `autoresearch/engine.py` | Python | COPY+增强 | ~1430 | 主引擎（copy 1178 + 6 步增强 250） |
| `autoresearch/session.py` | Python | COPY+增强 | ~100 | 会话管理 |
| `autoresearch/source_filter.py` | Python | COPY+增强 | ~315 | 源过滤器 + evidence_score |
| `autoresearch/quality_gate.py` | Python | COPY+增强 | ~250 | 8 门禁 |
| `autoresearch/report.py` | Python | COPY+增强 | ~260 | 报告生成 + 6 步 system |
| `autoresearch/review.py` | Python | COPY+增强 | ~160 | 评审 + 6 步 system |
| `autoresearch/gatherer.py` | Python | COPY | ~426 | 无修改 |
| `autoresearch/analyzer.py` | Python | COPY | ~93 | 无修改 |
| `autoresearch/synthesizer.py` | Python | COPY | ~145 | 无修改 |
| `autoresearch/web_search.py` | Python | COPY | ~274 | 无修改 |
| `autoresearch/task_manager.py` | Python | COPY | ~144 | 无修改 |

### Prompts 新建

| 文件 | 类型 | 行数 | 说明 |
|------|------|------|------|
| `prompts/_defaults/research_clarify.yaml` | YAML | ~40 | 概念澄清 prompt |
| `prompts/_defaults/research_structure_check.yaml` | YAML | ~40 | 结构校验 prompt |

### 修改文件

| 文件 | 改动量 | 说明 |
|------|--------|------|
| `server/http/routes.py` | +5 行 | 注册 `autoresearch_router` |

**注**：`agent/backend/research/` 下任何文件**不动**。

### 测试扩展

新建 `tests/test_autoresearch.py`（独立文件，不导入 `test_research.py`）：

| 测试类 | 行数 | 覆盖 |
|--------|------|------|
| `TestResearchClarifier` | ~80 | clarify/scope_check=false 重试/预算耗尽 |
| `TestReasoningChecker` | ~60 | 推理链 6 维评分/LLM 失败回退 |
| `TestStructureValidator` | ~80 | 三层支撑/规则回退 |
| `TestEvidenceScoring` | ~50 | evidence_score 5 维 |
| `TestFrameworkCompliance` | ~80 | 6 步合规检查 |
| `TestEngineSelfLoop` | ~80 | 完整 ReAct 集成 |
| `TestStateTransitions` | ~50 | clarifying 转换 |
| `TestResumeWithClarification` | ~60 | 状态恢复 |
| `TestSixStepGates` | ~60 | 4 新门禁 |
| `TestRetryManagers` | ~80 | Stage/LLM/DB 重试 |
| `TestAutoresearchRoutes` | ~80 | HTTP API 端点 |
| `TestAutoresearchIntegration` | ~80 | 端到端集成 |
| **总计** | **~600** | **25 个 TestClass** |

## ReAct 循环变更

### 现有流程

```
None → plan → gather → analyze → synthesize → report → review → done
```

### 新增流程

```
None → clarify → plan → gather → analyze → synthesize → [reasoning_check] → [structure_check] → report → [framework_check] → review → done
```

**关键变更**：

1. **新增 `clarify` 阶段**：在 `plan` 之前，调用 `ResearchClarifier.clarify()`
2. **新增质量门禁**：
   - `_action_synthesize()` 后：调用 `ReasoningChecker.check_reasoning_chain()`
   - `_action_report()` 后：调用 `StructureValidator.validate_structure()`
   - `_action_review()` 后：调用 `QualityGate.check_framework_compliance()`

### 状态机变更

```python
VALID_TRANSITIONS = {
    None:           ["clarify"],           # 新增
    "clarifying":   ["plan"],              # 新增
    "planning":     ["gather"],
    "gathering":    ["analyze", "plan"],
    "analyzing":    ["synthesizing", "plan"],
    "synthesizing": ["reporting", "plan"],
    "reporting":    ["reviewing"],
    "reviewing":    ["revise", "done"],
    "revise":       ["reviewing", "done"],
    "error":        ["done"],
    "done":         [],
}
```

## 实施计划

### Phase 1：copy 骨架 + 6 步第 1 步"概念澄清"（~3010 行新文件）

**目标**：建立 autoresearch/ 顶级目录骨架，copy 现有 research/ 模块作为基础，集成概念澄清阶段

| 步骤 | 操作 |
|------|------|
| 1 | 创建 `src/llmwikify/autoresearch/` 目录 |
| 2 | copy 14 个文件自 `agent/backend/research/` 到 `autoresearch/` |
| 3 | 修改 copy 后文件的 import 路径（research → autoresearch） |
| 4 | 新建 `__init__.py`、`config.py`、`clarifier.py` |
| 5 | 新建 `prompts/_defaults/research_clarify.yaml` |
| 6 | 新建 `db_migrations.py`（幂等 ALTER TABLE） |
| 7 | 修改 `autoresearch/engine.py`（增 6 步字段 + clarifying 状态 + _action_clarify） |
| 8 | 新建 `routes.py`，注册到 `server/http/routes.py` |
| 9 | 验证：`make test` 现有 16 个 TestClass 全通过 |

### Phase 2：copy 评估模块 + 6 步第 2/3 步（~680 行新代码）

**目标**：第 2 步"建立依据" + 第 3 步"推理严密"

| 步骤 | 操作 |
|------|------|
| 1 | 修改 `source_filter.py` 加 `compute_evidence_score()` + 2 维度评分 |
| 2 | 新建 `reasoning_checker.py`（6 维评分 + 规则回退） |
| 3 | 修改 `quality_gate.py` 加 2 个新门禁（evidence + reasoning） |
| 4 | 新建 `prompts/_defaults/research_structure_check.yaml` |
| 5 | 修改 `engine.py` `_evaluate_gate` 调度新门禁（6 步门失败 → 强制 plan） |
| 6 | 集成 `gather_evidence_with_loop` 自我循环到 `_action_gather` |

### Phase 3：copy 报告/评审 + 6 步第 4/5 步（~410 行新代码）

**目标**：第 4 步"稳固结构" + 第 5 步"结论输出"增强

| 步骤 | 操作 |
|------|------|
| 1 | 新建 `structure_validator.py`（三层支撑 + 规则回退） |
| 2 | 修改 `quality_gate.py` 加 2 个新门禁（structure + framework_compliance） |
| 3 | 修改 `report.py` 注入 6 步 system 提示（一句话结论/可执行建议/可验证性） |
| 4 | 修改 `review.py` 注入 5 条新评审标准 |
| 5 | 修改 `engine.py` `_action_report`/`_action_review` 后调新门禁 |

### Phase 4：重试机制 + 独立测试（~800 行新代码）

**目标**：3 个重试管理器 + 独立测试

| 步骤 | 操作 |
|------|------|
| 1 | 新建 `retry_managers.py`（StageRetryManager/LLMRetryManager/DBRetryManager） |
| 2 | 修改 `engine.py` `_action_*` 包装重试 |
| 3 | 新建 `tests/test_autoresearch.py`（25 个 TestClass 独立测试） |
| 4 | 运行 `make test` 确认 41 个 TestClass 全通过 |

## 关键决策汇总

| # | 决策 | 选项 |
|---|------|------|
| 1 | autoresearch 与 research 关系 | 完全独立 + 可 copy 代码 |
| 2 | 旧 research/ 目录 | 100% 保留不动 |
| 3 | 8 门禁调度 | 独立按阶段调度 |
| 4 | 自我循环超限 | 继续使用最后结果 + 警告 |
| 5 | 重试机制 | 作为新模块独立（retry_managers.py） |
| 6 | Prompt 复用 | 独立新文件（research_clarify.yaml 等） |
| 7 | 6 步门禁失败 | 强制返回 plan（受 _max_replan 限制） |
| 8 | Server 集成 | 独立注册新 router |

## 自我循环机制

### 设计原则

- **必须启用**：自我循环不可通过 config 关闭
- **仅限关键步骤**：概念澄清 + 建立依据
- **预算控制**：自我循环最多占用总预算的 30%
- **超限回退**（已确认）：**继续使用最后结果 + 警告**（不强制终止）
  - scope_check=false 重试超限 → 继续 plan，state.observations 追加"⚠ 澄清重试超限"
  - evidence_score 不达标重试超限 → 继续后续阶段，仅追加警告

### 概念澄清自我循环

```python
async def clarify_with_loop(self, query: str) -> dict:
    """概念澄清 + 自我循环"""
    max_retries = self.config.get("clarify_max_retries", 2)

    for attempt in range(max_retries + 1):
        clarification = await self.clarifier.clarify(query)

        # 质量检查：scope_check 是否通过
        if clarification.get("scope_check", False):
            return clarification

        # 反馈：注入更具体的上下文重新澄清
        if attempt < max_retries:
            query = self._narrow_query(query, clarification)
            yield {"type": "clarify_retry", "attempt": attempt + 1,
                   "reason": clarification.get("scope_issue", "scope too broad")}

    return clarification
```

**循环触发条件**：
- `scope_check = false`（范围不可研究）
- 前提假设不可靠
- 范围过宽，需要收窄

**改进策略**：
- 收窄研究范围
- 增加前提约束
- 补充背景信息

### 建立依据自我循环

```python
async def gather_evidence_with_loop(self, sub_queries: list) -> list:
    """证据收集 + 自我循环"""
    max_retries = self.config.get("evidence_max_retries", 2)
    all_sources = []

    for attempt in range(max_retries + 1):
        sources = await self.gatherer.gather(sub_queries)
        all_sources.extend(sources)

        # 质量检查：证据评分
        evidence_scores = [self._score_evidence(s) for s in all_sources]
        avg_score = sum(evidence_scores) / len(evidence_scores) if evidence_scores else 0

        if avg_score >= self.config.get("gate_min_evidence_score", 0.5):
            return all_sources

        # 反馈：生成补充查询
        if attempt < max_retries:
            gap_queries = self._generate_gap_queries(all_sources, query)
            sub_queries = gap_queries
            yield {"type": "evidence_retry", "attempt": attempt + 1,
                   "avg_score": avg_score, "gap_count": len(gap_queries)}

    return all_sources
```

**循环触发条件**：
- 平均证据评分 < 阈值
- 可追溯源不足
- 缺乏权威出处

**改进策略**：
- 生成补充查询填补缺口
- 优先搜索权威域名
- 增加 PDF/学术源

### 自我循环配置

```python
DEFAULT_RESEARCH_CONFIG = {
    # ... 现有参数 ...

    # 自我循环（必须启用，无开关）
    "clarify_max_retries": 2,       # 概念澄清最大重试
    "evidence_max_retries": 2,      # 证据收集最大重试
    "self_loop_budget_ratio": 0.3,  # 自我循环最多占用 30% 预算
}
```

### 自我循环状态追踪

```python
@dataclass
class ResearchState:
    # ... 现有字段 ...

    # 新增：自我循环追踪
    self_loop_counts: dict[str, int]  # 各步骤当前循环次数
    self_loop_history: list[dict]     # 循环历史记录
```

### 自我循环数据流

```
┌─────────────────────────────────────────────────────────────┐
│                    自我循环数据流                             │
│                                                              │
│  Step N → Execute → Check → Pass? ──Yes──→ Next Step         │
│             ▲        │                                        │
│             │        No                                       │
│             │        │                                        │
│             │        ▼                                        │
│             │    Feedback ──→ Retry ──→ Execute              │
│             │                            │                    │
│             └────────────────────────────┘                    │
│                                                              │
│  循环终止：                                                   │
│  1. Check Pass = True                                        │
│  2. self_loop_counts[step] >= max_retries                    │
│  3. budget_remaining < self_loop_budget_ratio                │
└─────────────────────────────────────────────────────────────┘
```

## 运行失败重试机制

### 集成方式（已确认）：作为新模块独立

新建 `autoresearch/retry_managers.py`，三个独立管理器类：

```python
# autoresearch/retry_managers.py
import asyncio
import json
import sqlite3
import time
import logging

logger = logging.getLogger(__name__)


class StageRetryManager:
    """阶段级重试：整个阶段失败时重试（指数退避 2s/4s/8s）。"""

    def __init__(self, max_retries: int = 2, base_delay: float = 2.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    async def with_stage_retry(self, stage_func, stage_name: str):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return await stage_func()
            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                last_error = e
                if attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning("Stage %s failed (attempt %d/%d): %s, retrying in %.1fs",
                                   stage_name, attempt + 1, self.max_retries, e, delay)
                    await asyncio.sleep(delay)
        raise last_error


class LLMRetryManager:
    """LLM 响应解析重试：JSON 解析失败时重新调用。"""

    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries

    async def with_parse_retry(self, llm_func):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                raw = await llm_func()
                return self._parse_json(raw)
            except (json.JSONDecodeError, KeyError, ValueError) as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning("LLM parse failed (attempt %d/%d): %s",
                                   attempt + 1, self.max_retries, e)
        raise last_error

    def _parse_json(self, raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)


class DBRetryManager:
    """DB 连接重试：数据库锁定时指数退避。"""

    def __init__(self, max_retries: int = 3, base_delay: float = 1.0):
        self.max_retries = max_retries
        self.base_delay = base_delay

    def with_db_retry(self, db_func):
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                return db_func()
            except sqlite3.OperationalError as e:
                if "database is locked" in str(e) and attempt < self.max_retries:
                    delay = self.base_delay * (2 ** attempt)
                    logger.warning("DB locked (attempt %d/%d), retrying in %.1fs",
                                   attempt + 1, self.max_retries, delay)
                    time.sleep(delay)
                    last_error = e
                else:
                    raise
        raise last_error
```

### 集成到 `autoresearch/engine.py`

```python
# autoresearch/engine.py
from .retry_managers import StageRetryManager, LLMRetryManager, DBRetryManager

class ResearchEngine:
    def __init__(self, wiki, db, llm_client, config=None):
        # ... 现有初始化 ...
        self.stage_retry = StageRetryManager(
            max_retries=merged.get("stage_max_retries", 2)
        )
        self.llm_retry = LLMRetryManager(
            max_retries=merged.get("llm_parse_max_retries", 3)
        )
        self.db_retry = DBRetryManager(
            max_retries=merged.get("db_retry_max_retries", 3)
        )
    
    async def _action_synthesize(self, state):
        # 包装父类方法 + 重试 + 推理门禁
        async def _do_synthesize():
            async for event in super()._action_synthesize(state):  # 实际是当前类方法（无继承）
                yield event
        # 注意：实际实现中无需继承，直接调用 _synthesize_impl
        ...
```

### 重试配置

```python
DEFAULT_SIX_STEP_CONFIG = {
    # ... 现有参数 ...
    "stage_max_retries": 2,         # 阶段级最大重试
    "llm_parse_max_retries": 3,     # LLM 响应解析最大重试
    "db_retry_base_delay": 1.0,     # DB 重试退避基数（秒）
    "db_retry_max_retries": 3,      # DB 最大重试
}
```

## Risk Mitigation

1. **零代码耦合**：autoresearch 不 import research/ 任何符号，可独立演进
2. **共享 DB 兼容性**：`db_migrations.py` 用幂等 `ALTER TABLE`（try/except OperationalError），不污染 research/ 的 DB schema
3. **路由独立**：`/api/autoresearch/*` 与 `/api/research/*` 互不干扰
4. **降级处理**：LLM 校验失败时，使用规则回退（如结构校验的章节数/引用数检查）
5. **性能影响**：新增 2-3 次 LLM 调用（澄清 + 结构校验 + 推理校验），可通过 `clarify_enabled=False` / `reasoning_check_enabled=False` 等开关控制
6. **自我循环保护**：最大重试次数（2 次）+ 预算限制（30%），防止无限循环
7. **运行失败恢复**：3 个重试管理器（Stage/LLM/DB），指数退避，避免雪崩
8. **零干扰现有功能**：autoresearch/ 独立模块，独立 router，独立测试，research/ 100% 保留

## Verification

1. **零耦合验证**：
   ```bash
   grep -r "from llmwikify.agent.backend.research" src/llmwikify/autoresearch/
   # 应返回 0 结果
   ```
2. **单元测试**：每个新模块独立测试（25 个 TestClass in test_autoresearch.py）
3. **集成测试**：完整 ReAct 循环端到端测试
4. **路由验证**：`curl localhost:8000/api/autoresearch/test/start` 应正常工作
5. **对比测试**：autoresearch 与 research 可同时运行，互不影响
6. **自我循环测试**：验证 scope_check=false 和证据不足时的重试行为
7. **重试测试**：验证超时、JSON 解析失败、DB 锁定的重试行为
8. **回归测试**：`make test` 现有 16 个 TestClass + 新增 25 个 TestClass 共 41 个全通过

## Verification

1. **单元测试**：每个新模块独立测试
2. **集成测试**：完整 ReAct 循环端到端测试
3. **对比测试**：开启/关闭框架功能的质量对比
4. **手动验证**：使用真实研究主题测试效果
5. **自我循环测试**：验证 scope_check=false 和证据不足时的重试行为
6. **重试测试**：验证超时、JSON 解析失败、DB 锁定的重试行为

## Revision History

### v4 (2026-06-04) — Independent autoresearch.db

**变更动机**：autoresearch 与 research 共享 `AgentDatabase` / `research_sessions` 表的设计带来以下问题：
- 6 步字段通过 `ALTER TABLE` 注入，与 research 模式耦合
- 任何 autoresearch 写入都会修改 research 共享表
- DB lock 竞争 / 备份 / 清理时无法独立处理

**变更内容**：
- 新增 `autoresearch/db.py`（`AutoResearchDatabase`），完全独立的 SQLite 文件
  - 路径：`~/.llmwikify/agent/autoresearch.db`
  - 表：`autoresearch_sessions / _sub_queries / _sources`
  - 6 步字段（`clarification_json / reasoning_json / structure_json` + 3 个扩展字段）**内置于 schema**，不再用 `ALTER TABLE`
- 重写 `db_migrations.py`：`init_autoresearch_db()` 替代 `ensure_six_step_columns()`，新增可选 `migrate_research_six_step_columns()` 清理旧 `.llmwiki_agent.db` 残留
- 5 个调用方 import / type hint 改（**公共方法名同形，调用方零代码逻辑改动**）
- `engine.py` 第 699 行裸 SQL 替换为 `db.update_six_step_fields()`
- `server/http/routes.py` 启动时创建独立 `AutoResearchDatabase(data_dir)`
- 测试 fixtures 改用独立 `AutoResearchDatabase`，新增 `TestAutoResearchDatabase`（14 个测试）覆盖表创建、字段、级联删除、零共享验证

**兼容性**：
- 公共方法名同形 → 现有 engine / session / gatherer / analyzer / routes 调用方零业务逻辑改动
- 旧数据不自动迁移（用户可手动调用 `migrate_research_six_step_columns`）
- 默认 status 从 `'planning'` 改为 `'clarifying'`（autoresearch 第一阶段是 clarify）

**验证**：
- 78 个 autoresearch 测试 + 110 个 research 测试 = **188 passed**，零回归
- `autoresearch.db` 不含 `research_sessions` 表
- `.llmwiki_agent.db` 不被 autoresearch 写入
- Server 启动日志显示两条独立 DB 路径

### v5 (2026-06-04) — 6 步门禁引擎集成 + 报告上下文注入

**变更动机**：v3-v4 完成了 6 步框架**骨架**（4 个 6 步门禁、3 个 6 步 checker、报告/评审框架块），但**引擎层未调度它们**——`engine.py:_evaluate_gate` 只调 4 个基础门禁；`ReasoningChecker` / `StructureValidator` 从未在 ReAct 循环中运行；`six_step_context` 从未传给报告生成器。现场跑 `POST /api/autoresearch/start`：clarify 跑完后所有 6 步字段除 `clarification_json` 外**全是 NULL**。

**变更内容**：
- `engine.py:_evaluate_gate`（A1）：在 4 个 phase 分支**叠加** 6 步门禁（gathering→check_evidence_quality / synthesizing→check_reasoning_quality / reporting→check_structure_quality / reviewing→check_framework_compliance）。6 步门禁与基础门禁叠加，任一失败触发 replan
- `engine.py:_action_gather`（A2）：gather 完成后遍历 `SourceFilter.compute_evidence_score`，写入 `state.evidence_scores: dict[str, float]`，并 `db.update_six_step_fields` 持久化
- `engine.py:_action_synthesize`（A3）：synthesize 完成后 instantiate `ReasoningChecker` 并 `state.reasoning_check = checker.check(...)`，持久化
- `engine.py:_action_report`（A4）：report 完成后 instantiate `StructureValidator` 并 `state.structure_check = validator.validate(...)`，持久化
- `engine.py:_action_report` / `_action_review`（B1+B2）：构建 `six_step_context = {clarification, reasoning_check, structure_check, evidence_scores}` 并作为 `generate_streaming` / `review.review` 的第 4 参数
- `engine.py:147`（A5）：`state.evidence_scores` 类型从 `list[float]` 改为 `dict[str, float]`（与 `update_six_step_fields.evidence_scores: dict` 签名一致）
- 4 个新守门：读取 `config["evidence_scoring_enabled"]` / `reasoning_check_enabled` / `structure_check_enabled` / `framework_check_enabled`
- 清理：删除 `engine.py:18` 和 `analyzer.py:11` 的两个**死 import**（`from llmwikify.agent.backend.db import AgentDatabase`）
- 新增 `TestAutoresearchIntegration` 类（D）：~7 个 e2e 测试验证完整 ReAct 循环 + 6 步门禁触发 + 6 步上下文传递

**兼容性**：
- 4 个 6 步开关默认 `True`（与 `framework_check_enabled` 既有配置一致）
- 失败行为：6 步门禁失败 → 引擎走 plan 重规划（受 `max_replan_attempts=2` 限制）
- 6 步门禁失败**优先级 >** 基础门禁失败（plan:170）

**验证**：
- 82 + 7 个 autoresearch 测试 = **89 passed**，零回归
- 完整 test suite（除 e2e + 3 个 pre-existing 失败）：**1290 passed, 0 regression**
- 现场跑 `POST /api/autoresearch/start` → `evidence_scores_json` / `reasoning_json` / `structure_json` 全部有值
- 报告生成器 prompt 实际收到非 None `six_step_context`

**实际影响**：
- v3-v4 的 6 步框架从"骨架"变为"运行中"——`check_evidence/reasoning/structure/framework_compliance` 4 个方法不再孤立
- 报告 prompt 自动注入 6 步框架 block（"本报告应反映 6 步"）
- 评审 prompt 自动注入 6 步框架 review block（"评审应覆盖 6 步"）

### v3 (2026-06-04) — 独立顶级子项目

详见本文件主体（928 行）。变更：
- `autoresearch/` 顶级子目录（与 `strategy/` 并列）
- 完全 copy 而非继承 / 组合
- 零 import 耦合到 `agent/backend/research/`
- 共享 `AgentDatabase`（v4 后改为独立 DB）+ `core/` 模块
