# 多用户与授权 · P1–P6 实施记录

> 日期: 2026-11-14
> 性质：**实施过程留痕**（讨论与设计见 `multiuser-auth-design-record.md`；方案正文见 `multiuser-auth-design.md` §12）
> 状态：**P1–P6 全部完成** · 15/15 决策拍板 · 门禁全过
> 验证基线：全量 **5201 passed** · mypy **415 files 0** · 架构 **0 violation** · ruff 干净
> 关联：`docs/designs/multiuser-auth-research.md`（业界调研）· `docs/llmwikify-auth-缺陷清单.md`（前置缺陷修复）

---

## 0. 一页总览

| 期 | 内容 | commit（code） | 状态 |
|---|---|---|---|
| **P1** | `wiki_grants` + `groups` + `group_members` + `GrantRepository`；M1 WAL / M2 连接复用 / M3 schema 一次 | `b6765c21` | ✅ |
| **P2** | `users.disabled_at` + `create-user` / `list-users` / `disable-user` / `enable-user` | `ed0e3f0f` | ✅ |
| **P3** | `TokenClaims.wgrants` + `snapshot_for_user` + `grant` / `revoke` / `can-i` | `a664d70c` | ✅ |
| **P3b** | `group create/list/add/remove` + `grant --group`（与 `--user` 互斥） | `9ff912eb` | ✅ |
| **P4a** | 纯函数 `authorize_request` + middleware 接入 + PAT 快照修补 | `90f9def0` | ✅ |
| **P4b** | 无 token 一律 401 + 用户存在检查 + 列表 snapshot ∩ live | `dc5e4259` | ✅ |
| **P5** | `/me` 权限矩阵 + grants API（admin）+ WebUI Access 页 | `4607feb3` | ✅ |
| **P6** | `share_tokens` 独立表 + `ShareTokenRepository`（数据层） | `3e46b86b` | ✅ |

**每个期都是 doc-first**：先写范围/验收进设计文档并 commit，再实现并 commit（见 §4 commit 清单）。

---

## 1. 最终授权模型

### 1.1 表结构

```sql
-- 身份
users(id, email, username, is_first_admin, created_at, last_login_at, disabled_at)
groups(id, name, created_at)
group_members(group_id, user_id, PRIMARY KEY(group_id, user_id))

-- 授权（D1 扁平 principal × wiki × r/w）
wiki_grants(
    principal_type TEXT CHECK IN ('user','group','public'),
    principal_id, wiki_id,          -- wiki_id 可为 '*'（Q3-a）
    can_read, can_write, granted_by, created_at,
    PRIMARY KEY(principal_type, principal_id, wiki_id)
)

-- 凭证
api_keys(...)                       -- PAT（已有）
share_tokens(...)                   -- P6：匿名分享链接（Q5=a，与 grants 分离）
```

### 1.2 请求裁决流（P4 最终态）

```
① local_mode（回环）     → pass（本地信任，Q6）
② 无 token               → 401 一律（P4b；public_read 废弃）
③ 验签失败               → 401
④ 用户缺失 / disabled     → 401
  scope 天花板            → 403（非 GET 需 write）
⑤ is_first_admin          → pass（PG owner）
⑥' 旧 token               → 跳过 ⑥⑦，wikis+scope 原样放行（全 wiki）
⑥ 查 wiki_grants 实时上界 → 无行/查询失败 → 403（fail-closed）
⑦ 快照 ∩ 实时             → 无 → 403
⑧ 放行
```

| 关键语义 | 决策 |
|---|---|
| **撤权** | 删行 ⇒ **下一个请求即 403**（D6=A，每请求查表） |
| **加权限** | **不追溯**老 token；要 `auth token` 重签（D7 快照上限） |
| **旧 token** | `wgrants` 空且 `wikis` 非空 → 跳过 grants，全 wiki（不提权 scope） |
| **列表路由** | `/api/wikis`、`/api/search/cross` = **snapshot ∩ live**（`accessible_wikis`） |
| **PAT** | 签发经 `snapshot_for_user`（修「非 admin PAT 全 wiki」漏洞）；PAT scopes 作**上限** |

### 1.3 签发语义（P3）

| 主体 | `wikis` | `wgrants` | `scope` |
|---|---|---|---|
| admin | `["*"]`（不变，G5） | `{}` | `write` |
| 非 admin + 写授权 | 具体列表（Q3-b） | `{wiki:"rw"…}` | `write` |
| 非 admin + 只读 | 具体列表 | `{wiki:"r"…}` | `read` |
| 非 admin 零授权 | `[]`（D8） | `{}` | `read` |

`scope = 快照含任一 rw ? write : read`（旧「非 admin 恒 read」是 D8 无授权的**现状**，非规则）。

---

## 2. 管理面

### 2.1 CLI（P2/P3/P3b）

| 命令 | 语义 |
|---|---|
| `auth create-user --email X` | 建**非 admin**；username 自动派生（P1-5 规则） |
| `auth list-users` | id / email / username / role / status |
| `auth disable-user X` | 软删（`disabled_at` 非空，**不删行**）；拒绝禁 admin |
| `auth enable-user X` | 撤销禁用 |
| `auth grant --user U \| --group G --wiki W [--write]` | 缺省 read；`--write` 蕴含 read；`--wiki '*'` 通配；**user/group 互斥** |
| `auth revoke --user U \| --group G --wiki W` | 删行；组撤销提示影响成员数（R7） |
| `auth can-i --user U --wiki W [--write]` | yes/no（K8s 风格） |
| `auth group create/list/add/remove` | 组管理；group 按 **name 或 id** 解析 |

全部 **admin 专属**（Q4）；`_require_admin()` fail-closed（无 token / 非 admin → 拒绝）。

### 2.2 HTTP（P5）

| 端点 | 权限 | 说明 |
|---|---|---|
| `GET /api/auth/me` | 登录 | 增 `permissions{accessible_wikis, wgrants, scope}` |
| `GET/POST/DELETE /api/auth/grants` | admin | grants CRUD |
| `GET /api/auth/users` · `GET /api/auth/groups` | admin | 管理页下拉 |

### 2.3 WebUI（P5）

`/agent/access`（导航 Access）：
- **权限矩阵**（任何登录用户）：scope + 可读 wiki + 快照
- **grants 表 + grant/revoke 表单**（仅 admin，非 admin 自动隐藏）

---

## 3. 关键实现决策

### 3.1 性能（M1–M3，设计 §4.2）

| # | 措施 | 实测/实现 |
|---|---|---|
| M1 | WAL | `get_connection()` 默认 `wal=True` |
| M2 | 连接复用 | auth 三仓库 + share 共用 thread-local `ManagedConnection`（**25µs vs 208µs**） |
| M3 | schema 一次 | `_schema_ready()` / `_schema_current()` 快路径 |
| M4 | fail-closed | grants 查询异常 → 403 `authz_unavailable` |
| M5 | 限流 | IP 级 rate limit（已有） |

**「疯狂鉴权会不会锁死」**：风险来自 rollback journal + 每次开新连接，**不是查表本身**。开 WAL + 复用连接后不锁（SQLite WAL 官方：读不挡写）。

### 3.2 旧 token 兼容（P4a）

| 解码后 | 判定 | 行为 |
|---|---|---|
| `wgrants` 非空 | 新 token | ⑥⑦ 精确裁决 |
| `wgrants` 空 + `wikis` 非空 | **旧 token** | 跳过 ⑥⑦；`wikis` 含该 wiki 或 `*` → 放行；`scope` 照旧 |
| `wgrants` 空 + `wikis=[]` | 新 token 零授权 | 走 ⑥，无行 → 403 |

> 「全部权限」= **wiki 维度全开**；`scope` 不提权（旧非 admin 仍 read-only）。
> 该值规则同时兼容既有测试里 `TokenClaims.new(wikis=[...])` 造的 fake token。

### 3.3 已知边界

| 项 | 状态 |
|---|---|
| share 完整功能（JWT/路由/CLI/远端只读/WebUI） | **defer** → roadmap Phase 3；P6 只落数据层 |
| `public_read` 参数 | 保留但 **ignore**（P4b）；`LLMWIKIFY_PUBLIC_READ` 行为上已无效 |
| D9 `public` 主体行 | **不做**（匿名通道已关；全员可读用组） |
| P2-3 JWT logout 吊销 | 仍开放（需 denylist） |
| P2-9 `is_local_default(None)==True` | 有意保留（decision 13） |
| P2-12 `_init_schema` 每次重跑 | 已由 M3 部分缓解；完全消除留后续 |

---

## 4. Commit 清单（doc-first → code）

```
# 调研 + 设计（前序，见 multiuser-auth-design-record.md）
ca78dade docs(auth): 业界调研 + 设计草案
330e2911 / 47aba7ec / b91073b3 / ecb43374 / 0dac300d / ef577203  决策拍板系列

# P1
5b00cb7e docs(auth): 讨论与规划完整记录
b6765c21 feat(auth): P1 授权表落地

# P2
92265ee1 docs(auth): P2 范围与验收
ed0e3f0f feat(auth): P2 用户生命周期

# P3
3106fe52 docs(auth): P3 范围与验收
a664d70c feat(auth): P3 签发装 grants 快照 + CLI

# P3b
7a918ded docs(auth): P3b 范围与验收
9ff912eb feat(auth): P3b 组管理 CLI

# P4a
dbe240dd docs(auth): P4a 裁决接入规格
90f9def0 feat(auth): P4a 裁决接入

# P4b
e44f3e6a docs(auth): P4b 收尾范围
dc5e4259 feat(auth): P4b 裁决收尾

# P5
aebb669e docs(auth): P5 范围与验收
4607feb3 feat(auth): P5 WebUI 授权管理

# P6
d81d786a docs(auth): P6 share_tokens 范围
3e46b86b feat(auth): P6 share_tokens 独立表
```

---

## 5. 验证快照（P6 完成时）

| 检查 | 结果 |
|---|---|
| `pytest tests/` | **5201 passed** / 106 skipped / 2 xfailed / 0 failed |
| `mypy src/` | **415 files · 0 errors** |
| `scripts/check_architecture.py` | **0 violation** |
| `ruff check src/ tests/` | 干净 |
| `tools/exploit_check_wikis_claim.py` | **4/4 blocked** |
| `tools/auth_defect_verify.py` | **4/4 NOT reproduced** |
| WebUI `tsc && vite build` | ✅（P5 时验证） |

**测试分布**（新增）：

| 文件 | 条数 | 覆盖 |
|---|---:|---|
| `test_foundation_auth_grants.py` | 23 | 表 / WAL / 连接 / grant-revoke / 通配 / 组 / public |
| `test_foundation_auth_authorize.py` | 20 | disabled / scope / admin / legacy / live / snapshot / fail-closed |
| `test_foundation_auth_share.py` | 9 | share_tokens CRUD / 过期 / 吊销 / 计数 |
| `test_cli_auth.py`（P2/P3/P3b 增量） | +21 | 用户生命周期 / grant / group |
| `test_interfaces_auth.py`（P5 增量） | +5 | grants API / 权限矩阵 |

---

## 6. 后续（明确 defer）

| 项 | 归属 | 依赖 |
|---|---|---|
| **完整 share 功能**：share JWT、`GET /share/{slug}`、`share` CLI、RemoteWiki 只读、WebUI ShareView | roadmap **Phase 3** | P6 数据层已就绪 |
| Hub 发布（OAuth / 中央知识库） | roadmap Phase 4 | — |
| 配置中枢剩余：参数登记表 162/388 渐进、Q2 族划分细则 | config hub | 已独立收口 |
| Auth 缺陷 P2-3（JWT logout 吊销）/ P2-9 / P2-12 | 缺陷清单 | 见 §3.3 |

---

## 7. 文档索引

| 文档 | 内容 |
|---|---|
| `docs/designs/multiuser-auth-design.md` | **方案正文**（D1–D9、Q1–Q6、§12.1–12.8 实现记录） |
| `docs/designs/multiuser-auth-research.md` | 业界调研（PG / NIST / K8s / Casbin / GitHub / SQLite / SpiceDB / Envoy） |
| `docs/summaries/2026-11-13-multiuser-auth-design-record.md` | 讨论与规划记录（拍板过程） |
| `docs/summaries/2026-11-13-platform-config-auth-report.md` | 本轮前期（平台无关 / 配置中枢 / auth 缺陷） |
| `docs/designs/auth-and-sharing-roadmap.md` | Phase 3/4 完整 share / hub 规划（**defer**） |
