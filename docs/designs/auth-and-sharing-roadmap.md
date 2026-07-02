# llmwikify Auth & Sharing Roadmap

> **方案锁定时间**: 2026-07-02
> **当前 phase**: Phase 2 (auth foundation)
> **预估完成**: 2026-07-31 (4 周内全部 4 phase 落地)
> **跟 AGENTS.md 的关系**: 8 原则受 Karpathy 启发。本文把"先沟通、再实施"原则用到极致,所有改动前先用本文对齐。
>
> **Architecture 层依赖** (G+Y 重构后):
> ```
> interfaces  →  apps, kernel, foundation
> apps        →  foundation, kernel
> kernel      →  foundation
> foundation  →  (self only)
> (reproduction 独立 sibling, 通过 interfaces/ 暴露)
> ```

## 0. 目标(从用户问答锁定)

| 维度 | 决定 |
|---|---|
| 鉴权层级 | 多用户 + PAT(每人独立 token,无密码) |
| 入口覆盖 | 本地 CLI + Web/MCP/REST 远端均鉴权 |
| session 隔离 | session 绑 user_id(Notion 模式),Phase 2 不动 chat DB |
| 存储位置 | `~/.llmwikify/auth.db`(独立 SQLite) |
| 默认行为 | `public_read=True`(本地开发友好) |
| **本地模式写权限** | **完全开放(localhost 信任)** — 任何 localhost 用户都能 POST/PUT/DELETE |
| **本地 vs 对外触发** | **host 检测**:`--host 127.0.0.1`/loopback = local(无 auth),非 loopback = public(强制 auth) |
| **serve 默认 host** | **读 env var `LLMWIKIFY_HOST`,缺省 `127.0.0.1`** |
| **auto-init 触发** | `serve` 时检测 host + 缺失 `auth.db` 时,自动交互 prompt first admin(email + password) |
| **TTY 不可用 fallback** | print hint `请运行 llmwikify auth init` + exit 1 |
| **认证方式** | **PAT (Personal Access Token)** — `llmw_` 前缀 + 24 字节 hex,SHA-256 hash 存储,无密码 |
| **WebUI 鉴权库** | **无** — 直接用 PAT 验证 + JWT 签发,不需要 fastapi-login |
| **CLI 交互 prompt** | **stdlib `input()`** — 只 prompt email,无密码 |
| **CLI OOB pairing** | stdlib `http.server` + `webbrowser` (Phase 2b) |
| **Cookie/session** | 自定义 JWT-in-httpOnly-cookie(fastapi-login `cookie_manager`) |
| 无感知机制 | A1 (本机 OOB token) + A2 (30d 长寿 access token) |
| 启动模式 | 本地账号(Phase 2),OIDC 留 Phase 3 |
| WebUI Login | MVP 包含(Phase 2 后期) |
| share 保护 | scope=read JWT,无独立路由 |
| share 渲染 | 路径 A(server 不渲染,WebUI 复用 react-markdown) |
| 复杂度 | PyJWT + PAT (SHA-256 stdlib) + YAGNI |
| keyring fallback | hard fail + 明确提示 |
| Passkey 预留 | 不加 stub |
| share 默认 exp | 7 天 |
| share 主动 revoke | 要 |
| 中央 hub 形态 | C 混合(官方 SaaS + 可自部署),email 作 handle |
| Phase 2 users.username | 加,可空,自动派生 |

---

## 1. Phase 2 — 基础鉴权(~1100 行, 3 commits, 2 天)

### 1.1 18 个决策点(锁定)

| # | 决策 | 锁定答案 |
|---|---|---|
| 1 | public_read 路径覆盖 | GET 公开 / POST/PUT/DELETE 403 / WS 始终要 / agent 始终要 |
| 2 | `--auth-token` 兼容 | 方案 B:把 secret 当 JWT signing secret |
| 3 | cookie vs bearer | 双轨:浏览器自动 cookie,CLI/curl 用 `Authorization: Bearer` |
| 4 | scope 判定 | HTTP method(GET=read)+ 例外表 |
| 5 | JWT 过期 | 30d 后重新 login,无 silent refresh |
| 6 | cookie secure | 默认 False(MVP 本地开发友好),CLI 警告 HTTPS |
| 7 | wikis claim | 逐个显式列举(α):auth init 签当前 wiki 列表 |
| 8 | rate limit | IP-based,跟现状一致 |
| 9 | local_token 文件 | chmod 600 在 init / token 写时 |
| 10 | 错误统一 | JSON `{error, status_code, detail}` |
| 11 | auth.db 位置 | `~/.llmwikify/auth.db` |
| **12** | **本地模式写权限** | **完全开放(localhost 信任)** — 不强制 auth |
| **13** | **serve 默认 host** | **读 env `LLMWIKIFY_HOST`,缺省 `127.0.0.1`** |
| **14** | **auto-init 触发** | serve 检测 host + `auth.db` 缺失 → 交互 prompt first admin |
| **15** | **TTY fallback** | print hint + exit 1 |
| **16** | **password hash** | **Argon2id** (t=3, m=64MB, p=4) — memory-hard 抗 GPU |
| **17** | **WebUI 鉴权库** | **fastapi-login** `LoginManager` — 节省 ~100 LoC 机械代码 |
| **18** | **CLI prompts** | **stdlib `input()` + `getpass.getpass()`** + TTY fallback |
| **19** | **WebUI Login 形式** | **独立页面 `/login`** — 全屏居中卡片,首次访问直接看到 |
| **20** | **Token 持久化** | **localStorage** — 关闭浏览器后仍登录,工具类产品 |
| **21** | **Device pairing** | **跳过 X2 (MVP)** — 留 Phase 3+ 再做 |
| **22** | **AuthInitBanner** | **独立组件** — 检测 local_mode=true 时不显示 |
| **23** | **VITE_API_TOKEN** | **保留为 fallback** — authStore 优先,兼容 CI/CD |
| **24** | **WebSocket auth** | **Query param `?token=xxx`** — 浏览器 WS 不支持自定义 headers |
| **25** | **认证方式** | **PAT (Personal Access Token)** — 一步到位删密码,token 即凭证 |
| **26** | **PAT 格式** | `llmw_` 前缀 + 24 字节 hex = 51 字符,SHA-256 hash 存储 |
| **27** | **PAT 存储** | `api_keys` 表 (id, key_prefix, key_hash, user_id, name, scopes, created_at, last_used_at, expires_at, revoked_at) |
| **28** | **密码处理** | **完全删除** — users 表删 password_hash 列,移除 argon2-cffi 依赖 |

### 1.2 文件清单

**新增 (8 文件, L1 + L4)**:

```
src/llmwikify/foundation/auth/
├── __init__.py                                       30  re-export
├── _jwt.py        (TokenClaims + PyJWT 包装 + scope/wikis)  30
├── db.py          (SQLite auth.db + UserRepository + Argon2id hash/verify + auto_first_admin)  130
└── _keyring.py    (keyring get/set, hard fail)        35

src/llmwikify/interfaces/server/http/
└── auth_routes.py    (POST /auth/login + GET /auth/me  via fastapi-login LoginManager)  60

src/llmwikify/interfaces/cli/commands/
├── auth.py            (auth init/token/whoami/logout + local_token inline)  130
└── serve.py           (LLMWIKIFY_HOST 解析 + auto-init prompt via stdlib input/getpass)  +60
```

**改动 (4 文件)**:

```
interfaces/server/http/middleware.py  +35  JWTAuthMiddleware (替换 AuthMiddleware,带 local-mode 旁路)
interfaces/server/http/routes.py       +5   register auth router
interfaces/server/core.py             +15  WikiServer(public_read=True, require_auth=auto, ...)
pyproject.toml                         +3   pyjwt + fastapi-login + argon2-cffi + keyring (从 dev 移 prod)
```

**测试 (~480 行)**:

```
tests/test_foundation_auth.py        150  6 tests (含 Argon2id hash/verify + rehash check)
tests/test_interfaces_auth.py        130  3 tests (集成)
tests/test_cli_auth.py                80  4 tests
tests/test_cli_serve_auth.py         120  4 tests (host 检测 + auto-init + TTY fallback)
```

### 1.3 JWT + claims

```python
@dataclass
class TokenClaims:
    sub: str                 # "user:<uuid>" | "share:<uuid>"  (subject)
    scope: str               # "read" | "write"
    wikis: list[str]         # 显式列表, ["*"] 表示通配
    aud: str = "llmwikify"
    iss: str = "llmwikify.local"
    exp: int                 # unix timestamp
    iat: int
```

### 1.4 auth.db schema (`~/.llmwikify/auth.db`)

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,                -- uuid4 hex (16 字符随机)
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE,                -- NULL OK, hub URL @handle 来源,email 派生
    password_hash TEXT NOT NULL,        -- argon2id $argon2id$v=19$m=65536,t=3,p=4$...
    is_first_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_username ON users(username);
```

### 1.5 数据流

```
F0 (server start,host 解析):
    host = os.environ.get("LLMWIKIFY_HOST", "127.0.0.1")
    if is_loopback(host): mode = "local"   # 无 auth
    else:                 mode = "public"  # 强制 auth

F1 (auth init,CLI): 邮箱 → Argon2id hash → keyring set secret → users 插入
                      → 扫描 registry → 签 JWT(wikis=[<current>]) → 写 local_token

F2 (serve,public 模式无 auth.db): 检测 → prompt first admin
                                   → TTY 检查(决策 15) → stdlib input + getpass
                                   → 调用 auto_first_admin()
                                   → auth.db 创建 + keyring 设置 + owner JWT 签发
                                   → 输出 token 给 user
                                   → 继续启动 server

F3 (serve,local 模式): JWTAuthMiddleware 旁路或 NOP(决策 12)
                       → public_read=True 默认
                       → GET/POST/PUT/DELETE 都 OK(localhost 信任)

F4 (browser GET public):    无 token + GET → 200
F5 (browser POST):          无 token + POST + public mode → 403
F6 (browser login):         POST /auth/login → Set-Cookie httpOnly + JWT (via fastapi-login)
F7 (CLI auth token):        读 keyring → 签新 JWT → 写 local_token
F8 (--auth-token 兼容):     旧 string 当 JWT secret 用
F9 (wikis add 续签):        如果 local_token 30d 内 → 自动 re-sign 新 wikis 列表
```

### 1.6 3 个 commit 序列(Phase 2a)

```
commit 1: feat(auth): 基础鉴权基础设施 (PyJWT + Argon2id + keyring + login/middleware)
  L1 4 个文件 + L4 auth_routes + 3 个 server 改 + pyproject
  +fastapi-login (LoginManager + cookie_manager)

commit 2: feat(cli): auth init/token/whoami/logout + serve host 检测 + auto-init prompt
  cli/auth.py + cli/serve.py (env LLMWIKIFY_HOST 解析 + stdlib input/getpass)

commit 3: tests + 设计文档增补
  4 个 test 文件 + 本文档(已存在,无需新增)
```

### 1.7 不在 Phase 2 范围 (显式)

- Refresh token + silent refresh
- WebAuthn / Passkey
- RBAC(`is_first_admin` 字段保留,但 MVP 不实现 ACL)
- OIDC
- Share tokens / share API
- Remote wiki client 只读强制
- WebUI Login 页面(Phase 3 补)

### 1.8 风险与缓解

| 风险 | 缓解 |
|---|---|
| keyring 没 daemon | hard fail + 提示装 `gnome-keyring-daemon` |
| 现有 `--auth-token=xxx` 用户 | 兼容:xxx 作 secret,MVP 可用 |
| python-jose vs PyJWT | 用 PyJWT (PyJWT 更新更活跃) |
| **Argon2id 参数过于激进** | 标准 t=3/m=64MB/p=4 在现代机器上 ~50ms/次,登录路径 <100ms,可接受 |
| **Argon2id 在低配机器上慢** | 启动时 measure 一次,>1s 时 warn 但不 fail(让用户决定) |
| **bcrypt 用户(若有测试 fixture)** | Phase 2 fresh start,无迁移负担;若以后需要 `verify_and_update` 渐进迁 |
| **fastapi-login 18+ 月 dormant** | API stable,zero runtime deps,transitive 用 PyJWT;主体代码我们手写,风险隔离 |
| **本地模式意外暴露** (--host 0.0.0.0) | 启动 banner 大字显示 `Network mode: bound to 0.0.0.0, auth ENFORCED` |
| **serve TTY 不可用** (CI / docker) | 决策 15 fallback:print hint + exit 1,不强交互 |
| **auto-init 中 Ctrl-C 中断** | signal handler 清理 partial auth.db(原子写:tempfile + rename) |
| **device pairing 临时 server 端口冲突** (Phase 2b) | CLI 随机选 8976-8999,失败重试 |
| JWKS endpoint 缺失 | Phase 3 OIDC 时加 |
| 密码 brute force | 5 次/分钟 in-memory counter,Phase 3+ 升级 |
| `local_token` 文件被读 | chmod 600 + warn if > 600 |
| HTTPOnly cookie + CSRF | SameSite=Lax |

### 1.9 验证步骤

```bash
# 单测
python3 -m pytest tests/test_foundation_auth.py tests/test_interfaces_auth.py tests/test_cli_auth.py tests/test_cli_serve_auth.py -v
# 预期 17 passed

# 架构 linter
python3 scripts/check_architecture.py     # 0 violation

# ruff
python3 -m ruff check src/llmwikify/foundation/auth/ src/llmwikify/interfaces/cli/commands/auth.py src/llmwikify/interfaces/cli/commands/serve.py src/llmwikify/interfaces/server/http/auth_routes.py src/llmwikify/interfaces/server/http/middleware.py

# 端到端冒烟:
# 1) 本地模式(无 auth)
rm -f ~/.llmwikify/auth.db ~/.llmwikify/local_token
llmwikify serve --web --port 8765 &
sleep 2
curl -i http://localhost:8765/api/wiki/pages | head -1   # 200 (local trust)
curl -i -X POST http://localhost:8765/api/wiki/pages -d '{}' | head -1   # 200 (local trust)
kill %1

# 2) Public 模式(需 auth)
rm -f ~/.llmwikify/auth.db
LLMWIKIFY_HOST=0.0.0.0 llmwikify serve --web --port 8765   # 触发交互 prompt
# 输入 email + password 两次
# 输出 token + 启动 server
sleep 2
TOK=$(echo "<your-token>")
curl -i http://<server-ip>:8765/api/wiki/pages | head -1   # 200 (public_read)
curl -i -X POST http://<server-ip>:8765/api/wiki/pages -d '{}' | head -1   # 403 (无 token)
curl -i -H "Authorization: Bearer $TOK" -X POST http://<server-ip>:8765/api/wiki/pages -d '{}' | head -1   # 200/201
```

---

## 1.10 Phase 2.5 — 无密码 PAT 认证(~560 行, 5 commits, 1 天)

### 1.10.1 决策 25-28(锁定)

| # | 决策 | 锁定答案 |
|---|---|---|
| 25 | 认证方式 | **PAT (Personal Access Token)** — 一步到位删密码,token 即凭证 |
| 26 | PAT 格式 | `llmw_` 前缀 + 24 字节 hex = 51 字符,SHA-256 hash 存储 |
| 27 | PAT 存储 | `api_keys` 表 (id, key_prefix, key_hash, user_id, name, scopes, created_at, last_used_at, expires_at, revoked_at) |
| 28 | 密码处理 | **完全删除** — users 表删 password_hash 列,移除 argon2-cffi 依赖 |

### 1.10.2 Schema 变更

```sql
-- users 表: 删除 password_hash
CREATE TABLE users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    username TEXT UNIQUE,
    is_first_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_login_at TEXT
);

-- 新增 api_keys 表
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,                    -- uuid4 hex
    key_prefix TEXT NOT NULL,               -- 前 8 字符: "llmw_a1b2"
    key_hash TEXT UNIQUE NOT NULL,          -- SHA-256(pat)
    user_id TEXT NOT NULL REFERENCES users(id),
    name TEXT,                              -- "laptop", "ci-pipeline"
    scopes TEXT NOT NULL DEFAULT 'write',   -- "read" | "write"
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    expires_at TEXT,                        -- NULL = 永不过期
    revoked_at TEXT                         -- NULL = 有效
);

CREATE INDEX idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX idx_api_keys_user ON api_keys(user_id);
```

### 1.10.3 认证流程

```
CLI 创建用户:
  llmwikify auth create-token --name "laptop"
  → prompt email (仅首次)
  → 生成 PAT (llmw_xxxxxxxxxxxx...)
  → SHA-256 hash 存 api_keys 表
  → 显示 token 一次
  → 保存到 ~/.llmwikify/local_token

WebUI 首次:
  GET /auth/me → 401
  显示 "Get Started":
    方式 A: "粘贴 token" → POST /auth/verify → 签 JWT → session
    方式 B: "创建账号" → 输入邮箱 → POST /auth/register → 返回 PAT → 存 localStorage

分享:
  llmwikify share create main --expires 7d
  → scope=read JWT (share token)
  → recipient 直接用, 不需要 PAT
```

### 1.10.4 文件清单

**新增 (1 文件)**:
```
foundation/auth/_pat.py       60  generate_pat / hash_pat / verify_pat
```

**改动 (9 文件)**:
```
foundation/auth/db.py          +40/-30  api_keys 表 + ApiKeyRepository + 删 password_hash
foundation/auth/utils.py       -50      删 hash_password / verify_password / needs_rehash / _PH
foundation/auth/prompt.py      -40      删密码 prompt,只保留 email
foundation/auth/__init__.py    +5/-10   更新 re-export
interfaces/server/http/auth_routes.py  +80/-30  PAT 路由 + /auth/register + /auth/verify
interfaces/server/http/middleware.py    +20      PAT 验证
interfaces/cli/commands/auth.py         +60/-20  create-token / list-tokens / revoke-token
pyproject.toml                          -1       删 argon2-cffi
ui/webui/src/components/auth/LoginPage.tsx  +30/-40  无密码登录
ui/webui/src/types/auth.ts             -5       删 password
```

**删除依赖**:
```
argon2-cffi  (从 pyproject.toml 移除)
```

### 1.10.5 5 个 commit 序列

```
commit 1: feat(auth): PAT 替代密码 — schema + utils + prompt 简化
  db.py (api_keys 表 + drop password_hash) + _pat.py + utils.py + prompt.py + __init__.py
  + 删除 argon2-cffi 依赖

commit 2: feat(auth): PAT 路由 + middleware 验证
  auth_routes.py + middleware.py

commit 3: feat(cli): auth create-token/list-tokens/revoke-token
  commands/auth.py

commit 4: feat(ui): WebUI 无密码登录 — token 粘贴 + 创建账号
  LoginPage.tsx + types/auth.ts

commit 5: tests + design doc 更新
  更新 4 个 auth 测试文件 + 本文档
```

---

## 2. Phase 3 — Share + Remote Wiki(~915 行, 4 commits, 8 天)

### 2.1 文件清单

**新增 (3 文件)**:

```
src/llmwikify/foundation/auth/
├── _share_jwt.py              50  share JWT (scope=read) generator with custom exp
└── _share_db.py               90  share_tokens 表 CRUD + blocklist

src/llmwikify/interfaces/server/http/
└── share_routes.py            155  GET /share/{slug} 服务端 + 只读 API

src/llmwikify/interfaces/cli/commands/
└── share.py                   150  share create/list/revoke
```

**改动 (3 文件)**:

```
src/llmwikify/kernel/multi_wiki/remote.py         +30  scope=read 禁 POST/PUT/DELETE
src/llmwikify/interfaces/cli/commands/wikis.py    +25  add --share-url / --share-token
ui/webui/src/App.tsx                              +10  /share/:slug 公开 route
ui/webui/src/components/shared/PageView.tsx       +30  复用 react-markdown
ui/webui/src/lib/api.ts                           +10  share token from URL 自动注入 Bearer
```

**测试 (~200 行)**:

```
tests/test_auth_share.py                            200  8 tests
tests/test_auth_remote.py                           100  4 tests
ui/webui/src/__tests__/ShareView.test.tsx           50  2 tests (前端 jest)
```

### 2.2 share_tokens schema

```sql
-- 在 auth.db 加 1 张表
CREATE TABLE share_tokens (
    id TEXT PRIMARY KEY,                -- jti (JWT ID),uuid4 hex
    token_hash TEXT UNIQUE NOT NULL,    -- sha256(token),不存原 JWT
    wiki_id TEXT NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at TEXT NOT NULL,           -- 默认 7d,可 --no-exp
    revoked_at TEXT,                    -- 主动 revoke 时间
    password_hash TEXT,                 -- --password 时 bcrypt,可选
    view_count INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TEXT
);

CREATE INDEX idx_share_tokens_jti ON share_tokens(id) WHERE revoked_at IS NULL;
CREATE INDEX idx_share_tokens_wiki ON share_tokens(wiki_id);
```

### 2.3 强制只读(3 层)

| 层 | 强制点 |
|---|---|
| RemoteWiki client | scope=read 时,所有 POST/PUT/DELETE 抛 `ReadOnlyShareError` |
| WikiInstance | `readonly` 字段,writes raise `PermissionError` |
| share_routes.py | 即便带 JWT(scope=write),`/api/share/*` 拒绝非 GET |

### 2.4 CLI

```bash
llmwikify share create main-research --expires 7d [--password ...] [--no-exp]
llmwikify share list
llmwikify share revoke <jti>
llmwikify wikis add alice-research --share-url "https://alice.com/share/<slug>?token=<jti>"
```

### 2.5 4 个 commit 序列

```
commit 4: feat(auth): share JWT(scope=read) + share_tokens 表 + revoke CLI
commit 5: feat(server): /share/{slug} API + wikis add --share-url
commit 6: feat(webui): ShareView 复用 react-markdown + token 自动捕获
commit 7: feat(kernel): RemoteWiki 强制只读 + scope=read JWT 注入
```

### 2.6 不在 Phase 3 范围

- Server 端 markdown → HTML(留给 phase 4 if needed)
- Email share
- 自定义 slug
- Per-page 公开标志(Phase 4 才加)

---

## 3. Phase 4 — Central Hub Publishing(~600 行 client + 独立 hub 仓库, 1.5 周)

### 3.1 部署形态

- 官方 SaaS: `hub.llmwikify.com`(owner: 项目方)
- 可自托管: 开源仓库 `llmwikify-hub`,`docker compose up` 启动
- 客户端配置 `~/.llmwikify/llmwikify.json` 加 `hub.oauth` section

### 3.2 客户端文件清单(本仓库)

**新增 (5 文件, L1 + L4)**:

```
src/llmwikify/foundation/hub/                ← L1,新子包
├── __init__.py                                15
├── config.py      (hub URL + token 解析)      50
├── client.py      (HTTP client + OAuth 握手)  200
└── packager.py    (扫 wiki public pages)       120

src/llmwikify/interfaces/cli/commands/
└── publish.py     4 子命令:login/list/update/remove  200
```

**改动 (1 文件)**:

```
src/llmwikify/interfaces/cli/commands/wikis.py     +20  hub_account 关联
```

**测试 (~150 行)**:

```
tests/test_foundation_hub.py         100  6 tests
tests/test_cli_publish.py             50  3 tests
```

### 3.3 OAuth 流程

```
client → hub:
  GET /hub/oauth/authorize?client_id=llmwikify-cli&redirect_uri=cli-cb&scope=publish:write
       ↑ browser
  user: 登录 + authorize
       ↓
  302 → cli-cb?code=xxx&state=yyy
client → hub:
  POST /hub/oauth/token  {code, client_id, client_secret}
       ↓
  {access_token, refresh_token, expires_in}
client: 存 ~/.llmwikify/hub_tokens.json
```

### 3.4 publish 命令

```bash
llmwikify publish login --to hub.llmwikify.com        # OAuth flow,开 browser
llmwikify publish main-research --to hub.llmwikify.com  # 推
llmwikify publish list
llmwikify publish update main-research
llmwikify publish remove main-research
```

### 3.5 Page-level visibility

```yaml
# page frontmatter 加字段
---
title: "..."
public: true    # NEW,publish 时只推 public:true 的
---
```

### 3.6 Hub 服务端独立仓库 (`llmwikify-hub`)

```
llmwikify-hub/                           ← NEW REPO
├── src/hub_server/        FastAPI
├── src/oauth/             OAuth provider
├── src/publishes/         publishes API
├── src/explore/           SSR browse + 搜索 (FTS)
├── src/admin/             后期 admin
├── docker-compose.yml     (Postgres + Redis + Nginx)
└── deploy/cloudflared/    官方 SaaS 部署
```

### 3.7 4 个 commit 序列(client 部分)

```
commit 8: feat(foundation): hub config + HTTP client + OAuth handshake
commit 9: feat(foundation): publish packager + page-level public flag resolver
commit 10: feat(cli): publish login/update/list/remove
commit 11: docs(hub): 中央知识库分享设计
```

### 3.8 Phase 4 不影响 Phase 2/3

- Phase 4 hub 用 **独立 OAuth token**,不复用本地 JWT(scope=write 给 hub 也得走 OAuth 换新 token)
- `~/.llmwikify/hub_tokens.json` 独立文件,不污染 auth.db
- 推的内容是 `public:true` pages 副本,hub 端持久存

---

## 4. 三 Phase 总览

| Phase | 提交数 | 客户端 LoC | 独立仓 | 时间 |
|---|---|---|---|---|
| Phase 2 (now) | 3 | ~895 | — | 2 天 |
| Phase 3 | 4 | ~915 | — | 8 天 |
| Phase 4 | 4 | ~600 | llmwikify-hub (~3000+ LoC) | 1.5 周 |
| **总计** | **11 client commits** | **~2410 客户端** | **hub 服务端** | **~4 周** |

---

## 5. 跨 phase 共用

| 复用点 | 用在哪 |
|---|---|
| `foundation/auth/jwt.py` encode/decode | Phase 2/3 都用,Phase 3 加 `scope=read` 选项 |
| `auth.db` users table | Phase 2 加,Phase 4 加 username email-link |
| `local_token` | Phase 2 OOB,Phase 3 wikis add 自动续签 |
| EXCLUDED_AUTH_PATHS | Phase 2 加 share/oidc 路由,Phase 3 加公开 share |

---

## 6. 安全护栏汇总 (跨 phase)

| 威胁 | 防护阶段 |
|---|---|
| 无 token 写 | Phase 2 (scope=write) |
| share link 抓取 | Phase 3 (token 32B 随机) |
| share 永久泄露 | Phase 3 (revoke 表 + exp) |
| 远程 wiki 误写 | Phase 3 (3 层只读) |
| XSS 取 cookie | Phase 2 (httpOnly) |
| 浏览器劫持 | Phase 2 (SameSite=Lax) |
| keyring 没 daemon | Phase 2 (hard fail) |
| JWT 过期 | Phase 2 (无 silent refresh, 30d 后重 login) |
| CSRF | Phase 2 (SameSite=Lax, 跨域 POST 拒) |
| 误推私有内容到 hub | Phase 4 (page-level public flag) |
| 搜索引擎抓 hub | Phase 4 (`<meta robots="noindex">` default) |
| OAuth code 截获 | Phase 4 (state + PKCE) |

---

## 7. 数据库演进 (schema migration 顺序)

```
Phase 2:      users(id, email, username, password_hash, is_first_admin, created_at, last_login_at)
                          +username TEXT UNIQUE  (Phase 2 一次到位)

Phase 3:      share_tokens(id, token_hash, wiki_id, created_by, expires_at, ...)

Phase 4:      (单独 llmwikify-hub 仓) posts, follows, takedowns
```

---

## 8. 待办(全部等你说 "go")

- [x] Phase 2a 设计文档: 增 §0/§1.1/§1.2/§1.4/§1.5/§1.6/§1.8 决策 12-18 + Argon2id 切换
- [x] Phase 2a commit 1: foundation/auth + auth_routes + middleware + pyproject
- [x] Phase 2a commit 2: CLI auth + serve host 检测 + auto-init prompt
- [x] Phase 2a commit 3: tests (4 文件) + 端到端冒烟
- [x] Phase 2a 完成后 review
- [x] Phase 2b 设计文档: 增 §0/§1.1 决策 19-24 (WebUI Login + auth store + token 持久化)
- [x] Phase 2b commit 4: authStore + api.ts interceptor (runtime token + 401 redirect + WS query param)
- [x] Phase 2b commit 5: LoginPage + ProtectedRoute + App.tsx 路由守卫
- [x] Phase 2b commit 6: AuthInitBanner 独立组件 + App.tsx 嵌入
- [x] Phase 2b 完成后 review
- [x] Phase 2.5 设计文档: 增 §0/§1.1/§1.10 决策 25-28 (无密码 PAT 认证)
- [ ] Phase 2.5 commit 7: schema + utils + prompt 简化 + 删 argon2-cffi
- [ ] Phase 2.5 commit 8: PAT 路由 + middleware 验证
- [ ] Phase 2.5 commit 9: CLI create-token/list/revoke
- [ ] Phase 2.5 commit 10: WebUI 无密码登录
- [ ] Phase 2.5 commit 11: tests + design doc 更新
- [ ] Phase 3 commits 12-15: share + remote wiki
- [ ] Phase 4 commits 16-19: 中央 hub publish
- [ ] Phase 4 hub 服务端独立仓立项 + 并行实施

---

## 9. 引用

- [logging-unification.md](logging-unification.md) — 同款 design doc 范例
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — 4 层架构
- [AGENTS.md](../../AGENTS.md) — 项目规约
