# Deep Research — Implementation Plan

> 创建时间：2025-05-26
> 状态：待实现

---

## 一、背景与目标

Deep Research 是一个**多源异步研究助手**，用户输入研究主题，系统自动完成：子查询分解 → 多源并行摄取 → 跨源综合分析 → 结构化报告生成。

**与 Chat 的区别**：

| 维度 | Chat | Deep Research |
|------|------|--------------|
| 交互模式 | 对话式，多轮上下文 | 单次主题，深度探索 |
| 来源 | 仅内部 Wiki | 多源（Web/YouTube/PDF/Wiki） |
| 输出 | 即时回复 | 结构化报告 + Wiki 页面 |
| 工具调用 | 实时展示 | 后台执行，进度驱动 |
| 适用场景 | 快速问答、编辑操作 | 深度调研、竞品分析、学习一门 topic |

---

## 二、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│  React WebUI（Research 面板）                               │
│  ├─ 新建研究表单                                            │
│  ├─ 研究列表（进度、状态、子查询）                           │
│  ├─ 报告查看 + 评分                                         │
│  └─ SSE 流式进度事件渲染                                     │
└────────────────────────────┬─────────────────────────────────┘
                             │ REST + SSE
┌────────────────────────────┴─────────────────────────────────┐
│  WikiServer (FastAPI)                                        │
│  └─ /research/*    （Research REST + SSE 路由）             │
└────────────────────────────┬─────────────────────────────────┘
                             │
┌────────────────────────────┴─────────────────────────────────┐
│  ResearchEngine（异步 6 阶段流程）                            │
│  ├─ ResearchSessionManager   （会话状态管理 + DB）           │
│  ├─ WebSearch                （DuckDuckGo 搜索）             │
│  ├─ SourceGatherer          （并行来源摄取）                 │
│  ├─ SourceAnalyzer           （来源内容分析）                 │
│  ├─ ResearchSynthesizer      （跨源综合）                    │
│  └─ ReportGenerator          （LLM 生成 markdown 报告）      │
└──────────────────────────────────────────────────────────────┘
```

---

## 三、数据库设计

### 3.1 现有表扩展

**`research_sessions` 表变更**：

| 字段 | 原有 | 变更后 |
|------|------|--------|
| `status` | `TEXT DEFAULT 'running'` | `TEXT DEFAULT 'planning'` |
| `current_step` | （不存在） | `TEXT DEFAULT 'planning'` |
| `result` | （不存在） | `TEXT`（存储 JSON 格式的完整报告） |
| `updated_at` | （不存在） | `TEXT DEFAULT (datetime('now'))` |

```sql
CREATE TABLE IF NOT EXISTS research_sessions (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    query TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'planning',
    current_step TEXT DEFAULT 'planning',
    progress REAL DEFAULT 0.0,
    result TEXT,
    wiki_page_name TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### 3.2 新建表

**`research_sub_queries`** — 每个子查询独立追踪

```sql
CREATE TABLE IF NOT EXISTS research_sub_queries (
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
    FOREIGN KEY (session_id) REFERENCES research_sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_sub_queries_session ON research_sub_queries(session_id, status);
```

**`research_sources`** — 摄取后的来源引用（分析后更新 analysis）

```sql
CREATE TABLE IF NOT EXISTS research_sources (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    sub_query_id TEXT,
    source_type TEXT NOT NULL,
    url TEXT,
    title TEXT,
    content_length INTEGER,
    content_preview TEXT,
    analysis TEXT,
    rating INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES research_sessions(id),
    FOREIGN KEY (sub_query_id) REFERENCES research_sub_queries(id)
);
CREATE INDEX IF NOT EXISTS idx_sources_session ON research_sources(session_id);
```

---

## 四、数据库方法

### 4.1 Sub Queries

| 方法 | 签名 | SQL |
|------|------|-----|
| `save_sub_query` | `(session_id, query, source_type, url=None)` → `str` | INSERT |
| `get_sub_queries` | `(session_id)` → `list[dict]` | SELECT WHERE session_id |
| `update_sub_query` | `(id, status, result=None, error=None)` | UPDATE |
| `complete_sub_query` | `(id, result)` | UPDATE SET status='done', completed_at, result |
| `fail_sub_query` | `(id, error)` | UPDATE SET status='failed', error |

### 4.2 Sources

| 方法 | 签名 | SQL |
|------|------|-----|
| `save_source` | `(session_id, sub_query_id, source_type, url, title, content_length, content_preview=None)` → `str` | INSERT |
| `get_sources` | `(session_id)` → `list[dict]` | SELECT WHERE session_id |
| `update_source_analysis` | `(source_id, analysis)` | UPDATE SET analysis |
| `rate_source` | `(source_id, rating)` | UPDATE SET rating |

### 4.3 Research Session

| 方法 | 签名 | SQL |
|------|------|-----|
| `create_research_session` | `(wiki_id, query)` → `str` | INSERT |
| `update_research_progress` | `(session_id, progress, wiki_page_name=None)` | UPDATE |
| `update_research_status` | `(session_id, status, step=None)` | UPDATE status, current_step |
| `finalize_research` | `(session_id, result, wiki_page_name)` | UPDATE SET result, wiki_page_name, status='done' |
| `get_research_session` | `(session_id)` → `dict` | SELECT WHERE id |
| `list_research_sessions` | `(wiki_id=None)` → `list[dict]` | SELECT [WHERE wiki_id] ORDER BY created_at DESC |

---

## 五、Research Engine 详解

### 5.1 配置项

```python
DEFAULT_RESEARCH_CONFIG = {
    "max_sub_queries": 20,              # 单次研究最大子查询数
    "max_source_content_length": 500000, # 单来源最大内容字符数（超出截断）
    "research_timeout_minutes": 30,      # 研究超时（分钟）
    "max_parallel_gathering": 5,         # 最大并行摄取数
    "web_search_results_per_query": 5,   # Web 搜索每查询结果数
    "max_retry_attempts": 3,             # 来源获取最大重试次数
    "similarity_threshold": 0.92,        # 近似重复 Jaccard 阈值
}
```

配置来源优先级：per-wiki `.wiki-config.yaml` → global `~/.llmwikify/llmwikify.json` → DEFAULT

### 5.2 ResearchSessionManager

```python
class ResearchSessionManager:
    def __init__(self, db: AgentDatabase, wiki: Wiki, config: dict)

    def create_session(self, query: str, wiki_id: str) -> str:
        """创建会话，写入 DB，返回 session_id"""

    def get_session(self, session_id: str) -> dict:
        """获取会话（包含 sub_queries + sources）"""

    def update_status(self, session_id: str, status: str, step: str | None = None, progress: float | None = None):
        """更新状态/步骤/进度"""

    def add_sub_query(self, session_id: str, query: str, source_type: str, url: str | None = None) -> str:
        """添加子查询"""

    def complete_sub_query(self, sub_query_id: str, result: dict):
        """标记子查询完成"""

    def fail_sub_query(self, sub_query_id: str, error: str):
        """标记子查询失败"""

    def add_source(self, session_id: str, sub_query_id: str, source_type: str, url: str, title: str, content_length: int, content_preview: str | None = None) -> str:
        """添加来源"""

    def update_source_analysis(self, source_id: str, analysis: dict):
        """更新来源分析结果"""

    def finalize(self, session_id: str, result: dict, wiki_page_name: str | None):
        """研究完成，收尾"""
```

### 5.3 WebSearch

```python
class WebSearch:
    def __init__(self, config: dict)
        self.config = config
        self.ddgs = DuckDuckGoSearchAPI()  # duckduckgo-search

    async def search(self, query: str, num_results: int | None = None) -> list[SearchResult]:
        """DuckDuckGo 搜索，返回标题/URL/snippet"""
        results = self.ddgs.run(query, num_results=num_results or self.config["web_search_results_per_query"])
        return [SearchResult(title=r["title"], url=r["url"], snippet=r["snippet"]) for r in results]

    async def search_with_type(self, query: str, source_type: str) -> list[dict]:
        """根据 source_type 执行搜索"""
        if source_type == "web":
            results = await self.search(query)
            return [{"query": query, "source_type": "web", "url": r.url} for r in results]
        elif source_type == "youtube":
            results = await self.search(f"site:youtube.com {query}")
            return [{"query": query, "source_type": "youtube", "url": r.url} for r in results]
        elif source_type == "wiki":
            return []  # Wiki 搜索由 Wiki.search() 提供
```

### 5.4 SourceGatherer

```python
@dataclass
class ExtractedSource:
    id: str
    sub_query_id: str
    source_type: str
    url: str
    title: str
    content: str
    content_length: int
    content_preview: str  # 前 500 字

class SourceGatherer:
    def __init__(self, wiki: Wiki, config: dict)
        self.wiki = wiki
        self.config = config
        self._semaphore: asyncio.Semaphore

    async def gather(self, sub_queries: list[dict]) -> AsyncIterator[dict]:
        """并行摄取所有子查询，通过 semaphore 控制并发度"""
        tasks = [self._gather_one(sq) for sq in sub_queries]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            if result is not None:
                yield result

    async def _gather_one(self, sub_query: dict) -> dict | None:
        """摄取单个子查询"""
        sq_id = sub_query["id"]
        source_type = sub_query["source_type"]
        url = sub_query.get("url")
        query = sub_query["query"]

        try:
            if source_type == "web":
                content = _extract_url(url).text
            elif source_type == "youtube":
                content = _extract_youtube(url).text
            elif source_type == "pdf":
                content = _extract_pdf(url).text
            elif source_type == "wiki":
                content = self.wiki.page_io.read_page(query)  # 直接搜 wiki 页面名
            else:
                raise ValueError(f"Unknown source_type: {source_type}")

            content = content[: self.config["max_source_content_length"]]
            preview = content[:500]
            title = url or query

            source_id = self.session_manager.add_source(
                session_id=self.session_id,
                sub_query_id=sq_id,
                source_type=source_type,
                url=url or "",
                title=title,
                content_length=len(content),
                content_preview=preview,
            )

            self.session_manager.complete_sub_query(sq_id, {"content_length": len(content)})

            return {
                "type": "source_gathered",
                "source_id": source_id,
                "source_type": source_type,
                "title": title,
                "url": url or "",
            }
        except Exception as e:
            self.session_manager.fail_sub_query(sq_id, str(e))
            return {
                "type": "sub_query_failed",
                "sub_query_id": sq_id,
                "error": str(e),
            }
```

### 5.5 SourceAnalyzer

```python
class SourceAnalyzer:
    def __init__(self, wiki: Wiki, llm_client)
        self.wiki = wiki
        self.llm_client = llm_client

    async def analyze_source(self, source: dict) -> dict:
        """对单个来源调用 Wiki.analyze_source()"""
        # 先将内容写入临时文件，供 analyze_source 使用
        import tempfile, hashlib
        content = source["content"]
        content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
        tmp_path = f"raw/research/{self.session_id}/{content_hash}.txt"
        (self.wiki.root / tmp_path).parent.mkdir(parents=True, exist_ok=True)
        (self.wiki.root / tmp_path).write_text(content)

        analysis = self.wiki.analyze_source(tmp_path)
        return analysis

    async def analyze_sources(self, sources: list[dict]) -> AsyncIterator[dict]:
        """并发分析所有来源"""
        tasks = [self._analyze_one(s) for s in sources]
        for coro in asyncio.as_completed(tasks):
            result = await coro
            yield result
```

### 5.6 ResearchSynthesizer

```python
class ResearchSynthesizer:
    def __init__(self, wiki: Wiki)
        self.wiki = wiki

    async def synthesize(self, sources: list[dict]) -> dict:
        """跨源综合"""
        # 1. 过滤有 analysis 的来源
        # 2. 按 rating 加权（高评分来源优先）
        # 3. 调用 Wiki.suggest_synthesis() 或直接调用 SynthesisEngine
        # 4. 返回跨源综合结果

        rated_sources = sorted(sources, key=lambda s: s.get("rating") or 0, reverse=True)
        suggestions = []
        for src in rated_sources:
            if src.get("analysis"):
                # synthesis 加权考虑 rating
                suggestion = engine.analyze_new_source(src["analysis"], src["title"])
                suggestions.append(suggestion)

        return {
            "suggestions": suggestions,
            "sources_analyzed": len(sources),
        }
```

### 5.7 ReportGenerator

```python
class ReportGenerator:
    def __init__(self, wiki: Wiki, llm_client)
        self.wiki = wiki
        self.llm_client = llm_client
        self.prompt_registry = wiki._get_prompt_registry()  # 或新建 registry

    def _build_source_map(self, sources: list[dict]) -> dict[str, dict]:
        """构建 hash → 来源信息的映射，供报告引用使用"""
        source_map = {}
        for s in sources:
            h = hashlib.md5((s.get("url") or s["title"]).encode()).hexdigest()[:12]
            source_map[h] = {
                "title": s["title"],
                "url": s.get("url", ""),
                "source_type": s["source_type"],
            }
        return source_map

    async def generate(self, query: str, sources: list[dict], synthesis: dict) -> str:
        """LLM 生成 markdown 报告"""
        source_map = self._build_source_map(sources)

        # 构建 source_contents：每个 source 的前 3000 字 + analysis
        source_contents = []
        for s in sources:
            h = hashlib.md5((s.get("url") or s["title"]).encode()).hexdigest()[:12]
            source_contents.append({
                "hash": h,
                "title": s["title"],
                "source_type": s["source_type"],
                "url": s.get("url", ""),
                "content": s.get("content_preview", "")[:3000],
                "analysis": s.get("analysis", {}),
            })

        registry = self.wiki._get_prompt_registry()
        messages = registry.get_messages(
            "research_report",
            query=query,
            sources=source_contents,
            synthesis=synthesis,
            wiki_index=self.wiki.index_file.read_text() if self.wiki.index_file.exists() else "",
        )
        params = registry.get_api_params("research_report")

        report_md = await self.llm_client.acall(messages, **params)
        return report_md
```

### 5.8 ResearchEngine（6 阶段主流程）

```python
class ResearchEngine:
    def __init__(self, wiki: Wiki, db: AgentDatabase, llm_client, config: dict)
        self.wiki = wiki
        self.db = db
        self.llm_client = llm_client
        self.config = config
        self.session_manager = ResearchSessionManager(db, wiki, config)

    async def run(self, session_id: str, query: str) -> AsyncIterator[dict]:
        """6 阶段主流程"""
        self.session_manager.session_id = session_id

        # PLANNING
        yield self._step_event("planning", "正在分解研究主题...")
        sub_queries = await self._plan_sub_queries(query)
        for sq in sub_queries:
            yield {
                "type": "sub_query_created",
                "sub_query_id": sq["id"],
                "query": sq["query"],
                "source_type": sq["source_type"],
                "url": sq.get("url"),
            }

        # GATHERING
        yield self._step_event("gathering", "开始摄取来源...")
        total = len(sub_queries)
        gathered = 0
        async for event in self._gather_sources(sub_queries):
            if event["type"] == "source_gathered":
                gathered += 1
                yield {
                    "type": "progress",
                    "progress": gathered / total * 0.4,
                    "message": f"已摄取 {gathered}/{total} 个来源",
                }
            yield event

        # ANALYZING
        yield self._step_event("analyzing", "正在分析来源...")
        sources = self.db.get_sources(session_id)
        analyzed = 0
        for src in sources:
            if src.get("analysis"):
                analyzed += 1
        total_src = len(sources)
        async for event in self._analyze_sources(sources):
            if event["type"] == "source_analyzed":
                analyzed += 1
                yield {
                    "type": "progress",
                    "progress": 0.4 + analyzed / total_src * 0.2,
                    "message": f"已分析 {analyzed}/{total_src} 个来源",
                }
            yield event

        # SYNTHESIZING
        yield self._step_event("synthesizing", "正在综合...")
        synthesis = await self._synthesize(sources)
        yield {"type": "synthesis_complete", "synthesis": synthesis}
        yield {
            "type": "progress",
            "progress": 0.7,
            "message": "综合完成",
        }

        # REPORT
        yield self._step_event("report", "正在生成报告...")
        report_md = await self._generate_report(query, sources, synthesis)
        yield {
            "type": "progress",
            "progress": 0.85,
            "message": "报告生成完成",
        }

        # DONE
        # 不在这里保存 sink，留给后续步骤
        yield {
            "type": "done",
            "report": {
                "query": query,
                "markdown": report_md,
                "sources": [
                    {"id": s["id"], "title": s["title"], "url": s.get("url"), "source_type": s["source_type"]}
                    for s in sources
                ],
            },
        }

    async def _plan_sub_queries(self, query: str) -> list[dict]:
        """LLM 分解主题为子查询"""
        wiki_index = self.wiki.index_file.read_text() if self.wiki.index_file.exists() else ""
        registry = self.wiki._get_prompt_registry()
        messages = registry.get_messages(
            "research_plan",
            query=query,
            wiki_index=wiki_index,
        )
        params = registry.get_api_params("research_plan")
        result = await self.llm_client.acall_json(messages, **params)
        # result = [{"query": "...", "source_type": "...", "url": "..."}]
        sub_queries = []
        for item in result[: self.config["max_sub_queries"]]:
            sq_id = self.session_manager.add_sub_query(
                session_id=self.session_manager.session_id,
                query=item["query"],
                source_type=item["source_type"],
                url=item.get("url"),
            )
            sub_queries.append({"id": sq_id, "query": item["query"], "source_type": item["source_type"], "url": item.get("url")})
        return sub_queries

    async def _gather_sources(self, sub_queries: list[dict]) -> AsyncIterator[dict]:
        gatherer = SourceGatherer(self.wiki, self.session_manager, self.config)
        async for event in gatherer.gather(sub_queries):
            yield event

    async def _analyze_sources(self, sources: list[dict]) -> AsyncIterator[dict]:
        analyzer = SourceAnalyzer(self.wiki, self.llm_client)
        async for event in analyzer.analyze_sources(sources):
            yield event

    async def _synthesize(self, sources: list[dict]) -> dict:
        synthesizer = ResearchSynthesizer(self.wiki)
        return await synthesizer.synthesize(sources)

    async def _generate_report(self, query: str, sources: list[dict], synthesis: dict) -> str:
        generator = ReportGenerator(self.wiki, self.llm_client)
        return await generator.generate(query, sources, synthesis)

    def _step_event(self, step: str, message: str) -> dict:
        return {"type": "step", "step": step, "message": message}
```

---

## 六、SSE 事件流

### 6.1 Research SSE 事件类型

| event type | 字段 | 说明 |
|------------|------|------|
| `step` | `step`, `message` | 阶段切换通知 |
| `sub_query_created` | `sub_query_id`, `query`, `source_type`, `url` | 子查询已创建 |
| `sub_query_done` | `sub_query_id`, `status` | 子查询完成 |
| `sub_query_failed` | `sub_query_id`, `error` | 子查询失败 |
| `source_gathered` | `source_id`, `source_type`, `title`, `url` | 来源已摄取 |
| `progress` | `progress` (0.0-1.0), `message` | 进度更新 |
| `synthesis_complete` | `synthesis` | 跨源综合完成 |
| `done` | `report` (dict), `wiki_page_name` | 研究完成 |
| `error` | `error` | 错误 |

### 6.2 SSE 事件示例

```
event: message
data: {"type": "step", "step": "planning", "message": "正在分解研究主题..."}

event: message
data: {"type": "sub_query_created", "sub_query_id": "abc123", "query": "LLM Agents 定义", "source_type": "web", "url": ""}

event: message
data: {"type": "step", "step": "gathering", "message": "开始摄取来源..."}

event: message
data: {"type": "source_gathered", "source_id": "def456", "source_type": "web", "title": "LLM Agents: A Survey", "url": "https://arxiv.org/abs/..."}

event: message
data: {"type": "progress", "progress": 0.35, "message": "已摄取 3/8 个来源"}

event: message
data: {"type": "step", "step": "analyzing", "message": "正在分析来源..."}

event: message
data: {"type": "step", "step": "synthesizing", "message": "正在综合..."}

event: message
data: {"type": "step", "step": "report", "message": "正在生成报告..."}

event: message
data: {"type": "done", "report": {"query": "...", "markdown": "..."}, "wiki_page_name": null}
```

---

## 七、API 端点设计

### 7.1 Research 路由（挂载于 `/api/research`）

| 端点 | 方法 | 描述 |
|------|------|------|
| `POST /api/research/start` | POST | 启动深度研究（SSE 流式） |
| `GET /api/research/` | GET | 列出所有研究会话 |
| `GET /api/research/{id}` | GET | 获取研究会话详情 |
| `POST /api/research/{id}/pause` | POST | 暂停研究 |
| `POST /api/research/{id}/resume` | POST | 恢复研究 |
| `DELETE /api/research/{id}` | DELETE | 取消研究 |
| `GET /api/research/{id}/sources` | GET | 列出摄取的来源 |
| `POST /api/research/{id}/rate` | POST | 评分（写入 source.rating） |

### 7.2 请求/响应格式

**`POST /api/research/start`**

```json
// Request
{ "query": "研究 LLM Agents 最新进展", "wiki_id": "optional" }

// Response: SSE stream
```

**`POST /api/research/{id}/rate`**

```json
// Request
{
  "rating": 4,
  "feedback": "报告很有帮助，但缺少 XX 方面的来源",
  "helpful_topics": [{"topic": "执行摘要", "helpful": true}, {"topic": "技术架构", "helpful": false}]
}

// Response
{ "rated": true }
```

---

## 八、Prompt 模板

### 8.1 `research_plan.yaml`

**用途**：PLANNING 阶段，LLM 分解研究主题为子查询列表

**输入变量**：
- `query` — 研究主题
- `wiki_index` — Wiki 索引摘要（让 LLM 知道已有内容，避免重复）

**输出**：JSON array of sub-queries

```json
[
  {"query": "LLM Agents 定义与概念", "source_type": "web", "url": ""},
  {"query": "LLM Agents 架构与核心技术", "source_type": "web", "url": ""},
  {"query": "LLM Agents 最新研究进展", "source_type": "web", "url": ""},
  {"query": "吴恩达 LLM Agents 课程", "source_type": "youtube", "url": "https://youtube.com/..."}
]
```

**设计原则**：
- source_type 在 `web/youtube/pdf/wiki` 中选择
- url 留空表示由 gatherer 自行搜索
- 子查询数量不超过 `max_sub_queries`

### 8.2 `research_report.yaml`

**用途**：REPORT 阶段，LLM 基于多源内容和综合结果生成结构化 markdown 报告

**输入变量**：
- `query` — 研究主题
- `sources` — 来源列表（含 content_preview + analysis）
- `synthesis` — 跨源综合结果
- `wiki_index` — Wiki 索引

**输出**：markdown 报告文本

**设计原则**：
- 包含执行摘要
- 各子话题章节
- 使用 `[[Source:hash]]` 内联引用来源
- 在末尾附上完整引用来源列表

---

## 九、前端组件设计

### 9.1 `api.ts` — research namespace

```typescript
api.research = {
  start: (query: string, wikiId?: string) => new ReadableStream({
    start(controller) {
      const es = new EventSource(`/api/research/start?query=${encodeURIComponent(query)}${wikiId ? `&wiki_id=${wikiId}` : ''}`);
      // 注意：SSE 无法通过普通 fetch 实现，改用 EventSource
      // 但 EventSource 不支持 POST body，需要改用 Fetch + ReadableStream 模式
      // 实际使用 WebSocket 或转用 fetch + 自定义 SSE parser
    }
  }),
  get: (id: string) => request<ResearchSession>(`/api/research/${id}`),
  list: (wikiId?: string) => request<ResearchSession[]>(`/api/research/${wikiId ? `?wiki_id=${wikiId}` : ''}`),
  pause: (id: string) => request(`/api/research/${id}/pause`, { method: 'POST' }),
  resume: (id: string) => request(`/api/research/${id}/resume`, { method: 'POST' }),
  delete: (id: string) => request(`/api/research/${id}`, { method: 'DELETE' }),
  sources: (id: string) => request<Source[]>(`/api/research/${id}/sources`),
  rate: (id: string, rating: ResearchRating) => request(`/api/research/${id}/rate`, { method: 'POST', body: rating }),
}
```

**SSE 流式处理说明**：`EventSource` 不支持 POST，需要前端改用 `fetch()` 搭配自定义 SSE parser（参考 `chatStream()` 实现）。

### 9.2 ResearchPanel.tsx

```
┌──────────────────────────────────────────────────────────────┐
│  Deep Research                                              │
├──────────────────────────────────────────────────────────────┤
│  [新建研究]  输入主题: ________________________________     │
│                                                              │
│  研究列表:                                                   │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 🔬 {topic}                       [{status} {progress}%] │ │
│  │  状态: {current_step_message}                        │ │
│  │  子查询:                                              │ │
│  │  ✓ {query1} — {source_type}                         │ │
│  │  ✓ {query2} — {source_type}                         │ │
│  │  ⟳ {query3} (进行中)                                 │ │
│  │  ○ {query4} (待处理)                                 │ │
│  │ [暂停] [取消] [查看报告]                              │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                              │
│  [加载更多]                                                   │
└──────────────────────────────────────────────────────────────┘
```

**状态**：`idle` / `planning` / `gathering` / `analyzing` / `synthesizing` / `report` / `done` / `paused` / `error`

### 9.3 ResearchRating.tsx

研究报告完成后弹出（或在查看报告时显示）：

```
┌──────────────────────────────────────────────────────────────┐
│  研究报告评分                                                │
├──────────────────────────────────────────────────────────────┤
│  请评价本次研究的质量：                                       │
│  ⭐⭐⭐⭐⭐  (hover 选星，1-5)                            │
│                                                              │
│  哪些章节有帮助？                                           │
│  ☑ 执行摘要   ☐ 技术架构   ☐ 应用场景   ☐ 引用来源          │
│                                                              │
│  文字反馈（可选）：                                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ 补充了 XX 方面的最新进展，但缺少 YY 方向的来源...       │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                              │
│  [提交评分]                                                  │
└──────────────────────────────────────────────────────────────┘
```

评分提交后：
- 写入 DB（`research_sources.rating`）
- 高评分来源在后续 `ResearchSynthesizer` 中获得更高权重

### 9.4 App.tsx — research view mode

```typescript
type ViewMode = 'chat' | 'settings' | 'research' | 'dashboard' | ...
```

`'research'` 视图渲染 `<ResearchPanel />`，导航栏显示 "Deep Research" 按钮。

---

## 十、文件变更清单

### 新增文件

| 文件 | 说明 |
|------|------|
| `src/llmwikify/agent/backend/research/__init__.py` | research 模块导出 |
| `src/llmwikify/agent/backend/research/config.py` | DEFAULT_RESEARCH_CONFIG |
| `src/llmwikify/agent/backend/research/session.py` | ResearchSessionManager |
| `src/llmwikify/agent/backend/research/web_search.py` | WebSearch（DuckDuckGo） |
| `src/llmwikify/agent/backend/research/gatherer.py` | SourceGatherer |
| `src/llmwikify/agent/backend/research/analyzer.py` | SourceAnalyzer |
| `src/llmwikify/agent/backend/research/synthesizer.py` | ResearchSynthesizer |
| `src/llmwikify/agent/backend/research/report.py` | ReportGenerator |
| `src/llmwikify/agent/backend/research/engine.py` | ResearchEngine（核心编排） |
| `src/llmwikify/prompts/_defaults/research_plan.yaml` | 子查询分解 prompt |
| `src/llmwikify/prompts/_defaults/research_report.yaml` | 报告生成 prompt |
| `src/llmwikify/web/webui-agent/src/components/ResearchPanel.tsx` | 研究面板 |
| `src/llmwikify/web/webui-agent/src/components/ResearchRating.tsx` | 评分组件 |

### 修改文件

| 文件 | 修改内容 |
|------|---------|
| `src/llmwikify/agent/backend/db.py` | 扩展 research_sessions schema，新增 5 张表的 CRUD 方法 |
| `src/llmwikify/agent/backend/routes/research.py` | 替换所有 stub 为真实实现 |
| `src/llmwikify/agent/backend/service.py` | 注入 ResearchEngine（通过 wiki_registry 获取 wiki） |
| `src/llmwikify/web/webui-agent/src/api.ts` | 新增 `api.research` namespace |
| `src/llmwikify/web/webui-agent/src/App.tsx` | 添加 `'research'` view mode |
| `pyproject.toml` | 添加 `duckduckgo-search>=4.0` 依赖 |

---

## 十一、实现顺序

| 顺序 | 步骤 | 工作量 |
|------|------|--------|
| 1 | DB schema 扩展 + 方法 | ~120 行 |
| 2 | `research/config.py` + `research/session.py` | ~100 行 |
| 3 | `research/web_search.py` + `research/gatherer.py` | ~250 行 |
| 4 | `research/analyzer.py` + `research/synthesizer.py` + `research/report.py` | ~200 行 |
| 5 | `research/engine.py`（核心编排） | ~200 行 |
| 6 | prompt 模板（2 个） | ~60 行 |
| 7 | 路由改造 `routes/research.py` | ~100 行 |
| 8 | 前端 API（`api.ts` research namespace） | ~50 行 |
| 9 | `ResearchPanel.tsx` + `ResearchRating.tsx` | ~250 行 |
| 10 | App.tsx research view mode | ~20 行 |
| 11 | `pyproject.toml` 添加依赖 | — |

**总增量**：约 1350 行

---

## 十二、关键设计决策

| 决策 | 选择 |
|------|------|
| 执行模式 | 异步（后台执行，SSE 推送进度） |
| Web 搜索 | DuckDuckGo（免费，无需 API key） |
| 并发控制 | `max_parallel_gathering=5` semaphore |
| 来源引用格式 | `[[Source:hash]]`，hash→来源映射内联在 ReportGenerator |
| rating 影响 | 高评分来源在 SynthesisEngine 加权优先 |
| Save to Wiki | 后续实现（不在第一期） |
| Wiki 来源 | 两层：wiki 页面 + raw/ 已摄取内容，LLM 自行决定 |

---

## 十三、风险与注意事项

### 风险 1：LLM 子查询分解质量
- 如果 LLM 生成的子查询质量差，后续研究效果差
- **缓解**：提供充分的 wiki_index context，让 LLM 知道已有内容

### 风险 2：YouTube 无字幕
- 部分 YouTube 视频无字幕，导致 youtube 来源失效
- **缓解**：捕获异常后标记 failed，继续其他来源

### 风险 3：来源内容过长
- 单来源可能超过 LLM context window
- **缓解**：配置 `max_source_content_length=500000`，超出截断

### 风险 4：Research SSE 前端 Fetch 实现
- `EventSource` 不支持 POST，需要使用 `fetch` + 自定义 SSE parser
- 参考 `chatStream()` 实现复用

### 风险 5：异步研究无法取消
- 用户关闭页面后研究仍在后台运行
- **缓解**：GET `/research/{id}` 时检测状态，若已完成但前端未显示则推送 done 事件

---

## 十四、未纳入第一期的功能

| 功能 | 说明 |
|------|------|
| Save to Sink（三阶段保存） | 报告先写入 `.sink/`，用户审批后写入 wiki |
| JWT 认证 | 多用户支持 |
| 研究超时管理 | `research_timeout_minutes` 配置项，但尚未实现主动超时检测 |
| 近似重复检测 | `similarity_threshold`，在 gatherer 中基于 Jaccard 去重 |
| 报告自动追加序号 | `Research: {topic} (20250526_1430)` 格式 |
| 前端 research 面板完整 UI | 报告查看、来源列表等交互细化 |