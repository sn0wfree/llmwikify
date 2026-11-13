# llmwikify Auth 子系统缺陷清单

> **第十五轮 · auth 缺陷审计** → **2026-11-13 修复收口**
> 基线 `main @ 3e09b0c3`（2026-11-10，1387 commits）
> 审计范围：`foundation/auth/`（9 文件）· `interfaces/cli/commands/auth.py` · `interfaces/server/http/auth_routes.py` · `interfaces/server/http/middleware.py` · `interfaces/server/core.py` · `interfaces/cli/commands/serve.py` · `ui/webui/src/{components/auth,stores,types}`
> 方法：**读代码 + 逐条可复现验证**（不是静态猜测）—— 复现脚本：`tools/exploit_check_wikis_claim.py`、`tools/auth_defect_verify.py`
> **终态**：P0 **5/5** · P1 **7/7** · P2 **10/13** 已修；探针 **4/4 NOT reproduced**
> 完整会话报告：`docs/summaries/2026-11-13-platform-config-auth-report.md`

> ## 复核批注（2026-11-11，另一会话）
>
> 按当前 `main` 逐条复核 **25 条，无一条误报**。三处修订：
>
> 1. **P0-4 已修** —— `_keyring._SECRET_FILE` 改为 `_secret_file()`，按 `global_config_home()`
>    调用时解析（commit `9f9dd8f1`）。这是本轮修的**同型第 3 处** import 期捕获，
>    另两处是 `doctor_cmd.py:26` `CONFIG_PATH` 与 `foundation/config.py` 的
>    `Config._home/_path`（commit `9c05ab3e`）。
> 2. **复现脚本已入库** —— 原位于仓库外的 `/workspace/.tools/`，现在在
>    `tools/`（见 §5，路径已改为仓库相对）。
> 3. **两处小勘误**（不影响结论）：
>    - P0-1 探针①的实际路由是 `GET /api/wiki/{wiki_id}/page/{path}`（单数 `page`），
>      清单写的 `pages/` 是笔误；
>    - P1-7 的复现需 `TestClient(base_url="http://127.0.0.1")` ——
>      `is_local_default` 看的是 `request.url.hostname`，TestClient 默认 Host
>      `testserver` 不是回环地址，会走 401 分支（脚本已处理）。
>
> **复核结论**：24 条仍成立，1 条（P0-4）已修，0 条误报。
>
> ## 修复批注（2026-11-13，CLI 组）
>
> | 条目 | 状态 | commit 主题 |
> |---|---|---|
> | P1-1 | ✅ 已修 | `auto_first_admin` 新邮箱 → `registration_closed` |
> | P1-2 | ✅ 已修 | `create-token --user`（email/username/id） |
> | P1-3 | ✅ 已修 | `local_token` 归属保护 + `init --force` |
> | P1-6 | ✅ 已修 | 同名活跃 PAT 复用，不再堆积 |
>
> ## 修复批注（2026-11-13，P1-5 / P1-7 / P2）
>
> | 条目 | 状态 | 说明 |
> |---|---|---|
> | P1-5 | ✅ 已修 | `_unique_username` 加 `_2`/`_3` 后缀；并发 UNIQUE → `AuthError` |
> | P1-7 | ✅ 已修 | `/me` 认 Bearer；无效 token → 401；前端带 Bearer 并在 `authenticated:false` 时 clear |
> | P2-1 | ✅ 已修 | 不再写 `llmwikify_pat`（JWT 仍在 zustand persist，decision 20） |
> | P2-2 | ✅ 已修 | cookie `secure = (scheme == https)` |
> | P2-4 | ✅ 已修 | CORS `allow_credentials=False` + `origins=*`（同源 cookie 不走 CORS） |
> | P2-5 | ✅ 已修 | `expires_at` 按 unix-epoch 整数比较（NULL=永不过期） |
> | P2-6 | ✅ 已修 | 类/`_atomic_write` docstring 与实现一致（事务，非 tempfile+rename） |
> | P2-7 | ✅ 已修 | `/me` 成功时 `touch_last_login` |
> | P2-8 | ✅ 已修 | 报错改为 `POST /auth/verify first` |
> | P2-10 | ✅ 已修 | `decode(..., issuer=ISSUER)` |
> | P2-11 | ✅ 已修 | `create()` 捕获 `IntegrityError` → `AuthError` |
> | P2-13 | ✅ 已修 | 公开 `UserRepository.first_user()`，CLI/serve 不再调 `_connect` |
> | 文档漂移 | ✅ 已修 | middleware `?token=` 说明、`core.py` `/auth/login` 注释 |
> | P2-3 | ⏸ 未修 | logout 吊销需服务端 denylist（JWT 无状态），另开任务 |
> | P2-9 | ⏸ 有意保留 | `is_local_default(None/"" )==True` 是 decision 13「未指定 bind=本地」；HTTP 路径经 `_resolve_effective_host` 回落 `env_host()`，不会裸传 None |
> | P2-12 | ⏸ 未修 | 每次实例化跑 `_init_schema`（性能，非安全） |

---

## 0. 一页结论

**先更正一条**：上一轮《补功能执行规划》把 **B8 Auth PAT** 列成"未做的功能缺口"是错的 —— 那是照抄 `docs/designs/auth-and-sharing-roadmap.md` 的 checkbox（过期快照）。实际 CLI / HTTP / WebUI 三侧全部已实现。

**审计结果**：共 **25 条缺陷**，其中

| 级别 | 条数 | 性质 | 状态（2026-11-13） |
|---|---:|---|---|
| **P0 安全越权 / 数据丢失** | **5** | 可被实际利用，不是理论风险 | ✅ **5/5 已修** |
| **P1 功能缺陷 / 越界操作** | **7** | 会导致操作对象错、权限模型与文档不符 | ✅ **7/7 已修** |
| **P2 安全姿态 / 可维护性** | **13** | 风险较低或暂不可达，但会持续咬人 | ✅ **10/13 已修** · 3 挂起（P2-3/9/12） |

**最危险的一条（已修）**：`wikis` claim（JWT 里唯一的授权维度）**只覆盖 `/api/wiki/` 一个前缀**。跨 wiki 搜索 `/api/search/cross` 和 wiki 目录 `/api/wikis` 完全在它之外 —— 实测一个**只授权 wiki-a 的 token 能读到 wiki-b 的机密内容**，而 `public_read` 默认 True ⇒ **连 token 都不用带**。→ commit `152a8297`

**最隐蔽的一条（已修）**：`_keyring.py` 的 JWT 签名密钥**不 honor `LLMWIKIFY_HOME`** —— auth.db / local_token / pat 都跟着隔离走，**只有密钥留在真实 HOME** ⇒ 隔离被打破。→ commit `9f9dd8f1`

**当前验证**：`tools/auth_defect_verify.py` → **4/4 NOT reproduced**；`tools/exploit_check_wikis_claim.py` 授权面 4/4 拦截。详见页首修复批注与 §4。

---

## 1. P0 · 安全越权 / 数据丢失

### P0-1 ★ `wikis` claim 只覆盖 `/api/wiki/` 前缀 ⇒ 跨 wiki 越权读

**位置**：`interfaces/server/http/middleware.py:450` `_check_wikis_claim()`

```python
if not path.startswith("/api/wiki/"):
    return None          # ← 其它所有路由直接放弃检查
```

**复现**（`tools/exploit_check_wikis_claim.py`，VERDICT: ★ 越权成立）：

| 请求 | 结果 |
|---|---|
| ① `GET /api/wiki/wiki-b/pages/secret.md`（token 只授权 wiki-a） | **403 forbidden_wiki** ✓ 拦住了 |
| ② `GET /api/search/cross?q=betasecret`（同一个 token） | **200，返回 wiki-b 的正文片段** ★ 越权 |
| ③ `GET /api/wikis` | **200，列出全部 wiki + 服务器绝对路径** ★ 泄漏 |
| ④ 同 ②，**完全不带 token** | **200，同样读到 wiki-b 的内容** ★ |

②的响应原文：
```json
{"results":[{"page_name":"secret","snippet":"# betasecret\n\nThis page contains betasecret content.\n",
  "wiki_id":"wiki-b","wiki_name":"Wiki B"}], ...}
```

**根因**：`interfaces/server/http/wiki/search_routes.py:30-31`
```python
wiki_ids = wikis.split(",") if wikis else None
results = registry.cross_wiki_search(q, wiki_ids, limit)   # None ⇒ 搜全部 wiki
```
`registry.py:432`：`target_wikis = wiki_ids or list(self._instances.keys())`

**影响**：授权模型的核心失效。`wikis=["wiki-a"]` 的 token 能读任意 wiki。

**修法方向**：把 `wikis` 检查从「按路径前缀」改成「按路由声明的 wiki 维度」—— 每个会碰 wiki 数据的端点显式声明 `wiki_id` 来源（query/body/registry），由中间件统一比对，而不是靠路径字符串猜。

---

### P0-2 ★ `public_read=True` 是默认值 ⇒ 未认证可读全部内容

**位置**：`interfaces/server/core.py:82`（`WikiServer.__init__` 默认 `public_read: bool = True`）→ `middleware.py:310`

```python
if request.method == "GET" and self.public_read:
    return await call_next(request)      # 无 token 直接放行
```

**实测**：上面 ④ —— 不带任何凭据，`GET /api/search/cross?q=betasecret` 返回 200 + wiki-b 的正文。

这是 decision 1 的显式设计（读开放、写需认证），但默认值是**开**的 ⇒ **任何一次部署，只要没显式关掉，wiki 内容就是公开的**。而 CLI/serve 路径里没有暴露对应的开关。

**修法方向**：`public_read` 默认为 `False`；或至少在非 loopback 绑定时强制关闭并在启动横幅里打印当前取值。

---

### P0-3 ★ 旧 schema 迁移**静默清空**用户表与 PAT 表

**位置**：`foundation/auth/db.py:130-137`（`UserRepository`）与 `db.py:327-334`（`ApiKeyRepository`，同一段逻辑复制了两份）

```python
if "password_hash" in columns:
    conn.executescript("DROP TABLE IF EXISTS api_keys; DROP TABLE IF EXISTS users;")
```

**实测**（`tools/auth_defect_verify.py` ②）：构造一个带 `password_hash` 的旧库（1 用户 + 1 PAT）→ 实例化仓库 → **users 1→0，api_keys 1→0，无任何提示、无备份**。

**影响**：从旧版 auth 升上来 ⇒ 所有用户与所有 PAT **静默消失**，且用户不会收到任何告警（只会在下次登录时发现"身份没了"）。

**修法方向**：改成 `ALTER TABLE ... DROP COLUMN` 或建新表 + 迁移数据；真要清库也必须先备份 + 打印明确告警。

---

### P0-4 ★ `LLMWIKIFY_HOME` 不覆盖 JWT 签名密钥 ⇒ 隔离被打破 ✅ **已修**

> **2026-11-11 复核：已修**（commit `9f9dd8f1`）。`_SECRET_FILE` 模块级常量改为
> `_secret_file()` 函数，经 `foundation.config.global_config_home()` 按**调用时**解析，
> 与同包其它三处一致。复现命令见 §5（原脚本的 `_SECRET_FILE` 已不存在）。
> 同型第 2、3 处也已修：`doctor_cmd.py:26` `CONFIG_PATH`、`foundation/config.py` 的
> `Config._home/_path`（commit `9c05ab3e`）。

**位置**：`foundation/auth/_keyring.py:48`

```python
_SECRET_FILE = Path("~/.llmwikify/jwt_secret").expanduser()   # ← 模块级常量，不看 LLMWIKIFY_HOME
```

对比同包其它三处**都 honor** `LLMWIKIFY_HOME`：`db.py:52`（`auth_db_path`）、`utils.py:85`（`local_token_path`）、`utils.py:115`（`pat_file_path`）。

**实测**：`LLMWIKIFY_HOME=/tmp/isolate` 时 ⇒ `auth.db`/`local_token`/`pat` 全在 `/tmp/isolate/.llmwikify/`，而 **`jwt_secret` 落到真实 HOME 的 `~/.llmwikify/jwt_secret`**。

**影响**：
- 以为"换了 HOME 就是另一套实例"，实际上**签名密钥是共享的** ⇒ 一个实例签的 JWT 在另一个实例也认。
- 测试/CI 用 `LLMWIKIFY_HOME` 隔离，密钥却污染开发者真实环境。
- 密钥文件的父目录 700 权限也加在真实 HOME 上。

**修法方向**：`_SECRET_FILE` 改成函数，按 `LLMWIKIFY_HOME` 动态解析（与其它三处一致）。

---

### P0-5 ★ `/api/wikis` 暴露全部 wiki 清单与服务器绝对路径

**位置**：`interfaces/server/http/wiki/registry_routes.py:29-35`

实测返回：
```json
{"wikis":[{"wiki_id":"wiki-a","name":"Wiki A","type":"local","root":"/tmp/wikis-xxx/a",
  "status":"ready","page_count":2,"is_default":true,"last_accessed":null,"error":null}, ...]}
```

**问题**：`root` 是**服务器文件系统绝对路径**；且该端点不在 `wikis` claim 校验范围，`public_read` 下**未认证即可读**。⇒ 泄漏目录结构 + wiki 清单，为后续攻击提供地图。

**修法方向**：对外只暴露 wiki_id / 名称 / 状态，隐藏 `root`；或纳入 `wikis` claim 校验。

---

## 2. P1 · 功能缺陷 / 越界操作

### P1-1 ★ `auto_first_admin()` 不检查是否已有 admin ⇒ CLI 可造多个管理员 ✅ **已修**

> **2026-11-13 修**：`auto_first_admin` 在已有 admin 时对**新邮箱**抛
> `AuthError(code="registration_closed")`（对齐 HTTP `/register`）；同邮箱仍幂等。
> 测试：`test_second_email_registration_closed_p1_1`、`test_init_second_email_rejected_p1_1`。

**位置**：`foundation/auth/db.py:260-282` —— 名字与 docstring 说"first admin"，实现只对**同邮箱**幂等：

```python
def auto_first_admin(email, *, db_path=None) -> User:
    repo = UserRepository(db_path=db_path)
    if repo.get_by_email(email) is not None:
        return repo.get_by_email(email)        # 只挡同邮箱
    return repo.create(email=email, is_first_admin=True)   # ← 永远 True
```

**实测**：连续 `auth init --email a@x` → `auth init --email b@x` ⇒ 数据库里 **2 个 `is_first_admin=1`**。

**与 HTTP 侧策略不一致**：`auth_routes.py:70-77` 的 `/register` 在有用户后正确返回 403 `registration_closed`。⇒ **CLI 侧是敞开的注册通道，HTTP 侧关着**。

### P1-2 ★ `create-token` 无法指定用户 ⇒ 靠 local_token 隐式决定归属 ✅ **已修**

> **2026-11-13 修**：加 `--user`（email → username → id 解析）；未知目标 exit 1。
> 给他人发 PAT **不覆盖**调用者的 `local_token`（P1-3 同规则）。
> 测试：`test_create_token_explicit_user_p1_2`。

**位置**：`interfaces/cli/commands/auth.py:136-163`

归属逻辑：① 从 `local_token` 解 `sub` 找用户；② 解不出就 `SELECT * FROM users LIMIT 1`（**第一个用户**）。

⇒ **没有 `--user` 参数**。给指定用户发 PAT 的唯一办法是**先 `auth init --email <对方>` 把 local_token 切成对方**（这又触发 P1-1 和 P1-3）。
⇒ 在**没有 local_token 的新机器**上跑 `create-token`，PAT 会发给**第一个用户**，不是你想给的人。

### P1-3 ★ `auth init` 覆盖 `local_token` ⇒ 把当前身份切走 ✅ **已修**

> **2026-11-13 修**：`_write_local_token` 仅在「无 token / 同用户 / `--force` / 不可读」时写入。
> `create-token` 同规则。测试：`test_init_keeps_foreign_local_token_p1_3`。

**实测**：先 `auth init --email you@x`（local_token = you 的 JWT），再 `auth init --email bob@x` ⇒ **local_token 变成 bob 的 JWT**，且输出里仍打印 "First admin created: bob@x"。

⇒ 「给同事建个号」这个动作会**顺手把你的登录态切成同事的**。

### P1-4 ★ `auth token` 永远签 `scope="write", wikis=["*"]`

**位置**：`interfaces/cli/commands/auth.py:321-326`

```python
claims = TokenClaims.new(sub=f"user:{user.id}", scope="write", wikis=["*"])
```

⇒ 任何本地用户跑一次 `auth token`，就拿到**全 wiki 写权限**的 owner 级 token（与该用户是不是 admin 无关）。

### P1-5 ★ `_derive_username` 不去重（docstring 说会去重） ✅ **已修**

> **2026-11-13 修**：`create()` 经 `_unique_username` 加 `_2`/`_3`…；并发 UNIQUE
> 包成 `AuthError(username_taken|email_taken)`。测试 `test_username_collision_gets_suffix_p1_5`。

**位置**：`foundation/auth/db.py:56-65`

```python
"""...users.username is auto-derived from email, with collisions suffixed."""
local, _, _ = email.partition("@")
safe = "".join(...).lower()
return safe[:64] or "user"        # ← 没有任何去重/加后缀
```

**实测**（`tools/auth_defect_verify.py` ④）：`alice@example.com` → username `alice`；再 `alice@other.com` ⇒ **抛裸 `sqlite3.IntegrityError: UNIQUE constraint failed: users.username`**（不是 `AuthError`，没有友好报错、没有可诊断信息）。

### P1-6 ★ 重复 `auth init` 每次都新增一个同名 PAT ✅ **已修**

> **2026-11-13 修**：`ApiKeyRepository.find_active(user, name)`；有活跃同名 PAT 则复用。
> CLI 用 `cli-init`，交互 prompt 用 `init`。复现脚本该探针现报 NOT reproduced。

**实测**（`tools/auth_defect_verify.py` ③）：同邮箱跑 3 次 ⇒ **3 个 PAT，名字全是 `cli-init`**。`auto_first_admin` 对用户幂等，但 PAT 不幂等 ⇒ 反复 init 会堆积无法区分的凭据。

### P1-7 ★ 本地模式下 `/api/auth/me` 对无效凭据返回 200 ⇒ 前端永远不清登录态 ✅ **已修**

> **2026-11-13 修**：`/me` 同时读 cookie 与 `Authorization: Bearer`；无效 Bearer → 401。
> `ProtectedRoute` 带 Bearer 校验，`!r.ok` 或 `authenticated===false` 时 `clearToken`。
> 复现脚本该探针现报 NOT reproduced。

**位置**：`interfaces/server/http/auth_routes.py:297-317` + `ui/webui/src/components/auth/ProtectedRoute.tsx:20-25`

```python
# 后端：本地模式 + 无 cookie
if not llmwikify_token:
    if local_mode:
        return {"authenticated": False, "user": {...,"local_mode": True}}   # ← HTTP 200
    raise HTTPException(401, ...)
```
```tsx
// 前端
fetch('/api/auth/me').then((r) => { if (!r.ok) clearToken(); })   // 200 ⇒ 永远不 clear
```

**实测**（`tools/auth_defect_verify.py` ①，host=127.0.0.1）：`GET /api/auth/me` → **HTTP 200, `authenticated: false`**。

⇒ 过期/失效的 token 会一直留在 localStorage，界面显示"已登录"，但写操作全部 403 ⇒ **排查成本极高**。另外该校验请求**没带 `Authorization` 头**（前端 `api.ts` 里的封装带了，这里用的是裸 `fetch`）。

---

## 3. P2 · 安全姿态 / 可维护性

> **2026-11-13**：P2-1/2/4/5/6/7/8/10/11/13 + 文档漂移已修（见页首修复批注）。
> 仍开放：P2-3（logout 吊销）、P2-9（有意保留）、P2-12（schema 性能）。

| # | 问题 | 位置 | 说明 |
|---|---|---|---|
| P2-1 | JWT 与 PAT 双份明文存 `localStorage` | `ui/webui/src/stores/authStore.ts:39-45`（zustand persist 含 `token`）、`components/auth/LoginPage.tsx:69-74`（`localStorage.setItem('llmwikify_pat', ...)`） | 任何 XSS 可窃取 30 天有效的写权限凭据。cookie 已是 `httponly`，前端却又存一份 ⇒ **最弱的环节决定安全性** |
| P2-2 | cookie `secure=False` | `auth_routes.py:212` | decision 6 的 MVP 取舍；非 loopback + HTTP 部署时 cookie 可被中间人截获 |
| P2-3 | `auth logout` 只删本地文件，不吊销凭据 | `cli/commands/auth.py:378-386` | JWT 无状态、无服务端撤销表 ⇒ 30 天内该 token 仍然有效（若被复制过） |
| P2-4 | CORS `allow_origins=["*"]` + `allow_credentials=True` | `interfaces/server/core.py:484-490` | 浏览器会因 `*` + credentials 拒绝发送凭据，实际风险被浏览器部分抵消，但配置本身是矛盾组合 |
| P2-5 | `expires_at` 用字符串比较 | `db.py:412` `expires_at > datetime('now')` | 当前无人写入该字段（恒为 NULL），但若将来写 ISO 格式（`2026-12-01T00:00:00Z`），`'T' > ' '` ⇒ **同年日期一律判为未过期** |
| P2-6 | `_atomic_write` 的两处 docstring 自相矛盾 | `db.py:83-85`（说 "tempfile+rename"）vs `db.py:110-117`（说 "We do NOT use the tempfile+rename trick"） | 实现是普通事务；类 docstring 描述的是不存在的行为 |
| P2-7 | `touch_last_login` 从未被调用 | `db.py:234` | `users.last_login_at` 恒为 NULL ⇒ 字段是死的 |
| P2-8 | 错误提示指向不存在的端点 | `middleware.py:446` "POST /auth/login first" | 实际只有 `/auth/register` `/auth/verify` `/auth/tokens` `/auth/me` `/auth/logout`，**没有 `/auth/login`** |
| P2-9 | `is_local_default(None) == True` | `foundation/auth/utils.py:52-53` | host 未指定 ⇒ 判定为本地可信 ⇒ 绕过鉴权 |
| P2-10 | `decode()` 不校验 `iss` | `foundation/auth/_jwt.py:121-126` | 只传了 `audience=`，没传 `issuer=` ⇒ 签发的 `iss` claim 从不被验证 |
| P2-11 | `create()` 的 check-then-insert 非原子 | `db.py:207-224` | 并发同邮箱 ⇒ UNIQUE 冲突抛裸 `IntegrityError`（同 P1-5 的暴露方式） |
| P2-12 | 每次实例化都跑一遍 `_init_schema` | `db.py:90` / `db.py:310` | 每次 `UserRepository()` / `ApiKeyRepository()` 都执行 `PRAGMA table_info` + `executescript`，且迁移判定与建表耦合在一起 |
| P2-13 | CLI 调私有方法取数据 | `cli/commands/auth.py:155` / `:311` / `serve.py:223` | `repo._connect().execute("SELECT * FROM users LIMIT 1")` —— 越层用私有 API，且绕过了 `get_by_*` 的语义 |

**另有一处文档漂移**：`middleware.py:247` 的 docstring 说支持 `?token=<X>` 查询参数回退，但 `_extract_token()`（`:363-371`）**只认 cookie 和 `Authorization: Bearer`** ⇒ 该回退路径不存在。

---

## 4. 缺陷分布与建议修序

| 子系统 | P0 | P1 | P2 | 小计 |
|---|---:|---:|---:|---:|
| 中间件 / 授权 | 3 | 0 | 2 | 5 |
| HTTP 路由 | 2 | 0 | 1 | 3 |
| `foundation/auth/db.py` | 2 | 3 | 4 | 9 |
| `foundation/auth/_keyring.py` | 1 | 0 | 0 | 1 |
| CLI | 0 | 4 | 1 | 5 |
| WebUI | 0 | 1 | 1 | 2 |

**建议修序（已执行，2026-11-13）**

1. ✅ **P0-1 / P0-2 / P0-5**（授权面）—— `wikis` 校验扩路由 + `public_read` 回环语义（`152a8297`）
2. ✅ **P0-4**（密钥随 HOME 走）—— `9f9dd8f1`
3. ✅ **P0-3**（迁移清库）—— `02e3f36c`
4. ✅ **P1-1 / P1-2 / P1-3** CLI 组 —— `52dc305e`
5. ✅ **P1-4 / P1-5 / P1-6 / P1-7** + P2 十项 + 文档漂移 —— `d21289b1` `a5918fe3`

**仍挂起**：P2-3（logout 吊销，需 denylist）、P2-9（有意保留，decision 13）、P2-12（schema 性能）。

**验证方式**：P0-1 用 `tools/exploit_check_wikis_claim.py`（现 4/4 拦截）；其余用 `tools/auth_defect_verify.py`（现 4/4 NOT reproduced）。

---

## 5. 复现命令

两个脚本已入库，全部状态（配置 home、wiki 根、JWT 密钥）建在临时目录里，
**不碰开发者真实的 `~/.llmwikify`**（先设 `$LLMWIKIFY_HOME`）。在仓库根目录执行：

```bash
# P0-1 / P0-2 / P0-5：wikis claim 越权 + 未认证可读 + wiki 目录泄漏
python tools/exploit_check_wikis_claim.py
#   修复后：4/4 探针均被拦截（①②③④ 不再复现越权/泄漏/未认证读）
#   修复前：VERDICT: 3 of 4 probes reproduced（②③④ 曾成立）

# P1-5 / P1-6 / P0-3 / P1-7：四条断言
python tools/auth_defect_verify.py
#   修复后：VERDICT: 4 of 4 probes did NOT reproduce
#   修复前：VERDICT: ALL CONFIRMED (4/4)
```

退出码：`0` = 按预期复现（缺陷成立）/ 脚本语义见文件头；`1` = 未复现；`2` = 脚本自身跑不起来。
**修复后跑应看到「NOT reproduced」**（exit 1）——这是预期结果，不是脚本坏了。

> **P1-7 的复现注意**：`/api/auth/me` 分支依赖 `is_local_default(request.url.hostname)`。
> 用 `fastapi.testclient.TestClient` 时默认 Host 是 `testserver`（非回环）→ 走 401 分支。
> 脚本用 `TestClient(app, base_url="http://127.0.0.1")` 绕开，等价于真机上 `curl127.0.0.1`。
> 现探针语义已改为：**无效 Bearer 必须 401**（P1-7 修复后的正确行为）。

---

## 6. 边界声明

- **审计轮（2026-11-10）只读**：当时仓库业务代码零改动；复现脚本后入库 `tools/`。
- **修复轮（2026-11-11 / 11-13）已改业务代码**，见页首三段修复批注与 §4。
- 两个脚本的全部状态建在临时目录，不碰开发者真实 `~/.llmwikify`。
- 结论基于 `main @ 3e09b0c3` 起审；**2026-11-13 按修复后 `main` 复验**：
  P0 5/5、P1 7/7、P2 10/13 已修，0 误报；探针 4/4 NOT reproduced。
- `proxy/v0.41-dev @ 582a7203` 上 auth 部分是否已修**未核**（该分支未合并）。
- 完整会话报告：`docs/summaries/2026-11-13-platform-config-auth-report.md`。
- 本清单**不含**未做的功能（B8 已实现，见 §0 更正）；这里列的全是**已实现代码里的缺陷**。
