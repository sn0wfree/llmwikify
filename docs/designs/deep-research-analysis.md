# Quick Research 系统分析报告

> 日期: 2026-05-29 | 分支: feature/deep-research-display-language | 版本: f4d8e7f

## 一、架构总览

核心流程是一个 **ReAct (Reason-Act-Observe) 循环**，最多 10 轮：

```
START → [REASON → ACT → OBSERVE → Quality Gate] × N → DONE
         ↓
    Plan → Gather → Analyze → Synthesize → Report → Review → (Revise?) → Done
```

### 模块清单（13 个后端模块）

| 文件 | 行数 | 职责 |
|------|------|------|
| `engine.py` | ~930 | 核心编排器：ReAct 循环、状态机、所有 action 实现 |
| `gatherer.py` | ~426 | 并行源抓取，early-exit、去重、per-source 超时 |
| `analyzer.py` | ~93 | 并行 LLM 源分析（wiki.analyze_source） |
| `synthesizer.py` | ~145 | 跨源综合，rating 加权聚合 |
| `report.py` | ~137 | Markdown 报告生成，`[[Source:hash]]` 引用 |
| `review.py` | ~126 | 报告质量评审 + 修订 |
| `quality_gate.py` | ~178 | 阶段转换质量门控 |
| `source_filter.py` | ~265 | 规则预过滤 + 质量评分 |
| `web_search.py` | ~274 | 多 Provider 搜索 + fallback 链 |
| `task_manager.py` | ~144 | 后台任务管理，per-session 事件队列 |
| `session.py` | ~84 | DB 持久化层 |
| `config.py` | ~51 | 配置默认值 + 合并 |
| `retry.py` | ~87 | 指数退避重试工具 |

### Prompt 模板（7 个研究相关）

| 模板 | 用途 | 参数 |
|------|------|------|
| `research_plan.yaml` | 分解 query 为 sub-query | max_tokens=2048, temp=0.3, json_mode |
| `research_replan.yaml` | 知识缺口补充规划 | max_tokens=1024, temp=0.3, json_mode |
| `analyze_source.yaml` | 单源结构化分析 | max_tokens=4096, temp=0.1 |
| `research_report.yaml` | 生成研究报告 | max_tokens=8192, temp=0.3 |
| `research_review.yaml` | 评审报告质量 | max_tokens=2048, temp=0.1, json_mode |
| `research_revise.yaml` | 根据评审修订报告 | max_tokens=8192, temp=0.3 |
| `wiki_synthesize.yaml` | Wiki 综合格式化 | - |

### 前端组件（12 个研究相关）

| 组件 | 职责 |
|------|------|
| `ResearchPanel.tsx` (1100行) | 会话列表、卡片交互、流消费、stage pipeline |
| `ResearchDetail.tsx` (316行) | 会话详情、子查询/源展示 |
| `ReportDetail.tsx` (468行) | 报告渲染、引用、表格、LaTeX |
| `CitationRef.tsx` (225行) | MD5 引用匹配、tooltip |
| `SaveToWikiModal.tsx` (93行) | 保存到 Wiki 确认弹窗 |
| `ConfirmationModal.tsx` (377行) | 工具确认详情、编辑模式 |
| `Confirmations.tsx` (188行) | 待确认列表面板 |
| `WikiViewer.tsx` (89行) | Wiki 页面查看器 |
| `api.ts` (542行) | API 调用、SSE 连接、事件解析 |

### API 端点（12 个）

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/research/start` | 启动新研究 |
| POST | `/{id}/resume` | 恢复暂停的会话 |
| GET | `/{id}/stream` | SSE 事件流 |
| GET | `/` | 列出所有会话 |
| GET | `/{id}` | 会话详情 |
| GET | `/{id}/sources` | 会话源列表 |
| GET | `/{id}/sub-queries` | 子查询列表 |
| POST | `/{id}/pause` | 暂停 |
| DELETE | `/{id}` | 取消/删除 |
| POST | `/{id}/save-to-wiki` | 保存到 Wiki |
| POST | `/{id}/rate` | 评分 |

---

## 二、核心步骤详解

### 1. Plan 阶段 (`engine.py:497-528`)

- 预搜索本地 wiki：`wiki.search(query, limit=5)`
- 读取 wiki index（前 3000 字符）
- LLM 分解为 3-10 个 sub-query，每个指定 source_type（wiki/web/youtube/pdf）
- 去重（case-insensitive），每轮最多 5 个新 sub-query
- 写入 DB `research_sub_queries` 表

### 2. Gather 阶段 (`gatherer.py:46-148`)

- **并发控制**：`asyncio.Semaphore(max_parallel)` 默认 5
- **Per-query 超时**：45 秒硬限制
- **Early-exit**：50% 任务完成 + 15 秒 grace 后取消剩余
- **URL 去重**：normalized URL set（去 protocol/www/尾斜杠/lowercase）
- **Fetch 重试**：2 次尝试，20 秒 hard timeout
- **Wiki 并行**：`parallel_wiki_search=True` 时 web + wiki 同时搜索

### 3. Analyze 阶段 (`analyzer.py:27-93`)

- 写入 `wiki.root/raw/research/{hash}.txt`
- 调用 `wiki.analyze_source(rel_path)`
- 输出：topics, entities, relations, claims, key_facts, quality_assessment
- 每个源独立分析，失败跳过

### 4. Synthesize 阶段 (`synthesizer.py:18-145`)

- Rating 加权：5→2.0x, 4→1.5x, 3→1.0x, 2→0.5x, 1→0.25x
- 逐源调用 `SynthesisEngine.analyze_new_source()`
- Wiki 交叉引用：搜索 wiki 中未被 gather 的页面（最多 5 个）
- 输出：reinforced_claims, contradictions, knowledge_gaps, new_entities, wiki_comparisons

### 5. Report 阶段 (`report.py:34-114`)

- 内容预算：per-source 4000 chars，总计 60000 chars
- LLM 生成 markdown，使用 `[[Source:hash]]` 引用
- 后验证：正则提取所有引用，检查 hash 有效性
- 3 次重试，120 秒 call timeout

### 6. Review 阶段 (`review.py:18-80`)

- LLM 评分 1-10，≥7 通过
- 输出：approved, score, feedback, issues[]
- 异常时创建默认 `{"approved": False, "score": 0}`

### 7. Revise 阶段 (`review.py:82-120`)

- 接收 issues + 原报告 + 源引用
- 修复所有问题，补充缺失引用
- 重置 review 为 None，触发重新评审

---

## 三、状态机

### 状态定义

| 状态 | 含义 |
|------|------|
| `planning` | 规划 sub-query |
| `gathering` | 抓取源 |
| `analyzing` | 分析源 |
| `synthesizing` | 综合 |
| `report` | 生成报告 |
| `reviewing` | 评审报告 |
| `done` | 完成 |
| `error` | 错误 |
| `paused` | 已暂停 |
| `pausing` | 暂停中（过渡态） |
| `cancelled` | 已取消 |
| `cancelling` | 取消中（过渡态） |
| `timeout` | 超时 |

### 状态转移图

```
                  ┌──────────────┐
                  │   planning   │
                  └──────┬───────┘
                         │
           ┌─────────────┼─────────────┐
           ▼             ▼             ▼
     ┌──────────┐  ┌──────────┐  ┌──────────┐
     │gathering │  │  error   │  │cancelling│
     └────┬─────┘  └──────────┘  └────┬─────┘
          │                            │
          ▼                            ▼
   ┌────────────┐               ┌──────────┐
   │ analyzing  │               │cancelled │
   └─────┬──────┘               └──────────┘
         │
         ▼
  ┌──────────────┐
  │ synthesizing │
  └──────┬───────┘
         │
         ▼
   ┌──────────┐
   │  report  │
   └─────┬────┘
         │
         ▼
  ┌────────────┐
  │ reviewing  │── review passed ──→ done
  └─────┬──────┘
        │ review failed
        ▼
  ┌──────────┐
  │  revise  │── rounds exhausted ──→ done
  └──────────┘

  Any running ←── POST /pause ──→ pausing ──→ paused
  Any running ←── DELETE / ──→ cancelling ──→ cancelled
  Timeout ──→ timeout
```

---

## 四、发现的问题与优化点

### 🔴 高优先级（影响功能正确性）

#### 1. Gatherer early-exit 过于激进

**位置**: `gatherer.py:55-57`

**现状**: 50% 任务完成 + 15s grace 后取消剩余任务

**问题**: 慢但有价值的源（PDF、arxiv、长文）可能被过早取消

**建议**: 改为按质量而非数量判断，或提高阈值到 70-80%

#### 2. 失败的 sub-query 没有重试

**位置**: `gatherer.py:364-373`

**现状**: 失败直接标记为 "failed"，永不重试

**问题**: 网络抖动导致永久丢失一个搜索方向

**建议**: 在下一轮 ReAct 中自动重试失败的 sub-query（检查 `status == "failed"`）

#### 3. Report 阶段无流式输出

**位置**: `report.py:89-103`

**现状**: 整个报告生成是阻塞式 LLM 调用（120s timeout）

**问题**: 用户在最耗时的阶段看不到任何进度

**建议**: 支持 report LLM 流式输出，边生成边展示（需要 SSE 支持 partial report 事件）

#### 4. Review 失败时静默创建默认失败结果

**位置**: `engine.py:626-629`

**现状**: LLM 调用异常时创建 `{"approved": False, "score": 0}`

**问题**: LLM 调用失败 ≠ 报告质量差，白白浪费一个 revise 轮次

**建议**: 异常时跳过 review，直接进入 done（标记为 "review_skipped"）

### 🟡 中优先级（影响性能/体验）

#### 5. 全量源内容存储在 SQLite

**位置**: `db.py:347`

**现状**: 每个 source 的完整内容（最大 500K chars）存入 `content` 列

**问题**: DB 膨胀，查询变慢，resume 时加载慢

**建议**: 大内容存文件系统（`raw/`），DB 只存 metadata + preview

#### 6. 控制信号每轮都读 DB

**位置**: `engine.py:392-403`

**现状**: `_check_control_signals()` 每次循环都 `get_research_session()`

**问题**: 不必要的 I/O

**建议**: 每 N 轮检查一次，或用 in-memory 事件（asyncio.Event）代替 DB 轮询

#### 7. 前端 SSE 无自动重连

**位置**: `api.ts:318-355`

**现状**: 流断开后用户必须手动 resume

**问题**: 网络不稳定时体验差

**建议**: 实现 exponential backoff 自动重连（1s → 2s → 4s → 8s，最多 5 次）

#### 8. 前端无 AbortController

**位置**: `ResearchPanel.tsx:563-564`

**现状**: `readerRef` 存了 reader 但没接 cancel 逻辑

**问题**: 导航离开后 fetch 继续运行，浪费资源

**建议**: 组件 unmount 时 abort 流

#### 9. ResearchDetail 不支持实时更新

**位置**: `ResearchDetail.tsx:43-63`

**现状**: 用一次性 REST 加载，不用 SSE

**问题**: 查看运行中的 session 看到的是过时数据

**建议**: 对 running 状态的 session 也建立 SSE 连接

### 🟢 低优先级（代码质量/可维护性）

#### 10. engine.py 过于庞大（930 行）

**现状**: 所有 action handler、reasoning、observation、state 都在一个类

**建议**: 拆分为 `Reasoner`、`ActionDispatcher`、`Observer` 子模块

#### 11. handleStreamEvent 是 120+ 行的 switch

**位置**: `ResearchPanel.tsx:632-755`

**现状**: 单一函数处理 16 种事件类型

**建议**: 用 strategy pattern 或 reducer 模式拆分

#### 12. 静默错误吞没

**位置**: 多处（loadSessions, handlePause, handleDelete）

**现状**: catch 后 silent，用户不知道操作是否成功

**建议**: 至少在 console.warn，或用 toast 提示

#### 13. 无可观测性指标

**现状**: 没有 LLM token 用量追踪、没有耗时统计、没有成本估算

**建议**: 在 engine 中添加 metrics 收集

#### 14. 状态机是隐式的

**现状**: Phase 分散在各个 action handler 中赋值，没有集中的状态验证

**建议**: 定义显式的状态转移表（dict[from_status] → set[to_status]）

---

## 五、优化建议优先级排序

| 优先级 | 优化项 | 预期收益 | 复杂度 |
|--------|--------|----------|--------|
| P0 | 失败 sub-query 自动重试 | 避免丢失搜索方向 | 低 |
| P0 | Review 异常不浪费轮次 | 减少无效 revise | 低 |
| P1 | Report 流式输出 | 大幅改善等待体验 | 中 |
| P1 | Gatherer early-exit 阈值调整 | 提高源质量 | 低 |
| P1 | 前端 SSE 自动重连 | 提高稳定性 | 中 |
| P2 | 源内容存文件系统 | DB 性能提升 | 中 |
| P2 | 控制信号检查频率优化 | 减少冗余 I/O | 低 |
| P2 | 前端 AbortController | 资源管理 | 低 |
| P3 | engine.py 拆分 | 可维护性 | 高 |
| P3 | 状态机显式化 | 代码健壮性 | 中 |
| P3 | 可观测性指标 | 调试/优化依据 | 中 |

---

## 六、数据流概览

```
User POST /start {query}
  → DB: INSERT research_sessions (status=planning)
  → TaskManager: create asyncio.Task + Queue

  [Background ReAct Loop]
  → Engine._react_loop()
      → _reason(): LLM or rule-based → pick action
      → _action_*(): execute action, yield events to Queue
      → _observe(): refresh state from DB
      → _evaluate_gate(): quality gate checks
      → loop until "done" or max rounds

  [SSE Consumer]
  GET /{id}/stream → TaskManager.get_event_stream()
    → reads from Queue → yields as SSE events

User POST /pause
  → DB: UPDATE status='pausing'
  → TaskManager: cancel asyncio.Task
  → Engine: _check_control_signals() detects 'pausing' → breaks loop
  → DB: UPDATE status='paused'

User POST /resume
  → TaskManager: create new asyncio.Task
  → Engine: _load_resume_state() from DB
  → ReAct loop continues from saved state

User POST /save-to-wiki
  → Registry.execute("research_save_to_wiki")
  → requires_confirmation="pre" → returns confirmation_required
  → User POST /confirmations/{id} (approve)
  → Registry.confirm_execution() → _handle_research_save()
  → Writes report + sources + synthesis to wiki
```

---

## 七、配置参考

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `max_sub_queries` | 20 | 每轮最大 sub-query 数 |
| `max_source_content_length` | 500,000 | 单源最大内容长度 |
| `research_timeout_minutes` | 30 | 总超时（分钟） |
| `max_parallel_gathering` | 5 | 并行抓取数 |
| `web_search_results_per_query` | 5 | 每次搜索结果数 |
| `max_retry_attempts` | 3 | LLM 重试次数 |
| `similarity_threshold` | 0.92 | 去重相似度阈值 |
| `max_review_rounds` | 2 | 最大评审轮次 |
| `max_react_rounds` | 10 | 最大 ReAct 循环数 |
| `quality_threshold` | 7 | 评审通过分数 |
| `max_replan_attempts` | 2 | 最大重新规划次数 |
| `gate_min_sources` | 3 | Gather 门控最小源数 |
| `gate_min_type_diversity` | 2 | Gather 门控最小类型多样性 |
| `gate_min_analyzed` | 2 | Analyze 门控最小分析数 |
| `gate_min_avg_credibility` | 5 | Analyze 门控最小平均可信度 |
| `gate_max_knowledge_gaps` | 3 | Synthesize 门控最大知识缺口 |
| `gate_min_reinforced_claims` | 2 | Synthesize 门控最小强化主张 |
