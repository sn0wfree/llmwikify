# AutoResearch Compounding Wiki Upgrade

> 日期：2026-06-13
> 状态：规划草案
> 目标：将现有 AutoResearch 从“一次性研究报告生成”升级为符合 Karpathy LLM Wiki 思想的“持续复利研究系统”。

## 1. 背景

当前 AutoResearch 已具备 6 步研究框架、session 管理、source gather/analyze、synthesis、report、review、save-to-wiki 等能力。

现有链路更接近：

```text
query → research session → report → save-to-wiki
```

目标升级为：

```text
query → clarify/plan/gather/analyze/synthesize/report/review
  → evidence cards
  → findings
  → wiki update proposals
  → human confirm
  → wiki pages + graph relations + research memory
```

核心思想：AutoResearch 不只是生成报告，而是让每次研究都沉淀为可复用的 Wiki 知识资产，使下一次研究站在已有知识之上。

## 2. 产品定位

建议定位为：

> AutoResearch as LLM-maintained Wiki

也可以称为：

> Compounding AutoResearch Loop

它和普通 Deep Research 的区别：

| 类型 | 输出 | 是否复利 |
|---|---|---|
| 普通 Deep Research | 一份报告 | 弱 |
| llmwikify AutoResearch | 报告 + 证据卡 + 研究发现 + Wiki 更新建议 + Graph 关系 + Research Memory | 强 |

## 3. 保留现有 ResearchEngine

现有流程不推倒重来，保留：

1. clarify
2. plan
3. gather
4. analyze
5. synthesize
6. report
7. review / revise

升级重点放在 `report/review` 之后的知识沉淀层。

建议目标流程：

```text
clarify → plan → gather → analyze → synthesize → report → review
  → propose
  → confirm
  → compound
  → done
```

## 4. 新增核心 Artifact

建议新增 4 类结构化 artifact。

### 4.1 EvidenceItem

每条证据的最小单元。

字段建议：

```json
{
  "id": "evidence_xxx",
  "session_id": "...",
  "source_id": "...",
  "title": "...",
  "source_type": "web|wiki|pdf|paper|raw|data",
  "url": null,
  "quote": "...",
  "summary": "...",
  "supports": [],
  "contradicts": [],
  "confidence": 0.0,
  "relevance": 0.0,
  "source_location": null
}
```

作用：把 source 从“全文材料”变成可引用、可复用、可审计的证据卡。

### 4.2 ResearchFinding

研究发现。

字段建议：

```json
{
  "id": "finding_xxx",
  "session_id": "...",
  "claim": "...",
  "summary": "...",
  "confidence": "high|medium|low|uncertain",
  "evidence_ids": [],
  "contradiction_ids": [],
  "implications": [],
  "open_questions": []
}
```

作用：将报告里的结论结构化，便于下一次研究检索和推理。

### 4.3 WikiUpdateProposal

Wiki 更新建议，不直接覆盖。

字段建议：

```json
{
  "id": "proposal_xxx",
  "session_id": "...",
  "type": "create|update|append|link|graph_edge",
  "target_page": "research/topic.md",
  "title": "...",
  "content": "...",
  "rationale": "...",
  "evidence_ids": [],
  "risk": "low|medium|high",
  "requires_confirmation": true
}
```

作用：贯彻 human-in-loop。AI 只提议，人确认后写入。

### 4.4 ResearchMemory

本次研究可反哺后续研究的记忆。

字段建议：

```json
{
  "session_id": "...",
  "topic": "...",
  "summary": "...",
  "key_findings": [],
  "known_contradictions": [],
  "open_questions": [],
  "recommended_followups": [],
  "wiki_pages": [],
  "graph_nodes": []
}
```

作用：下一次研究开始前检索，作为 prior context。

## 5. Save-to-wiki 升级方向

当前 save-to-wiki 更接近保存最终报告。升级后应变为知识沉淀动作。

建议写入多类页面：

```text
wiki/research/<topic>.md        研究报告和结论
wiki/evidence/<source>.md       证据卡片
wiki/concepts/<concept>.md      概念页
wiki/questions/<question>.md    问题页
wiki/log.md                     研究日志
```

建议写入图谱关系：

```text
Question investigates Concept
Finding supported_by Evidence
Finding contradicts Finding
Concept related_to Concept
Report summarizes Source
WikiPage derived_from ResearchSession
ResearchSession produced Finding
```

## 6. UI 升级方向

`/agent/autoresearch` 从“报告查看器”升级为研究工作台。

建议 tab：

| Tab | 内容 |
|---|---|
| Overview | 研究状态、质量评分、最终摘要、进度 |
| Evidence | 证据卡片、来源、引用、可信度 |
| Findings | 结构化发现、支持证据、矛盾、开放问题 |
| Report | 完整研究报告 |
| Wiki Updates | 建议新增/修改页面、graph edge、风险、确认按钮 |

关键按钮：

- Start Research
- Resume
- Pause
- View Evidence
- Review Wiki Updates
- Apply to Wiki

## 7. 最小实施路线

### Phase 1：结构化沉淀，不改主流程

目标：不动现有 ResearchEngine 主循环，只在 report/review 后生成结构化结果。

任务：

1. 从 `sources`、`analysis`、`synthesis_json` 生成 `EvidenceItem[]`
2. 从 `synthesis_json` 和 report 生成 `ResearchFinding[]`
3. 生成 `WikiUpdateProposal[]`
4. 在 session detail API 返回这些结构
5. WebUI 新增 Evidence / Findings / Wiki Updates 展示

验收：用户能看到报告之外的证据卡、发现和 Wiki 更新建议，但不会自动写入。

### Phase 2：确认后写入 Wiki

目标：把 save-to-wiki 从“保存报告”升级为“应用 Wiki 更新建议”。

任务：

1. 扩展 `/save-to-wiki` 请求参数，支持选择 proposal
2. 写入 research/evidence/concepts/questions 页面
3. 更新 `wiki/log.md`
4. 建立 wikilinks
5. 生成/写入 graph relation
6. 保留人工确认流

验收：用户确认后，研究结果变成多页 Wiki 知识，而不只是一篇报告。

### Phase 3：Research Memory 反哺下一次研究

目标：新研究开始前优先检索已有研究记忆。

任务：

1. 在 clarify/plan 前检索相关 research pages、findings、evidence、open questions
2. 将历史发现作为 planning context
3. 如果发现已有结论，提示“已有研究基础”
4. 如果发现矛盾，生成 contradiction task
5. 在报告中区分“已有知识”和“本次新增知识”

验收：连续研究同一主题时，第二次研究能复用第一次沉淀的内容。

### Phase 4：Graph 驱动研究导航

目标：研究不只围绕文本检索，也围绕图谱探索。

任务：

1. 从 ResearchFinding / EvidenceItem 生成 graph nodes/edges
2. 支持从 graph node 发起研究
3. 支持“找矛盾”“找缺口”“找桥接概念”
4. AutoResearch plan 阶段可引用 graph neighbors / shortest path / communities

验收：用户可以从 Wiki Graph 中发现研究问题并启动 AutoResearch。

## 8. 风险与约束

| 风险 | 对策 |
|---|---|
| AI 自动写 Wiki 造成污染 | 所有写入走 proposal + confirmation |
| artifact 过多导致 UI 复杂 | Phase 1 只展示 Evidence / Findings / Wiki Updates 三类 |
| 数据库 schema 膨胀 | 可先用 JSON 字段落地，稳定后再拆表 |
| 证据引用不可靠 | EvidenceItem 必须保留 source_id、quote、source_location |
| 研究结果不可复现 | 保存 prompt version、source snapshot、model config、session events |
| 与现有 save-to-wiki 冲突 | 保留旧模式，新增 proposal mode |

## 9. 推荐优先级

1. ResearchFinding JSON
2. EvidenceItem JSON
3. WikiUpdateProposal JSON
4. UI 展示 proposals
5. 确认后多页面写入 Wiki
6. Graph relation 写入
7. 下一轮 Research 检索历史 memory

## 10. 一句话结论

不要把 AutoResearch 做成“生成报告工具”，而要升级成：

> 每次研究都会产生证据、发现、页面更新建议和图谱关系；用户确认后沉淀进 Wiki，使下一次研究自动站在已有知识之上。

## 11. 方案调整：Skill-first AutoResearch

经过讨论，优先采用 Skill-first 方案：不继续把 AutoResearch 的升级逻辑硬编码到 `ResearchEngine` / `actions.py` 中，而是把它做成 Chat Agent 可调用的 Skill / Workflow。

### 11.1 调整原因

原始方案是在现有 AutoResearch `done` 前后追加 artifact builder：

```text
/api/autoresearch/start
  → ResearchEngine
  → hard-coded actions
  → report
  → artifacts
```

调整后希望变成：

```text
Chat
  → LLM 判断需要研究
  → 调用 autoresearch_compound skill
  → workflow 执行 clarify/plan/gather/analyze/synthesize/propose
  → 返回 report + artifacts
  → 用户确认后再调用 apply-to-wiki skill
```

核心变化：

```text
AutoResearch 不只是一个独立页面按钮触发的流程，而是 Chat Agent 的一个研究能力。
```

### 11.2 现有架构基础

项目中已经存在 Skill / Workflow 基础设施：

- `Skill / SkillAction / SkillContext`
  - `src/llmwikify/apps/chat/skills/base.py`
- `SkillRegistry`
  - `src/llmwikify/apps/chat/skills/registry.py`
- `SkillRuntime`
  - `src/llmwikify/apps/chat/skills/runtime.py`
- 已有 research skill
  - `src/llmwikify/apps/chat/skills/research_skill.py`
- 已有 dynamic workflow skill
  - `src/llmwikify/apps/chat/skills/workflows/skill.py`
- 已有内置 research workflow
  - `src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml`

关键问题不是没有 Skill 框架，而是 Chat 主链路目前主要暴露的是 `WikiToolRegistry` 工具，SkillRegistry 里的 action 还没有稳定作为 LLM tool 暴露给 Chat。

因此第一优先级应是打通：

```text
SkillRegistry / SkillRuntime → Chat Tool Registry → LLM function tools
```

### 11.3 新目标架构

目标链路：

```text
用户：
“帮我研究一下 XXX”

Chat LLM：
识别 research intent

Chat tool call：
autoresearch_compound.run({
  question: "...",
  wiki_id: "...",
  mode: "compound"
})

SkillRuntime：
加载并执行 autoresearch-compound workflow

Workflow：
clarify → plan → gather → analyze → synthesize
→ extract_evidence
→ extract_findings
→ propose_wiki_updates
→ final_report

返回给 Chat：
{
  "report": "...",
  "evidence_items": [],
  "findings": [],
  "wiki_update_proposals": [],
  "open_questions": []
}

Chat：
展示研究结果，并询问是否应用到 Wiki
```

### 11.4 Phase 0：Chat → Skill Bridge

目标：让 Chat Agent 可以看到并调用 SkillRegistry 中的 skill action。

建议新增一个适配层：

```text
SkillRegistry → ToolSpec Adapter → Chat Tool Registry
```

适配后的 LLM tool 示例：

```json
{
  "name": "autoresearch_compound.run",
  "description": "Run compound AutoResearch and return report, evidence, findings, and wiki update proposals.",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "wiki_id": {"type": "string"},
      "mode": {"type": "string", "enum": ["compound"]}
    },
    "required": ["question"]
  }
}
```

执行时调用：

```text
SkillRuntime.execute("autoresearch_compound.run", args, context)
```

涉及区域：

- `src/llmwikify/apps/chat/skills/service.py`
- `src/llmwikify/apps/chat/skills/runtime.py`
- `src/llmwikify/apps/agent/tools/__init__.py`
- `src/llmwikify/apps/chat/agent/orchestrator.py`

验收标准：

1. Chat tool list 中可以出现 skill action。
2. Chat LLM 可以通过 tool call 调用 skill。
3. skill 执行结果可以作为 tool observation 回到 Chat。
4. 不破坏现有 wiki tools。

### 11.5 Phase 1：新增 `autoresearch_compound` Skill

建议新增独立 skill，而不是直接改旧 `research_skill`。

原因：

- 旧 `research_skill` 更像一次性 research pipeline。
- 新 skill 目标是 Wiki 复利沉淀。
- 避免破坏旧逻辑。

建议 skill 名称：

```text
autoresearch_compound
```

建议 actions：

```text
autoresearch_compound.run
autoresearch_compound.status
autoresearch_compound.resume
autoresearch_compound.propose_wiki_updates
autoresearch_compound.apply_wiki_updates
```

Phase 1 只实现：

```text
autoresearch_compound.run
autoresearch_compound.status
```

`apply_wiki_updates` 留到 Phase 2。

### 11.6 Phase 1 Workflow：`autoresearch-compound.yaml`

新增内置 workflow：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/autoresearch-compound.yaml
```

建议阶段：

```text
clarify
plan
gather
analyze
synthesize
extract_evidence
extract_findings
propose_wiki_updates
final_report
```

示意：

```yaml
name: autoresearch-compound
description: Compound AutoResearch workflow that produces report, evidence, findings, and wiki update proposals.
inputs:
  question:
    type: string
    required: true
  wiki_id:
    type: string
    required: false
phases:
  clarify:
    actor: clarifier
  plan:
    actor: planner
    needs: [clarify]
  gather:
    actor: researcher
    needs: [plan]
  analyze:
    actor: researcher
    needs: [gather]
  synthesize:
    actor: synthesizer
    needs: [analyze]
  extract_evidence:
    actor: evidence_extractor
    needs: [synthesize]
  extract_findings:
    actor: finding_extractor
    needs: [extract_evidence]
  propose_wiki_updates:
    actor: wiki_proposer
    needs: [extract_findings]
  final_report:
    actor: synthesizer
    needs: [propose_wiki_updates]
```

### 11.7 Actor Prompts

新增或复用 actor prompt 文件：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-clarifier.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-planner.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-evidence-extractor.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-finding-extractor.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-wiki-proposer.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-synthesizer.md
```

每个 actor 负责输出结构化结果，而不是由 Python 硬编码生成。

`evidence-extractor` 输出：

```json
{
  "evidence_items": []
}
```

`finding-extractor` 输出：

```json
{
  "findings": []
}
```

`wiki-proposer` 输出：

```json
{
  "wiki_update_proposals": []
}
```

### 11.8 和原计划的区别

| 维度 | 原方案 | Skill-first 方案 |
|---|---|---|
| 触发方式 | `/api/autoresearch/start` | Chat tool call |
| 流程位置 | ResearchEngine / actions.py | Skill / Workflow |
| 扩展方式 | Python action | YAML workflow + actor prompt |
| 是否硬编码 | 较多 | 较少 |
| Chat 是否可直接调用 | 弱 | 强 |
| 是否方便新增垂直研究能力 | 一般 | 强 |
| 是否符合 Agent 架构 | 一般 | 更好 |

### 11.9 新版 Phase 1 定义

新版 Phase 1 改为：

> 让 Chat 可以通过 Skill 调用 AutoResearch Compound Workflow，并返回结构化 artifacts，但不写入 Wiki。

验收标准：

1. Chat 工具列表中能看到 `autoresearch_compound.run`。
2. 用户在 Chat 中提出研究问题时，LLM 可以调用该 skill。
3. skill 返回：
   - report
   - evidence_items
   - findings
   - wiki_update_proposals
   - open_questions
4. 不自动写 Wiki。
5. 用户确认写入 Wiki 的能力留到 Phase 2。

### 11.10 推荐执行顺序

1. 打通 Chat → Skill Bridge。
2. 确认并注册 dynamic workflow skill。
3. 新增 `autoresearch-compound.yaml`。
4. 新增 actor prompts。
5. 新增 `autoresearch_compound` skill 作为 workflow 的薄封装。
6. 让 Chat tool list 暴露 `autoresearch_compound.run`。
7. 在 Chat 中测试研究问题触发。
8. 后续再将结果接入 `/agent/autoresearch` 页面。

### 11.11 规划结论

下一步不应优先修改 `ResearchEngine/actions.py`。

优先做：

```text
Skill Bridge → dynamic workflow registration → autoresearch-compound workflow → Chat 调用
```

这样 AutoResearch 会从“独立功能”升级成“Agent Skill 能力”，同时更符合 LLM-maintained Wiki 的长期方向。
