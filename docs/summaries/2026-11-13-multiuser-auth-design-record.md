# 多用户与授权模型 — 讨论与规划完整记录

> 日期: 2026-11-13
> 性质：**讨论过程 + 决策留痕 + 实施规划**（非最终方案正文；方案正文见 `docs/designs/multiuser-auth-design.md`）
> 产出物：
> - `docs/designs/multiuser-auth-research.md` — 业界调研（9 个一手源取证）
> - `docs/designs/multiuser-auth-design.md` — 设计方案（15/15 决策已拍板）
> 状态：**设计收口，可开 P1 实施**
> 关联：`docs/summaries/2026-11-13-platform-config-auth-report.md`（本轮前期三阶段报告）、
> `docs/llmwikify-auth-缺陷清单.md`（现状缺陷基线）

---

## 0. 一页总览

| 阶段 | 内容 | 产出 |
|---|---|---|
| 1 | 现状盘点：多用户与 user×wiki×r/w 现状如何 | 数据流图 + 差异表 |
| 2 | 业界调研：能否借用 DB 权限管理 | 调研文档（PG/NIST/K8s/Casbin/GitHub/SQLite/SpiceDB/Envoy） |
| 3 | 设计草案：表结构 + 裁决流 + 管理面 | 设计文档（D1–D9 + Q1–Q6） |
| 4 | 决策评审：15 项逐条拍板 | 决策日志 |
| 5 | 性能验证：每请求查表会不会锁死 DB | 实测 + 业界缓存做法 + M1–M5 硬措施 |
| 6 | 实施规划：P1–P6 分期 | 每期独立可验收 |

**最终决策状态**：**D1–D9 + Q1–Q6 全部 15/15 拍板**，无遗留。

**核心一句话**：借数据库 `GRANT` 模型的形状，建 `wiki_grants` 表（`principal × wiki × read/write`），
把授权从「JWT 里写死的常量」变成「可管理的行」；裁决取 **快照 ∩ 实时上界**。

---

## 1. 起点：现状盘点

### 1.1 问题

用户提问：**现在如何进行多用户管理，以及如何对多（用户 × wiki × 读写）进行管理？**

### 1.2 实证结论

| 维度 | 现状 | 缺口 |
|---|---|---|
| **多用户** | 只能建 1 个 admin（`registration_closed`） | 无 `create-user` / 无禁用 / 无列用户 |
| **user** | `users` 只有 `is_first_admin` 一个布尔 | 无角色、无组 |
| **wiki** | JWT 里 `wikis` **恒 `["*"]`** | 无 per-user 授权表 |
| **r/w** | **全局** `scope`（read/write） | 不能「wiki-A 可写、wiki-B 只读」 |
| **裁决点** | ✅ **已存在**（`_check_wikis_claim` / registry / search 三处） | **只缺数据源** |

**根因一句话**：`wikis` claim **没有数据源** —— 只有签发时写死的常量。

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 300" width="100%">
<style>
text { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.t { font-size: 14px; font-weight: 500; fill: #0C447C; }
.s { font-size: 12px; fill: #444441; }
.b { font-size: 13px; fill: #0C447C; }
.a { font-size: 11px; fill: #5F5E5A; }
</style>
<defs>
  <marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs>
<text x="40" y="34" class="t">现状 · 三维度都挤在 JWT 两个字段里</text>
<text x="40" y="52" class="s">签发时写死，没有可管理的授权表</text>

<rect x="40" y="80" width="150" height="72" rx="8" fill="#FCEBEB" stroke="#A32D2D" stroke-width="0.5"/>
<text x="115" y="106" text-anchor="middle" class="b">users</text>
<text x="115" y="126" text-anchor="middle" class="a">仅 1 个 admin</text>
<text x="115" y="142" text-anchor="middle" class="a">无 create-user</text>

<rect x="265" y="80" width="220" height="72" rx="8" fill="#EEEDFE" stroke="#534AB7" stroke-width="0.5"/>
<text x="375" y="106" text-anchor="middle" class="b">JWT claim</text>
<text x="375" y="126" text-anchor="middle" class="a">scope: read | write（全局）</text>
<text x="375" y="142" text-anchor="middle" class="a">wikis: 恒 ["*"]</text>

<rect x="540" y="80" width="100" height="72" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
<text x="590" y="112" text-anchor="middle" class="b">middleware</text>
<text x="590" y="132" text-anchor="middle" class="a">按请求裁决</text>

<line x1="190" y1="116" x2="263" y2="116" stroke="#534AB7" stroke-width="1" marker-end="url(#ar)"/>
<line x1="485" y1="116" x2="538" y2="116" stroke="#185FA5" stroke-width="1" marker-end="url(#ar)"/>

<rect x="40" y="196" width="600" height="86" rx="12" fill="#F1EFE8" stroke="#B4B2A9" stroke-width="0.5"/>
<text x="60" y="222" class="b">三维实际取值</text>
<text x="60" y="246" class="a">user  → 只有 first admin 可建；他人只能手工插库再 create-token --user</text>
<text x="60" y="268" class="a">wiki  → 签发时恒 ["*"]；r/w → 全局 scope，不能按 wiki 分</text>
</svg>
```

---

## 2. 业界调研（题目主线：借用 DB 权限管理）

### 2.1 取证来源（9 个一手源）

| # | 一手源 | 取到 |
|---|---|---|
| S1 | PostgreSQL 18 `GRANT` 文档 | ✅ 全文 |
| S2 | NIST CSRC — RBAC | ✅ 全文 |
| S3 | Kubernetes — Using RBAC Authorization | ✅ 全文 |
| S4 | Apache Casbin — RBAC with Domains | ✅ 全文 |
| S5 | GitHub — Managing personal access tokens | ✅ 全文 |
| S6 | MySQL `GRANT` 文档 | ❌ 404（未取证） |
| S7 | SQLite — Write-Ahead Logging | ✅ 全文 |
| S8 | SpiceDB — Consistency（鉴权缓存） | ✅ 全文 |
| S9 | Envoy — External Authorization | ✅ 全文 |

### 2.2 六条结论

| # | 结论 | 依据 |
|---|---|---|
| **C1** | 授权记录应落成**表**（`user × object × privilege`），不靠 JWT 两个字段 | PG acl 表、K8s Role/Binding |
| **C2** | **纯加法、无 deny**；撤销 = 删行 | PG「sum of privileges」+ K8s「no deny rules」 |
| **C3** | **owner / admin 隐含全权**，不写 grant 行 | PG「owner has all privileges by default」 |
| **C4** | **token 权限 ⊆ 用户权限**；授权变更要能影响已发 token | GitHub「a token cannot grant additional access」 |
| **C5** | **wiki 就是 namespace/domain** | K8s namespace + Casbin `g = _,_,_` |
| **C6** | **角色层延后**；先上 RBAC0 的扁平投影 | NIST：RBAC 价值在 500+ 规模；我们 <50 人 |

### 2.3 PG 的五条可直接借用规则

| # | PG 规则 | 原文要点 | 对我们的意义 |
|---|---|---|---|
| R1 | owner 隐含全权 | "the owner has all privileges by default" | admin 不需要 grant 行 |
| R2 | 权限累加，无拒绝 | "sum of privileges granted directly … and PUBLIC" | 多行并集 |
| R3 | PUBLIC 伪角色 | "implicitly defined group that always includes all roles" | 未认证可读 = `public` 行 |
| R4 | 授权可传递（GRANT OPTION） | — | **不做** |
| R5 | 记录 grantor | "GRANTED BY …" | 审计列 `granted_by` |

### 2.4 关键判断

| 系统 | 对象维度 | 权限粒度 | 拒绝规则 | 角色层 |
|---|---|---|---|---|
| PostgreSQL | table/schema/db | SELECT/INSERT/… | ❌ 无 | ✅ |
| Kubernetes | resource (+namespace) | verb | ❌ 无 | ✅ |
| GitHub FG-PAT | repo | read/write/admin | — | ❌ |
| Casbin | obj（任意） | act | ✅ 视 matcher | ✅ |
| **llmwikify 现状** | wiki（JWT 字段） | read/write（全局） | ❌ | ❌ |

**Casbin / OPA 判定 YAGNI**：资源只有 1 类（wiki）、动作 2 个（read/write）、主体 1 种（user）；
新依赖 + DSL 学习成本不值 —— **借形状，不借引擎**。

---

## 3. 设计方案

### 3.1 表结构（定稿）

```sql
wiki_grants(
    principal_type TEXT NOT NULL,      -- 'user' | 'group' | 'public'
    principal_id   TEXT NOT NULL,      -- user_id | group_id | '*'
    wiki_id        TEXT NOT NULL,      -- 具体 wiki_id，或 '*' 通配
    can_read       INTEGER NOT NULL DEFAULT 0,
    can_write      INTEGER NOT NULL DEFAULT 0,
    granted_by     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (principal_type, principal_id, wiki_id)
);
groups(id, name, created_at)
group_members(group_id, user_id, PRIMARY KEY(group_id, user_id))
```

**主体类型并入同一张表**（K8s `subject.kind` + PG PUBLIC 的合并做法）—— **组支持不改表数量**。

### 3.2 请求裁决流

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 420" width="100%">
<style>
text { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif; }
.t { font-size: 14px; font-weight: 500; fill: #0C447C; }
.s { font-size: 12px; fill: #444441; }
.b { font-size: 13px; fill: #0C447C; }
.bg { font-size: 13px; fill: #085041; }
.a { font-size: 11px; fill: #5F5E5A; }
.ok { font-size: 12px; fill: #3B6D11; }
</style>
<defs>
  <marker id="ar2" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
    <path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </marker>
</defs>
<text x="40" y="34" class="t">请求裁决流（middleware 热路径）</text>
<text x="40" y="52" class="s">短路优先：本地信任 → 验签 → 身份状态 → admin 隐含全权 → 实时上界 ∩ 快照</text>

<rect x="250" y="72" width="180" height="42" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
<text x="340" y="93" text-anchor="middle" class="b">HTTP 请求</text>
<line x1="340" y1="114" x2="340" y2="134" stroke="#185FA5" stroke-width="1" marker-end="url(#ar2)"/>

<rect x="40" y="136" width="200" height="56" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
<text x="140" y="158" text-anchor="middle" class="b">① local_mode？</text>
<text x="140" y="178" text-anchor="middle" class="ok">是 → pass（Q6）</text>

<rect x="250" y="136" width="180" height="56" rx="8" fill="#E6F1FB" stroke="#185FA5" stroke-width="0.5"/>
<text x="340" y="158" text-anchor="middle" class="b">② 提取 token</text>
<text x="340" y="178" text-anchor="middle" class="a">cookie → Bearer → PAT</text>

<rect x="460" y="136" width="180" height="56" rx="8" fill="#FCEBEB" stroke="#A32D2D" stroke-width="0.5"/>
<text x="550" y="158" text-anchor="middle" class="b">③ 验签 / 查 PAT</text>
<text x="550" y="178" text-anchor="middle" class="a">失败 → 401</text>
<line x1="340" y1="192" x2="340" y2="214" stroke="#185FA5" stroke-width="1" marker-end="url(#ar2)"/>

<rect x="250" y="216" width="180" height="56" rx="8" fill="#FCEBEB" stroke="#A32D2D" stroke-width="0.5"/>
<text x="340" y="238" text-anchor="middle" class="b">④ disabled_at?</text>
<text x="340" y="258" text-anchor="middle" class="a">非空 → 401</text>
<line x1="340" y1="272" x2="340" y2="294" stroke="#185FA5" stroke-width="1" marker-end="url(#ar2)"/>

<rect x="250" y="296" width="180" height="56" rx="8" fill="#EAF3DE" stroke="#3B6D11" stroke-width="0.5"/>
<text x="340" y="318" text-anchor="middle" class="b">⑤ is_first_admin?</text>
<text x="340" y="338" text-anchor="middle" class="ok">是 → pass（PG owner）</text>
<line x1="340" y1="352" x2="340" y2="372" stroke="#185FA5" stroke-width="1" marker-end="url(#ar2)"/>

<rect x="250" y="374" width="180" height="42" rx="8" fill="#E1F5EE" stroke="#0F6E56" stroke-width="0.5"/>
<text x="340" y="395" text-anchor="middle" class="bg">⑥ 查 grants ∩ ⑦ 快照 → allow/403</text>
</svg>
```

| 步 | 条件 | 结果 | 为什么先做 |
|---|---|---|---|
| ① | `local_mode` | pass | Q6（decision 12） |
| ② | 无 token | `public` 行 ? GET pass : 401/403 | D9 |
| ③ | 验签失败 | 401 | — |
| ④ | `disabled_at` 非空 | 401 | **D6：禁用立即生效** |
| ⑤ | `is_first_admin` | pass | C3（PG owner） |
| ⑥ | 查 `wiki_grants`（user ∪ group ∪ public） | 无行 → 403；失败 → **fail-closed** | **D6-a** |
| ⑦ | 快照 ∩ 实时 | 无 → 403 | **D7** |

### 3.3 管理面数据流

```
auth init / create-user ─────────▶ users
auth group create/add/remove ────▶ groups + group_members
auth grant --user|--group ───────▶ wiki_grants   （INSERT/upsert）
auth revoke ─────────────────────▶ wiki_grants   （DELETE = 撤销）
auth disable-user ───────────────▶ users.disabled_at
auth create-token ───────────────▶ api_keys + JWT claims 快照
auth can-i --user U --wiki W --write → 只读自检
```

| 约束 | 说明 |
|---|---|
| admin 专属 | `create-user` / `group` / `grant` / `disable-user`（Q4） |
| `--user` 与 `--group` 互斥 | 一条 grant 只授给一个主体 |
| 撤销 = 删行 | 无 deny 行（D5） |
| WebUI = 同一套表的 UI | P5 |

---

## 4. 决策留痕（15/15 全部拍板）

| # | 决策 | 结论 | 一句话理由 |
|---|---|---|---|
| **D1** | 授权表形状 | ✅ 扁平 `principal×wiki×r/w` **含组支持** | C6：规模 <50 人；组按 K8s `subject.kind` 并入同表 |
| **D2** | 授权存哪 | ✅ `auth.db` | 授权是**全局**事实，与 wiki 生命周期解耦 |
| **D3** | 授权粒度 | ✅ **wiki 级**（无 page_id） | page 级 = 每次读页都查表；N7 排除 |
| **D4** | 动作集合 | ✅ **read / write** | admin 是**身份**不是动作 |
| **D5** | deny 规则 | ✅ **无，删行即撤销** | PG/K8s 均无；语义无歧义 |
| **D6** | 撤销后已发 token | ✅ **(a) 每请求查表，立即失效** | 见 §5 专节 |
| **D7** | token 载荷 | ✅ **快照 ∩ 实时上界** | 快照=上限，实时=撤权生效 |
| **D8** | 非 admin 默认 | ✅ **无授权**（最小权限） | K8s 警告：通配易过度授权 |
| **D9** | `public_read` 落点 | ✅ **`public` 主体行** | 组支持后更统一（PG PUBLIC） |
| **Q1** | 组支持 | ✅ **支持** | `groups` + `group_members` |
| **Q2** | wiki 属主 | ✅ **只 admin**；属主机制后续升级 | 无属主记录，先不做 |
| **Q3** | `["*"]` 语义 | ✅ **(a) 通配行 + (b) 快照求值展开 + (i) 覆盖新建 wiki** | 见 §6 专节 |
| **Q4** | 授权权下放 | ✅ **不能** —— `grant` admin 专属 | 最小权限 |
| **Q5** | share token 归属 | ✅ **(a) 独立表 `share_tokens`** | 有过期/口令等独立语义 |
| **Q6** | 本地模式绕过 | ✅ **绕过**（decision 12） | localhost 完全信任，既有决策 |

### 4.1 D6 的讨论过程（本记录重点）

**用户提问**：「D6 撤权 已发 token 立即失效 这个是什么意思？」

**术语澄清**：

| 术语 | 含义 |
|---|---|
| **已发 token** | 已签好、正在使用的 JWT/PAT；claims 里写死当时能访问哪些 wiki（快照） |
| **撤权** | `DELETE FROM wiki_grants WHERE …` |
| **立即失效** | **下一个请求就被拒**，不用等 30 天过期 |

**判定场景**：

| 时间 | 事件 |
|---|---|
| 10:00 | admin 给 alice 授权 wiki-a 可写 |
| 10:05 | alice 拿到 token T（30 天，claims 含 wiki-a:rw） |
| 10:30 | alice 用 T 写 wiki-a → 成功 |
| **11:00** | **admin 撤权** |
| 11:01 | alice 又用 T 写 wiki-a → **？** |

| 方案 | 11:01 | 后果 |
|---|---|---|
| B 纯快照 | 仍成功 | **撤权形同虚设** ❌ |
| **A 每请求查表** ✅ | **403** | 撤权真生效 |
| C 短 TTL | 403，最迟延迟 ≤ TTL | 折中 |

**用户结论**：「D6 撤权 已发 token 立即失效 我同意；就是类似 A」

---

## 5. 性能与并发验证（本记录重点）

**用户提问**：「每次查表性能问题；如果疯狂鉴权会不会锁死 db，调研业界怎么做」

### 5.1 实测（5000 行，主键点查）

| 姿势 | 单次 | 说明 |
|---|---:|---|
| 复用连接点查 | **25–28 µs** | 1000 次 = 25 ms |
| **每次开新连接** | **208 µs** | ≈ **8 倍** —— 连接建立是大头 |
| `journal_mode` 默认 | **`delete`（回滚日志）** | ⚠️ 我们现状 |

### 5.2 SQLite WAL 并发语义（S7）

| 模式 | 语义 | 疯狂鉴权时 |
|---|---|---|
| rollback journal（现状） | **读阻塞写、写阻塞读** | 一次 `auth grant` 挡住鉴权读 ⇒ **会排队** |
| WAL | "readers do not block writers and a writer does not block readers" | 读写并发；只允许 1 个写者 |
| WAL 坑 | 持续读 + 长事务 ⇒ checkpoint 无法完成 ⇒ WAL 无限增长 | 不锁死但读变慢 |
| WAL 仍会 BUSY | exclusive locking / 崩溃恢复 / 最后连接清理 | `busy_timeout=5s` 兜底 |

**结论**：**「锁死」的风险来自 journal mode + 每次开新连接，不是「查表」本身。**

### 5.3 业界的鉴权缓存

| 系统 | 做法 | 证据 |
|---|---|---|
| **SpiceDB / Zanzibar** | 多层缓存权限判定，一致性等级换延迟 | "implements a number of levels of caching…"；`fully_consistent` "bypasses caching, dramatically impacting latency" |
| **Envoy ext_authz** | 外部授权服务 + 超时 + fail-closed | `timeout: 200ms`；`failure_mode_allow: false` |

**规模差异**：SpiceDB 缓存是为「每秒百万次检查」；llmwikify 是 <50 人本地工具，
一次 wiki 页读是毫秒级 ⇒ 25µs 鉴权查表占比 **<1%**。**不需要**上 SpiceDB 式缓存。

### 5.4 五条硬措施

| # | 措施 | 为什么 | 归属 |
|---|---|---|---|
| **M1** | `auth.db` **开 WAL** | 消除读写互锁 | P1 必做 |
| **M2** | **复用连接**（进程内 1 个/线程） | 8 倍性能差 | P1 必做 |
| **M3** | **`_init_schema` 不每次跑**（P2-12 同根） | 每实例化 PRAGMA + executescript 是纯开销 | P1 必做 |
| **M4** | **fail-closed + 超时** | 查表失败 → 403，不放行、不悬挂 | P4 必做 |
| **M5** | **IP 级 rate limit** | 「疯狂鉴权」的闸门（已有） | 覆盖鉴权路径 |

> **Windows 额外注意**：锁语义更紧、杀软会短暂持锁 —— M1/M2 尤其重要。

---

## 6. Q3 `["*"]` 语义（本记录重点）

**三个子问题**：

| 子问题 | 选项 | 业界对照 |
|---|---|---|
| **Q3-a** 表里能否写 `wiki_id='*'` | (a) 能，通配行 (b) 不能 | GitHub「All repositories」= 通配；PG `ALL TABLES` = 展开 |
| **Q3-b** claims 快照存什么 | (a) 存 `*` (b) **签发时求值展开** | GitHub token 签发时明确「All / Only select」 |
| **Q3-c** `*` 覆盖**未来新建** wiki？ | (i) 覆盖（GitHub） (ii) 不覆盖（PG） | 两家相反 |

**关键洞察：两层可以不一致**（D7 已定「快照 ∩ 实时上界」）：

| 层 | `*` 的含义 | 新 wiki 时 |
|---|---|---|
| **grants 表（实时上界）** | 一行表示「对全部 wiki 的授权」 | **自动纳入上限**（Q3-c = i） |
| **claims 快照（token 上限）** | **不存在** —— 签发时求值展开 | **老 token 拿不到** |
| **裁决** | 实时：`*` 命中；快照：精确列表 | 交集 |

**拍板**：**Q3-a = (a) / Q3-b = (b) / Q3-c = (i)**。
一句话：**表里允许 `*`（管理便利），token 里永远是具体列表（范围明确）**。

| 收益 | 说明 |
|---|---|
| 管理方便 | `auth grant --user u --wiki '*'` 一行搞定 |
| token 范围明确 | 快照是具体列表，审计无歧义 |
| 新 wiki 不静默扩权 | 老 token 要访问新 wiki 得 `auth token` 重签 |
| 撤权立即生效 | `auth revoke --user u --wiki '*'` 删一行 |
| 与 D8 一致 | `*` 是**显式**给的全集，不是默认 |

**代价**：新 wiki 对已授权用户「可见」但要重签才可访问；`auth whoami` / `auth can-i` 会提示。

---

## 7. 实施规划（P1–P6，每期独立可验收）

| 期 | 内容 | 风险 | 依赖 | 状态 |
|---|---|---|---|---|
| **P1** | `wiki_grants` + `groups` + `group_members` 表 + `GrantRepository`（含 `*` 通配求值）+ 迁移探测（`public_read` → `public` 行）+ **M1/M2/M3** | **低**（纯新增） | ✅ 已解 | **可开工** |
| **P2** | `users.disabled_at` + `auth create-user/list-users/disable-user` | 低 | — | 待开工 |
| **P3** | 签发装 `wgrants`（快照求值展开）+ `auth grant/revoke/can-i` CLI | 中（改签发） | P1 P2 | 待开工 |
| **P3b** | 组 CLI（`auth group create/list/add/remove` + `grant --group`） | 低 | P1 P3 | 待开工 |
| **P4** | 裁决接入（实时上界 + 快照比对 + disabled + fail-closed） | **中高**（动中间件） | P3 | 待开工 |
| **P5** | WebUI 授权管理页 + `/me` 返回权限矩阵 | 中 | P3 | 待开工 |
| **P6** | share token 独立表 `share_tokens`（Q5=a） | 低 | 可延后 | 待开工 |

**顺序强调**：P1–P3 是**纯增量**（不动裁决路径），可先落地再评审 P4 的裁决策略。

**G5 零破坏**：单 admin 场景行为完全不变（admin 隐含全权，无需 grant 行）。

---

## 8. 风险与缓解

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 裁决改动引入回归（P0-1/P0-2 刚修好） | P4 单独评审；`tools/exploit_check_wikis_claim.py` 作回归门禁 |
| R2 | 每请求多一次 SQLite 查询 | M1 WAL + M2 连接复用（25µs vs 208µs）+ M3 schema 一次 |
| R3 | D6 立即失效 vs JWT 无状态 | 快照 ∩ 实时上界；**fail-closed**（M4） |
| R4 | admin 把自己锁在外面 | `is_first_admin` 短路；`auth can-i` 自检；`--force` 救援 |
| R5 | `public_read` 与 grants 语义重叠 | D9 落成 `public` 主体行，统一语义 |
| R6 | 复杂度膨胀 | N1–N7 明确排除；角色层延后；每期独立可验收 |
| R7 | 组授权撤销影响面放大 | 文档明示；`auth group list` 显示成员数；撤销前提示 |
| R8 | **疯狂鉴权锁死 auth.db**（Windows 锁更紧 + 杀软） | M1/M2/M5；详见 §5 |

---

## 9. 非目标（明确排除）

| # | 非目标 | 理由 |
|---|---|---|
| N1 | 角色表 / role membership / 继承 | RBAC 价值在 500+ 规模 |
| N2 | deny / 拒绝规则 | PG/K8s 均无 |
| N3 | `WITH GRANT OPTION`（授权可传递） | 单层 admin 足够 |
| N4 | 通用策略引擎（Casbin / OPA / Cedar） | 资源 1 类、动作 2 个；YAGNI |
| N5 | 列级 / 表级细分权限 | 只有 wiki 一个对象粒度 |
| N6 | 外部 IdP（OIDC / LDAP） | roadmap Phase 4 hub |
| N7 | 页级（page-level）权限 | roadmap Phase 4 |

---

## 10. 讨论过程中的关键问答

| 问 | 答 |
|---|---|
| 多用户现在怎么管？ | **几乎不能管** —— 只有 1 个 admin，无 create-user |
| 能借用 DB 权限管理吗？ | **能，而且最贴切** —— PG `GRANT` 的 object/privilege/grantee 与 user/wiki/r/w 同构 |
| Casbin 要不要上？ | **不要** —— 借形状不借引擎 |
| 撤权已发 token 立即失效是什么意思？ | 下一个请求就 403，不等 30 天过期（D6=A） |
| 疯狂鉴权会锁死 db 吗？ | 今天会排队（rollback journal）；**开 WAL + 复用连接就不会** |
| `["*"]` 怎么表达？ | **表允许通配，token 永远具体列表** |
| 组支持要不要？ | **要** —— K8s `subject.kind` 模式，并入同一张表 |

---

## 11. 文档索引

| 文档 | 内容 |
|---|---|
| `docs/designs/multiuser-auth-research.md` | 业界调研（9 个一手源，S1–S9） |
| `docs/designs/multiuser-auth-design.md` | 设计方案正文（表结构 + 裁决流 + 决策日志 + P1–P6） |
| `docs/summaries/2026-11-13-platform-config-auth-report.md` | 本轮前期三阶段报告（平台无关化 / 配置中枢 / auth 缺陷） |
| `docs/llmwikify-auth-缺陷清单.md` | 现状缺陷基线（P0 5/5 · P1 7/7 · P2 10/13 已修） |
| `docs/designs/auth-and-sharing-roadmap.md` | 既有 Phase 3/4 规划（share token / hub） |
