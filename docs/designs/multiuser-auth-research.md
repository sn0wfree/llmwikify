# 多用户与授权模型 — 业界调研

> 日期: 2026-11-13
> 目的：为 llmwikify 的 **user × wiki × 读写** 授权模型选型提供业界依据
> 范围：数据库权限管理为主（题目所问），辅以 RBAC / ABAC / token 授权
> 关联：`docs/designs/multiuser-auth-design.md`（设计文档，待评审）、
> `docs/llmwikify-auth-缺陷清单.md`（现状缺陷）、
> `docs/designs/auth-and-sharing-roadmap.md`（Phase 3/4 的 share / hub 规划）
> 方法：**一手文档取证**（下表 URL 均实际抓取），非记忆转述；未取到的一手源明确标注

---

## 0. TL;DR

1. **数据库权限模型就是我们要的形状**。PostgreSQL 的 `GRANT … ON <object> TO <role>` 与
   「user × wiki × 读写」是**同构**的：object = wiki，privilege = read/write，
   grantee = user。K8s RBAC 是同一模型的 API 化（Role + RoleBinding）。
2. **业界主流是「加法授权、无拒绝规则」**（K8s 明写 "Permissions are purely additive
   (there are no 'deny' rules)"）。这与我们要的「给权限」语义一致，**不要引入 deny**。
3. **token ⊆ owner** 是硬约束（GitHub 明写："A token cannot grant additional access
   capabilities to a user"）。⇒ 我们的 PAT/JWT **不能**比它的用户权限更大。
4. **域/命名空间是切面，不是维度爆炸**。K8s 用 namespace、Postgres 用 schema、
   Casbin 用 domain 三元组 —— 都是把「同一套角色按域实例化」，**不是**给每个域建新角色。
5. **Casbin / OPA 这类通用策略引擎对我们是 YAGNI**：引入新依赖 + DSL 学习成本，
   而我们的资源模型只有 1 个对象类型（wiki）+ 2 个动作（read/write）。
6. **推荐方向**：**照搬 DB 授权表的扁平形状**（`user × wiki × privilege`），
   角色层（role 表 + binding）**延后**；token 侧走 **claims 快照**（改授权需重签）。

---

## 1. 取证来源

| # | 一手源 | URL | 取到 |
|---|---|---|---|
| S1 | PostgreSQL 18 `GRANT` 文档 | postgresql.org/docs/current/sql-grant.html | ✅ 全文 |
| S2 | NIST CSRC — Role Based Access Control | csrc.nist.gov/projects/role-based-access-control | ✅ 全文 |
| S3 | Kubernetes — Using RBAC Authorization | kubernetes.io/docs/reference/access-authn-authz/rbac/ | ✅ 全文 |
| S4 | Apache Casbin — RBAC with Domains | casbin.org/docs/rbac-with-domains | ✅ 全文 |
| S5 | GitHub Docs — Managing personal access tokens | docs.github.com/…/managing-your-personal-access-tokens | ✅ 全文 |
| S6 | MySQL `GRANT` 文档 | dev.mysql.com/doc/refman/8.4/en/privileges.html | ❌ 404（未取证，下文按标准模型描述并标注） |
| S7 | SQLite — Write-Ahead Logging | sqlite.org/wal.html | ✅ 全文 |
| S8 | SpiceDB — Consistency（鉴权缓存 + 一致性等级） | authzed.com/docs/spicedb/concepts/consistency | ✅ 全文 |
| S9 | Envoy — External Authorization（ext_authz） | envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter | ✅ 全文 |

---

## 2. 数据库权限模型（题目主线）

### 2.1 PostgreSQL（最有参考价值）

**授权语句形状**（S1 原文）：

```sql
GRANT { SELECT | INSERT | UPDATE | DELETE | … } ON table_name TO role_specification [ WITH GRANT OPTION ]
GRANT role_name TO role_specification [ WITH { ADMIN | INHERIT | SET } … ]
```

**核心构件**：

| 构件 | PG 术语 | 我们的对应 |
|---|---|---|
| 被授权对象 | object（table / schema / database / sequence …） | **wiki** |
| 权限 | privilege（`SELECT`/`INSERT`/`UPDATE`/`DELETE`/`USAGE`…） | **read / write** |
| 被授权者 | role（8.1 起 user 与 group 统一为 role） | **user** |
| 角色成员关系 | `GRANT role TO role` | （我们延后） |
| 授权记录 | `pg_class.relacl` / `pg_auth_members` | **`wiki_grants` 表** |

**五条可直接借用的规则**（S1 原文依据）：

| # | PG 规则 | 原文要点 | 对我们的意义 |
|---|---|---|---|
| R1 | **对象 owner 隐含全部权限** | "There is no need to grant privileges to the owner of an object … the owner has all privileges by default" | wiki 属主 / admin 天然全权，**无需 grant 行** |
| R2 | **权限累加，无拒绝** | "the sum of privileges granted directly to it, privileges granted to any role it is presently a member of, and privileges granted to PUBLIC" | 多条 grant **并集**；不存在 deny 行 |
| R3 | **PUBLIC 伪角色** | "PUBLIC can be thought of as an implicitly defined group that always includes all roles" | 「所有人默认可读」= 一条 PUBLIC grant（等价于我们今天的 `public_read`） |
| R4 | **授权可传递（WITH GRANT OPTION）** | "the recipient of the privilege can in turn grant it to others" | 我们**先不做**（多租户再考虑） |
| R5 | **授权记录归属 grantor** | "If GRANTED BY is specified, the specified grantor must be the current user" | 记录 `granted_by`，审计用 |

**表级 → 列级的教训**（S1 Notes 段）：

> "Granting the privilege on a table does not automatically extend permissions to any sequences used by the table … Permissions on sequences must be set separately."

⇒ **粒度必须显式**：我们若允许「wiki 可写」，就要想清楚是否隐含「该 wiki 的 chat DB 可写」。
PG 的教训是：**别让一个 grant 悄悄带出别的对象的权限**。

**与我们的差距**（实证，非猜测）：

| PG 构件 | llmwikify 现状 |
|---|---|
| role（用户/组统一） | `users` 表只有 `is_first_admin` 一个布尔标记 |
| object privilege 记录 | **无表** —— `wikis` 只是 JWT 里写死的 `["*"]` |
| `GRANT` / `REVOKE` 语句 | **无 CLI、无 API** |
| `pg_auth_members`（角色成员） | 无 |

### 2.2 MySQL（标准模型，未取证）

MySQL 的层级与 PG 类似但更啰嗦：privilege 分 **global / database / table / column** 四层，
每层独立授予，`GRANT OPTION` 语义与 PG 相同，并有 `ALL PRIVILEGES` 简写。

⚠️ **S6 未取到（404）**，以上为标准模型描述，**实施时以 PG（S1）为准**并实测 MySQL 行为。
值得借的一条：**层级越多，运维心智负担越重** —— 我们只有 1 个对象类型，
**不要**学 MySQL 的多层 privilege namespace。

### 2.3 SQLite（本项目实际存储）

SQLite **没有**内置角色/授权系统（`PRAGMA` 也不提供）。业界做法是**自己在业务表里模拟**：

- 常见落地：一张 `acl(resource_type, resource_id, principal, privilege)` 表
- 或「主表 + 每对象一行权限」：`permissions(resource_id, user_id, can_read, can_write)`

⇒ **我们只能在 `auth.db` 里自建授权表**（这本来就是 S1/S3 的通用做法）。

---

## 3. RBAC / ABAC 理论线（NIST）

### 3.1 RBAC 基本模型（S2）

> "Role based access control (RBAC) … as formalized in 1992 by David Ferraiolo and Rick Kuhn …
> The NIST model for RBAC was adopted as American National Standard 359-2004 … revised as INCITS 359-2012."

**RBAC 的管理成本论证**（S2）：

> "administrators usually specify access control lists for each user on the system individually.
> With RBAC, security is managed at a level that corresponds closely to the organization's structure.
> Each user is assigned one or more roles, and each role is assigned one or more privileges."

**标准的基本元素**（S2）：**users · roles · permissions · operations · objects** 与它们之间的关系。

**RBAC vs ABAC**（S2 原文）：

> "ABAC is a rule-based approach to access control that can be easy to set up but complex to manage."

NIST 另有一篇 *Adding Attributes to Role-Based Access Control*（Kuhn/Coyne/Weil 2010），
方向是**混合**（RBAC 打底 + ABAC 加属性条件），不是替代。

### 3.2 RBAC 四种模型（S2 的标准结构）

| 模型 | 关系 | 我们是否需要 |
|---|---|---|
| **RBAC0** | user ↔ role ↔ permission | 基础 |
| **RBAC1** | + role 继承（role hierarchy） | 延后 |
| **RBAC2** | + 职责分离 constraint | 延后 |
| **RBAC3** | + RBAC1 + RBAC2 | 延后 |

### 3.3 成本参照（S2）

> "NIST's RBAC research was estimated to have saved industry $1.1 billion over multiple months …"
> "As of 2010, the majority of users in enterprises of 500 or more were using RBAC"

⇒ RBAC 的价值在**规模**（500+ 人企业）。llmwikify 的目标用户规模是
**单团队 / 小机构（<50 人）** ⇒ **先上 RBAC0 的扁平投影**（user × object × privilege），
**角色层等真的有人抱怨"每人配一堆 grant"时再加**。

---

## 4. Kubernetes RBAC（API 化的 DB 授权模型）

### 4.1 四个对象（S3）

| 对象 | 作用域 | 内容 |
|---|---|---|
| `Role` | **namespaced** | `rules`（apiGroups / resources / resourceNames / verbs） |
| `ClusterRole` | cluster-scoped | 同上，可被绑到任意 namespace |
| `RoleBinding` | namespaced | `subjects`（user/group/SA）+ `roleRef` |
| `ClusterRoleBinding` | cluster | 同上 |

⇒ **「wiki」就是 namespace**，「user」就是 subject，「read/write」就是 verbs。

### 4.2 五条规则（S3 原文依据）

| # | 规则 | 原文要点 | 对我们的意义 |
|---|---|---|---|
| K1 | **纯加法，无 deny** | "Permissions are purely additive (there are no 'deny' rules)" | **不实现 deny**；撤销 = 删 grant |
| K2 | **Role 必带 namespace，ClusterRole 不带** | "A Kubernetes object always has to be either namespaced or not namespaced; it can't be both" | 我们的 grant 行天然带 wiki_id（=namespace） |
| K3 | **`roleRef` 不可变** | "After you create a binding, you cannot change the Role or ClusterRole that it refers to" | 改授权 = 删绑 + 重建，或换绑定目标 |
| K4 | **默认用户角色分层** | `view`（只读）/ `edit`（读写）/ `admin`（读写 + 授权）/ `cluster-admin` | **现成的模板**：我们可给 `viewer`/`editor` 预设 |
| K5 | **`kubectl auth can-i` 自检** | "kubectl auth can-i" 命令 | 我们的 CLI 也该有 `auth can-i --user X --wiki Y --write` |

### 4.3 最小权限警告（S3）

> "Caution: Using wildcards in resource and verb entries could result in overly permissive access …
> The principle of least privilege should be employed"

⇒ 通配 `wikis=["*"]` 应当是**显式选择**，不是默认。我们今天的默认就是 `["*"]` —— 正是这个警告的实例。

### 4.4 默认角色的分层权限（S3 `view` / `edit` / `admin`）

| 角色 | 权限 |
|---|---|
| `view` | 只读；**不能**查看 role/binding（防提权） |
| `edit` | 读写大部分对象；**不能**修改 role/binding；**可读 Secrets**（⚠️ 等于可拿 SA 凭据提权） |
| `admin` | 读写 + 可创建 role/binding；不可写 resource quota / 改 namespace |

⚠️ `edit` 能读 Secrets 从而提权 —— 这提醒我们：**「可写某个 wiki」不该顺带包含「可读该 wiki 的凭据」**。

---

## 5. Casbin（通用策略引擎）

### 5.1 域内 RBAC（S4 原文）

```ini
[role_definition]
g = _, _, _          # 第三个字段 = domain

[request_definition]
r = sub, tenant, obj, act
[policy_definition]
p = sub, tenant, obj, act
[matchers]
m = g(r.sub, p.sub, r.dom) && r.dom == p.dom && r.obj == p.obj && r.act == p.act
```

策略与绑定示例（S4）：

```
p, admin, tenant1, data1, read
g, alice, admin, tenant1
g, alice, user,  tenant2
```

⇒ **同一用户在不同域有不同角色**；`alice` 在 tenant1 是 admin（能读 data1），在 tenant2 只是 user（不能读 data2）。

**这正是我们要的形状**：`g(user, role, wiki)` + `p(role, wiki, act)`。

### 5.2 但对我们是 YAGNI

| 成本 | 说明 |
|---|---|
| 新依赖 | `casbin` + 配置文件 + model.conf 格式学习 |
| 表达力过剩 | 我们的资源只有 1 种（wiki）、动作 2 种（read/write）、主体 1 种（user） |
| 调试门槛 | 匹配器求值链对「为什么这个用户没权限」不直观 |
| 迁移成本 | Casbin 的 `g`/`p` 是文本规则，不是 SQL 表 ⇒ 与 `auth.db` 的事务/备份割裂 |

**结论**：**借它的「形状」（domain 化角色），不引入它的「引擎」**。
我们的域就是 wiki_id，直接作为列存在表里。

---

## 6. Token 侧授权（PAT / JWT）

### 6.1 GitHub fine-grained PAT（S5 原文）

| 事实 | 原文要点 |
|---|---|
| **token ⊆ owner** | "A token has the same capabilities … that the owner of the token has, and is further limited by any scopes or permissions granted to the token. **A token cannot grant additional access capabilities to a user.**" |
| **三段式授权** | ① **Resource owner**（user/org）② **Repository access**（哪些 repo）③ **Permissions**（细粒度 read/write/admin） |
| **权限级别** | `read` / `write` / `admin`；"write always includes read, and admin always includes write" |
| **令牌失效** | "Both fine-grained personal access tokens and personal access tokens (classic) are tied to the user who generated them and will become inactive if the user loses access to the resource" |
| **过期默认** | 建议加 expiration；classic 一年未用自动删 |

⇒ **对我们的直接映射**：

| GitHub | llmwikify |
|---|---|
| Resource owner | user |
| Repository access | **wiki 列表**（我们已有 `wikis` claim） |
| Permissions | **read/write**（我们已有 `scope`） |
| token ⊆ owner | **我们今天违反了**：非 admin 也签 `wikis=["*"]`（P1-4 已修为 read，但 wiki 维度仍全开） |

### 6.2 业界两种「token 携带授权 vs 实时查表」

| 方式 | 代表 | 优点 | 代价 |
|---|---|---|---|
| **claims 快照** | OAuth2 / JWT / GitHub PAT / K8s ServiceAccount token | 中间件零 IO；性能好 | 授权变更需重签（GitHub 靠 token 短有效期 + 重新签发） |
| **实时查表** | 我们的 `ParamRegistry` 式；OPA；Zanzibar | 改授权**立即生效** | 每请求查权限存储 |

**GitHub 的做法值得注意**：token 同时带「资源范围」与「权限级别」，
但**授权变更（失去 repo 访问权）会立即使 token 失效**（"will become inactive if the user loses access"）——
即 **授权的「上界」实时查，「快照」只是缓存**。

---

## 7. 横向对比总表

| 系统 | 对象维度 | 权限粒度 | 授权者 | 拒绝规则 | 撤销方式 | 角色层 |
|---|---|---|---|---|---|---|
| **PostgreSQL** | table/schema/db | SELECT/INSERT/… | role（user=role） | ❌ 无 | REVOKE | ✅ role membership |
| **MySQL** | global/db/table/column | 多层级 | user/host | ❌ 无 | REVOKE | ✅ role |
| **Kubernetes** | resource (+namespace) | verb | subject（user/group/SA） | ❌ 无（纯加法） | 删 RoleBinding | ✅ Role/ClusterRole |
| **Casbin** | obj（任意） | act | sub + domain | ✅ 视 matcher | 改策略 | ✅ g 关系图 |
| **GitHub FG-PAT** | repo | permission(read/write/admin) | token owner（用户自己） | — | 删 token / 失权自动失效 | ❌ 无 |
| **llmwikify 现状** | wiki（JWT 字段，非表） | read/write（全局） | 仅 first admin | ❌ 无 | 无 | ❌ 无 |

---

## 8. 从调研到本项目的 6 条结论

| # | 结论 | 依据 |
|---|---|---|
| **C1** | 授权记录应落成**表**（`user × object × privilege`），不靠 JWT 里两个字段 | S1（PG acl 表）、S3（Role/Binding 资源） |
| **C2** | **纯加法、无 deny**；撤销 = 删行 | S1 R2、S3 K1 |
| **C3** | **owner / admin 隐含全权**，不写 grant 行 | S1 R1 |
| **C4** | **token 权限 ⊆ 用户权限**；授权变更要能影响已发 token | S5（token ⊆ owner；失权即失效） |
| **C5** | **wiki 就是 namespace/domain**：角色按 wiki 实例化，而非按 wiki 复制角色表 | S3 K2、S4（domain 三元组） |
| **C6** | **角色层延后**；先上 RBAC0 的扁平投影（user × wiki × priv） | S2（RBAC 价值在 500+ 规模）、S3 K4（预设角色可后加）、Casbin YAGNI |

---

## 9. 本项目现有内部先例（实证）

| 位置 | 是什么 | 与本主题的关系 |
|---|---|---|
| `apps/chat_db/permission_repo.py` | `chat_permissions(id, session_id, tool_name, pattern, response, created_at)` | ⚠️ **名字像但语义不同** —— 这是「工具自动放行」记录（`response='always'`），**不是用户授权**。命名沿用 `*_permissions` 传统，但**不可复用** |
| `foundation/auth/db.py` | `users` + `api_keys` | `api_keys.scopes` 是**全局** read/write，与 wiki 无关 |
| `foundation/auth/_jwt.py` | `TokenClaims(sub, scope, wikis, exp, aud, iss)` | `wikis` 是**唯一**的 wiki 维度载体，且写死 `["*"]` |
| `interfaces/server/http/middleware.py` | `_check_wikis_claim(path, claims)` | 只认 `/api/wiki/{id}/…`（5+ 段）—— 已在 P0-1 修复中扩到 search/registry 路由 |
| `interfaces/server/http/wiki/registry_routes.py` / `search_routes.py` | 按 `claims.wikis` 过滤 | **已有 wiki 维度的裁决点**，只是数据源是 JWT 而非表 |

⇒ **裁决点已存在，只缺「数据源」**。这是本设计能小步落地的关键。

---

## 10. 性能与并发（2026-11-13 补：每请求查表是否锁死 DB）

**实测**（本机 5000 行，主键点查）：

| 姿势 | 单次 | 说明 |
|---|---:|---|
| 复用连接点查 | 25–28 µs | 1000 次 = 25 ms |
| 每次开新连接 | **208 µs** | ≈ 8 倍（连接建立是大头） |
| `journal_mode` 默认 | `delete`（回滚日志） | 我们现状（`connect(wal=False)`） |

**SQLite WAL 并发语义**（S7）：

> "WAL provides more concurrency as readers do not block writers and a writer does not block readers."

| 模式 | 语义 |
|---|---|
| rollback journal | **读阻塞写、写阻塞读** —— 会排队 |
| WAL | 读写并发；**只允许 1 个写者**；仍可能 `SQLITE_BUSY`（三个窄窗口） |
| WAL 坑 | 持续读 + 长事务 ⇒ checkpoint 无法完成 ⇒ WAL 无限增长（"the WAL file will grow without bound"） |

**业界的鉴权缓存**：

| 系统 | 做法 | 证据 |
|---|---|---|
| **SpiceDB / Zanzibar** | 多层缓存权限判定，一致性等级换延迟 | S8："implements a number of levels of caching, to ensure that repeated permissions checks do not need to be recomputed over and over again"；`fully_consistent` "explicitly bypasses caching, dramatically impacting latency" |
| **Envoy ext_authz** | 外部授权服务 + 超时 + fail-closed | S9：`timeout: 200ms`（默认）；`failure_mode_allow: false` |
| **NIST / PG / K8s** | 无通用缓存层（DB 自己的页缓存） | — |

**对 llmwikify 的结论**：<50 人本地工具，一次 wiki 页读是毫秒级 ⇒ 25µs 鉴权查表占比 **<1%**。
**不需要**上 SpiceDB 式缓存；但必须 **WAL + 连接复用**，否则在 Windows 上「锁死」是真风险。
详见 `multiuser-auth-design.md` §4.2 的五条硬措施（M1–M5）。

---

## 11. 未取证 / 存疑项

| 项 | 状态 |
|---|---|
| MySQL `GRANT` 原文 | ❌ 404（按标准模型描述，实施以 PG 为准） |
| OPA / Cedar 的具体模型 | 本轮未取证；**结论上**归入「通用策略引擎 = YAGNI」，若评审要求再补 |
| Zanzibar / ReBAC | 本轮未取证；与本题规模不匹配，暂不展开 |
| 各家「授权变更立即生效」的**实现细节** | S5 只给了行为承诺（失权即 token 失效），未给实现机制 |
| Zanzibar 热点缓存实现 | S8 有导读（authzed.com/blog/hotspot-caching…）未逐字取证；缓存 + 一致性等级的结论已足够 |

---

## 12. 参考

- S1 https://www.postgresql.org/docs/current/sql-grant.html
- S2 https://csrc.nist.gov/projects/role-based-access-control
- S3 https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- S4 https://casbin.org/docs/rbac-with-domains
- S5 https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens
- S7 https://www.sqlite.org/wal.html （WAL 并发语义，一手）
- S8 https://authzed.com/docs/spicedb/concepts/consistency （鉴权缓存 + 一致性等级）
- S9 https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter （外部授权 + 超时 + fail-closed）
- 内部：`docs/designs/auth-and-sharing-roadmap.md`（Phase 3 share token / Phase 4 hub 的既有规划）
