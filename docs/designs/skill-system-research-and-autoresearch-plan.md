# Skill System Research and AutoResearch Integration Plan

> 日期：2026-06-13
> 状态：调研与落地方案
> 目标：梳理 llmwikify 当前 Skill 体系，参考业界 Agent/Tool/Plugin 实践，提出将 AutoResearch 升级为 Chat 可调用 Skill/Workflow 的方案。

## 1. 背景

llmwikify 的 AutoResearch 方向正在从“一次性研究报告生成”升级为基于 Karpathy LLM Wiki 思想的持续复利研究系统。

目标链路：

```text
用户提出研究问题
  → Chat Agent 判断需要研究
  → 调用 AutoResearch Skill
  → Skill 内部执行 Workflow
  → 返回 report / evidence / findings / wiki proposals
  → 用户确认后沉淀到 Wiki / Graph / Research Memory
```

本阶段核心问题：

> 现有 Skill 体系是否足以支撑 Chat 直接调用 AutoResearch？如果不足，应该如何改造？

结论：现有 Skill 框架方向正确，但尚未成为 Chat 的一等工具系统。应优先补齐 `SkillRegistry / SkillRuntime → Chat Tool Adapter → CompositeToolRegistry` 这一层，然后再实现 `autoresearch_compound`。

## 2. 当前项目 Skill 体系

Skill 框架主要位于：

```text
src/llmwikify/apps/chat/skills/
```

核心抽象：

| 组件 | 文件 | 职责 |
|---|---|---|
| `SkillResult` | `src/llmwikify/apps/chat/skills/base.py:74` | 标准化 skill 返回值 |
| `SkillAction` | `src/llmwikify/apps/chat/skills/base.py:143` | skill 内部的可调用动作 |
| `SkillContext` | `src/llmwikify/apps/chat/skills/base.py:218` | 执行上下文，注入 wiki/db/llm/config/session |
| `Skill` | `src/llmwikify/apps/chat/skills/base.py:250` | 能力包，类似 plugin |
| `SkillManifest` | `src/llmwikify/apps/chat/skills/base.py:335` | 面向 LLM/外部系统的描述 |
| `SkillRegistry` | `src/llmwikify/apps/chat/skills/registry.py:56` | 注册、查找、聚合 skill/action |
| `SkillRuntime` | `src/llmwikify/apps/chat/skills/runtime.py:147` | 校验参数并执行 skill action |
| `SkillService` | `src/llmwikify/apps/chat/skills/service.py:25` | 初始化、注册、执行 skill 的 facade |

抽象映射：

```text
Skill = Plugin / ToolSpec
SkillAction = Tool / Function
SkillContext = Runtime Context
SkillResult = Tool Result
SkillRegistry = Tool Registry
SkillRuntime = Tool Executor
```

## 3. 当前已有能力

### 3.1 Base Action Skills

定义位置：

```text
src/llmwikify/apps/chat/skills/actions/__init__.py
```

覆盖能力包括：search、extract、read、write、lint、plan、analyze、summarize、score、revise、filter、graph、reason、observe、detect、clarify、web search 等。

注册入口：

```text
src/llmwikify/apps/chat/skills/actions/__init__.py:119
```

### 3.2 ResearchSkill

已有 `research_skill`：

```text
src/llmwikify/apps/chat/skills/research_skill.py:624
```

暴露动作：

```text
run_research
resume_research
cancel_research
```

相关位置：

```text
src/llmwikify/apps/chat/skills/research_skill.py:560
src/llmwikify/apps/chat/skills/research_skill.py:594
src/llmwikify/apps/chat/skills/research_skill.py:603
src/llmwikify/apps/chat/skills/research_skill.py:643
```

它内部实现了研究 pipeline：

```text
plan → gather → analyze → synthesize → score → revise → report
```

但它和当前生产 AutoResearch HTTP 路径不是同一条链路。

### 3.3 Dynamic Workflow Skill

已有 dynamic workflow skill：

```text
src/llmwikify/apps/chat/skills/workflows/skill.py:151
```

目标动作：

```text
dynamic_workflow.list
dynamic_workflow.run
dynamic_workflow.status
dynamic_workflow.resume
```

但当前 `SkillService.register_all()` 没有稳定注册它。这意味着 Workflow 能力存在，但默认不可由 Chat 发现和调用。

### 3.4 Workflow DSL

Workflow DSL：

```text
src/llmwikify/apps/chat/skills/workflows/dag.py
```

支持通过 YAML 描述 actors、phases、dependencies、inputs、limits、budget、prompt files、tool permissions。

内置 workflow 加载：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/__init__.py
```

已有 research workflow：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/llmwikify-research.yaml
```

已有 actor prompts：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/wikify-research-planner.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/wikify-phase-researcher.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/wikify-synthesizer.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/wikify-adversarial-verifier.md
```

## 4. 当前生产 Chat Tool 链路

当前 Chat 主链路主要走 `WikiToolRegistry`，不是 `SkillRegistry`。

关键文件：

```text
src/llmwikify/interfaces/server/http/chat_sse.py:57
src/llmwikify/apps/chat/agent/agent_service.py:28
src/llmwikify/apps/chat/agent/orchestrator.py:179
src/llmwikify/apps/wiki/service.py:188
src/llmwikify/apps/agent/tools/__init__.py:23
```

当前真实链路：

```text
Chat
  → ChatOrchestrator
  → WikiService.get_tool_registry()
  → WikiToolRegistry.list_tools()
  → LLM tool call
  → WikiToolRegistry.execute()
```

`WikiToolRegistry` 暴露工具列表：

```text
src/llmwikify/apps/agent/tools/__init__.py:670
```

执行工具：

```text
src/llmwikify/apps/agent/tools/__init__.py:682
```

当前不是：

```text
Chat → SkillRegistry → SkillRuntime
```

这是 AutoResearch Skill-first 方案的主要阻塞点。

## 5. 当前问题

### 5.1 Skill 没有成为 Chat 一等工具系统

当前存在两套并行体系：

```text
SkillRegistry / SkillRuntime
WikiToolRegistry
```

但 Chat 主要只接入 `WikiToolRegistry`。

影响：

- 新写 skill 不一定能被 Chat 看到。
- Workflow skill 即使存在，也不一定能被 Chat 调用。
- AutoResearch 如果只写成 skill，可能仍无法进入生产对话链路。

### 5.2 DynamicWorkflowSkill 未默认注册

`DynamicWorkflowSkill` 存在，但没有进入 `SkillService.register_all()`。

影响：

- Chat 无法发现 `dynamic_workflow.run`。
- 后续 `autoresearch_compound` 无法简单封装 dynamic workflow。

### 5.3 SkillService.execute 异步语义不清

`SkillService.execute()` 看起来是同步函数，但实际返回 `SkillRuntime.execute(...)` coroutine。

位置：

```text
src/llmwikify/apps/chat/skills/service.py:119
src/llmwikify/apps/chat/skills/service.py:165
```

建议改为：

```text
async def execute(...)
```

### 5.4 Confirmation 机制未完整落地

`SkillAction.requires_confirmation` 已有字段，但 `SkillRuntime` 目前没有完整强制 pre-confirmation。

位置：

```text
src/llmwikify/apps/chat/skills/runtime.py:257
```

影响：写 Wiki、应用 proposal、删除/覆盖等动作不能只靠 metadata，`apply_wiki_updates` 必须接入真正 human-in-loop。

### 5.5 JSON Schema 校验较弱

当前 runtime 只支持轻量 schema：required、primitive type、additionalProperties。

不完整支持 enum、items、nested object、anyOf / oneOf、string constraints、numeric constraints。

影响：对 `EvidenceItem[]`、`ResearchFinding[]`、`WikiUpdateProposal[]` 这类结构不够稳。

### 5.6 Tool name 兼容性风险

内部 qualified name 可能是：

```text
autoresearch_compound.run
```

但业界更推荐对外暴露：

```text
autoresearch_compound_run
```

原因：部分 provider 对点号、空格、特殊字符支持不一致；snake_case 对 LLM 更友好；LangChain、Semantic Kernel、LlamaIndex 都强调 name/description 对工具选择很关键。

## 6. 业界实践调研

参考对象：

- LangChain Tools
- Model Context Protocol Tools
- Microsoft Semantic Kernel Plugins
- LlamaIndex Tools / ToolSpecs
- Anthropic / Claude Skills 概念方向

### 6.1 LangChain Tools

核心模式：

```text
function → tool schema → model chooses tool → runtime executes → result returns to model
```

可借鉴点：

1. Tool 是带 schema 的函数。
2. name / description / parameters 对模型选择非常关键。
3. runtime context 不暴露给 LLM。
4. tool 可访问 state / context / store / stream_writer。
5. 支持动态工具选择，避免一次暴露太多工具。
6. 工具返回可以是 string、object、state update command。
7. 长任务工具可以 stream progress。

对 llmwikify 的启发：

```text
SkillContext ≈ ToolRuntime
SkillResult ≈ ToolMessage / structured result
SkillRegistry ≈ Tool Collection
```

建议：`wiki/db/session/user/config` 由 `SkillContext` 注入；LLM 只传业务参数；长任务返回 `run_id`，通过 `status` 或 SSE 获取进度。

### 6.2 MCP Tools

MCP 模型：

```text
tools/list
tools/call
```

Tool 定义包含 name、title、description、inputSchema、outputSchema、annotations。

Tool result 包含：

```text
content
structuredContent
isError
```

可借鉴点：标准化 discovery 和 invocation；支持 structuredContent；支持 outputSchema；支持 listChanged；强调 human-in-loop；强调 input validation、access control、rate limit、timeout、audit log。

对 llmwikify 的启发：

```text
SkillRegistry 应能导出 MCP-compatible tools/list。
SkillRuntime 应能执行 MCP-compatible tools/call。
SkillResult 应支持 structuredContent / isError。
```

建议：`SkillToolAdapter` 直接向 MCP 结果模型靠拢；同一套 skill 未来可同时供 Chat、HTTP、MCP 使用。

### 6.3 Semantic Kernel Plugins

Semantic Kernel 的模式：

```text
Plugin = 一组 functions
Function = 可由 AI 自动调用的动作
```

可借鉴点：

1. Plugin 封装一组相关能力。
2. Function 需要语义化 description。
3. LLM 通过 function calling 自动选择函数。
4. Plugin 可依赖注入服务、数据库、HTTP client。
5. Plugin 可从 native code、OpenAPI、MCP Server 导入。
6. 企业场景下 Plugin 比散乱 function 更好维护。

Semantic Kernel 还区分两类函数：

| 类型 | 说明 | llmwikify 对应 |
|---|---|---|
| Data retrieval function | 查询/检索信息 | wiki_search、graph_query、source_search |
| Task automation function | 执行动作/写入/变更 | wiki_write、apply_wiki_updates |

建议：`Skill` 应是一组相关 action，而不是一个 action 一个 skill；`autoresearch_compound` 应包含 run/status/resume/apply 等动作；写操作必须有 confirmation。

### 6.4 LlamaIndex Tools / ToolSpecs

LlamaIndex 的工具体系包括 `FunctionTool`、`QueryEngineTool`、`ToolSpec`、Utility Tools。

可借鉴点：

1. 任意函数可以包装成 Tool。
2. QueryEngine / Agent 也可以包装成 Tool。
3. ToolSpec 是一组围绕单一服务的工具集合。
4. 大结果不应直接塞回 LLM，可以缓存/索引后返回 handle。
5. description 对工具选择非常关键。
6. 支持 async tool。

对 llmwikify 的启发：AutoResearch 不应把所有中间材料直接返回 Chat；应返回 `run_id/session_id` + summary + artifact handles；详细 evidence/findings 可由 UI 或 status API 拉取。

### 6.5 Anthropic / Claude Skills 概念

Claude Skills 的理念更接近：

```text
Skill = instructions + resources + scripts + workflows
```

可借鉴点：Skill 不只是函数，也可以包含提示词、模板、脚本和领域知识；Skill 适合表达“如何完成某类任务”；对复杂任务，skill 应加载专门上下文和操作规程。

对 llmwikify 的启发：`autoresearch_compound` 不应只是一个 Python 函数，它应包含 workflow YAML、actor prompts、artifact schema、写入规则和审计规则。

## 7. 推荐目标架构

建议将 llmwikify Skill 体系整理成 4 层：

```text
Skill
  = 能力包 / plugin

SkillAction
  = 一个可调用 action / function / tool

Workflow
  = 多 action 编排 / DAG / long-running task

Tool Adapter
  = 把 SkillAction 暴露给 Chat / MCP / HTTP
```

目标链路：

```text
Chat
  → CompositeToolRegistry
      → WikiToolRegistry
      → SkillToolAdapter
          → SkillRegistry
          → SkillRuntime
              → SkillAction handler / Workflow
```

## 8. SkillToolAdapter 方案

新增：

```text
SkillToolAdapter
```

职责：

```text
list_tools()
execute(tool_name, arguments, context)
```

### 8.1 list_tools

从 `SkillRegistry.all_actions()` 生成 LLM tool schema。

外部 tool name 使用 snake_case：

```text
autoresearch_compound_run
```

内部映射：

```text
autoresearch_compound_run → autoresearch_compound.run
```

Tool schema 示例：

```json
{
  "name": "autoresearch_compound_run",
  "description": "Run compound AutoResearch and return report, evidence, findings, and wiki update proposals.",
  "parameters": {
    "type": "object",
    "properties": {
      "question": {"type": "string"},
      "wiki_id": {"type": "string"}
    },
    "required": ["question"]
  }
}
```

### 8.2 execute

执行链路：

```text
external tool name
  → resolve qualified skill action
  → build SkillContext
  → SkillRuntime.execute(skill, action, args, ctx)
  → normalize SkillResult
  → return tool observation
```

### 8.3 Result 规范

建议 `SkillResult` 向 MCP 靠拢：

```json
{
  "status": "ok|error|needs_confirmation|running",
  "content": "human readable summary",
  "structuredContent": {},
  "isError": false,
  "run_id": null,
  "confirmation_id": null
}
```

## 9. CompositeToolRegistry 方案

不要替换现有 `WikiToolRegistry`，而是做组合：

```text
CompositeToolRegistry
  - WikiToolRegistry
  - SkillToolAdapter
```

对 Chat 来说仍然只有一个 registry：

```text
list_tools()
execute(name, args)
confirm_execution(...)
```

好处：

1. 保留现有 wiki tools。
2. 降低迁移风险。
3. Skill 可以逐步接入。
4. 后续可以按场景动态筛选工具。

工具冲突策略：

- 优先禁止重名。
- SkillToolAdapter 对外统一加稳定前缀或 snake_case 映射。
- 发现重名时启动失败或记录清晰错误。

## 10. AutoResearch Skill 设计

不要把每个内部阶段都暴露给 Chat。外部暴露少量高层 action，内部用 workflow 编排。

推荐 skill 名称：

```text
autoresearch_compound
```

外部 tool：

```text
autoresearch_compound_run
autoresearch_compound_status
autoresearch_compound_resume
autoresearch_compound_apply_wiki_updates
```

内部 qualified name：

```text
autoresearch_compound.run
autoresearch_compound.status
autoresearch_compound.resume
autoresearch_compound.apply_wiki_updates
```

第一阶段只实现：

```text
autoresearch_compound.run
autoresearch_compound.status
```

`apply_wiki_updates` 留到 Phase 2，且必须要求 confirmation。

## 11. AutoResearch Workflow 设计

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

外部 Chat 只调用：

```text
autoresearch_compound_run({ question, wiki_id })
```

内部 workflow 负责：

```text
clarify → plan → gather → analyze → synthesize
→ extract_evidence
→ extract_findings
→ propose_wiki_updates
→ final_report
```

返回结构：

```json
{
  "run_id": "...",
  "report": "...",
  "evidence_items": [],
  "findings": [],
  "wiki_update_proposals": [],
  "open_questions": []
}
```

长任务推荐返回：

```json
{
  "status": "running",
  "run_id": "...",
  "content": "AutoResearch started. Use status to check progress."
}
```

完成后再由 status 或 UI 拉取完整 artifact。

## 12. Actor Prompt 设计

建议新增：

```text
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-clarifier.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-planner.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-evidence-extractor.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-finding-extractor.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-wiki-proposer.md
src/llmwikify/apps/chat/skills/workflows/builtins/actor_prompts/autoresearch-synthesizer.md
```

输出规范：

`evidence-extractor`：

```json
{
  "evidence_items": []
}
```

`finding-extractor`：

```json
{
  "findings": []
}
```

`wiki-proposer`：

```json
{
  "wiki_update_proposals": []
}
```

每个 finding 必须引用 evidence；无法证实时标记为 `uncertain`；proposal 只提出建议，不直接写 Wiki。

## 13. Tool 暴露策略

业界普遍不建议一次暴露太多工具。建议分层：

### 13.1 默认 Chat 工具

默认只暴露：

```text
wiki_search
wiki_read_page
wiki_write_page
research_save_to_wiki
autoresearch_compound_run
autoresearch_compound_status
```

### 13.2 高级工具按需暴露

只有当任务进入特定模式才暴露：

```text
dynamic_workflow_run
dynamic_workflow_status
skill_debug_list
skill_debug_run
```

### 13.3 写操作工具

写操作工具必须具备：

```text
requires_confirmation = pre
```

例如：

```text
wiki_write_page
autoresearch_compound_apply_wiki_updates
```

## 14. 安全与审计策略

借鉴 MCP 和 enterprise plugin 实践，建议所有 skill action 至少具备：

| 能力 | 要求 |
|---|---|
| input validation | 运行前校验参数 |
| timeout | 长任务必须有超时 |
| rate limit | 避免循环调用或滥用 |
| permission | 写操作和外部访问需要权限控制 |
| confirmation | 任何写 Wiki / 删除 / 覆盖必须 human-in-loop |
| audit log | 记录 tool name、args 摘要、session_id、result status |
| structured result | 尽量返回 structuredContent |
| error isolation | 工具错误返回给模型，不崩溃主 chat loop |

## 15. 落地阶段

### Phase 0：Skill Bridge

目标：Chat 可以看到并调用 SkillRegistry 中的 skill action。

任务：

1. 注册 `DynamicWorkflowSkill`。
2. 修正 `SkillService.execute` async 语义。
3. 新增 `SkillToolAdapter`。
4. 新增 `CompositeToolRegistry`。
5. Chat tool list 同时包含 wiki tools 和 selected skill tools。
6. 验证 Chat 可调用一个已有 skill。

验收：

- Chat tool list 中出现 skill action。
- Chat 可调用一个已有 skill。
- skill result 能作为 tool observation 返回。
- 现有 wiki tools 不受影响。

### Phase 1：AutoResearch Compound Skill

目标：让 Chat 通过 skill 启动 compound AutoResearch。

任务：

1. 新增 `autoresearch_compound` skill。
2. 新增 `autoresearch-compound.yaml`。
3. 新增 actor prompts。
4. `run` 调用 workflow。
5. `status` 查询 workflow run。
6. 返回 report、evidence、findings、wiki proposals。

验收：

- Chat 可调用 `autoresearch_compound_run`。
- 返回结构化 artifacts。
- 不自动写 Wiki。

### Phase 2：Apply Wiki Updates

目标：用户确认后应用 Wiki 更新建议。

任务：

1. 实现 `autoresearch_compound_apply_wiki_updates`。
2. 接入 confirmation。
3. 写入 research/evidence/concepts/questions 页面。
4. 写入 log。
5. 建立 wikilinks。
6. 生成 graph relations。

验收：

- 未确认不写入。
- 确认后多页写入 Wiki。
- 可审计。

### Phase 3：Research Memory 反哺

目标：下一次研究可复用历史 findings/evidence/open questions。

任务：

1. clarify/plan 前检索 research memory。
2. 区分已有知识与新增知识。
3. 发现矛盾时生成 contradiction task。
4. 从 graph node 发起研究。

验收：

- 同主题二次研究可复用上次沉淀。
- AutoResearch 产生知识复利。

## 16. 推荐执行顺序

建议真正开始实现时按以下顺序：

1. 只读确认 `SkillService.register_all()`。
2. 注册 `DynamicWorkflowSkill`。
3. 将 `SkillService.execute` 改为明确 async。
4. 新增 `SkillToolAdapter`。
5. 新增 `CompositeToolRegistry`。
6. 接入 ChatOrchestrator 的 tool registry 获取逻辑。
7. 用已有 skill 做最小 smoke test。
8. 新增 `autoresearch_compound`。
9. 新增 workflow YAML 和 actor prompts。
10. 最后接入 UI 和 save-to-wiki。

## 17. 最终建议

不要直接继续在 `ResearchEngine/actions.py` 里追加复杂逻辑。

优先路线：

```text
Skill Bridge
  → DynamicWorkflowSkill registration
  → CompositeToolRegistry
  → autoresearch_compound workflow
  → Chat 调用
  → human-in-loop 写 Wiki
```

这条路线更符合：

- 业界 Tool / Plugin / Skill 设计
- llmwikify 现有 Skill 框架
- AutoResearch 长期产品方向
- Karpathy LLM-maintained Wiki 思想

一句话结论：

> llmwikify 的 Skill 体系方向是对的，但现在缺的是从 SkillRegistry 到 Chat ToolRegistry 的桥；先打通这个桥，再把 AutoResearch 做成高层 skill，内部用 workflow/prompt 生成 report、evidence、findings 和 wiki proposals。
