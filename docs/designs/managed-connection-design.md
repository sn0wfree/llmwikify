# ManagedConnection 设计文档

> **版本**: v1.0.0
> **日期**: 2026-07-05
> **状态**: 实施中

## 1. 背景

### 1.1 问题

项目中 SQLite 连接管理存在以下问题：

| 问题 | 影响 |
|------|------|
| **57 处裸 `sqlite3.connect` 调用** | 每次调用新建连接，无复用 |
| **PRAGMA 设置不一致** | 大部分路径无 WAL/busy_timeout |
| **38 处手动 `row_factory` 设置** | 重复代码 |
| **60 处内联 `dict(r)` 转换** | 重复代码 |
| **100+ 处手动 `conn.commit()`** | 重复代码 |

### 1.2 目标

1. 统一 SQLite 连接管理
2. 实现连接复用 (Thread-local)
3. 统一 PRAGMA 设置 (WAL + busy_timeout)
4. 提供 CRUD 辅助方法
5. 向后兼容现有代码

## 2. 设计

### 2.1 架构

```
foundation/db.py
├── connect()                    # 工厂函数 (已有，保持不变)
├── rows_to_dicts/row_to_dict   # 行转换 (已有，保持不变)
│
├── ManagedConnection            # 核心: Thread-local 持久连接
│   ├── _local = threading.local()
│   ├── conn property            # Thread-local 懒初始化
│   ├── transaction()            # 显式事务 context manager
│   ├── select_one/all           # CRUD 辅助
│   ├── execute_write()          # 写操作 + 自动 commit
│   └── close()
│
├── get_connection()             # per-path 单例函数
└── close_all()                  # 清理所有单例
```

### 2.2 `ManagedConnection` 类

```python
class ManagedConnection:
    """Thread-local persistent SQLite connection with transaction support."""
    
    def __init__(
        self,
        db_path: Path | str,
        *,
        row_factory: bool = True,
        foreign_keys: bool = True,
        wal: bool = True,
        busy_timeout: int = 5000,
        synchronous: str = "NORMAL",
    ):
        self._db_path = str(db_path)
        self._pragmas = {
            "row_factory": row_factory,
            "foreign_keys": foreign_keys,
            "wal": wal,
            "busy_timeout": busy_timeout,
            "synchronous": synchronous,
        }
        self._local = threading.local()
    
    @property
    def db_path(self) -> str:
        return self._db_path
    
    @property
    def conn(self) -> sqlite3.Connection:
        """Thread-local lazy-init connection."""
        c = getattr(self._local, 'conn', None)
        if c is None:
            c = connect(self._db_path, **self._pragmas)
            self._local.conn = c
        return c
    
    @contextmanager
    def transaction(self):
        """Transaction context manager (auto-commit/rollback)."""
        conn = self.conn
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def select_one(self, sql: str, params: tuple = ()) -> dict | None:
        """SELECT single row → dict or None."""
        row = self.conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    
    def select_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """SELECT multiple rows → list[dict]."""
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    
    def execute_write(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute SQL (auto-commit)."""
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor
    
    def execute_many(self, sql: str, params_seq: list[tuple]) -> None:
        """Execute SQL for multiple parameter sets (auto-commit)."""
        self.conn.executemany(sql, params_seq)
        self.conn.commit()
    
    def table_exists(self, table_name: str) -> bool:
        """Check if table exists."""
        row = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row is not None
    
    def add_column_if_missing(
        self, table: str, column: str, col_type: str, default: str | None = None
    ) -> bool:
        """Add column if missing (safe ALTER TABLE)."""
        try:
            sql = f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            if default is not None:
                sql += f" DEFAULT {default}"
            self.conn.execute(sql)
            return True
        except sqlite3.OperationalError:
            return False
    
    def close(self):
        """Close current thread's connection."""
        c = getattr(self._local, 'conn', None)
        if c is not None:
            c.close()
            self._local.conn = None
```

### 2.3 单例注册表

```python
_connections: dict[str, ManagedConnection] = {}
_connections_lock = threading.Lock()


def get_connection(db_path: Path | str, **kwargs) -> ManagedConnection:
    """Get or create per-path singleton ManagedConnection."""
    key = str(db_path)
    if key not in _connections:
        with _connections_lock:
            if key not in _connections:
                _connections[key] = ManagedConnection(key, **kwargs)
    return _connections[key]


def close_all():
    """Close all singleton connections."""
    for mc in _connections.values():
        mc.close()
    _connections.clear()


atexit.register(close_all)
```

### 2.4 PRAGMA 默认值

| PRAGMA | 默认值 | 理由 |
|--------|--------|------|
| `journal_mode` | WAL | 允许并发读写 |
| `busy_timeout` | 5000ms | 避免 `database is locked` |
| `synchronous` | NORMAL | WAL 安全模式 |
| `foreign_keys` | ON | 引用完整性 |
| `row_factory` | sqlite3.Row | 统一行访问 |

## 3. 迁移策略

### 3.1 阶段 1: 增强 `foundation/db.py`

- 新增 `ManagedConnection` 类
- 新增 `get_connection()` 单例函数
- 新增 `close_all()` 清理函数
- 保持 `connect()` 工厂函数不变

### 3.2 阶段 2: 迁移 `apps/db_base.py`

- `BaseDatabase.__init__`: 创建 `self._mgr = get_connection(self.db_path)`
- `BaseDatabase._connect()`: 委托 `self._mgr.conn`
- 新增 `BaseDatabase._transaction()`: 委托 `self._mgr.transaction()`

### 3.3 阶段 3: 迁移 `apps/chat/db/base.py`

- `ChatDBBase.__init__`: 创建 `self._mgr = get_connection(db_path)`
- `ChatDBBase._connect()`: 委托 `self._mgr.conn`

### 3.4 阶段 4: 迁移高频调用文件

| 文件 | 裸调用数 | 迁移方式 |
|------|---------|---------|
| `apps/wiki/db.py` | 18 | 注入 `ManagedConnection` |
| `apps/chat/memory/facts_store.py` | 10 | 注入 `ManagedConnection` |
| `apps/chat/memory/consolidation_store.py` | 7 | 注入 `ManagedConnection` |
| `apps/chat/agent/event_log.py` | 3 | 注入 `ManagedConnection` |

### 3.5 阶段 5: 迁移 Chat repos

| 文件 | 裸调用数 | 已用 `_connect()` | 迁移方式 |
|------|---------|------------------|---------|
| `apps/chat/db/chat_session_repo.py` | 7 | 2 | 改 `_connect()` 委托 |
| `apps/chat/db/chat_message_repo.py` | 4 | 1 | 改 `_connect()` 委托 |
| `apps/chat/db/tool_call_repo.py` | 3 | 1 | 改 `_connect()` 委托 |
| `apps/chat/db/admin_stats_repo.py` | 1 | 4 | 改 `_connect()` 委托 |
| `apps/chat/db/permission_repo.py` | 2 | 1 | 改 `_connect()` 委托 |
| `apps/chat/db/_facade.py` | 2 | 0 | 改 `_connect()` 委托 |

### 3.6 阶段 6: 单元测试

| 测试文件 | 测试内容 |
|---------|---------|
| `tests/test_managed_connection.py` | 生命周期、事务、线程安全、CRUD 辅助 |

## 4. 预期收益

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 连接创建 | 57 次/启动 | 3-5 次 (per-thread per-path) |
| PRAGMA 一致性 | 不一致 | 统一 WAL + busy_timeout |
| `database is locked` | 高风险 | 低 (WAL + busy_timeout) |
| fetchone/fetchall 重复 | 60 处内联 | 统一 `select_one`/`select_all` |
| 代码行数 | 重复连接管理 | 减少 ~300 行 |

## 5. 风险

| 风险 | 缓解措施 |
|------|---------|
| Thread-local 连接泄漏 | `atexit.register(close_all)` 清理 |
| 事务嵌套 | `transaction()` 不支持嵌套，显式事务保持原样 |
| 向后兼容 | `_connect()` 接口不变，子类改动最小 |
