# 多用户与授权模型 — 设计方案（待评审）

> 日期: 2026-11-13
> 状态：**草案，待评审** —— 文中的 **D1–D9** 是待拍板的决策点，**Q1–Q6** 是需要讨论的问题
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

---

## 3. 目标模型

### 3.1 形状（借 PG 的 `GRANT`，调研 C1/C3/C5）

```
wiki_grants(
    user_id   TEXT NOT NULL REFERENCES users(id),
    wiki_id   TEXT NOT NULL,          -- = namespace / domain
    can_read  INTEGER NOT NULL DEFAULT 0,
    can_write INTEGER NOT NULL DEFAULT 0,
    granted_by TEXT,                  -- 审计（R5）
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, wiki_id)
)
```

**三条语义规则**（直接来自 PG）：

| 规则 | 来源 | 我们的落地 |
|---|---|---|
| **纯加法**：多行并集，无 deny | PG R2 / K8s K1 | 撤销 = `DELETE` 行 |
| **owner 隐含全权** | PG R1 | `is_first_admin=1` 的用户**不需要** grant 行；wiki 的属主（创建者）同理 |
| **PUBLIC 伪角色** | PG R3 | 「所有人默认可读」= 一条 `user_id='*'` 的 grant（等价今天的 `public_read`） |

### 3.2 身份与权限的分离

| 层 | 存什么 | 变不变 |
|---|---|---|
| **身份**（who） | `users` | 很少变 |
| **能力**（what can do） | `wiki_grants` | 经常变 |
| **凭证**（how prove） | `api_keys` / JWT | 每 token 一份 |
| **快照**（token 上的副本） | `claims.wikis` | 签发时冻结 |

### 3.3 token 与授权的关系（GitHub 铁律 C4）

```
最终权限 = token 上签的 grants  ∩  用户当前 grants
```

> **上限实时查，快照只是缓存** —— 这正是 GitHub「失去 repo 访问权 ⇒ token 立即失效」的做法（S5）。

---

## 4. 决策点（待拍板）

| # | 决策 | 选项 | 建议 | 理由 |
|---|---|---|---|---|
| **D1** | 授权表形状 | (a) 扁平 `user×wiki×r/w` (b) 角色表 + grant (c) 通用引擎 | **(a)** | 调研 C6；规模 <50 人；少 2 张表 |
| **D2** | 授权存哪 | (a) `auth.db` (b) wiki 自己的 DB | **(a)** | 授权是**全局**事实；与 wiki 生命周期解耦；`auth.db` 已是权限事实源 |
| **D3** | 授权粒度 | (a) 只到 wiki (b) 到 page | **(a)** | page 级授权 = 每次读页都查表；N7 已排除 |
| **D4** | 动作集合 | (a) read/write (b) read/write/admin | **(a)** | admin 是**身份**不是**动作**；`is_first_admin` 已表达 |
| **D5** | deny 规则 | (a) 无 (b) 有 | **(a)** | PG/K8s 均无；撤销=删行，语义无歧义 |
| **D6** | 撤销后已发 token | (a) 立即失效 (b) 需重签 | **(a)** | GitHub 铁律 C4；否则撤权形同虚设 |
| **D7** | token 载荷 | (a) grants 快照进 JWT (b) 每请求查表 (c) 两者都做 | **(a) + (b) 兜底校验** | 中间件零 IO；但 D6 要立即失效 ⇒ 需要 (b) 查一次上界 |
| **D8** | 非 admin 的默认 | (a) 默认无授权 (b) 默认全 wiki 只读 | **(a)** | 最小权限（K8s 警告）；今天默认 `["*"]` 正是反例 |
| **D9** | `public_read` 落点 | (a) 保留为全局开关 (b) 变成 PUBLIC grant 行 | **先 (a)，预留 (b)** | (b) 更统一但改动面大；PUBLIC 行需特殊主体语义 |

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
2. 无 token → public_read ? GET 放行 : 401/403
3. 验签（JWT / PAT）失败 → 401
4. 全局 scope 检查（非 GET 需 write）→ 403
5. 取 wiki_id（路径 / registry / search 三类路由）
6. 查 wiki_grants（实时，上界）→ 无行 → 403
7. 快照比对（claims.wgrants）：快照没有该 wiki → 403（D6：撤权立即生效）
8. 放行
```

> **第 6 步是「实时上界」，第 7 步是「快照」** —— 两者取交集即 D6 语义。
> 第 6 步的查询**必须带索引**（`(user_id, wiki_id)` 主键已够）。

### 5.3 用户生命周期

| 命令 | 语义 | 约束 |
|---|---|---|
| `auth create-user --email X` | 建非 admin 用户 | 只有 admin 能跑；`username` 自动派生去重（P1-5 已修） |
| `auth list-users` | 列用户 + 其授权摘要 | 只读 |
| `auth disable-user <id>` | 禁用（软删） | 其 token 立即失效（D6）；**不删行**（审计留痕） |
| `auth grant --user U --wiki W [--read/--write]` | 加授权 | 幂等（upsert） |
| `auth revoke --user U --wiki W` | 撤授权 | 删行；对应 token 立即失效 |
| `auth can-i --user U --wiki W --write` | 自检（K8s K5） | 只读，返回 yes/no |

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
| **P1** | `wiki_grants` 表 + `GrantRepository`（建表/读写/查）+ 迁移探测 | **低**（纯新增） | — |
| **P2** | `users.disabled_at` + `auth create-user/list-users/disable-user` | 低 | — |
| **P3** | 签发装 `wgrants`（claims）+ `auth grant/revoke/can-i` CLI | 中（改签发） | P1 P2 |
| **P4** | 裁决接入（实时上界 + 快照比对 + disabled 检查） | **中高**（动中间件） | P3 |
| **P5** | WebUI：授权管理页 + `/me` 返回权限矩阵 | 中 | P3 |
| **P6** | share token 与 grants 的关系（roadmap Phase 3） | — | 待定 |

**建议顺序强调**：P1–P3 是**纯增量**（不动裁决路径），可先落地再评审 P4 的裁决策略。

---

## 8. 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 裁决路径改动引入回归（P0-1/P0-2 刚修好） | P4 单独评审；保留 `wikis` 旧路径做双跑对比；`tools/exploit_check_wikis_claim.py` 作回归门禁 |
| R2 | 每次请求多一次 SQLite 查询 | 主键索引；可加进程内 LRU 缓存（失效靠 `auth grant` 时清） |
| R3 | D6「立即失效」与 JWT 无状态冲突 | 已在 5.2 定义为「快照 ∩ 实时上界」；文档明说 |
| R4 | 忘记「admin 隐含全权」⇒ admin 把自己锁在外面 | 裁决第 6 步：`is_first_admin` 短路；`auth can-i` 自检；提供 `--force` 救援 |
| R5 | 授权与 `public_read` 语义重叠导致困惑 | D9 先保留开关；文档明确「未认证 GET」vs「用户可读」是两层 |
| R6 | 复杂度膨胀（用户已就 config hub 反馈过） | N1–N7 明确排除；角色层延后；每期独立可验收 |

---

## 9. 需要讨论的问题（Q）

| # | 问题 | 选项 | 我的倾向 |
|---|---|---|---|
| **Q1** | 授权的**主体**只有 user 吗？要不要支持「组 / 团队」？ | (a) 只 user (b) user + group（多一张表 + 解析链） | **(a)** 先；组的需求等真有人提 |
| **Q2** | wiki 的「属主」怎么定？创建 wiki 的人自动全权吗？ | (a) 是（PG owner 语义） (b) 否，只由 admin 授权 | **(a)**，但当前无 wiki 属主记录 ⇒ 退化为「只有 admin 隐含全权」 |
| **Q3** | `wikis=["*"]` 语义在授权表落地后怎么表达？ | (a) 保留为「通配」 (b) 展开成 N 行 | **(a)** 保留通配；展开会让 wiki 增删时授权行失配 |
| **Q4** | 非 admin 拿到授权后，**能不能建用户 / 授权别人**？ | (a) 不能（只有 admin）(b) 能 | **(a)**；`grant` 是 admin 专属 |
| **Q5** | share token（roadmap Phase 3）算不算一种 grant？ | (a) 独立表 `share_tokens` (b) 复用 `wiki_grants` | **(b) 倾向**：share = 「对某 wiki 的 read grant + 匿名主体」；但 share 有过期/口令等独立语义 ⇒ **(a) 更干净** |
| **Q6** | 本地模式（回环）是否应绕过 grants？ | (a) 绕过（现状） (b) 也走 grants | **(a)** 保留 —— decision 12「localhost 完全信任」是既有决策；改动会破坏本地开发体验 |

---

## 10. 决策日志（评审时逐条填）

| # | 决策 | 结论 | 拍板人 | 日期 |
|---|---|---|---|---|
| D1 | 授权表形状 | | | |
| D2 | 授权存储位置 | | | |
| D3 | 授权粒度 | | | |
| D4 | 动作集合 | | | |
| D5 | deny 规则 | | | |
| D6 | 撤销后 token | | | |
| D7 | token 载荷 | | | |
| D8 | 非 admin 默认 | | | |
| D9 | `public_read` 落点 | | | |
| Q1 | 组支持 | | | |
| Q2 | wiki 属主 | | | |
| Q3 | `["*"]` 语义 | | | |
| Q4 | 授权权下放 | | | |
| Q5 | share token 归属 | | | |
| Q6 | 本地模式绕过 | | | |

---

## 11. 关联文档

- `docs/designs/multiuser-auth-research.md` — 业界调研（PostgreSQL / NIST / K8s / Casbin / GitHub 一手取证）
- `docs/llmwikify-auth-缺陷清单.md` — 现状缺陷与修复批注（P0/P1 已清）
- `docs/designs/auth-and-sharing-roadmap.md` — 既有 Phase 3/4 规划（share token / hub）
- `docs/designs/refactor-4layer-architecture.md` — 4 层依赖规则（`foundation` 不得依赖 `apps`）
