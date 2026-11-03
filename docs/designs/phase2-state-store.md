# Phase 2 / 方案 5 — 状态外置（Checkpointer + SQLite）

日期: 2026-11-02 · 分支: v0.41-dev
上游: [`docs/architecture/architecture-review-2026-11.md`](../architecture/architecture-review-2026-11.md)

## 问题

架构评审 P1-04：会话状态在进程内 dict，只增不减，多实例不可共享。

实测 `ChatOrchestrator.__init__` 里的三个字典：

| dict | 内容 | 清理 |
|------|------|------|
| `_session_status` | `session_id → "busy"/"idle"` | **无**（只在 chat 结束时置 "idle"，键仍在） |
| `_abort_events` | `session_id → asyncio.Event` | chat 结束时 pop ✓ |
| `_tool_registries` | `(session_id, wiki_id) → registry` | **无** ← 泄漏源 |

`_tool_registries` 缓存的是 `CompositeToolRegistry`——里面挂着 tool adapter、wiki 句柄、
（父 registry 还有）活的 SubagentManager。**长跑进程会为每个 (session, wiki) 组合永久留一份。**

## 关键判断：什么能外置，什么不能

不是所有状态都能外置。逐一分类：

| 状态 | 性质 | 处置 |
|------|------|------|
| `_session_status` | 持久状态（"busy" 值得跨实例可见） | **可外置** → store 抽象 |
| `_abort_events` | `asyncio.Event`——**不可序列化**，且天然是每进程的 | 留在进程内（已有界） |
| `_tool_registries` | 活对象——**不可序列化** | 留在进程内，但**加上界** |

强行把活对象塞进 DB 是自欺欺人。诚实的做法是：**能外置的外置，不能外置的有界**。

## 实现

### `apps/chat/agent/state_store.py`（新）

```python
@dataclass(frozen=True)
class SessionState:
    status: str = "idle"
    holder: str = ""        # 谁持有租约（实例 id）
    expires_at: float = 0.0 # 租约何时到期
```

三个实现：

| 实现 | 用途 |
|------|------|
| `InMemorySessionStateStore` | **默认**。今天的语义 + 两条上界：最多 512 条 + 1 小时 TTL，LRU 淘汰 |
| `SqliteSessionStateStore` | 落到已有的 `chat_sessions.metadata` blob（`session_state` 键），并持有**租约** |
| `DictSessionStateStore` | 兼容层：把调用方的裸 dict 包成 store（老路径不变） |

### 租约（Lease）—— 多实例的关键

业界模式（K8s Lease / Temporal 任务队列 / Redis 锁）：**有到期时间的占用声明**。

```python
def try_acquire(self, session_id, *, ttl=0.0) -> bool:
    """另一个实例持有有效租约时返回 False —— 两个服务不能同时跑同一个会话。"""
```

租约到期即失效 → **实例崩溃不会把会话永久卡在 "busy"**。

### `apps/chat/agent/registry_cache.py`（新）

`ToolRegistryCache` —— 保持原 dict 的接口（`in` / `[]` / `[]=` / `.items()`），
但**有界 + LRU 淘汰**（默认 64 条）。

### 接线

- `ChatOrchestrator.__init__` 新增 `state_store` 参数（可注入 → 多实例用 SQLite 版）
- `SessionManager` 改从 store 读；`_session_status` 变成 store 之上的 **dict 视图**
  （老代码 `mgr._session_status["s1"] = "busy"` 仍然可用）

## 途中踩到的两个坑

1. **`__getitem__` 里重新插入会破坏迭代**。LRU 的常见写法是「读时把 key 移到末尾」，
   但 `dict(cache.items())` 会在迭代中改结构 → `RuntimeError: dictionary keys changed
   during iteration`。修法：recency 用**独立的计数器**记录，不动数据结构本身。
2. **Windows 的 `time.time()` 分辨率只有 ~15.6 ms**。用时间戳给 LRU 排序时，
   连续三次写入拿到**同一个时间戳** → 淘汰顺序随机。修法：recency 用**单调计数器**，
   墙钟只负责 TTL。

## 回归网

`tests/test_chat_state_store.py`（29 项）：

| 分组 | 内容 |
|------|------|
| InMemory | 读写/清理、条目上限淘汰、TTL 淘汰、读刷新 recency、过期租约读作 idle |
| Dict（兼容） | 调用方的 dict 仍是真源 |
| 视图 | dict 语义、读穿透到 dict、未知键抛 KeyError |
| SQLite | 持久化、新实例可见、租约互斥、过期可接管、release、clear 不动其它 metadata、**DB 坏了不拖垮聊天** |
| RegistryCache | mapping 接口、LRU 淘汰、读刷新、**永不超上限** |
| 接线 | orchestrator 用了有界缓存与 store、可注入 store、session manager 走 store |

## 验证

```
pytest tests/test_chat_state_store.py + session_manager → 42 passed
全量 pytest → 59 failed（基线 58）
  唯一「新增」是 test_elapsed_sec —— 已确认是 Windows 时钟精度 flaky
  （改动前后单跑都随机）
ruff check → clean
```

## 未做

- 状态写入走**异步落盘**（写后 flush），避免每次 chat 起止都同步写一次 DB。
  当前 SQLite store 是同步写的——metadata blob 的写是 UPSERT，成本可接受，
  但高频场景需要改成写后异步。
- 多实例的**读放大**：`SqliteSessionStateStore.list_all()` 要扫 session 行，
  高频调用需要缓存。
