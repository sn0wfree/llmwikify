# 多用户与授权模型 — 设计方案（待评审）

> 日期: 2026-11-13
> 状态：**评审中** —— **D1 / D2 / D5 / D6 / D7 + Q1（组支持）已拍板**；
> D3 / D4 / D8 / D9 与 Q2–Q6 待定
> 依据：`docs/designs/multiuser-auth-research.md`（业界调研，含 PostgreSQL / NIST / Kubernetes / Casbin / GitHub 一手取证）
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
| public_read | 全局开关 | `principal_type='public'` 行（D9 待定） |
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
    wiki_id        TEXT NOT NULL,      -- = namespace / domain
    can_read       INTEGER NOT NULL DEFAULT 0,
    can_write      INTEGER NOT NULL DEFAULT 0,
    granted_by     TEXT,               -- 审计（PG R5）
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (principal_type, principal_id, wiki_id)
);

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
| **D3** | 授权粒度 | (a) 只到 wiki (b) 到 page | ⬜ 待定 | page 级授权 = 每次读页都查表；N7 已排除 → 倾向 (a) |
| **D4** | 动作集合 | (a) read/write (b) read/write/admin | ⬜ 待定 | admin 是**身份**不是**动作** → 倾向 (a) |
| **D5** | deny 规则 | (a) 无 (b) 有 | ✅ **(a) 删行即撤销** | PG/K8s 均无；撤销=删行，语义无歧义 |
| **D6** | 撤销后已发 token | (a) 每请求查表（实时） (b) 纯快照 (c) 短 TTL + refresh | ✅ **(a) 每请求查表，已发 token 立即失效** | 见 §4.1 |
| **D7** | token 载荷 | (a) 快照 (b) 每请求查表 (c) 两者都做 | ✅ **(c) 快照 + 实时上界校验** | 快照=token 上限，实时=撤权/禁用户立即生效 |
| **D8** | 非 admin 的默认 | (a) 默认无授权 (b) 默认全 wiki 只读 | ⬜ 待定 | 最小权限（K8s 警告）→ 倾向 (a) |
| **D9** | `public_read` 落点 | (a) 保留全局开关 (b) `public` 主体行 | ⬜ 待定 | 组支持后 (b) 更统一 → 倾向 (b) |

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
| `wikis` 保留 | 现有 `_check_wikis_claim` / registry / search 三处过滤**不用改** |
| `scope` 保留 | 全局上限，非 admin 仍 read-only（现状） |

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
| **`public_read`** | 保持全局开关（D9-a）；非 admin 默认无授权（D8），与 public_read 叠加后：未认证 GET 仍公开 |

---

## 7. 分期实施（每期独立可验收）

| 期 | 内容 | 风险 | 依赖 |
|---|---|---|---|
| **P1** | `wiki_grants` + `groups` + `group_members` 表 + `GrantRepository`（建表/读写/查）+ 迁移探测 | **低**（纯新增） | — |
| **P2** | `users.disabled_at` + `auth create-user/list-users/disable-user` | 低 | — |
| **P3** | 签发装 `wgrants`（claims）+ `auth grant/revoke/can-i` CLI | 中（改签发） | P1 P2 |
| **P3b** | 组管理 CLI（`auth group create/list/add/remove` + `grant --group`） | 低 | P1 P3 |
| **P4** | 裁决接入（实时上界 + 快照比对 + disabled 检查 + fail-closed） | **中高**（动中间件） | P3（**D6 已定为 A**） |
| **P5** | WebUI：授权管理页 + `/me` 返回权限矩阵 | 中 | P3 |
| **P6** | share token 与 grants 的关系（roadmap Phase 3） | — | 待定（Q5） |

**建议顺序强调**：P1–P3 是**纯增量**（不动裁决路径），可先落地再评审 P4 的裁决策略。

---

## 8. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 裁决路径改动引入回归（P0-1/P0-2 刚修好） | P4 单独评审；保留 `wikis` 旧路径做双跑对比；`tools/exploit_check_wikis_claim.py` 作回归门禁 |
| R2 | 每次请求多一次 SQLite 查询 | 主键索引；如需缓存用 `auth.db` mtime 作版本号（撤权即写 DB ⇒ 跨进程也失效） |
| R3 | D6「立即失效」与 JWT 无状态冲突 | 已定义为「快照 ∩ 实时上界」；**查表失败 fail-closed** |
| R4 | 忘记「admin 隐含全权」⇒ admin 把自己锁在外面 | 裁决第 6 步：`is_first_admin` 短路；`auth can-i` 自检；提供 `--force` 救援 |
| R5 | 授权与 `public_read` 语义重叠导致困惑 | D9 落定后统一为「public 主体行」；文档明确「未认证 GET」vs「用户可读」是两层 |
| R6 | 复杂度膨胀（用户已就 config hub 反馈过） | N1–N7 明确排除；角色层延后；每期独立可验收 |
| R7 | **组授权撤销影响面放大**（组内全员立即失权） | 文档明示；`auth group list` 显示成员数；撤销前提示 |

---

## 9. 需要讨论的问题（Q）

| # | 问题 | 选项 | 我的倾向 |
|---|---|---|---|
| **Q1** | 授权的**主体**只有 user 吗？要不要支持「组 / 团队」？ | (a) 只 user (b) user + group | ✅ **(b) 支持组** —— 按 K8s `subject.kind` 并入同一张 `wiki_grants`；新增 `groups` / `group_members` |
| **Q2** | wiki 的「属主」怎么定？创建 wiki 的人自动全权吗？ | (a) 是（PG owner 语义） (b) 否，只由 admin 授权 | **(a)**，但当前无 wiki 属主记录 ⇒ 退化为「只有 admin 隐含全权」 |
| **Q3** | `wikis=["*"]` 语义在授权表落地后怎么表达？ | (a) 保留为「通配」 (b) 展开成 N 行 | **(a)** 保留通配；展开会让 wiki 增删时授权行失配 |
| **Q4** | 非 admin 拿到授权后，**能不能建用户 / 授权别人**？ | (a) 不能（只有 admin）(b) 能 | **(a)**；`grant` 是 admin 专属 |
| **Q5** | share token（roadmap Phase 3）算不算一种 grant？ | (a) 独立表 `share_tokens` (b) 复用 `wiki_grants` | **(b) 倾向**：share = 「对某 wiki 的 read grant + 匿名主体」；但 share 有过期/口令等独立语义 ⇒ **(a) 更干净** |
| **Q6** | 本地模式（回环）是否应绕过 grants？ | (a) 绕过（现状） (b) 也走 grants | **(a)** 保留 —— decision 12「localhost 完全信任」是既有决策；改动会破坏本地开发体验 |

---

## 10. 决策日志

| # | 决策 | 结论 | 拍板人 | 日期 |
|---|---|---|---|---|
| D1 | 授权表形状 | ✅ 扁平 `principal×wiki×r/w`，**含组支持**（K8s subject.kind） | 用户 | 2026-11-13 |
| D2 | 授权存哪 | ✅ `auth.db` | 用户 | 2026-11-13 |
| D3 | 授权粒度 | ⬜ 待定（倾向 wiki 级） | | |
| D4 | 动作集合 | ⬜ 待定（倾向 read/write） | | |
| D5 | deny 规则 | ✅ 无 deny，**删行即撤销** | 用户 | 2026-11-13 |
| D6 | 撤销后 token | ✅ **(a) 每请求查表，已发 token 立即失效**（下一个请求即 403） | 用户 | 2026-11-13 |
| D7 | token 载荷 | ✅ **快照 + 实时上界校验**（交集） | 用户 | 2026-11-13 |
| D8 | 非 admin 默认 | ⬜ 待定（倾向默认无授权） | | |
| D9 | `public_read` 落点 | ⬜ 待定（组支持后倾向 `public` 主体行） | | |
| Q1 | 组支持 | ✅ **支持**（`groups` + `group_members`） | 用户 | 2026-11-13 |
| Q2 | wiki 属主 | ⬜ 待讨论 | | |
| Q3 | `["*"]` 语义 | ⬜ 待讨论（倾向保留通配） | | |
| Q4 | 授权权下放 | ⬜ 待讨论（倾向 admin 专属） | | |
| Q5 | share token 归属 | ⬜ 待讨论 | | |
| Q6 | 本地模式绕过 | ⬜ 待讨论（倾向绕过） | | |

---

## 11. 关联文档

- `docs/designs/multiuser-auth-research.md` — 业界调研（PostgreSQL / NIST / K8s / Casbin / GitHub 一手取证）
- `docs/llmwikify-auth-缺陷清单.md` — 现状缺陷与修复批注（P0/P1 已清）
- `docs/designs/auth-and-sharing-roadmap.md` — 既有 Phase 3/4 规划（share token / hub）
- `docs/designs/refactor-4layer-architecture.md` — 4 层依赖规则（`foundation` 不得依赖 `apps`）
