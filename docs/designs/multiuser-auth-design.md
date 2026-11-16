# 多用户与授权模型 — 设计方案（待评审）

> 日期: 2026-11-13
> 状态：**设计已收口** —— **D1–D9 全部拍板，Q1–Q6 全部拍板**；可开 P1 实施
> 依据：`docs/designs/multiuser-auth-research.md`（业界调研，含 PostgreSQL / NIST / Kubernetes / Casbin / GitHub / SQLite / SpiceDB / Envoy 一手取证）
> 现状基线：`docs/llmwikify-auth-缺陷清单.md`（25 条，P0/P1 全清）
> 架构约束：`foundation → 仅 foundation`；`apps` 互不依赖；`scripts/check_architecture.py` 门禁 0 violation

---

## 0. 一页摘要

**问题**：今天 llmwikify 的授权只有两个 JWT 字段（`scope` 全局 read/write、`wikis` 恒 `["*"]`），
没有「谁能读/写哪个 wiki」的管理面。

**方案**：借数据库授权表的形状，建一张 `wiki_grants` 表
（`user_id × wiki_id × read/write`），把授权从「JWT 里的常量」变成「可管理的行」。

```
今天：  user ──签──▶ JWT{ scope: read|write, wikis: ["*"] }  ──▶ middleware 裁决
明天：  user ──▶ wiki_grants 表 ──签──▶ JWT{ grants: [...] } ──▶ middleware 裁决
                            ▲
                     auth grant / revoke CLI
```

**不做**：角色表 / 继承 / deny 规则 / 策略引擎（Casbin/OPA）/ GRANT OPTION。

---

## 1. 目标与非目标

### 1.1 目标

| # | 目标 | 可验收 |
|---|---|---|
| G1 | 能表达「用户 A 可读 wiki-X、可写 wiki-Y」 | `wiki_grants` 能存下并被裁决 |
| G2 | 授权可管理（CLI 增删查） | `auth grant/revoke/list` 可用 |
| G3 | 用户生命周期可管理 | `auth create-user/list-user/disable-user` |
| G4 | **token 权限 ⊆ 用户权限**（GitHub 铁律） | 用户失权后其 token 不再越权 |
| G5 | 现有单用户用法**零破坏** | 单 admin 场景行为不变 |

### 1.2 非目标（明确排除）

| # | 非目标 | 理由 |
|---|---|---|
| N1 | 角色表 / role membership / 继承 | 调研 C6：RBAC 价值在 500+ 规模；我们是 <50 人团队 |
| N2 | deny / 拒绝规则 | K8s「纯加法无 deny」是主流；撤销 = 删行 |
| N3 | `WITH GRANT OPTION`（授权可传递） | 单层 admin 足够 |
| N4 | 通用策略引擎（Casbin / OPA / Cedar） | 资源只有 1 类、动作只有 2 个；新依赖不值 |
| N5 | 列级 / 表级细分权限 | 我们只有 wiki 一个对象粒度 |
| N6 | 与外部 IdP（OIDC/LDAP）集成 | roadmap Phase 4 hub 的事 |
| N7 | 页级（page-level）权限 | roadmap Phase 4 才谈 public flag |

---

## 2. 现状盘点（实证）

### 2.1 数据面

```
users(id, email, username, is_first_admin, created_at, last_login_at)
api_keys(id, key_prefix, key_hash, user_id, name, scopes, created_at,
         last_used_at, expires_at, revoked_at)
```

`users` 只有 `is_first_admin` 一个布尔标记 ⇒ **只有两种身份：admin / 非 admin**。

### 2.2 签发面

| 位置 | 签什么 | 问题 |
|---|---|---|
| `cli/commands/auth.py:_sign_local_token` | admin → `scope=write, wikis=["*"]`；非 admin → `scope=read, wikis=["*"]` | **wiki 维度全开**；无 per-user 授权可读 |
| `http/auth_routes.py` `/verify` | `scope=api_key.scopes, wikis=["*"]` | 同上 |
| `http/auth_routes.py` `/register` | `scope=write, wikis=["*"]` | 同上 |
| `prompt.py`（serve auto-init） | `scope=write, wikis=["*"]` | 同上 |

**根因一句话**：`wikis` claim **没有数据源** —— 只有签发时写死的常量。

### 2.3 裁决面（已存在，可直接复用）

| 位置 | 做什么 |
|---|---|
| `middleware.py:_check_wikis_claim(path, claims)` | `/api/wiki/{id}/…`（5+ 段）比对 `claims.wikis` |
| `wiki/registry_routes.py:42` | `/api/wikis` 按 `claims.wikis` 过滤 |
| `wiki/search_routes.py:23` | 跨 wiki 搜索按 `claims.wikis` 取交集 |

✅ **裁决点已在（P0-1 修复时扩过），只缺数据源。**

### 2.4 用户管理面

| 能力 | 现状 |
|---|---|
| 建第一个 admin | ✅ `auth init` / HTTP `/register` |
| 建第二个用户 | ❌ `registration_closed`（P1-1 修复后**故意**关的）—— **无 CLI / API 入口** |
| 给已有用户发 token | ✅ `auth create-token --user`（P1-2 修复后） |
| 禁用 / 删除用户 | ❌ 无 |
| 列出用户 | ❌ 无 |
| 管理 wiki 授权 | ❌ 无 |

### 2.5 与目标的差异总表

| 维度 | 现状 | 目标（本设计） |
|---|---|---|
| 用户数 | 只有 1 个 admin | `create-user` / `list-users` / `disable-user` |
| 组 | 无 | `groups` + `group_members` |
| 授权载体 | JWT 里写死的 `wikis=["*"]` | **`wiki_grants` 表** + claims 快照 |
| wiki 维度 | 全开（`["*"]`） | `principal×wiki×r/w`，非 admin 默认无 |
| 读写粒度 | **全局** `scope` | **per-wiki** `can_read / can_write` |
| 撤销 | 无（logout 不吊销） | 删行即生效；禁用即失效（D6 = A） |
| public_read | 全局开关 | `principal_type='public'` 行（D9 已定） |
| 自检 | 无 | `auth can-i` |
| 裁决 | 只查 claims | claims **∩** grants 表；失败 fail-closed |

---

## 3. 目标模型

### 3.1 形状（借 PG 的 `GRANT`，调研 C1/C3/C5；**含组支持**）

```sql
-- 主体：user / group / public（public = PG 的 PUBLIC 伪角色 /
--       K8s 的 system:authenticated 组）
wiki_grants(
    principal_type TEXT NOT NULL,      -- 'user' | 'group' | 'public'
    principal_id   TEXT NOT NULL,      -- user_id | group_id | '*'
    wiki_id        TEXT NOT NULL,      -- 具体 wiki_id，或 '*' 通配（Q3-a）
    can_read       INTEGER NOT NULL DEFAULT 0,   -- D4：只有 read / write
    can_write      INTEGER NOT NULL DEFAULT 0,
    granted_by     TEXT,               -- 审计（PG R5）
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (principal_type, principal_id, wiki_id)
);
-- D3 = wiki 级：无 page_id（N7 排除）
-- D8 = 非 admin 默认无授权：不写任何默认行
-- D9 = 未认证可读 = principal_type='public' 行（不是全局开关）

-- 组（K8s 式 Group subject）
groups(id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, created_at TEXT)
group_members(group_id TEXT NOT NULL REFERENCES groups(id),
              user_id   TEXT NOT NULL REFERENCES users(id),
              PRIMARY KEY (group_id, user_id))
```

**一次性解析用户的主体集合**（纯加法并集，PG R2 / K8s K1）：

```sql
SELECT wiki_id, MAX(can_read) AS r, MAX(can_write) AS w
FROM wiki_grants
WHERE (principal_type = 'user'  AND principal_id = :uid)
   OR (principal_type = 'group' AND principal_id IN
       (SELECT group_id FROM group_members WHERE user_id = :uid))
   OR  principal_type = 'public'
GROUP BY wiki_id
```

**四条语义规则**（直接来自 PG）：

| 规则 | 来源 | 我们的落地 |
|---|---|---|
| **纯加法**：多行并集，无 deny | PG R2 / K8s K1 | 撤销 = `DELETE` 行（D5） |
| **owner 隐含全权** | PG R1 | `is_first_admin=1` 的用户**不需要** grant 行 |
| **PUBLIC 伪角色** | PG R3 | `principal_type='public'` 行 = 未认证可读 |
| **授权可传递** | PG R4 | **不做**（N3） |

### 3.2 身份与权限的分离

| 层 | 存什么 | 变不变 |
|---|---|---|
| **身份**（who） | `users` + `groups` / `group_members` | 很少变 |
| **能力**（what can do） | `wiki_grants` | 经常变 |
| **凭证**（how prove） | `api_keys` / JWT | 每 token 一份 |
| **快照**（token 上的副本） | `claims.wgrants` | 签发时冻结 |

### 3.3 token 与授权的关系（GitHub 铁律 C4 + **D7**）

```
最终权限 = token 快照（claims.wgrants）  ∩  用户实时上界（wiki_grants 查询）
```

> **快照管上限，实时管当下** ——
> 「加权限」不追溯到已发 token（快照不动）；
> 「撤权限 / 禁用户」立即生效（实时收紧）。

---

## 4. 决策点

| # | 决策 | 选项 | 状态 | 理由 |
|---|---|---|---|---|
| **D1** | 授权表形状 | (a) 扁平 `principal×wiki×r/w` (b) 角色表 + grant (c) 通用引擎 | ✅ **(a)**，**含组支持** | 调研 C6；规模 <50 人；少 2 张角色表；组按 K8s 的 `subject.kind` 并入同一表 |
| **D2** | 授权存哪 | (a) `auth.db` (b) wiki 自己的 DB | ✅ **(a)** | 授权是**全局**事实；与 wiki 生命周期解耦 |
| **D3** | 授权粒度 | (a) 只到 wiki (b) 到 page | ✅ **(a) wiki 级** | page 级 = 每次读页都查表；N7 已排除 |
| **D4** | 动作集合 | (a) read/write (b) read/write/admin | ✅ **(a) read/write** | admin 是**身份**不是**动作** |
| **D5** | deny 规则 | (a) 无 (b) 有 | ✅ **(a) 删行即撤销** | PG/K8s 均无；撤销=删行，语义无歧义 |
| **D6** | 撤销后已发 token | (a) 每请求查表（实时） (b) 纯快照 (c) 短 TTL + refresh | ✅ **(a) 每请求查表，已发 token 立即失效** | 见 §4.1 |
| **D7** | token 载荷 | (a) 快照 (b) 每请求查表 (c) 两者都做 | ✅ **(c) 快照 + 实时上界校验** | 快照=token 上限，实时=撤权/禁用户立即生效 |
| **D8** | 非 admin 的默认 | (a) 默认无授权 (b) 默认全 wiki 只读 | ✅ **(a) 默认无授权**（最小权限） | K8s 警告：通配易过度授权 |
| **D9** | `public_read` 落点 | (a) 保留全局开关 (b) `public` 主体行 | ✅ **(b) `public` 主体行** | 组支持后更统一（PG PUBLIC 伪角色） |

### 4.1 D6 讨论 → **已拍板：A（2026-11-13）**

> **拍板结论**：**A —— 每请求查 `wiki_grants`，已发 token 立即失效。**
> 「立即失效」= **下一个请求就被拒**，不用等 token 的 30 天自然过期。

**澄清「撤权 / 已发 token / 立即失效」**（评审中讨论的留痕）：

| 术语 | 含义 |
|---|---|
| **已发 token** | 已经签好、发给用户、正在使用的 JWT/PAT。其 claims 里**写死**了当时能访问哪些 wiki（「快照」） |
| **撤权** | `DELETE FROM wiki_grants WHERE principal=… AND wiki_id=…` |
| **立即失效** | **下一个请求就被拒**，不必等 token 过期 |

**判定场景**：

| 时间 | 事件 |
|---|---|
| 10:00 | admin 给 alice 授权 `wiki-a` 可写 |
| 10:05 | alice 登录 → 拿到 token **T**（有效 30 天，claims 含 wiki-a:rw） |
| 10:30 | alice 用 T 写 `wiki-a` → 成功 |
| **11:00** | **admin 撤权**（删 `wiki_grants` 行） |
| 11:01 | alice 又用 **T** 写 `wiki-a` → **？** |

| 方案 | 11:01 结果 | 后果 |
|---|---|---|
| **B. 纯快照** | 仍成功，直到 T 过期 | **撤权形同虚设** ❌ |
| **A. 每请求查表**（✅ 已定） | **403，下一个请求就拒** | 撤权真生效 |
| **C. 短 TTL** | 403，最迟延迟 ≤ TTL | 折中 |

**语义先定死**（D7 = c 的直接推论）：

| 组成 | 作用 | 是否需查库 |
|---|---|---|
| **快照** `claims.wgrants` | **token 的上限** —— 签发时该 token 允许哪些 wiki/动作 | 否（claims 自带） |
| **实时上界** `wiki_grants` 查询 | **用户当前的上限** —— 撤权 / 禁用户立刻生效 | **是**（每次请求 1 次） |

最终权限 = **交集**。
⇒「加权限」不追溯已发 token（快照不动）；
⇒「撤权限 / 禁用户」立即生效（实时收紧）。

**三案对比（评审依据）**：

| | **A. 每请求查表** ✅ | **B. 纯快照** | **C. 短 TTL + refresh** |
|---|---|---|---|
| 撤权生效 | **立即** | token 过期（30d）❌ | ≤ TTL |
| 请求路径 IO | 1 次主键点查 | 0 | 0 |
| 实现量 | 小（1 条 SELECT） | 最小 | 大（+refresh 表/端点/cookie） |
| 跨进程可见 | ✅ DB 共享 | — | — |
| 主要风险 | 依赖 auth.db 可读 | **撤销形同虚设** | 交互复杂，本地工具过重 |

**选 A 的理由**：

1. **性能不是瓶颈**：grants 是主键点查（warm 约 20–100µs）；一次 wiki 页读是「文件 + SQLite + 图分析」毫秒级 ⇒ 开销 **<1%**。若后续压测需要，可用 `auth.db` mtime 作缓存版本号（撤权即写 DB ⇒ mtime 变 ⇒ 跨进程也自然失效）。
2. **B 在产品上是错的**：最需要撤权的两个场景（误授权、凭据泄露）恰恰是 B 最无能为力的时候。
3. **CLI 与 server 常是不同进程**：B/C 都要求「改授权 ⇒ 重签 token」，但 `auth revoke` 在 CLI 进程、用户不会想到去服务端重签。

**A 的代价（如实记录）**：每次请求依赖 `auth.db` 可读 ⇒ **查表失败必须 fail-closed**（保守拒绝），不得放行。

**A 的附带收益**：落地后 `users.disabled_at` 可支撑「禁用用户 ⇒ 其所有 token 立即失效」。
⚠️ 但**单 token 级吊销**（JWT logout）仍需 denylist —— 那是 P2-3，独立议题，本次不做。

### 4.2 D6 的性能与并发（2026-11-13 补，实测 + 业界）

**问题**：每次请求查表，会不会锁死 `auth.db`？

**实测**（5000 行，主键点查）：

| 姿势 | 单次耗时 | 说明 |
|---|---:|---|
| 复用连接点查 | **25–28 µs** | 1000 次 = 25 ms |
| **每次开新连接** | **208 µs** | ≈ **8 倍** —— 连接建立是大头 |
| `journal_mode` 默认 | **`delete`（回滚日志）** | ⚠️ **现在就是这样**（`foundation/db.py::connect(wal=False)`） |

**SQLite 并发语义**（一手源：sqlite.org/wal.html）：

| 模式 | 语义 | 疯狂鉴权时 |
|---|---|---|
| **rollback journal（现状）** | **读阻塞写、写阻塞读** | 一次 `auth grant`（写）挡住后面的鉴权读 ⇒ **会排队** |
| **WAL** | "readers do not block writers and a writer does not block readers" | 读写并发；**只允许 1 个写者**（auth 写很少） |
| WAL 的坑 | 持续读 + 长事务 ⇒ checkpoint 无法完成 ⇒ WAL 无限增长 ⇒ 读变慢 | 不锁死，但要留「reader gaps」 |
| WAL 仍会 BUSY | exclusive locking / 崩溃恢复 / 最后连接清理 三个窄窗口 | 已有 `busy_timeout=5s` 兜底 |

⇒ **「锁死」的风险来自 journal mode + 每次开新连接，不是「查表」本身。**

**业界做法**（一手源）：

| 系统 | 做法 | 证据 |
|---|---|---|
| **SpiceDB / Zanzibar** | **多层缓存权限判定**，用一致性等级换延迟 | "implements a number of levels of caching, to ensure that repeated permissions checks do not need to be recomputed over and over again"；`fully_consistent` "explicitly bypasses caching, dramatically impacting latency" |
| **Envoy ext_authz** | 外部授权服务 + **超时 + fail-closed** | `timeout: 200ms`（默认）；`failure_mode_allow: false`；`ok/denied/error/failure_mode_allowed` 统计 |
| **SQLite WAL** | 读写并发 + checkpoint | 见上表 |

**规模差异**：SpiceDB 缓存是为「每秒百万次检查」；llmwikify 是 **<50 人本地工具**，
一次 wiki 页读是毫秒级（文件 + SQLite + 图分析）⇒ 25µs 鉴权查表 **占比 <1%**。

**D6 语义不变，实现加两层**：

```
1. local_mode / is_first_admin / 无 token + public_read → 短路，根本不查表
   （热路径大多数请求在这里就结束）
2. 查 wiki_grants：WAL + 复用连接 + 主键点查 ≈ 25µs
3. （可选）内存缓存 + epoch 失效 —— 只有压测证明需要才加
```

**五条硬措施**：

| # | 措施 | 为什么 | 归属 |
|---|---|---|---|
| **M1** | `auth.db` **开 WAL**（`connect(wal=True)`） | 消除读写互锁 | P1 必做 |
| **M2** | **复用连接**（进程内 1 个/线程） | 8 倍性能差；现在 `_connect()` 每次新建 | P1 必做 |
| **M3** | **`_init_schema` 不每次跑**（P2-12 同根） | 每实例化 PRAGMA + executescript 是纯开销 | P1 必做 |
| **M4** | **fail-closed + 超时** | 查表失败/超时 → 403，不放行、不悬挂 | P4 必做 |
| **M5** | **IP 级 rate limit** | 「疯狂鉴权」的闸门（middleware 已有） | 已有，需覆盖鉴权路径 |

> **Windows 额外注意**：锁语义更紧、杀软会短暂持锁 —— M1/M2 尤其重要。

---

### 4.3 Q3 讨论 → **已拍板：表允许通配，token 永远具体列表（2026-11-13）**

> **拍板结论**（用户确认「按建议」）：
> **Q3-a = (a)** 表里允许 `wiki_id='*'` 通配行；
> **Q3-b = (b)** claims 快照**签发时求值展开**为具体 wiki 列表；
> **Q3-c = (i)** `*` **覆盖未来新建**的 wiki（GitHub 语义）。
>
> 一句话：**表里允许 `*`（管理便利），token 里永远是具体列表（范围明确）**。

**三个子问题**：

| 子问题 | 选项 | 业界对照 |
|---|---|---|
| **Q3-a** 表里能否写 `wiki_id='*'` | (a) 能，通配行 (b) 不能，只能具体 id | GitHub「All repositories」= 通配；PG `ALL TABLES IN SCHEMA` = 展开 |
| **Q3-b** claims 快照存什么 | (a) 存 `*` (b) **签发时求值展开**为具体列表 | GitHub token 签发时明确「All / Only select」 |
| **Q3-c** `*` 覆盖**未来新建**的 wiki 吗 | (i) 覆盖（GitHub 语义） (ii) 不覆盖（PG 语义） | 两家相反 |

**业界两种做法**（一手源）：

| 系统 | 做法 | 原文要点 |
|---|---|---|
| **GitHub FG-PAT** | **通配**：「All repositories」= 新仓库**自动纳入** | "Repository access: All repositories / Only select repositories" |
| **PostgreSQL** | **展开**：`GRANT … ON ALL TABLES IN SCHEMA` 只对**当时的**表；新表不自动 | "This functionality is currently supported only for tables…"；另有 `ALTER DEFAULT PRIVILEGES` 专治「新对象默认授权」 |
| **Kubernetes** | `resources: ["*"]` 是**类型**通配；**namespace 必须显式**（Role 绑定到 ns） | "Caution: Using wildcards … could result in overly permissive access" |

**关键洞察：两层可以不一致**（D7 已定「最终权限 = 快照 ∩ 实时上界」）：

| 层 | `*` 的含义 | 新 wiki 时 |
|---|---|---|
| **grants 表（实时上界）** | 一行表示「该主体对全部 wiki 的授权」 | **自动纳入上限**（Q3-c = i） |
| **claims 快照（token 上限）** | **不存在** —— 签发时求值展开为 `["wiki-a","wiki-b"]` | **老 token 拿不到** |
| **裁决** | 实时：`*` 命中该 wiki；快照：精确列表比对 | 交集 |

**收益**：

| 收益 | 说明 |
|---|---|
| 管理方便 | `auth grant --user u --wiki '*'` 一行搞定；wiki 增删不失配 |
| token 范围**明确** | 快照是具体列表，`auth whoami` 直接可见；审计无歧义 |
| 新 wiki **不静默扩大 token 权限** | 老 token 要访问新 wiki 得 `auth token` 重签 —— 权限增长经过一道显式动作 |
| 撤权立即生效 | `auth revoke --user u --wiki '*'` 删一行 ⇒ 实时收紧（D6） |
| 与 D8 一致 | 非 admin 默认无授权；`*` 是**显式**给的全集，不是默认 |

**代价**：新 wiki 对已授权用户「可见」但要重签才可访问 ⇒ 文档写清，并在 `auth whoami` / `auth can-i` 提示「当前 token 未覆盖新 wiki，重签请跑 `auth token`」。

**建议**：~~**Q3-a = (a) 通配行**；**Q3-b = (b) 快照求值展开**；**Q3-c = (i) `*` 覆盖新建 wiki**。~~
**→ 已采纳**（见本节开头拍板结论）。

---

## 5. 关键机制设计

### 5.1 签发：claims 装什么

**候选 A（拍板 D7）**：

```json
{
  "sub": "user:abc",
  "scope": "read",              // 保留：全局上限（向后兼容）
  "wikis": ["wiki-a", "wiki-b"], // 保留：可访问 wiki 列表
  "wgrants": {                  // 新增：per-wiki 读写
     "wiki-a": "r",
     "wiki-b": "rw"
  },
  "exp": ..., "aud": ..., "iss": ...
}
```

| 兼容点 | 说明 |
|---|---|
| 老 token（无 `wgrants`） | 裁决时按「`wikis` 全可写」（= 今天的 admin 行为）→ **向后兼容**，不必强制重签 |
| `wikis` 保留 | 现有 `_check_wikis_claim` / registry / search 三处过滤**不用改**；**但值改为求值展开后的具体列表**（Q3-b），不再出现 `["*"]` |
| `scope` 保留 | 全局上限，非 admin 仍 read-only（现状） |
| 新建 wiki | 实时上界含 `*` 时自动纳入；**老 token 需 `auth token` 重签**才可见（Q3-c） |

### 5.2 裁决：请求 → 决策

```
GET  /api/wiki/wiki-a/page/x   → 需 can_read(wiki-a)
POST /api/wiki/wiki-a/page/x   → 需 can_write(wiki-a)
GET  /api/wikis                → 列 claims.wikis 覆盖的 wiki
GET  /api/search/cross         → 列 claims.wikis ∩ 可读集合
```

裁决顺序（**短路**）：

```
1. local_mode（回环）→ 全放行                 ← 决策 12，保留
2. 无 token → public 主体行 ? GET 放行 : 401/403
3. 验签（JWT / PAT）失败 → 401
4. 全局 scope 检查（非 GET 需 write）→ 403
5. 取 wiki_id（路径 / registry / search 三类路由）
6. 查 wiki_grants（实时上界，含 user + group + public 三路并集）
   → 无行 → 403；查表失败 → fail-closed 403
7. 快照比对（claims.wgrants）：快照没有该 wiki → 403
8. 放行
```

> **第 6 步是「实时上界」，第 7 步是「快照」** —— 两者取交集即 D7 语义。
> 第 6 步一次查询覆盖 user / group / public 三路（§3.1 的 SQL），
> 主键 `(principal_type, principal_id, wiki_id)` 索引够用；
> `group_members(user_id)` 需索引。
> ⚠️ **查表失败必须 fail-closed**（保守拒绝），不得放行。

### 5.3 用户生命周期

| 命令 | 语义 | 约束 |
|---|---|---|
| `auth create-user --email X` | 建非 admin 用户 | 只有 admin 能跑；`username` 自动派生去重（P1-5 已修） |
| `auth list-users` | 列用户 + 其授权摘要 | 只读 |
| `auth disable-user <id>` | 禁用（软删） | 其 token 立即失效（D6）；**不删行**（审计留痕） |
| `auth grant --user U --wiki W [--read/--write]` | 加授权 | 幂等（upsert） |
| `auth revoke --user U --wiki W` | 撤授权 | 删行；对应 token 立即失效 |
| `auth can-i --user U --wiki W --write` | 自检（K8s K5） | 只读，返回 yes/no |

**组相关命令**（Q1 = b 后新增）：

| 命令 | 语义 | 约束 |
|---|---|---|
| `auth group create <name>` | 建组 | 只有 admin |
| `auth group list` | 列组 + 成员 | 只读 |
| `auth group add <group> --user U` | 加成员 | 幂等 |
| `auth group remove <group> --user U` | 移成员 | |
| `auth grant --group G --wiki W [--read/--write]` | 给**组**授权 | 幂等 upsert；与 `--user` 互斥 |

> **组授权的撤销影响面更大**：撤一个组授权 ⇒ 组内所有成员立即失权（D6 语义在组场景下更重要）。

### 5.4 用户禁用如何让 token 失效

`users` 加一列：

```sql
ALTER TABLE users ADD COLUMN disabled_at TEXT;   -- NULL = 有效
```

裁决第 3 步之后追加：

```
3.5 claims.sub → user_id → 查 users.disabled_at
    非空 → 401 user_disabled
```

> 为何不用 JWT denylist：JWT 无状态，加 denylist 就要查表（本来就查），
> 且 **JWT 里的用户状态本来就是会变的**（禁用）—— 与「授权变更立即生效」是同一类问题。
> 查 `users` 一次的成本可接受（SQLite 本地，同进程）。

### 5.5 撤销 / 禁用的生效路径（D6 = A 的完整语义）

| 动作 | 写什么 | 对**已发** token 的影响 | 生效 |
|---|---|---|---|
| `auth revoke --user U --wiki W` | `DELETE FROM wiki_grants WHERE …` | 该 wiki 的操作被**裁决第 6 步**拦下 | **立即** |
| `auth disable-user U` | `UPDATE users SET disabled_at=now()` | 其**所有** token 被**第 4 步**拦下 | **立即** |
| `auth revoke-token <id>` | `api_keys.revoked_at=now()` | 该 PAT 失效（已有功能） | **立即** |
| **JWT logout** | 无 | **仍无法吊销**（P2-3，需 denylist） | 30 天后过期 |
| `auth grant …` | `INSERT …` | **不追溯**老 token（快照未含该 wiki） | 新签 token 才可见 |

> 「加权限」只流向新 token；「减权限 / 禁用户」立刻收紧 —— 这是 D6 + D7 的组合语义。

### 5.6 管理面数据流（CLI → 表）

```
auth init / create-user ─────────▶ users
auth group create/add/remove ────▶ groups + group_members
auth grant --user|--group ───────▶ wiki_grants   （INSERT/upsert）
auth revoke ─────────────────────▶ wiki_grants   （DELETE = 撤销）
auth disable-user ───────────────▶ users.disabled_at
auth create-token ───────────────▶ api_keys  +  JWT claims 快照
auth can-i --user U --wiki W --write  → 只读自检（K8s kubectl auth can-i）
```

**管理面约束**：

| 规则 | 说明 |
|---|---|
| **admin 专属** | `create-user` / `group` / `grant` / `disable-user` 只有 admin 能跑 |
| **`--user` 与 `--group` 互斥** | 一条 `grant` 只授给一个主体 |
| **幂等** | `grant` = upsert；`group add` = 幂等 |
| **撤销 = 删行** | 无 deny 行（D5）；`group list` 显示成员数，撤销前提示影响面 |
| **WebUI = 同一套表的 UI** | P5 的授权管理页直接读写 `wiki_grants` |

---

## 6. 数据迁移与兼容

| 场景 | 处理 |
|---|---|
| **升级后现有单 admin** | `is_first_admin=1` ⇒ 隐含全权，**无需写 grant 行**（PG R1） |
| **升级后现有非 admin** | 今天不存在（建不了第二个用户）⇒ 无需迁移 |
| **老 JWT（无 `wgrants`）** | 裁决时按老语义（`wikis` 全可写）；`auth token` 重签后按新语义 |
| **单用户场景** | 行为**完全不变**（admin 隐含全权）⇒ G5 零破坏 |
| **`public_read`** | **D9 = (b) 落成 `principal_type='public'` 行**；升级时把现有 `public_read=True` 行为迁移为一条 `public` 的 read grant（见 P1 迁移） |

---

## 7. 分期实施（每期独立可验收）

| 期 | 内容 | 风险 | 依赖 | 状态 |
|---|---|---|---|---|
| **P1** | `wiki_grants` + `groups` + `group_members` 表 + `GrantRepository`（建表/读写/查 + `*` 通配求值）+ **M1 WAL / M2 连接复用 / M3 schema 一次** | **低**（纯新增） | ✅ | ✅ **已完成**（§12.1） |
| **P2** | `users.disabled_at` + `auth create-user/list-users/disable-user/enable-user` | 低 | — | ✅ **已完成**（§12.2） |
| **P3** | 签发装 `wgrants`（claims）+ `auth grant/revoke/can-i` CLI | 中（改签发） | P1 P2 | ✅ **已完成**（§12.3） |
| **P3b** | 组管理 CLI（`auth group create/list/add/remove` + `grant --group`） | 低 | P1 P3 | ✅ **已完成**（§12.4） |
| **P4a** | 纯函数 `authorize()` + ④⑤⑥'⑥⑦ + 旧 token 兼容 + fail-closed + PAT 快照修补 | 中（动中间件） | P3 | ✅ **已完成**（§12.5） |
| **P4b** | 列表路由 snapshot ∩ live + ② 无 token → 401（`public_read` 废弃）+ 用户存在检查 + exploit 终验 | 中低 | P4a | ✅ **已完成**（§12.6） |
| **P5** | WebUI：授权管理页 + `/me` 返回权限矩阵 | 中 | P3 | 待开工 |
| **P6** | share token（roadmap Phase 3）—— **独立表 `share_tokens`**（Q5 = a） | 低 | 可延后，与 P1–P5 解耦 | 待开工 |

**建议顺序强调**：P1–P3 是**纯增量**（不动裁决路径），可先落地再评审 P4 的裁决策略。

---

## 8. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 裁决路径改动引入回归（P0-1/P0-2 刚修好） | P4 单独评审；保留 `wikis` 旧路径做双跑对比；`tools/exploit_check_wikis_claim.py` 作回归门禁 |
| R2 | 每次请求多一次 SQLite 查询 | M1 WAL + M2 连接复用（实测 25µs vs 208µs）+ M3 schema 一次；如需缓存用 `auth.db` mtime 作版本号（撤权即写 DB ⇒ 跨进程也失效） |
| R3 | D6「立即失效」与 JWT 无状态冲突 | 已定义为「快照 ∩ 实时上界」；**查表失败 fail-closed**（M4） |
| R4 | 忘记「admin 隐含全权」⇒ admin 把自己锁在外面 | 裁决第 6 步：`is_first_admin` 短路；`auth can-i` 自检；提供 `--force` 救援 |
| R5 | 授权与 `public_read` 语义重叠导致困惑 | D9 落定后统一为「public 主体行」；文档明确「未认证 GET」vs「用户可读」是两层 |
| R6 | 复杂度膨胀（用户已就 config hub 反馈过） | N1–N7 明确排除；角色层延后；每期独立可验收 |
| R7 | **组授权撤销影响面放大**（组内全员立即失权） | 文档明示；`auth group list` 显示成员数；撤销前提示 |
| R8 | **疯狂鉴权锁死 auth.db**（Windows 锁更紧 + 杀软持锁） | M1 WAL（读写不互锁）+ M2 连接复用 + M5 限流；详见 §4.2 |

---

## 9. 需要讨论的问题（Q）

| # | 问题 | 选项 | 我的倾向 |
|---|---|---|---|
| **Q1** | 授权的**主体**只有 user 吗？要不要支持「组 / 团队」？ | (a) 只 user (b) user + group | ✅ **(b) 支持组** —— 按 K8s `subject.kind` 并入同一张 `wiki_grants`；新增 `groups` / `group_members` |
| **Q2** | wiki 的「属主」怎么定？创建 wiki 的人自动全权吗？ | (a) 是（PG owner 语义） (b) 否，只由 admin 授权 | ✅ **(b) 只 admin**（Q2 暂定；属主机制留后续升级） |
| **Q3** | `wikis=["*"]` 语义在授权表落地后怎么表达？ | (a) 通配 (b) 展开 | ✅ **(a)+(b)+(i)**：表允许 `*` 通配；快照签发时求值展开；`*` 覆盖新建 wiki（§4.3） |
| **Q4** | 非 admin 拿到授权后，**能不能建用户 / 授权别人**？ | (a) 不能（只有 admin）(b) 能 | ✅ **(a) 不能** —— `grant` 是 admin 专属 |
| **Q5** | share token（roadmap Phase 3）算不算一种 grant？ | (a) 独立表 `share_tokens` (b) 复用 `wiki_grants` | ✅ **(a) 独立表**（有过期/口令等独立语义） |
| **Q6** | 本地模式（回环）是否应绕过 grants？ | (a) 绕过（现状） (b) 也走 grants | ✅ **(a) 绕过** —— decision 12「localhost 完全信任」是既有决策 |

---

## 10. 决策日志

| # | 决策 | 结论 | 拍板人 | 日期 |
|---|---|---|---|---|
| D1 | 授权表形状 | ✅ 扁平 `principal×wiki×r/w`，**含组支持**（K8s subject.kind） | 用户 | 2026-11-13 |
| D2 | 授权存哪 | ✅ `auth.db` | 用户 | 2026-11-13 |
| D3 | 授权粒度 | ✅ **(a) wiki 级**（无 page_id） | 用户 | 2026-11-13 |
| D4 | 动作集合 | ✅ **(a) read/write** | 用户 | 2026-11-13 |
| D5 | deny 规则 | ✅ 无 deny，**删行即撤销** | 用户 | 2026-11-13 |
| D6 | 撤销后 token | ✅ **(a) 每请求查表，已发 token 立即失效**（下一个请求即 403） | 用户 | 2026-11-13 |
| D7 | token 载荷 | ✅ **快照 + 实时上界校验**（交集） | 用户 | 2026-11-13 |
| D8 | 非 admin 默认 | ✅ **(a) 默认无授权**（最小权限） | 用户 | 2026-11-13 |
| D9 | `public_read` 落点 | ✅ **(b) `public` 主体行**（组支持后更统一） | 用户 | 2026-11-13 |
| Q1 | 组支持 | ✅ **支持**（`groups` + `group_members`） | 用户 | 2026-11-13 |
| Q2 | wiki 属主 | ✅ **只 admin**；属主机制留后续升级 | 用户 | 2026-11-13 |
| Q3 | `["*"]` 语义 | ✅ **(a) 通配行 + (b) 快照求值展开 + (i) `*` 覆盖新建 wiki** | 用户 | 2026-11-13 |
| Q4 | 授权权下放 | ✅ **不能** —— `grant` admin 专属 | 用户 | 2026-11-13 |
| Q5 | share token 归属 | ✅ **(a) 独立表 `share_tokens`** | 用户 | 2026-11-13 |
| Q6 | 本地模式绕过 | ✅ **(a) 绕过**（decision 12） | 用户 | 2026-11-13 |

---

## 11. 关联文档

- `docs/designs/multiuser-auth-research.md` — 业界调研（PostgreSQL / NIST / K8s / Casbin / GitHub / SQLite / SpiceDB / Envoy 一手取证）
- `docs/summaries/2026-11-13-multiuser-auth-design-record.md` — 讨论与规划完整记录
- `docs/llmwikify-auth-缺陷清单.md` — 现状缺陷与修复批注（P0/P1 已清）
- `docs/designs/auth-and-sharing-roadmap.md` — 既有 Phase 3/4 规划（share token / hub）
- `docs/designs/refactor-4layer-architecture.md` — 4 层依赖规则（`foundation` 不得依赖 `apps`）

---

## 12. 实现记录

### 12.1 P1 · 授权表 + 仓库（2026-11-13 完成）

**新增** `src/llmwikify/foundation/auth/grants.py`：

| API | 作用 |
|---|---|
| `GrantRepository(db_path=None)` | 建表 + CRUD；WAL + 线程本地连接 |
| `grant(type, id, wiki_id, *, read, write, granted_by)` | upsert 一行（加法，无 deny） |
| `revoke(type, id, wiki_id)` | 删行（D5 / D6-a：下个请求即生效） |
| `effective(user_id, wiki_id) -> (r, w)` | 单 wiki 实时上界，求值 `*`（Q3-a/c） |
| `expand(user_id, wiki_ids) -> {wiki: (r,w)}` | 签发用：**快照永不含 `*`**（Q3-b） |
| `create_group / list_groups / add_member / remove_member / list_members / groups_of` | 组管理（Q1） |
| `list_grants(...)` | 审计查询 |
| `PRINCIPAL_TYPES` / `WILDCARD` | `{'user','group','public'}` / `'*'` |

**表结构**（与 §3.1 一致，含 CHECK 约束）：

```sql
wiki_grants(principal_type CHECK IN ('user','group','public'),
            principal_id, wiki_id, can_read, can_write, granted_by, created_at,
            PRIMARY KEY(principal_type, principal_id, wiki_id))
groups(id, name, created_at)
group_members(group_id, user_id, PRIMARY KEY(group_id, user_id))
```

**性能三措施落地**（§4.2）：

| # | 措施 | 实现 |
|---|---|---|
| **M1** | WAL | `foundation.db.get_connection()` 默认 `wal=True` |
| **M2** | 连接复用 | 三仓库共用**同一** thread-local `ManagedConnection`（测试断言 `u._connect() is a._connect() is g._connect()`） |
| **M3** | schema 一次 | `_schema_ready()` / `_schema_current()` 快路径，跳过 `executescript` |

**改动** `foundation/auth/db.py`：`UserRepository` / `ApiKeyRepository` 的 `_connect()` 改为返回
线程本地持久连接；`_atomic_write()` 委托 `ManagedConnection.transaction()`（不再每写新建+关闭连接）。

**测试** `tests/test_foundation_auth_grants.py`（23 条）：schema / WAL / 连接复用 / grant-revoke /
通配求值与展开 / 组成员与即时撤权 / public 主体 / 参数校验。

**验证**：全量 **5138 passed** · mypy 413 files 0 · 架构 0 violation · ruff 干净。

### 12.2 P2 · 用户生命周期（2026-11-13，doc-first）

**范围**（对应 §5.3 与 D8 / Q2 / Q4）：

| 项 | 内容 |
|---|---|
| **schema** | `users` 增列 `disabled_at TEXT`（NULL=有效；非 NULL=禁用）；已有库走幂等 `ALTER TABLE ADD COLUMN` |
| **`User` dataclass** | 增 `disabled_at` 字段 |
| **`create-user`** | 建**非 admin** 用户（admin 已由 `registration_closed` 锁定，Q2：属主机制后续升级）；`username` 自动派生去重（P1-5 同规则）；**admin 专属**（Q4） |
| **`list-users`** | 列 id / email / username / is_first_admin / disabled_at / 授权摘要；**admin 专属** |
| **`disable-user`** | 置 `disabled_at=now()`（软删，**不删行**，审计留痕）；**admin 专属**（Q4） |
| **`enable-user`** | 置 `disabled_at=NULL` —— **P2 附带**（超出原设计清单，为避免单向门） |

**身份校验（Q4 = admin 专属）**：

```
create-user / list-users / disable-user / enable-user
  → 从 local_token 解出当前用户
  → 不是 admin / 解不出 / 无 token → 拒绝（fail-closed）
```

**刻意不做**（本期）：

| 不做 | 归属 |
|---|---|
| 裁决时查 `disabled_at`（让已发 token 立即失效） | **P4**（D6-a 的第 4 步） |
| 删除用户（硬删） | 非目标；软删即可 |
| 授权摘要的完整矩阵展示 | P5 WebUI |

**验收**：

- ✅ `auth create-user --email a@x` → 建非 admin，username 自动派生
- ✅ 重复 email → `email_taken`
- ✅ 非 admin 跑 `create-user` → 拒绝
- ✅ `auth disable-user a@x` → `disabled_at` 非空；再次禁用幂等
- ✅ `auth enable-user a@x` → `disabled_at` 归 NULL
- ✅ `auth list-users` → 表格含 disabled 标记
- ✅ 全量测试 + mypy + 架构门禁 0

**实现记录（2026-11-13）**：

| 文件 | 改动 |
|---|---|
| `foundation/auth/db.py` | `users` 增 `disabled_at` 列（CREATE + 幂等 ALTER `_ensure_users_columns`）；`User.disabled_at`；`list_users` / `disable` / `enable` / `is_disabled`；`create()` 为**所有**用户派生 username |
| `interfaces/cli/commands/auth.py` | `create-user` / `list-users` / `disable-user` / `enable-user`；`_require_admin()` fail-closed 校验（Q4）；disable admin 拒绝（防锁死） |
| 测试 | `TestUserLifecycleP2`（5 条，含 pre-P2 迁移）+ `TestUserLifecycleCLIP2`（8 条） |

**验证**：全量 **5151 passed** · mypy 413 files 0 · 架构 0 violation · ruff 干净。

### 12.3 P3 · 签发装 grants + 授权 CLI（2026-11-13，doc-first）

**范围**（对应 §5.1 签发 + §5.6 管理面）：

| 项 | 内容 |
|---|---|
| **`TokenClaims.wgrants`** | 新增 `dict[str, str]`（`wiki_id → "r" \| "rw"`），默认 `{}`；`from_dict` 对旧 token 容错 |
| **admin 签发** | `wikis=["*"]`、`wgrants={}`、`scope=write` —— **行为不变**（G5；裁决第 5 步短路，registry/search 过滤用 `*` 才能看见未来 wiki） |
| **非 admin 签发** | `GrantRepository.expand(user_id, known_wikis)` 求值展开（Q3-b）：`wikis=[具体列表]`、`wgrants={wiki:"r"\|"rw"}` |
| **`scope` 规则澄清** | **scope = 快照里是否含任一 `rw`**（有则 `write`，否则 `read`）。旧「非 admin 恒 read-only」是 D8（无授权）下的**现状**，不是规则；D4 允许 per-wiki write 后，有写授权的非 admin 必须拿到 `scope=write`，否则中间件第 4 步会误杀 |
| **`known_wikis` 来源** | CLI → `WikiRegistry(config).list_wikis()`；HTTP `/verify` → `request.app.state.wiki_registry` |
| **`auth grant`** | `--user U --wiki W [--write]`（缺省 read；write蕴含 read）；admin 专属（Q4）；`wiki_id` 可为 `'*'`（Q3-a） |
| **`auth revoke`** | `--user U --wiki W`；删行即撤（D5/D6） |
| **`auth can-i`** | `--user U --wiki W [--write]` → `yes`/`no`（K8s `kubectl auth can-i`） |

**刻意不做**（本期）：

| 不做 | 归属 |
|---|---|
| 中间件按 `wgrants` 做 per-wiki 读写裁决 | **P4** |
| `auth group …` 与 `grant --group` | **P3b** |
| 改 `_check_wikis_claim` / registry / search 过滤逻辑 | **P4**（P3 只改 claims 内容，现有过滤自动受益） |

**P3 单独上线时的裁决效果**（诚实记录）：

| 场景 | P3 后 | P4 补齐 |
|---|---|---|
| 非 admin 读 wiki-a | ✅ `wikis=["wiki-a"]` 放行 | — |
| 非 admin 访问 wiki-b（未授权） | ✅ `wikis` 不含 → 403 | — |
| 非 admin 在 wiki-a 可写、wiki-b 只读 | ⚠️ `scope=write` + `wikis` 含两者 ⇒ **POST wiki-b 仍会过**（旧全局 scope 检查） | P4 按 `wgrants[wiki-b]="r"` 拒 |
| admin | ✅ 完全不变 | — |

⇒ **P3 是增量改善**（wiki 维度收窄已生效）；**per-wiki 读写精确裁决在 P4**。

**验收**：

- ✅ admin 签出的 token 与 P3 前**同形**（`wikis=["*"]`、`wgrants={}`、`scope=write`）
- ✅ 非 admin 有 read 授权 → token `wikis` 含该 wiki、`wgrants[wiki]="r"`、`scope=read`
- ✅ 非 admin 有 write 授权 → `scope=write`、`wgrants[wiki]="rw"`
- ✅ 非 admin 零授权 → `wikis=[]`
- ✅ `auth grant/revoke/can-i` 可用；非 admin 跑 → 拒绝
- ✅ `auth grant --wiki '*'` 写入通配行；`can-i` 对新 wiki 返回 yes（Q3-c）
- ✅ 全量测试 + mypy + 架构门禁 0

**实现记录（2026-11-13）**：

| 文件 | 改动 |
|---|---|
| `foundation/auth/_jwt.py` | `TokenClaims.wgrants: dict[str,str]`（`field(default_factory=dict)`）；`new(..., wgrants=)`；`from_dict` 对旧 token 容错 |
| `foundation/auth/grants.py` | 新增 `snapshot_for_user(user_id, known_wikis, *, is_admin)` → `(wikis, wgrants, scope)` |
| `foundation/auth/prompt.py` | 签发改走 `snapshot_for_user`（admin → `["*"]` 不变） |
| `interfaces/cli/commands/auth.py` | `_sign_local_token(..., known_wikis)`；`_known_wiki_ids()`；`grant` / `revoke` / `can-i`（admin 专属） |
| `interfaces/server/http/auth_routes.py` | `_build_user_claims()` + `_known_wiki_ids()`；`/register`、`/verify` 走快照；PAT scopes 作**上限**（与计算值取更紧者） |
| 测试 | `TestSnapshotForUserP3`（4 条）+ `TestGrantCLIP3`（6 条）+ 更新 `TestSignLocalTokenGrant` |

**验证**：全量 **5162 passed** · mypy 413 files 0 · 架构 0 violation · ruff 干净。

### 12.4 P3b · 组管理 CLI（2026-11-13，doc-first）

**范围**（对应 §5.6 + Q1 组支持 + Q4 admin 专属）：

| 命令 | 语义 |
|---|---|
| `auth group create <name>` | 建组；重名 → `group_exists` |
| `auth group list` | 列组：id / name / 成员数 |
| `auth group add <group> --user U` | 加成员（幂等）；`<group>` 按 name 或 id 解析 |
| `auth group remove <group> --user U` | 移成员 |
| `auth grant --group G --wiki W [--write]` | 给**组**授权；**与 `--user` 互斥**（一条 grant 只授一个主体） |
| `auth revoke --group G --wiki W` | 撤组授权 |
| `auth can-i --user U …` | 已有；组授权经 `group_members` 自动生效（P1 的 `effective()` 已支持） |

**约束**：

| 规则 | 说明 |
|---|---|
| **admin 专属** | 全部命令（Q4）；沿用 `_require_admin()` |
| **`--user` 与 `--user`/`--group` 互斥** | `grant`/`revoke` 必须二选一，都给或都不给 → 报错 |
| **组解析** | `<group>` 接受 group name 或 group id |
| **撤销影响面** | 撤组授权 ⇒ 组内全员立即失权（R7）；输出提示成员数 |

**刻意不做**（本期）：

| 不做 | 归属 |
|---|---|
| `auth group rename` / `delete` | 未在设计清单；需要时再加 |
| WebUI 组管理页 | P5 |
| 按组签发 claims 的特殊逻辑 | **无需** —— `snapshot_for_user` → `expand()` 已走 `group_members` 三路并集（P1） |

**验收**：

- `auth group create team` → 成功；重复 → `group_exists`
- ✅ `auth group add team --user bob@e` → 幂等；`group list` 成员数 1
- ✅ `auth grant --group team --wiki wiki-a --write` → 组内成员 `can-i --write` = yes
- ✅ `auth revoke --group team --wiki wiki-a` → 成员立即 no
- ✅ `grant --user X --group G` 同时给 → 报错
- ✅ 非 admin → 拒绝
- ✅ 全量测试 + mypy + 架构门禁 0

**实现记录（2026-11-13）**：

| 文件 | 改动 |
|---|---|
| `interfaces/cli/commands/auth.py` | `group create/list/add/remove`（`_dispatch_group`）；`_resolve_group`（name 或 id）；`grant`/`revoke` 支持 `--group`，与 `--user` **互斥**；`_subject_label` 输出 email/组名；组授权撤销提示影响成员数（R7） |
| 测试 | `TestGroupCLIP3b`（5 条）：建组/幂等加成员/组授权→成员 can-i/互斥校验/admin 专属 |

**验证**：全量 **5167 passed** · mypy 413 files 0 · 架构 0 violation · ruff 干净。

### 12.5 P4a · 裁决接入（2026-11-13，doc-first）

**规格定稿**（评审中拍板，覆盖 §5.2 原文）：

| 步 | 条件 | 结果 | 归属 |
|---|---|---|---|
| ① | `local_mode`（回环） | pass | 不变 |
| ② | **无 token** | **401（一律）**；`public_read` 废弃 | **P4b**（本期不动，见下） |
| ③ | 验签失败 | 401 | 不变 |
| ④ | `disabled_at` 非空 | 401 | **P4a** |
| ⑤ | `is_first_admin` | pass（PG owner） | **P4a** |
| ⑥' | **旧 token** | 跳过 ⑥⑦，`wikis`+`scope` 原样放行 | **P4a** |
| ⑥ | 查 `wiki_grants` 实时上界 | 无行→403；失败→**fail-closed 403** | **P4a** |
| ⑦ | 快照 ∩ 实时 | 无→403 | **P4a** |
| 列表路由 | snapshot ∩ live | — | **P4b** |

**旧 token 判定**（无 `legacy` 字段，纯值规则）：

| 解码后 | 判定 | 行为 |
|---|---|---|
| `wgrants` 非空 | 新 token（P3+） | ⑥⑦ 精确裁决 |
| `wgrants` 空 **且** `wikis` 非空 | **旧 token**（P3 前恒 `wikis=["*"]`） | 跳过 ⑥⑦；`wikis` 含该 wiki 或 `*` → 放行；`scope` 照旧 |
| `wgrants` 空 **且** `wikis == []` | 新 token 零授权（D8） | 走 ⑥，无行 → 403 |

> 「全部权限」= **wiki 维度全开**；`scope` 不提权（旧非 admin 仍 read-only）。
> 该规则同时兼容既有测试里的 `TokenClaims.new(wikis=[...])` 造的 fake token（`wgrants={}`）。

**实现要点**：

| 项 | 内容 |
|---|---|
| **纯函数** | 新增 `foundation/auth/authorize.py`：`authorize_request(claims, *, wiki_id, need_write, db_path)` → `AuthzDecision(allowed, status, code, detail)`；**可单测穷举** |
| **middleware** | `dispatch` 用 `authorize_request` 替换「scope 检查 + `_check_wikis_claim`」；抽出 `_wiki_id_from_path`；**② 无 token 分支本期保持不动**（P4b 改） |
| **PAT 路径修补** | `_verify_token` 的 PAT 分支现签 `wikis=["*"], wgrants={}` ⇒ 会被误判为旧 token → **非 admin PAT 拿到全 wiki**。改为经 `snapshot_for_user` 装快照（需把 `known_wikis` 传入） |
| **user 缺失** | P4a **不**新增「用户不存在 → 401」（避免破坏 `user:fake` 既有测试；`disabled` 只在用户存在时生效）。删除用户后旧 token 仍可能用 —— 记为已知缺口，P4b 或后续处理 |
| **fail-closed** | grants 查询异常 → 403 `authz_unavailable`，不放行（M4） |
| **门禁** | `tools/exploit_check_wikis_claim.py` + `tools/auth_defect_verify.py` 必须保持「已修」状态 |

**P4a 刻意不做**（→ P4b）：

| 不做 | 归属 |
|---|---|
| ② 无 token → 401（`public_read` 废弃） | P4b |
| 列表路由 snapshot ∩ live | P4b |
| 用户不存在 → 401 | P4b（与 fake-token 测试改造一起） |
| D9 `public` 行 | 已定不做 |

**验收**：

- ✅ `authorize_request` 单测覆盖：disabled / scope / admin / legacy 三分支 / live / snapshot / fail-closed（20 条）
- ✅ 既有 middleware 测试（`user:fake` + `wikis=[...]`）**全部保持通过**（走 legacy 分支）
- ✅ 新增：真实 user + grant → 放行；revoke → 下一请求 403；disabled → 401
- ✅ 非 admin PAT 不再全 wiki（`_verify_token` PAT 分支经 `snapshot_for_user`）
- ✅ `public_read` 相关测试**不动**（P4b 才改）
- ✅ 门禁：`exploit_check_wikis_claim.py` **4/4 blocked**；`auth_defect_verify.py` **4/4 NOT reproduced**
- ✅ 全量 **5187 passed** · mypy 414 files 0 · 架构 0 violation · ruff 干净

**实现记录（2026-11-13）**：

| 文件 | 改动 |
|---|---|
| **新增** `foundation/auth/authorize.py` | `AuthzDecision` + `authorize_request()`：disabled → scope → admin → non-wiki → legacy → live（fail-closed）→ snapshot |
| `foundation/auth/__init__.py` | 导出 `AuthzDecision` / `authorize_request` |
| `interfaces/server/http/middleware.py` | `dispatch` 改调 `authorize_request`；抽出 `_wiki_id_from_path`；**PAT 分支经 `snapshot_for_user` 装快照**（修「非 admin PAT 全 wiki」漏洞）；`_known_wiki_ids(request)` |
| **新增** `tests/test_foundation_auth_authorize.py` | 20 条穷举单测 |
| `tests/test_interfaces_auth.py` | share-token 测试接受中间件层 `invalid_subject`（路由层 `share_token_not_here` 保留为纵深） |

**已知缺口（→ P4b）**：用户被删除后其旧 token 仍可能通过（P4a 不查 user 存在性，避免破坏 `user:fake` 测试）。

### 12.6 P4b · 裁决收尾（2026-11-14，doc-first）

**范围**（P4 的「刻意不做」项 + 规格里已拍板的 ②/列表路由）：

| 项 | 内容 |
|---|---|
| **② 无 token → 401** | `dispatch` 删掉 `public_read` 放行分支；无 token **一律 401**（回环 ① 仍最先短路）。`public_read` 参数**保留但忽略**（构造兼容；`serve.py` 的 `LLMWIKIFY_PUBLIC_READ` 仍在传，行为上已无效） |
| **用户存在检查** | `authorize_request`：`user is None` → **401 `user_not_found`**（补 P4a 缺口）；置于 **scope 之后**（scope 是纯检查，先跑可保留 `forbidden_scope` 语义） |
| **列表路由 snapshot ∩ live** | 新增 `accessible_wikis(claims, known_wikis, db_path)` → 可读 wiki 集合；`registry_routes` / `search_routes` 改用它，替代裸 `claims.wikis` 过滤 |
| **`accessible_wikis` 规则** | 与 `authorize_request` 对齐：admin → 全部 known；legacy → `wikis`（`*`=known）；新 token → `wgrants` 可读键 ∩ live `expand()` |
| **exploit 终验** | 两个脚本保持「已修」状态 |

**`accessible_wikis` 语义**（列表可见 = 能读）：

| token 类型 | 结果 |
|---|---|
| admin | `set(known_wikis)` |
| legacy（`wgrants` 空 + `wikis` 非空） | `wikis`（`*` → known）∩ known |
| 新 token | `{w ∈ wgrants 可读} ∩ known` ∩ live `expand()` |
| 用户缺失 / share | `set()` |

**测试改造**：

| 测试 | 改法 |
|---|---|
| `TestMiddlewareScope._make_token` | `user:fake` → **真实 user**（`_ensure_user()`）；token 仍走 legacy 分支（`wikis` 非空 + `wgrants={}`），断言不变 |
| `test_public_read_allows_get_without_token` | 期望改为 **401** |
| `test_api_routes.py` / `test_wiki_server.py` 中依赖 `public_read` 匿名 GET 的用例 | 改期望 401，或改用 local_mode / 带 token |

**验收**：

- ✅ 无 token（非回环）→ **一律 401**（GET/POST/列表均是）
- ✅ 回环 `local_mode` → 仍全放行
- ✅ 真实 user + legacy token → 行为与 P4a 一致
- ✅ 用户被删 → 其 token → 401 `user_not_found`
- ✅ `/api/wikis`、`/api/search/cross` 可见集 = snapshot ∩ live
- ✅ 门禁两脚本保持「已修」（exploit 4/4 blocked；defect 4/4 NOT reproduced）
- ✅ 全量 **5187 passed** · mypy 414 files 0 · 架构 0 violation · ruff 干净

**实现记录（2026-11-14）**：

| 文件 | 改动 |
|---|---|
| `foundation/auth/authorize.py` | 用户缺失 → 401 `user_not_found`（scope 之后）；新增 `accessible_wikis(claims, known_wikis)` |
| `interfaces/server/http/middleware.py` | 无 token → 401 一律；`public_read` 保留但**忽略**；删 `_deny_no_token` |
| `wiki/registry_routes.py` | `/api/wikis` 可见集改 `accessible_wikis` |
| `wiki/search_routes.py` | `_filter_by_claim` 改 `accessible_wikis`（传入 known_wikis） |
| 测试 | `TestMiddlewareScope._make_token` → 真实 user；`test_no_token_returns_401_p4b`；`test_api_routes`/`test_wiki_server` 依赖匿名 GET 的用例改 401 或 local_mode；authorize 测试改用真实 user |

**P4 至此收口**（P4a + P4b）：per-wiki 读写精确裁决 + 无 token 拒绝 + 列表一致 + 用户生命周期联动。

### 12.7 P5 · WebUI 授权管理（2026-11-14，doc-first）

**范围**（对应 §5.6 管理面的 HTTP/UI 侧；CLI 已在 P3/P3b 覆盖）：

| 项 | 内容 |
|---|---|
| **`GET /api/auth/me` 增强** | 返回**权限矩阵**：`accessible_wikis`（live 可读集，`accessible_wikis()`）+ `wgrants`（快照）+ 既有 `wikis`/`can_edit` |
| **Grants API（admin）** | `GET /api/auth/grants` 列表 · `POST /api/auth/grants` upsert · `DELETE /api/auth/grants` 删行（body: `principal_type/principal_id/wiki_id`） |
| **下拉数据（admin）** | `GET /api/auth/users` · `GET /api/auth/groups`（管理页选主体用） |
| **admin 校验** | 新增 `_require_admin(request)`：claims → user → `is_first_admin`，否则 403 `admin_required`（与 CLI `_require_admin` 对齐，Q4） |
| **WebUI 页面** | `/agent/access`（挂在 agent 导航）：① 自己的权限矩阵（任何登录用户）② grants 表 + grant/revoke 表单（仅 admin，非 admin 隐藏） |

**刻意不做**（本期）：

| 不做 | 理由 |
|---|---|
| 用户创建/禁用的 UI | CLI 已有（P2）；UI 建号涉及注册流，另议 |
| 组成员管理 UI | CLI 已有（P3b）；本期 UI 只读展示组 |
| 分页 / 搜索 grants | 当前规模（<50 人）全量列表足够 |
| i18n | WebUI 现状英文为主，跟随 |

**验收**：

- `/me` 返回 `accessible_wikis` + `wgrants`；非 admin 的 `/me` 矩阵与 `can-i` 一致
- admin 调 grants API → 200；非 admin → 403 `admin_required`
- grant → POST 后 GET 列表含该行；DELETE 后消失
- WebUI：登录后 `/agent/access` 可见矩阵；admin 可 grant/revoke；非 admin 只读
- 全量测试 + mypy + 架构门禁 0 + WebUI `tsc && vite build`
