# Agent Framework & Quick Research — 设计文档

> 创建时间：2025-05-25
> 最后更新：2025-05-25（全面更新：新增 5.7-5.10，LLM 适配层、SSE/JWT 认证、Chat 会话管理、评分机制）

---

## 一、项目背景与目标

**总目标**：将 Agent 框架构建为独立界面和应用，深度绑定 llmwikify 项目，同时新增 Quick Research（深度研究）功能。

**约束**：
- WebUI 不依赖 npm 环境，采用方案 D（内联到 Python 包）
- Agent 框架先在此项目内，成熟后可拆分为独立项目

**用户决策**：
1. Agent 界面形态：混合模式（Chat 对话 + Task 面板）
2. Autoresearch 范围：内部 + 网络 + 视频/YouTube
3. LLM 支持：Ollama（本地主力）+ OpenAI（复杂推理）
4. Quick Research 执行方式：同步 + 异步均支持

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  React WebUI（Agent 界面）                                    │
│  ├─ Chat 视图（流式输出 + 工具调用展示）                       │
│  ├─ Research 面板（研究会话列表 + 进度）                       │
│  ├─ Confirmations 面板（批量审批）                            │
│  └─ Dream Proposals 面板（编辑提案审批）                       │
└────────────────────────────┬─────────────────────────────────┘
                             │ REST + SSE 流式传输
┌────────────────────────────┴─────────────────────────────────┐
│  WikiServer (FastAPI)                                        │
│  ├─ /agent/*      （新增 Agent REST 路由）                   │
│  ├─ /research/*   （新增 Research REST 路由）                │
│  ├─ /api/wiki/*   （现有 Wiki REST 路由）                     │
│  └─ /mcp          （MCP ASGI 接入外部 Agent）                 │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────┴─────────────────────────────────┐
│  Agent Core                                                 │
│  ├─ AgentService       （新 — 替代废弃的 WikiAgent）           │
│  ├─ ToolRegistry      （增强的 WikiToolRegistry）             │
│  ├─ LLMClient         （增强 — 流式输出 + function calling）   │
│  ├─ MemoryManager     （来自 legacy）                          │
│  └─ HookSystem        （来自 legacy）                          │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────┴─────────────────────────────────┐
│  Research Engine（新增）                                       │
│  ├─ ResearchSession    （研究会话管理 + 状态持久化）           │
│  ├─ WebSearch         （Web 搜索 API — DuckDuckGo）          │
│  ├─ SourceGatherer    （并行摄取 URL/YouTube/PDF/Wiki）      │
│  └─ ReportSynthesizer （多源综合报告生成）                    │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、数据库设计

**路径**：`wiki_root / ".llmwiki_agent.db"`（独立数据库，不与 `.llmwikify.db` 共用）

### 表结构

```sql
-- 1. Chat 会话
CREATE TABLE chat_sessions (
    id TEXT PRIMARY KEY,
    title TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,  -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    tool_calls TEXT,     -- JSON: [{tool, args, result}]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
);

-- 2. 工具调用日志（用于 confirmations）
CREATE TABLE tool_calls (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL,  -- JSON
    result TEXT,              -- JSON
    status TEXT NOT NULL,     -- 'pending' | 'approved' | 'rejected' | 'executed'
    confirmation_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    executed_at TIMESTAMP
);

-- 3. 深度研究会话
CREATE TABLE research_sessions (
    id TEXT PRIMARY KEY,
    query TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'planning' | 'gathering' | 'analyzing' | 'synthesizing' | 'done' | 'paused' | 'error'
    progress REAL DEFAULT 0.0,
    current_step TEXT,
    result TEXT,           -- JSON: ResearchReport
    wiki_page_name TEXT,  -- 保存到的 Wiki 页面名
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. 研究子查询
CREATE TABLE research_sub_queries (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    query TEXT NOT NULL,
    source_type TEXT NOT NULL,  -- 'web' | 'youtube' | 'pdf' | 'wiki'
    url TEXT,
    status TEXT NOT NULL,      -- 'pending' | 'in_progress' | 'done' | 'failed'
    result TEXT,                -- JSON: ExtractedContent
    error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id)
);

-- 5. 摄取的来源引用
CREATE TABLE research_sources (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    title TEXT,
    content_length INTEGER,
    analysis TEXT,  -- JSON: {entities, relations, topics, claims}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES research_sessions(id)
);

-- 6. Dream 编辑提案（来自 legacy，可复用）
CREATE TABLE dream_proposals (
    id TEXT PRIMARY KEY,
    page_name TEXT NOT NULL,
    edit_type TEXT NOT NULL,  -- 'append' | 'create' | 'insert_before' | 'replace'
    content TEXT NOT NULL,
    reason TEXT,
    content_length INTEGER,
    status TEXT NOT NULL,     -- 'pending' | 'approved' | 'rejected' | 'applied'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP
);
```

---

## 四、核心组件设计

### 4.1 AgentService（新）

```python
class AgentService:
    def __init__(self, wiki: Wiki, llm_client: LLMClient, db_path: Path)

    # 对话（SSE 流式）
    async def chat(
        message: str,
        session_id: str | None = None,
        stream: bool = True,
    ) -> AsyncIterator[ChatEvent]

    # 会话管理
    async def list_sessions() -> list[ChatSession]
    async def get_session(session_id: str) -> ChatSession
    async def delete_session(session_id: str)

    # 工具
    async def execute_tool(name: str, arguments: dict) -> ToolResult
    async def list_tools() -> list[ToolDef]

    # 审批
    async def list_confirmations() -> list[Confirmation]
    async def approve_confirmation(id: str)
    async def reject_confirmation(id: str)
    async def batch_confirm(ids: list[str], action: str)  # 'approve' | 'reject'
```

### 4.2 LLMClient 增强

```python
class LLMClient:
    def chat(
        self,
        messages: list[dict],
        tools: list[ToolDef] | None = None,  # function calling
        stream: bool = False,
        **generation_params
    ) -> str | AsyncIterator[str]
```

**关键改动**：
- 从 `requests.post` 改为 `openai` SDK（支持 streaming）
- 添加 `tools` 参数支持 function calling
- SSE 实时推送 tool_call 事件给前端
- 支持 Ollama/OpenAI 双 provider，通过统一配置切换模型

**适配层设计**：
- Ollama 和 OpenAI 的 API 格式存在差异，需要抽象适配层统一处理
- `LLMAdapter` 接口定义统一方法：`chat()`, `stream_chat()`, `list_models()`
- `OpenAIAdapter`：标准 OpenAI API 格式
- `OllamaAdapter`：适配 Ollama 的 `/api/chat` 格式
- 模型切换通过配置 `llm.model` 实现，无需改代码

### 4.3 ResearchEngine

```python
@dataclass
class ResearchSession:
    id: str
    query: str
    status: str
    sub_queries: list[SubQuery]
    sources_gathered: list[SourceRef]
    current_step: str
    progress: float
    result: ResearchReport | None
    created_at: datetime
    updated_at: datetime

@dataclass
class SubQuery:
    id: str
    query: str
    source_type: str  # web | youtube | pdf | wiki
    url: str | None
    status: str
    result: ExtractedContent | None

@dataclass
class ResearchReport:
    query: str
    summary: str
    sections: list[ReportSection]
    citations: list[Citation]
    wiki_page_name: str | None
```

---

## 五、Quick Research 核心功能详解

### 5.1 核心定位

Quick Research 是一个**多源异步研究助手**，用户输入一个研究主题，系统自动完成：子查询分解 → 多源并行摄取 → 跨源综合分析 → 结构化报告生成 → 保存为 Wiki 页面。

### 5.2 六阶段研究流程

```
User: "Research LLM Agents"
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  1. PLANNING                                            │
│     - LLM 分解为子查询：                                 │
│       ["LLM Agents 定义", "LLM Agents 架构",             │
│        "LLM Agents 应用场景", "最新研究进展"]             │
│     - 确定每条查询的 source_type                         │
│     - 保存到 research_sessions 表                       │
└────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  2. GATHERING（并行）                                   │
│     ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│     │ Web 搜索    │  │ YouTube    │  │ Wiki 内部  │ │
│     │ DuckDuckGo │  │ 字幕提取   │  │ FTS5 搜索  │ │
│     └─────────────┘  └─────────────┘  └─────────────┘ │
│     - 保存到 research_sources 表                       │
└────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  3. ANALYSIS                                           │
│     - 每条 source 调用 wiki_analyze_source              │
│     - 提取 entities, relations, topics, claims         │
│     - 更新 research_sources.analysis                   │
└────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  4. SYNTHESIS                                          │
│     - wiki_suggest_synthesis 跨源综合                   │
│     - 找矛盾、找 gap、找 reinforced claims             │
└────────────────────────────────────────────────────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│  5. REPORT                                             │
│     - 生成 markdown 报告                               │
│     - 自动保存为 Wiki 页面                             │
│     - 流式返回每一步进展                               │
└────────────────────────────────────────────────────────┘
```

### 5.3 支持的来源类型

| 来源类型 | 获取方式 | 内容 |
|----------|----------|------|
| `web` | DuckDuckGo 搜索 + trafilatura 提取 | 网页正文文章 |
| `youtube` | YouTubeTranscriptApi 字幕提取 | 视频文字稿 |
| `pdf` | PyMuPDF 提取 | PDF 全文 |
| `wiki` | 内部 FTS5 搜索 | Wiki 已有点 |
| `file` | MarkItDown 通用提取 | Office/图片/音频等 |

### 5.4 跨源综合类型

| 类型 | 说明 | 判断标准 |
|------|------|---------|
| `reinforced_claims` | 多源确认的强声明 | ≥2 个来源支持，overlap ≥ 0.4 |
| `contradictions` | 来源间的矛盾声明 | overlap ≥ 0.5 + 立场相反 |
| `knowledge_gaps` | 主题有提及但 Wiki 未覆盖 | 研究中出现但 Wiki 搜索为空 |
| `new_entities` | Wiki 中不存在的新实体 | 来源有但 Wiki 索引查不到 |
| `suggested_updates` | 已有页面应更新 | 新来源补充了已有页面的内容 |

### 5.5 异步执行与进度追踪

**执行模式**：

| 模式 | 说明 | 适用场景 |
|------|------|---------|
| `sync`（同步） | 阻塞等待，结果实时流式推送 | 快速研究（< 5 分钟） |
| `async`（异步） | 后台执行，轮询或 SSE 推送进度 | 长研究任务（> 5 分钟） |

**进度事件流**（SSE）：
```
→ {"type": "step", "step": "planning", "message": "正在分解研究主题..."}
→ {"type": "step", "step": "gathering", "message": "开始摄取来源..."}
→ {"type": "source_gathered", "source_id": "s1", "source_type": "web", "title": "LLM Agents 综述"}
→ {"type": "progress", "progress": 0.45, "message": "已摄取 5/12 个来源"}
→ {"type": "step", "step": "analyzing", "message": "正在分析来源..."}
→ {"type": "section_complete", "section": "执行摘要", "content": "..."}
→ {"type": "done", "report": {...}, "wiki_page_name": "Research: LLM Agents"}
```

### 5.6 研究会话状态

| 状态 | 说明 |
|------|------|
| `planning` | 正在分解主题 |
| `gathering` | 正在摄取来源 |
| `analyzing` | 正在分析来源 |
| `synthesizing` | 正在综合 |
| `done` | 完成 |
| `paused` | 暂停（可恢复） |
| `error` | 出错 |

### 5.7 研究限制与边界

以下参数可通过配置文件调整：

| 限制项 | 默认值 | 说明 |
|--------|--------|------|
| `max_sub_queries` | 20 | 单次研究最大子查询数 |
| `max_source_content_length` | 500,000 | 单来源最大内容字符数（超出截断） |
| `research_timeout_minutes` | 30 | 研究超时（分钟） |
| `max_parallel_gathering` | 5 | 最大并行摄取数 |
| `web_search_results_per_query` | 5 | Web 搜索每查询结果数 |
| `max_retry_attempts` | 3 | 来源获取最大重试次数 |
| `similarity_threshold` | 0.92 | 近似重复 Jaccard 阈值（可配置） |

### 5.8 错误处理与重试策略

| 场景 | 处理方式 |
|------|---------|
| Web 搜索失败 | 重试 3 次，指数退避，仍失败记录 error 继续 |
| YouTube 无字幕 | 跳过该来源，记录 warning，继续其他来源 |
| PDF 提取失败 | 重试 3 次，仍失败记录 error 继续 |
| 来源提取超时 | 30 秒超时，记录 error 继续 |
| 部分来源失败 | 继续其他来源，失败条目标记 failed |
| LLM 调用失败 | 重试 3 次，仍失败返回 error 状态 |

**原则**：单个来源失败不影响整体研究，收集所有失败项后返回部分成功结果。

### 5.9 研究评分机制

研究报告完成后，用户可对结果进行评分：

```sql
-- 研究报告评分表
CREATE TABLE research_ratings (
    id TEXT PRIMARY KEY,
    research_session_id TEXT NOT NULL,
    rating INTEGER NOT NULL,        -- 1-5 星
    feedback TEXT,                  -- 用户文字反馈
    helpful_topics TEXT,           -- JSON: [{topic, helpful}]
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (research_session_id) REFERENCES research_sessions(id)
);
```

**评分流程**：
```
研究报告完成
    ↓
用户查看报告
    ↓
用户评分（1-5 星）+ 可选文字反馈
    ↓
评分记录到 research_ratings 表
    ↓
评分数据影响后续研究排序（如：高分来源优先）
```

**评分反馈内容**：
- 整体评分（1-5 星）
- 哪些章节有帮助/无帮助
- 是否有遗漏的关键来源

### 5.10 Save to Wiki — 研究报告保存流程

#### 5.7.1 三阶段保存流程

```
研究报告生成完成
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  1. 原始数据 → raw/research_{topic}/                    │
│     raw/research_{topic}/                              │
│     ├─ sources/                                         │
│     │   ├─ {hash1}.txt  (网页正文)                    │
│     │   ├─ {hash2}.txt  (YouTube 字幕)               │
│     │   └─ {hash3}.txt  (PDF 内容)                    │
│     ├─ meta.json     (来源元数据：URL、title、type)   │
│     └─ analysis/    (分析结果缓存)                     │
└─────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  2. 处理后的报告 → .sink/ 缓冲区                       │
│     wiki/.sink/Research: {topic}.sink.md                │
│     - 带完整 [[Source:xxx]] Wiki 链接引用              │
│     - 等待用户审批                                     │
└─────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  3. 用户审批 → 正式保存到 wiki/                        │
│     wiki/Research: {topic}.md                           │
│     或追加到已存在的相关页面                             │
└─────────────────────────────────────────────────────────┘
```

#### 5.7.2 Sink 文件格式（复用 QuerySink 设计）

参考现有 `QuerySink` 的 Content Store + Entry Log 模式：

```
wiki/.sink/Research: LLM Agents.sink.md

---
formal_page: "Research: LLM Agents"
formal_path: wiki/Research: LLM Agents.md
created: 2025-05-25T10:00:00Z
unique_count: 3
entry_count: 5
last_updated: 2025-05-26T14:30:00Z
research_topic: "LLM Agents"
---

# Query Sink: Research: LLM Agents

> Pending entries for [[Research: LLM Agents]]

---

## Content Store

### abc12345 — 2025-05-25
{研究报告内容 1}

### def67890 — 2025-05-26
{研究报告内容 2}

---

## Entry Log

| # | Timestamp | Query | Answer Hash | Note |
|---|-----------|-------|-------------|------|
| 1 | 2025-05-25 10:00 | 研究 LLM Agents | `abc12345` | — |
| 2 | 2025-05-26 14:30 | 研究 LLM Agents 最新进展 | `def67890` | — |
```

#### 5.7.3 来源数据存储（raw/research_{topic}/）

```
raw/research_{LLM_Agents}/
├── sources/
│   ├── abc12345.txt   # 网页正文（按 URL hash 命名）
│   ├── def67890.txt   # YouTube 字幕
│   └── ghi11223.txt   # PDF 内容
├── meta.json          # 来源元数据
│   [{
│     "hash": "abc12345",
│     "type": "web",
│     "url": "https://arxiv.org/abs/...",
│     "title": "LLM Agents: A Survey",
│     "gathered_at": "2025-05-25T10:00:00Z"
│   }, ...]
└── analysis/
    ├── abc12345.json  # 分析结果缓存
    └── def67890.json
```

#### 5.7.4 重复研究追加逻辑

基于 QuerySink 的去重机制，Jaccard 阈值可通过 `similarity_threshold` 配置：

| 场景 | 行为 |
|------|------|
| 研究报告完全相同 | 标记 `duplicate`，不重复存储 |
| 研究报告相近（Jaccard ≥ 阈值） | 合并到已有条目，标记 `merged from #N` |
| 来源 URL 相同 | 复用已有 hash，不重复下载 |
| 同一 topic 多次研究 | 追加序号到同一 sink 文件的 Entry Log |

**追加规则**：
- 同一 `research_topic` 的研究追加到同一个 `Research: {topic}.sink.md`
- 每次研究生成唯一 `research_id`，记录在 Entry Log 中
- 用户审批时可查看每次研究的独立内容

**Wiki 页面命名规则**：
- 原始 topic：`LLM Agents 最新研究`
- 清理特殊字符 + 翻译英文：`LLM_Agents_Latest_Research`
- 追加时间戳格式 `YYYYMMDD_HHMM`：`Research_LLM_Agents_Latest_Research_20250526_1430`
- 最终格式：`Research: LLM Agents Latest Research (20250526_1430)`
- 同一天多次研究追加序号：`Research: LLM Agents Latest Research (20250526_1430-2)`

#### 5.7.5 引用格式

研究报告中的来源引用使用 Wiki 链接格式：

```markdown
# LLM Agents 最新研究进展

## 执行摘要
基于多项研究，LLM Agents 展现出强大的任务规划能力 [[Source:abc12345]]。

## 引用来源
[[Source:abc12345]] LLM Agents: A Comprehensive Survey - https://arxiv.org/abs/...
[[Source:def67890]] GPT-4 Technical Report - https://arxiv.org/abs/...
```

其中 `[[Source:abc12345]]` 对应 `raw/research_{topic}/sources/abc12345.txt`。

#### 5.7.6 审批后行为

| Wiki 已有页面状态 | 审批行为 |
|------|---------|
| 不存在 | 创建 `wiki/Research: {topic}.md` |
| 存在 | 追加内容到现有页面的相关章节 |
| 存在且内容高度相似 | 提示用户选择覆盖或追加 |

---

## 六、API 端点设计

### 6.1 Agent 路由

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /agent/chat` | POST | 发送消息（stream: true → SSE） |
| `GET /agent/sessions` | GET | 列出所有会话 |
| `GET /agent/sessions/{id}` | GET | 获取会话详情 |
| `DELETE /agent/sessions/{id}` | DELETE | 删除会话 |
| `GET /agent/confirmations` | GET | 列出待审批项 |
| `POST /agent/confirmations/{id}` | POST | 审批（approve/reject） |
| `POST /agent/confirmations/batch` | POST | 批量审批 |
| `GET /agent/tools` | GET | 列出可用工具 |

### 6.2 Research 路由

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /research/start` | POST | 启动深度研究 |
| `GET /research/{id}` | GET | 获取研究进度 |
| `GET /research` | GET | 列出所有研究会话 |
| `POST /research/{id}/pause` | POST | 暂停研究 |
| `POST /research/{id}/resume` | POST | 恢复研究 |
| `DELETE /research/{id}` | DELETE | 取消研究 |
| `GET /research/{id}/sources` | GET | 列出摄取的来源 |

### 6.3 SSE 流式事件类型

**Chat 流式事件**：
```python
ChatStreamEvent = (
    {"type": "message_delta", "content": str}
    | {"type": "tool_call_start", "tool": str, "args": dict}
    | {"type": "tool_call_end", "tool": str, "result": dict}
    | {"type": "tool_call_error", "tool": str, "error": str}
    | {"type": "done", "final_response": str, "actions": list}
    | {"type": "confirmation_required", "confirmation_id": str, "details": dict}
)
```

**Research 流式事件**：
```python
ResearchStreamEvent = (
    {"type": "step", "step": str, "message": str}
    | {"type": "source_gathered", "source_id": str, "source_type": str, "title": str}
    | {"type": "progress", "progress": float, "message": str}
    | {"type": "section_complete", "section": str, "content": str}
    | {"type": "done", "report": dict}
)
```

### 6.4 SSE 连接管理

**重连策略**：
- 连接断开时，前端自动重连（指数退避：1s, 2s, 4s, 8s...）
- 重连后发送 `GET /research/{id}/status` 获取当前状态
- 如果研究已完成，服务器立即推送 `done` 事件

**心跳机制**：
- 服务器每 30 秒发送一次 ping 事件，保持连接活跃
- 前端若无心跳响应，判定连接断开并触发重连

### 6.5 JWT 认证

**多用户支持**：
- 所有 API 请求通过 Bearer token 验证
- Token 格式：`Authorization: Bearer <jwt_token>`
- Token 包含用户身份信息（user_id, exp 等）

**路由保护**：
- `/agent/*`、`/research/*` 等路由需要有效 JWT
- `/api/health`、`/docs` 等公开路由无需认证

---

## 七、前端组件设计

### 7.1 视图结构

```typescript
type ViewMode =
  | 'edit' | 'dashboard' | 'insights'  // 现有
  | 'chat'        // Agent Chat（主界面）
  | 'research'    // Quick Research 面板
  | 'tasks'       // 研究任务列表
  | 'confirmations' | 'proposals' | 'ingest' | 'history'  // 现有 agent
```

### 7.2 Chat 视图布局

```
┌──────────────────────────────────────────────────────────────┐
│  Chat                                            [新会话]   │
├─────────────────────────────────────┬────────────────────────┤
│  消息列表                           │  侧栏                  │
│  ┌──────────────────────────────┐  │  ┌──────────────────┐ │
│  │ User: 研究 LLM Agents        │  │  │ 当前会话         │ │
│  └──────────────────────────────┘  │  │ • 会话ID: xxx   │ │
│  ┌──────────────────────────────┐  │  │ • 消息数: 12    │ │
│  │ Assistant: 正在研究...        │  │  │ • 工具调用: 5   │ │
│  │  ├─ 🔍 wiki_search(...)    │  │  ├──────────────────┤ │
│  │  ├─ 📄 wiki_read_page(...) │  │  │ 快捷操作         │ │
│  │  └─ 📝 [结果预览]          │  │  │ [+ 新研究]       │ │
│  └──────────────────────────────┘  │  │ [查看报告]      │ │
│  ┌──────────────────────────────┐  │  │ [中断]          │ │
│  │ Assistant: 根据研究...        │  │  └──────────────────┘ │
│  │ (流式输出中...)              │  │                        │
│  └──────────────────────────────┘  │                        │
├─────────────────────────────────────┴────────────────────────┤
│  输入框: "请分析..."                           [发送] [⚙]   │
└──────────────────────────────────────────────────────────────┘
```

### 7.3 Research 面板布局

```
┌──────────────────────────────────────────────────────────────┐
│  Quick Research                                              │
├──────────────────────────────────────────────────────────────┤
│  [新建研究]  输入研究主题: ________________________________   │
│                                                              │
│  现有研究:                                                   │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 🔬 LLM Agents 深度分析                    [进行中] 45%  │  │
│  │ 状态: 正在摄取来源 (3/12)                              │  │
│  │ 子查询:                                                │  │
│  │  ✓ LLM Agents 定义                                    │  │
│  │  ✓ LLM Agents 架构                                    │  │
│  │  ⟳ 最新研究进展 (进行中)                               │  │
│  │  ○ 应用场景                                           │  │
│  │  ○ 知名项目                                           │  │
│  │ [暂停] [取消] [查看报告→]                              │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 7.4 Chat 会话管理

| 项目 | 值 | 说明 |
|------|-----|------|
| 消息持久化 | 全部 | 所有消息存入 `chat_messages` 表 |
| 默认显示条数 | 50 条 | 前端滚动加载更多 |
| Context window 超限 | LLM 总结 | 当消息总长度超过 10 万字符时触发 |

**Context 窗口管理流程**：
1. 每次发送消息前，计算消息总长度
2. 超过 10 万字符时，调用 LLM 总结历史消息
3. 总结后的内容替换原始历史，保留关键信息
4. 原始消息仍保留在 DB 中，供后续检索

### 7.5 研究评分 UI

研究报告完成后，显示评分组件：
```
┌──────────────────────────────────────────────────────────────┐
│  研究报告评分                                                │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  请评价本次研究的质量：                                       │
│                                                              │
│  ⭐⭐⭐⭐⭐                                                 │
│                                                              │
│  哪些章节有帮助？（可多选）                                    │
│  ☑ 执行摘要   ☐ 技术架构   ☐ 应用场景   ☐ 引用来源          │
│                                                              │
│  文字反馈（可选）：                                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 补充了 XX 方面的最新进展...                            │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  [提交评分]                                                  │
└──────────────────────────────────────────────────────────────┘
```

---

## 八、文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `server/http/routes_agent.py` | Agent REST 路由 |
| `server/http/routes_research.py` | Research REST 路由 |
| `agent/service.py` | AgentService（替代 WikiAgent） |
| `agent/llm_client.py` | LLM 客户端（流式 + function calling） |
| `agent/memory.py` | 来自 legacy，可直接复用 |
| `agent/hooks.py` | 来自 legacy，可直接复用 |
| `agent/db.py` | Agent 数据库管理（连接、表初始化） |
| `agent/adapters.py` | LLM 适配层（Ollama/OpenAI 统一接口） |
| `research/engine.py` | ResearchEngine 核心 |
| `research/session.py` | ResearchSession 模型 |
| `research/web_search.py` | Web 搜索集成（DuckDuckGo） |
| `research/gatherer.py` | 并行源摄取 |
| `research/synthesizer.py` | 报告生成 |
| `research/ratings.py` | 研究评分管理 |
| `prompts/_defaults/research_plan.yaml` | 研究规划 prompt |
| `prompts/_defaults/research_report.yaml` | 研究报告 prompt |
| `webui/src/components/ChatView.tsx` | Chat 主视图 |
| `webui/src/components/ResearchPanel.tsx` | 研究面板 |
| `webui/src/components/ResearchRating.tsx` | 研究评分组件 |
| `webui/src/components/MessageBubble.tsx` | 消息气泡（含工具调用） |
| `webui/src/components/ToolCallCard.tsx` | 工具调用卡片 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `server/core.py` | 注册新路由 |
| `llm_client.py` | 增强支持流式 + function calling |
| `pyproject.toml` | 添加 `duckduckgo-search` 依赖 |
| `webui/src/api.ts` | 添加 `agent.*`、`research.*` API 端点 |
| `webui/src/App.tsx` | 添加 chat、research 视图 |
| `webui/src/components/AgentChat.tsx` | 重写支持 SSE 流式 |

---

## 九、依赖变更

```toml
# pyproject.toml 新增依赖
[project.optional-dependencies]
agent = [
    "fastmcp>=3.0.0",
    "openai>=1.12.0",         # 流式 + function calling
    "duckduckgo-search>=4.0",  # Web 搜索
    "requests[socks]>=2.31.0",
]
```

---

## 十、实施计划

### Phase 1: 基础设施（1-2 天）
1. 增强 `LLMClient` 支持流式 + function calling
2. 创建 `agent/db.py` 数据库管理
3. 创建 `server/http/routes_agent.py` Agent 路由
4. 创建基础 `AgentService`
5. 前端 API 客户端更新

### Phase 2: Chat 界面（1-2 天）
1. 实现 `/agent/chat` SSE 端点
2. 实现 `ChatView` 组件（流式输出）
3. 实现 `ToolCallCard` 组件（展示工具调用）
4. 集成到 App.tsx 视图系统

### Phase 3: Quick Research（2-3 天）
1. 实现 `WebSearch` 模块（DuckDuckGo）
2. 实现 `ResearchSession` 模型 + 数据库表
3. 实现 `ResearchEngine` 核心流程
4. 实现 Research SSE 端点
5. 实现 `ResearchPanel` 前端组件

### Phase 4: 完善与集成（1-2 天）
1. 研究会话持久化（SQLite）
2. 报告自动保存为 Wiki 页面
3. 研究历史与恢复
4. 端到端测试

---

## 十一、关键设计决策

| 决策 | 选择 |
|------|------|
| 流式传输 | SSE（WebSocket 后续扩展） |
| Web 搜索 | DuckDuckGo 免费 API（后续可加 SerpAPI） |
| 数据库 | `.llmwiki_agent.db`（独立，不共用 wiki.db） |
| 报告存储 | 先保存到 `.sink/` 缓冲区，等待用户审批 |
| 来源存储 | 原始数据保存在 `raw/research_{topic}/`，处理后报告在 Wiki |
| 重复研究 | 追加序号，类似 QuerySink 合并机制 |
| 合并阈值 | Jaccard 0.92，暴露为可配置参数 |
| 近似重复处理 | 合并而非保留两份 |
| LLM 路由 | 统一 API 调用，通过配置切换 Ollama/OpenAI 模型 |
| LLM 适配层 | Ollama/OpenAI 差异通过适配层统一处理 |
| 多用户支持 | JWT 身份识别 |
| 研究评分 | 1-5 星 + 文字反馈 + helpful_topics |
| Wiki 命名 | `Research: {topic}`，清理特殊字符，翻译英文，追加时间戳 |
| 时间戳格式 | `YYYYMMDD_HHMM`（如同一天多次，追加序号） |
| Chat 显示 | 默认 50 条，超限 10 万字符触发 LLM 总结 |
| SSE 重连 | 指数退避 + status API 恢复 + 30s 心跳 |
| 研究限制 | 推荐值可接受，暴露为可配置参数 |

---

## 十二、与现有 llmwikify 的关系

### 共用组件

| 组件 | 来源 | 用途 |
|------|------|------|
| `WikiToolRegistry` | 现有 `agent/tools.py` | 20+ 工具注册 |
| `HookSystem` | 现有 `agent/hooks.py` | 生命周期钩子 |
| `Confirmation flow` | 现有 `agent/tools.py` | 审批流程 |
| `DreamEditor` | 现有 `agent/dream_editor.py` | 编辑提案 |
| `MemoryManager` | 现有 `agent/memory.py` | 对话历史 |
| `extractors` | 现有 `extractors/` | 多源内容提取 |
| `SynthesisEngine` | 现有 `core/synthesis_engine.py` | 跨源综合 |
| `Prompts` | 现有 `prompts/_defaults/` | prompt 模板 |

### 新增交互

```
Quick Research
    ├──→ 调用 wiki_search（摄取的 wiki 内部来源）
    ├──→ 调用 wiki_analyze_source（分析每个来源）
    ├──→ 调用 wiki_suggest_synthesis（跨源综合）
    └──→ 调用 wiki_write_page（保存报告到 Wiki）

WebUI Chat
    ├──→ 调用 AgentService.chat（对话式交互）
    ├──→ 调用 AgentService.execute_tool（执行工具）
    └──→ 调用 AgentService.approve_confirmation（审批提案）
```

---

## 十三、Chat vs Quick Research 对比

| 维度 | Chat | Quick Research |
|------|------|--------------|
| 交互模式 | 对话式，多轮上下文 | 单次主题，深度探索 |
| 来源 | 仅内部 Wiki | 多源（Web/YouTube/PDF/Wiki） |
| 输出 | 即时回复 | 结构化报告 + Wiki 页面 |
| 工具调用 | 实时展示 | 后台执行，进度驱动 |
| 适用场景 | 快速问答、编辑操作 | 深度调研、竞品分析、学习一门 topic |

两者**共用同一个 AgentService**：
- Chat 调用工具时触发 confirmations
- Quick Research 后台执行不打扰用户，但完成后可生成 Wiki 页面供 Chat 使用
