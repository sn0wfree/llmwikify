# Agent 功能完整实现计划

> 创建时间：2025-05-26
> 状态：待评估

---

## 一、决策确认

| 决策 | 选择 |
|------|------|
| 复用 vs 重写 | **复用** — DreamEditor/NotificationManager/WikiToolRegistry 逻辑已验证 |
| 持久化 | **SQLite** — 所有状态写入 `.llmwikify/agent/.llmwiki_agent.db` |
| Wiki 隔离 | **是** — 每个命名空间按 wiki_id 分表/分区 |
| Confirmations | **迁移 SQLite** — 从 WikiToolRegistry 内存迁移到 DB |
| /agent/status scheduler 数据 | **真实数据** — 需持有 WikiScheduler 实例 |
| ingest revert | **返回 error** — append-only 设计 |

---

## 二、架构设计

```
AgentService (单例, 全局)
├── AgentDatabase (SQLite: 7 张表)
├── WikiRegistry (多 Wiki 支持)
├── _llm: StreamableLLMClient
├── _dream_editors: dict[wiki_id, DreamEditor]       (per-wiki 缓存)
├── _notification_managers: dict[wiki_id, NotificationManager]  (per-wiki 缓存)
├── _schedulers: dict[wiki_id, WikiScheduler]        (per-wiki 缓存)
└── _tool_registries: dict[wiki_id, WikiToolRegistry] (per-wiki 缓存)
```

**每个 per-wiki 组件首次访问时 lazy-init，通过 wiki_id 定位到具体 Wiki 实例。**

---

## 三、数据库 Schema

### 3.1 现有表 (db.py)

```sql
-- 已存在: chat_sessions, tool_calls, research_sessions
```

### 3.2 新增表

```sql
-- dream_proposals (持久化 + wiki 隔离)
CREATE TABLE dream_proposals (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    page_name TEXT NOT NULL,
    edit_type TEXT NOT NULL,    -- 'append'|'create'|'insert_before'|'replace'|'insert_after'|'replace_section'
    content TEXT NOT NULL,
    reason TEXT,
    content_length INTEGER,
    source_entries TEXT,       -- JSON array
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|auto_approved|applied
    created_at TEXT DEFAULT (datetime('now')),
    reviewed_at TEXT
);
CREATE INDEX idx_dream_proposals_wiki_status ON dream_proposals(wiki_id, status);

-- notifications (持久化 + wiki 隔离)
CREATE TABLE notifications (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    type TEXT NOT NULL,        -- 'info'|'success'|'warning'|'error'
    message TEXT NOT NULL,
    data TEXT,                 -- JSON object
    read INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_notifications_wiki_read ON notifications(wiki_id, read);

-- confirmations (持久化 + wiki 隔离)
CREATE TABLE confirmations (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,  -- JSON object
    action_type TEXT,
    impact TEXT,               -- JSON object
    group_name TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|executed
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_confirmations_wiki_status ON confirmations(wiki_id, status);

-- ingest_log (持久化 + wiki 隔离)
CREATE TABLE ingest_log (
    id TEXT PRIMARY KEY,
    wiki_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,   -- JSON object
    result_summary TEXT,
    status TEXT NOT NULL,      -- 'executed'|'error'
    timestamp TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_ingest_log_wiki ON ingest_log(wiki_id, timestamp DESC);
```

---

## 四、AgentDatabase 新增方法

### 4.1 Proposals

| 方法 | 签名 | SQL |
|------|------|-----|
| save_proposal | `(proposal: dict)` | INSERT OR REPLACE |
| get_proposals | `(wiki_id: str, status: str \| None, limit: int)` | SELECT WHERE wiki_id [AND status] |
| update_proposal_status | `(id: str, status: str)` | UPDATE, SET reviewed_at |
| get_proposal_stats | `(wiki_id: str)` | SELECT status, COUNT(*) GROUP BY |

### 4.2 Notifications

| 方法 | 签名 | SQL |
|------|------|-----|
| save_notification | `(n: dict)` | INSERT |
| list_notifications | `(wiki_id: str, unread_only: bool)` | SELECT WHERE wiki_id [AND read=0] |
| mark_notification_read | `(id: str)` | UPDATE read=1 |
| get_unread_count | `(wiki_id: str)` | SELECT COUNT WHERE read=0 AND wiki_id=? |

### 4.3 Confirmations

| 方法 | 签名 | SQL |
|------|------|-----|
| save_confirmation | `(c: dict)` | INSERT |
| get_confirmations | `(wiki_id: str, status: str \| None)` | SELECT WHERE wiki_id [AND status] |
| update_confirmation_status | `(id: str, status: str)` | UPDATE status |
| delete_confirmation | `(id: str)` | DELETE |
| get_confirmation | `(id: str)` | SELECT WHERE id=? |

### 4.4 Ingest

| 方法 | 签名 | SQL |
|------|------|-----|
| log_ingest | `(entry: dict)` | INSERT |
| get_ingest_log | `(wiki_id: str, limit: int)` | SELECT WHERE wiki_id ORDER BY timestamp DESC |
| get_ingest_entry | `(id: str)` | SELECT WHERE id=? |

---

## 五、组件改造

### 5.1 DreamEditor (agent/dream_editor.py)

**构造函数变更:**

```python
# 当前
def __init__(self, wiki: Any, data_dir: Path | None = None):

# 改造后
def __init__(self, wiki: Any, data_dir: Path | None = None, db: AgentDatabase | None = None, wiki_id: str | None = None):
```

**ProposalManager 改造:**

```python
class ProposalManager:
    def __init__(self, max_size: int = 200, db: AgentDatabase | None = None, wiki_id: str | None = None):
        self._proposals: list[dict[str, Any]] = []
        self._max_size = max_size
        self.db = db
        self.wiki_id = wiki_id
        if db and wiki_id:
            self._proposals = db.get_proposals(wiki_id, status=None)  # 加载所有状态

    def _sync_to_db(self, proposal: dict) -> None:
        self.db.save_proposal(proposal)

    def create_proposal(self, ...):
        proposal = {...}
        self._proposals.append(proposal)
        if self.db:
            self._sync_to_db(proposal)
        return proposal

    def approve(self, proposal_id: str) -> dict | None:
        for p in self._proposals:
            if p["id"] == proposal_id:
                p["status"] = "approved"
                p["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                self._sync_to_db(p)
                return p
        return None
```

**所有修改状态的方法** (approve/reject/batch_approve) 都需要 `_sync_to_db`。

### 5.2 NotificationManager (agent/notifications.py)

**构造函数变更:**

```python
# 当前
def __init__(self, max_size: int = 100):

# 改造后
def __init__(self, max_size: int = 100, db: AgentDatabase | None = None, wiki_id: str | None = None):
    self.db = db
    self.wiki_id = wiki_id
    self._notifications: list[dict[str, Any]] = []
    if db and wiki_id:
        self._notifications = db.list_notifications(wiki_id, unread_only=False)
```

**add() 方法同步到 DB:**
```python
def add(self, event_type: str, message: str, data: dict | None = None) -> dict:
    n = {...}
    self._notifications.append(n)
    if len(self._notifications) > self._max_size:
        self._notifications = self._notifications[-self._max_size:]
    if self.db:
        self.db.save_notification(n)
    return n
```

**mark_read() 方法同步到 DB:**
```python
def mark_read(self, notification_id: str) -> bool:
    for n in self._notifications:
        if n["id"] == notification_id:
            n["read"] = True
            if self.db:
                self.db.mark_notification_read(notification_id)
            return True
    return False
```

### 5.3 WikiToolRegistry (agent/tools.py)

**构造函数变更:**

```python
# 当前
def __init__(self, wiki: Any):

# 改造后
def __init__(self, wiki: Any, db: AgentDatabase | None = None, wiki_id: str | None = None):
    self.wiki = wiki
    self.db = db
    self.wiki_id = wiki_id
    self._tools: dict[str, dict] = {}
    self._pending_confirmations: dict[str, dict] = {}
    self._ingest_log: list[dict] = []  # 保留内存用于快速访问，长期由 AgentService 写入 DB
    self._max_ingest_log = 100
    self._register_all_tools()
    if db and wiki_id:
        self._load_confirmations_from_db()
```

**新增方法:**
```python
def _load_confirmations_from_db(self) -> None:
    rows = self.db.get_confirmations(self.wiki_id, status="pending")
    for c in rows:
        self._pending_confirmations[c["id"]] = c
```

**execute() 改为 async 并支持 DB:**

```python
async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
    tool = self._tools.get(name)
    if tool is None:
        raise ValueError(f"Unknown tool: {name}")

    confirmation_mode = tool.get("requires_confirmation", False)

    if confirmation_mode is False:
        return tool["handler"](arguments)

    elif confirmation_mode == "posthoc":
        result = tool["handler"](arguments)
        self._log_posthoc(name, arguments, result)
        return result

    else:  # "pre"
        impact = self._analyze_impact(name, arguments)
        group = self._classify_page_group(arguments)
        confirmation_id = str(uuid.uuid4())[:8]

        confirmation = {
            "id": confirmation_id,
            "tool": name,
            "arguments": arguments,
            "action_type": tool["action_type"],
            "impact": impact,
            "group": group,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }
        if self.db and self.wiki_id:
            confirmation["wiki_id"] = self.wiki_id
            self.db.save_confirmation(confirmation)
        self._pending_confirmations[confirmation_id] = confirmation

        return {
            "status": "confirmation_required",
            "confirmation_id": confirmation_id,
            "impact": impact,
            "group": group,
        }
```

**confirm_execution() / reject_execution() 同步 DB:**

```python
def confirm_execution(self, confirmation_id: str) -> Any:
    confirmation = self._pending_confirmations.pop(confirmation_id, None)
    if confirmation is None:
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}
    tool = self._tools.get(confirmation["tool"])
    if tool is None:
        return {"status": "error", "error": f"Tool not found: {confirmation['tool']}"}
    try:
        result = tool["handler"](confirmation["arguments"])
        confirmation["status"] = "approved"
        if self.db:
            self.db.update_confirmation_status(confirmation_id, "approved")
        return {"status": "executed", "confirmation_id": confirmation_id, "result": result}
    except Exception as e:
        confirmation["status"] = "rejected"
        if self.db:
            self.db.update_confirmation_status(confirmation_id, "rejected")
        return {"status": "error", "error": str(e)}

def reject_execution(self, confirmation_id: str) -> dict:
    confirmation = self._pending_confirmations.pop(confirmation_id, None)
    if confirmation is None:
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}
    confirmation["status"] = "rejected"
    if self.db:
        self.db.update_confirmation_status(confirmation_id, "rejected")
    return {"status": "rejected", "confirmation_id": confirmation_id}
```

---

## 六、AgentService 改造 (service.py)

### 6.1 新增属性

```python
class AgentService:
    def __init__(self, wiki_registry: Any, data_dir: Path):
        # ... existing ...
        self._dream_editors: dict[str, DreamEditor] = {}
        self._notification_managers: dict[str, NotificationManager] = {}
        self._schedulers: dict[str, WikiScheduler] = {}
        self._tool_registries: dict[str, WikiToolRegistry] = {}
```

### 6.2 Per-wiki 工厂方法

```python
def _get_wiki(self, wiki_id: str | None) -> Wiki:
    if wiki_id:
        return self.wiki_registry.get_wiki(wiki_id)
    return self.wiki_registry.get_default_wiki()

def _get_dream_editor(self, wiki_id: str | None = None) -> DreamEditor:
    wiki_id = wiki_id or self._get_default_wiki_id()
    if wiki_id not in self._dream_editors:
        wiki = self._get_wiki(wiki_id)
        self._dream_editors[wiki_id] = DreamEditor(
            wiki=wiki,
            data_dir=self.data_dir / wiki_id,
            db=self.db,
            wiki_id=wiki_id,
        )
    return self._dream_editors[wiki_id]

def _get_notification_manager(self, wiki_id: str | None = None) -> NotificationManager:
    wiki_id = wiki_id or self._get_default_wiki_id()
    if wiki_id not in self._notification_managers:
        self._notification_managers[wiki_id] = NotificationManager(
            max_size=100,
            db=self.db,
            wiki_id=wiki_id,
        )
    return self._notification_managers[wiki_id]

def _get_scheduler(self, wiki_id: str | None = None) -> WikiScheduler:
    wiki_id = wiki_id or self._get_default_wiki_id()
    if wiki_id not in self._schedulers:
        wiki = self._get_wiki(wiki_id)
        scheduler_dir = self.data_dir / wiki_id / "scheduler"
        scheduler_dir.mkdir(parents=True, exist_ok=True)
        scheduler = WikiScheduler(scheduler_dir)
        dream_editor = self._get_dream_editor(wiki_id)
        nm = self._get_notification_manager(wiki_id)
        scheduler.register_system_tasks(wiki, dream_editor, nm)
        scheduler.load_state()
        self._schedulers[wiki_id] = scheduler
    return self._schedulers[wiki_id]

def _get_tool_registry(self, wiki_id: str | None = None) -> WikiToolRegistry:
    wiki_id = wiki_id or self._get_default_wiki_id()
    if wiki_id not in self._tool_registries:
        wiki = self._get_wiki(wiki_id)
        self._tool_registries[wiki_id] = WikiToolRegistry(wiki, self.db, wiki_id)
    return self._tool_registries[wiki_id]
```

### 6.3 Dream 方法

```python
async def run_dream(self, wiki_id: str | None = None) -> dict:
    wiki_id = wiki_id or self._get_default_wiki_id()
    editor = self._get_dream_editor(wiki_id)
    result = editor.run_dream()
    if result.get("pending_review", 0) > 0:
        nm = self._get_notification_manager(wiki_id)
        nm.add("info", f"Dream generated {result['pending_review']} proposals for review", data=result)
    return result

def get_dream_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
    wiki_id = wiki_id or self._get_default_wiki_id()
    editor = self._get_dream_editor(wiki_id)
    return editor.get_edit_log(limit)

def get_dream_proposals(self, wiki_id: str | None = None) -> dict:
    wiki_id = wiki_id or self._get_default_wiki_id()
    editor = self._get_dream_editor(wiki_id)
    return {
        "proposals": editor.proposal_manager.get_pending_by_page(),
        "stats": editor.proposal_manager.get_stats(),
    }

def approve_proposal(self, proposal_id: str) -> dict:
    for editor in self._dream_editors.values():
        p = editor.proposal_manager.approve(proposal_id)
        if p:
            return p
    return {"status": "error", "error": "Proposal not found"}

def reject_proposal(self, proposal_id: str) -> dict:
    for editor in self._dream_editors.values():
        p = editor.proposal_manager.reject(proposal_id)
        if p:
            return p
    return {"status": "error", "error": "Proposal not found"}

def batch_approve_proposals(self, proposal_ids: list[str]) -> dict:
    results = []
    for pid in proposal_ids:
        r = self.approve_proposal(pid)
        results.append(r)
    return {"approved": len(results), "results": results}

async def apply_proposals(self, wiki_id: str | None = None, proposal_ids: list[str] | None = None) -> dict:
    wiki_id = wiki_id or self._get_default_wiki_id()
    editor = self._get_dream_editor(wiki_id)
    result = editor.apply_proposals(proposal_ids)
    if result.get("applied", 0) > 0:
        nm = self._get_notification_manager(wiki_id)
        nm.add("success", f"Applied {result['applied']} dream proposals", data=result)
    return result
```

### 6.4 Notifications 方法

```python
def list_notifications(self, wiki_id: str | None = None, unread_only: bool = False) -> list[dict]:
    wiki_id = wiki_id or self._get_default_wiki_id()
    nm = self._get_notification_manager(wiki_id)
    if unread_only:
        return nm.list_unread()
    return nm.list_all()

def mark_notification_read(self, notification_id: str) -> dict:
    for nm in self._notification_managers.values():
        if nm.mark_read(notification_id):
            return {"status": "ok", "notification_id": notification_id}
    return {"status": "error", "error": "Notification not found"}
```

### 6.5 Confirmations 方法 (改造后的路由直接调用 registry)

注意: 改造后 confirmations 的 list/approve/reject 由 WikiToolRegistry 管理,
但路由层通过 AgentService 统一路由:

```python
def list_confirmations(self, wiki_id: str | None = None) -> dict[str, list[dict]]:
    wiki_id = wiki_id or self._get_default_wiki_id()
    registry = self._get_tool_registry(wiki_id)
    return registry.get_pending_by_group()

async def approve_confirmation(self, confirmation_id: str) -> dict:
    for registry in self._tool_registries.values():
        result = registry.confirm_execution(confirmation_id)
        if result.get("status") != "error":
            return result
    return {"status": "error", "error": "Confirmation not found"}

async def reject_confirmation(self, confirmation_id: str) -> dict:
    for registry in self._tool_registries.values():
        result = registry.reject_execution(confirmation_id)
        if result.get("status") != "error":
            return result
    return {"status": "error", "error": "Confirmation not found"}

async def batch_approve_confirmations(self, confirmation_ids: list[str]) -> dict:
    results = []
    for cid in confirmation_ids:
        r = await self.approve_confirmation(cid)
        results.append(r)
    return {"approved": len(results), "results": results}
```

### 6.6 Ingest 方法

```python
def get_ingest_log(self, wiki_id: str | None = None, limit: int = 20) -> list[dict]:
    wiki_id = wiki_id or self._get_default_wiki_id()
    return self.db.get_ingest_log(wiki_id, limit)

def get_ingest_entry(self, ingest_id: str) -> dict | None:
    return self.db.get_ingest_entry(ingest_id)
```

### 6.7 /agent/status

```python
def get_agent_status(self, wiki_id: str | None = None) -> dict:
    wiki_id = wiki_id or self._get_default_wiki_id()

    scheduler = self._get_scheduler(wiki_id)
    tasks = scheduler.list_tasks()

    editor = self._get_dream_editor(wiki_id)
    dream_stats = editor.proposal_manager.get_stats()

    nm = self._get_notification_manager(wiki_id)
    unread = nm.unread_count()

    registry = self._get_tool_registry(wiki_id)
    pending_confs = len(registry.get_pending_confirmations())

    return {
        "state": "idle",
        "scheduler_tasks": tasks,
        "pending_work": {},
        "action_log": [],
        "pending_confirmations": pending_confs,
        "dream_proposals": dream_stats,
        "unread_notifications": unread,
    }
```

### 6.8 聊天流程中的 Ingest 拦截

在 `chat()` 的 `_execute_tool()` 中拦截 posthoc 工具，写入 DB:

```python
async def _execute_tool(self, tool_name, args, tool_registry, session_id):
    call_id = self.db.log_tool_call(session_id, tool_name, args, "pending")
    try:
        result = await tool_registry.execute(tool_name, args)
        status = "confirmation_required" if isinstance(result, dict) and result.get("status") == "confirmation_required" else "executed"
        self.db.update_tool_call(call_id, result, status)

        # 如果是 posthoc 工具，写入 ingest_log
        tool_def = tool_registry._tools.get(tool_name, {})
        if tool_def.get("requires_confirmation") == "posthoc":
            entry_id = f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
            self.db.log_ingest({
                "id": entry_id,
                "wiki_id": ctx.wiki_id or "default",
                "tool": tool_name,
                "arguments": args,
                "result_summary": str(result)[:500] if result else "",
                "status": "executed",
            })

        return result
    except Exception as e:
        self.db.update_tool_call(call_id, {"error": str(e)}, "error")
        return {"status": "error", "error": str(e)}
```

---

## 七、路由扩展 (routes/agent.py)

### 7.1 保留现有端点 (无需修改)
- `POST /agent/chat` — SSE 流式对话
- `GET /agent/sessions`
- `POST /agent/sessions`
- `GET /agent/sessions/{session_id}`
- `DELETE /agent/sessions/{session_id}`
- `GET /agent/sessions/recent`
- `POST /agent/sessions/recent`
- `GET /confirmations` → **改为** `GET /agent/confirmations`
- `POST /agent/confirmations/{confirmation_id}`
- `DELETE /agent/confirmations/{confirmation_id}`
- `POST /agent/confirmations/batch`
- `GET /agent/tools`
- `GET /agent/status` → **改造实现**

### 7.2 新增端点

| 方法 | 路径 | Handler | 说明 |
|------|------|---------|------|
| GET | `/agent/dream/log` | `dream_log` | 获取 dream 历史运行记录 |
| POST | `/agent/dream/run` | `dream_run` | 触发 dream cycle |
| GET | `/agent/dream/proposals` | `dream_proposals` | 获取 pending proposals |
| POST | `/agent/dream/proposals/{id}/approve` | `approve_proposal` | 批准提案 |
| POST | `/agent/dream/proposals/{id}/reject` | `reject_proposal` | 拒绝提案 |
| POST | `/agent/dream/proposals/batch-approve` | `batch_approve_proposals` | 批量批准 |
| POST | `/agent/dream/proposals/apply` | `apply_proposals` | 应用提案到 wiki |
| GET | `/agent/notifications` | `list_notifications` | 列出通知 |
| POST | `/agent/notifications/{id}/read` | `mark_notification_read` | 标记已读 |
| GET | `/agent/ingest/log` | `ingest_log` | 获取摄取日志 |
| GET | `/agent/ingest/log/{id}` | `ingest_changes` | 获取单条摄取详情 |
| POST | `/agent/ingest/log/{id}/revert` | `revert_ingest` | 返回 error |
| GET | `/agent/status` | `agent_status` | 完整状态 |

---

## 八、实施顺序

| 顺序 | 步骤 | 文件 | 工作量 | 风险 |
|------|------|------|--------|------|
| 1 | Extend DB schema + CRUD methods | `db.py` | ~120 行 | 低 |
| 2 | DreamEditor constructor + ProposalManager DB-sync | `dream_editor.py` | ~30 行 | 中 (构造函数签名) |
| 3 | NotificationManager DB-sync | `notifications.py` | ~20 行 | 低 |
| 4 | WikiToolRegistry DB-sync + async execute | `tools.py` | ~80 行 | 中 (改为 async) |
| 5 | AgentService: per-wiki caches + all methods | `service.py` | ~200 行 | 中 (新逻辑) |
| 6 | Agent routes: 13 new endpoints + update existing | `routes/agent.py` | ~90 行 | 低 |
| 7 | Build + 端点验证 | — | — | — |

**总增量**: ~540 行

---

## 九、风险评估

### 风险 1: WikiToolRegistry.execute() 改为 async
- **影响**: `AgentService._execute_tool()` 已用 `await`，但 WikiAgent 旧代码可能有同步调用
- **缓解**: 仅改 `execute()` 本身，不改 handler 签名；handler 仍为同步
- **检查点**: 确认 `agent/wiki_agent.py` 中无直接调用 `tool_registry.execute()`

### 风险 2: DreamEditor 构造函数签名变更
- **影响**: 所有直接创建 DreamEditor 实例的地方需更新
- **缓解**: 使用 `**kwargs` 兼容旧调用，或更新所有调用点
- **检查点**: `grep -r "DreamEditor(" --include="*.py"`

### 风险 3: 循环依赖
- **流程**: AgentService → DreamEditor → WikiToolRegistry → AgentService?
- **缓解**: DreamEditor 不直接持有 AgentService，但 ProposalManager 持有 AgentDatabase
- **检查点**: DreamEditor.run_dream() 调用的是 wiki 实例方法，不调用 AgentService

### 风险 4: 多 wiki 下的 confirmations 查找
- **当前**: `approve_confirmation()` 遍历所有 `_tool_registries` 查找
- **问题**: 如果 confirmation_id 在 wiki_A 但请求从 wiki_B 发起，会找不到
- **缓解**: 路由强制要求 `wiki_id` 参数，AgentService 直接定位到对应 registry
- **改造**:
```python
async def approve_confirmation(self, confirmation_id: str, wiki_id: str | None = None) -> dict:
    wiki_id = wiki_id or self._get_default_wiki_id()
    registry = self._get_tool_registry(wiki_id)
    return registry.confirm_execution(confirmation_id)
```

### 风险 5: WikiScheduler 依赖 croniter
- **状态**: `HAS_CRONITER` 可能为 False
- **缓解**: `ScheduledTask.should_run()` 在无 croniter 时返回 True（每次都运行）
- **检查点**: 确认 `croniter` 在 requirements 中

### 风险 6: API 路径不一致 — 前端 `/agent/*` vs 后端 `/api/agent/*`
- **影响**: 所有 agent/dream/notifications/ingest 端点 404
- **根因**: 后端 `agent_router` 挂载 prefix `/api/agent`，前端 api.ts 调用 `/agent/*`
- **修复**: 修改 `webui/src/api.ts` 和 `webui-agent/src/api.ts` 中所有 agent 相关路径前缀，从 `/agent/` 改为 `/api/agent/`
- **受影响端点**: `/agent/dream/*`, `/agent/notifications/*`, `/agent/ingest/*`, `/agent/confirmations/*`, `/agent/status`

### 风险 7: confirmations 重启后丢失，无法找到
- **影响**: server 重启后，`confirmations` 存在 DB 但 `_pending_confirmations` 内存为空
- **根因**: `confirm_execution()` 仅查内存，不查 DB
- **修复**: `confirm_execution()` / `reject_execution()` 先查 DB，再查内存兜底

### 风险 8: Notifications 查询读写不一致
- **影响**: DB 写入失败时数据不一致；server 重启后内存数据丢失
- **根因**: `list_all()` / `list_unread()` 读内存而非 DB，但 `add()` 同时写 DB + 内存
- **修复**: `list_all()` / `list_unread()` 直接读 DB，不再以内存为缓存

### 风险 9: apply_proposals 不更新 DB 状态
- **影响**: server 重启后 applied proposals 在 DB 中仍为 `approved`，会被重复应用
- **修复**: `apply_proposals()` 遍历时同步 `applied` 状态到 DB

---

## 十、需要确认/检查的事项

### 10.1 DreamEditor 调用点 (已确认)

```
agent/wiki_agent.py:78  — DreamEditor(self.wiki, self.data_dir)         # 2 参数，兼容
tests/test_agent_layer.py — DreamEditor(wiki_root, data_dir) × 7     # 2 参数，兼容
```

**构造函数变更向后兼容**: 新增 `db` 和 `wiki_id` 参数都有默认值 `None`，旧调用仍然有效，无需修改所有调用点。

### 10.2 croniter 依赖 (已确认)

```toml
# pyproject.toml:68
"croniter>=2.0.0",
```

### 10.3 agent_router 导出 (已确认)

```python
# agent/backend/routes/__init__.py
from .agent import router as agent_router
from .research import router as research_router
__all__ = ["agent_router", "research_router"]
```

### 10.4 前端 /agent/status 字段匹配 (已确认)

```typescript
// api.ts 期望
{
  state: string,
  scheduler_tasks: TaskInfo[],        // WikiScheduler.to_dict() 输出匹配
  pending_work: unknown,
  action_log: unknown[],
  pending_confirmations: number,
  dream_proposals: Record<string, number>,
  unread_notifications: number,
}
```

WikiScheduler.to_dict() 输出的 task 字段: `name, cron_expr, description, enabled, is_write, last_run, next_run, run_count` — 完整覆盖 TaskInfo 接口。

### 10.5 关键风险缓解

| 风险 | 缓解措施 | 验证方式 |
|------|---------|---------|
| DreamEditor 构造函数签名 | 新参数有默认值，向后兼容 | 现有测试通过 |
| WikiToolRegistry.execute() 改 async | handler 仍为同步，仅 execute 本身 await | 单元测试 |
| 多 wiki confirmation 查找 | 路由强制 wiki_id，AgentService 直接路由到对应 registry | 集成测试 |
| 循环依赖 | DreamEditor.run_dream() 调用 wiki 方法，不调用 AgentService | 代码审查 |
| API 路径不一致 | 前端 api.ts 路径前缀 `/agent/` → `/api/agent/` | 端点测试 |
| confirmations 重启丢失 | confirm_execution() 先查 DB 再查内存 | 重启后测试 |
| Notifications 读写不一致 | list_all/list_unread 直接读 DB | 写后读测试 |
| apply_proposals DB 状态 | 每次 apply 同步状态到 DB | 重启后验证 |

### 10.6 未解决问题

| 问题 | 说明 |
|------|------|
| **WikiScheduler 多 wiki 隔离** | `register_system_tasks(wiki, dream_editor, nm)` 注册的 handler 持有 wiki 实例，每个 wiki 的 scheduler 独立。但 `data_dir / wiki_id / "scheduler"` 路径隔离，`scheduler.json` 也隔离。|
| **chat() 中 `ctx` 在 `_execute_tool` 中不可见** | `_execute_tool` 无法直接访问 `ctx.wiki_id`，需要通过 `tool_registry.wiki_id` 获取。已在设计中处理。|

### 10.7 风险 6-9 详细修复

#### 风险 6 修复 — 前端路径修正

```typescript
// webui/src/api.ts 和 webui-agent/src/api.ts

// 改造前
confirmations: {
  list: () => request<...>('/agent/confirmations'),
  ...
}
dream: {
  log: (limit = 20) => request<...>(`/agent/dream/log?limit=${limit}`),
  ...
}

// 改造后
confirmations: {
  list: () => request<...>('/api/agent/confirmations'),
  ...
}
dream: {
  log: (limit = 20) => request<...>(`/api/agent/dream/log?limit=${limit}`),
  ...
}
```

同样修改 `notifications` 和 `ingest` 命名空间下的所有路径。

#### 风险 7 修复 — confirm_execution() 先查 DB

```python
def confirm_execution(self, confirmation_id: str) -> Any:
    # 1. 如果有 DB，先查 DB
    if self.db:
        conf = self.db.get_confirmation(confirmation_id)
        if conf and conf.get("wiki_id") == self.wiki_id:
            if conf["status"] != "pending":
                return {"status": "error", "error": f"Confirmation already {conf['status']}"}
            tool = self._tools.get(conf["tool"])
            if tool is None:
                return {"status": "error", "error": f"Tool not found: {conf['tool']}"}
            try:
                result = tool["handler"](json.loads(conf["arguments"]))
                self.db.update_confirmation_status(confirmation_id, "approved")
                return {"status": "executed", "confirmation_id": confirmation_id, "result": result}
            except Exception as e:
                self.db.update_confirmation_status(confirmation_id, "rejected")
                return {"status": "error", "error": str(e)}

    # 2. 内存兜底（无 DB 或 ID 不匹配本 wiki）
    confirmation = self._pending_confirmations.pop(confirmation_id, None)
    if confirmation is None:
        return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}
    ...
```

同样处理 `reject_execution()`。

#### 风险 8 修复 — Notifications 读写都走 DB

```python
class NotificationManager:
    def list_all(self) -> list[dict[str, Any]]:
        # 直接读 DB，不走内存
        if self.db and self.wiki_id:
            return self.db.list_notifications(self.wiki_id, unread_only=False)
        return list(self._notifications)

    def list_unread(self) -> list[dict[str, Any]]:
        if self.db and self.wiki_id:
            return self.db.list_notifications(self.wiki_id, unread_only=True)
        return [n for n in self._notifications if not n["read"]]

    def unread_count(self) -> int:
        if self.db and self.wiki_id:
            return self.db.get_unread_count(self.wiki_id)
        return sum(1 for n in self._notifications if not n["read"])
```

#### 风险 9 修复 — apply_proposals 同步到 DB

```python
def apply_proposals(self, proposal_ids: list[str] | None = None) -> dict:
    ...
    for proposal in to_apply:
        try:
            self._apply_single_proposal(proposal)
            proposal["status"] = "applied"
            self._sync_to_db(proposal)  # 新增：状态变更同步 DB
            results["applied"] += 1
        except Exception as e:
            ...
```

---

## 十一、文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `agent/backend/db.py` | 修改 | +5 表定义 + ~20 方法 |
| `agent/dream_editor.py` | 修改 | ProposalManager DB-sync + 构造函数变更 |
| `agent/notifications.py` | 修改 | NotificationManager DB-sync + 构造函数变更 |
| `agent/tools.py` | 修改 | WikiToolRegistry DB-sync + async execute |
| `agent/backend/service.py` | 修改 | per-wiki 缓存 + 所有新增方法 |
| `agent/backend/routes/agent.py` | 修改 | 13 个新端点 + status 改造 |
| `webui/src/api.ts` | 修改 | agent 相关路径 `/agent/` → `/api/agent/` |
| `webui-agent/src/api.ts` | 修改 | 同上，agent SPA 的 api.ts |

---

## 十二、测试计划

```bash
# 1. 构建验证
npm run build

# 2. 单 wiki 模式验证 (路径已修正为 /api/agent/*)
curl http://localhost:8000/api/agent/status
curl http://localhost:8000/api/agent/dream/proposals
curl http://localhost:8000/api/agent/dream/run
curl http://localhost:8000/api/agent/notifications
curl http://localhost:8000/api/agent/ingest/log
curl http://localhost:8000/api/agent/confirmations

# 3. 多 wiki 隔离验证
# - 注册 wiki_A, wiki_B
# - 在 wiki_A 上 run_dream 生成 proposals
# - 确认 wiki_B 的 proposals 列表为空

# 4. 持久化验证
# - 重启 server
# - 确认 proposals/notifications/confirmations 仍存在

# 5. 路径一致性验证
# - 确认前端调用 /api/agent/* 正确返回数据（非 404）
```