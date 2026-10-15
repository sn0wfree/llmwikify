# MCP Lifespan 修复 + public_read 接线 + 公网服务化专项（B3）— 调查与执行计划

> 日期: 2026-10-14
> 范围: `dev/refocus-v0.40-2026-07-05` @ `1f9741f`（本专项将在其之上叠加 4 处补丁）
> 实测环境: 本机 Ubuntu 22.04（Python 3.10.12）+ 服务器 8.133.234.138（CentOS Stream 9，
> 容器 `llmwikify-server:0.40.2-slim`，数据 `~/CKbase` 442 页）
> 数据: `/mcp/mcp` 带有效 PAT **100% 返回 500** · 无 token `GET /api/wiki/status` **放行（200）**
> 状态: **调查完成，方案定稿**（4 处补丁 + 7 步执行 + 2 项回退预案）；执行待批

---

## 1. TL;DR

统一服务器（`llmwikify serve --web`）存在两个与本项目"对外服务"目标直接相关的缺陷：

1. **MCP over HTTP 完全不可用**：带合法 PAT 调用 `/mcp/mcp` 返回 **500**。根因是
   `core.py` 用 `app.mount()` 挂载 FastMCP ASGI 应用，但 **Starlette 的 `mount()` 不运行
   子应用 lifespan** → `StreamableHTTPSessionManager` 从未初始化。另有一个隐藏坑：
   `MCPAdapter.asgi_app` 是 **property 且每次访问新建实例**，修复必须"捕获一次、lifespan 与
   mount 共用同一实例"。
2. **读操作无鉴权（设计预留项未接线）**：`serve.py:255` 的 `public_read` 被硬编码为 `True`
   （注释自述 "can be overridden later"）。任何能访问端口的人（无 token）可读取全部 wiki 内容；
   写操作（非 GET）已有 403 保护。middleware 侧 `public_read=False` 的 401 分支**已完整实现**，
   只差把开关接出来。

修复 = **4 处小改动（~30 行含注释）**：`core.py` ×3 + `serve.py` ×1。修复后按
"公网小圈子"方案部署：nginx + Let's Encrypt **IP 证书**（2026-01 GA，无需域名/备案）+
8443 + `LLMWIKIFY_PUBLIC_READ=false`。

**2026-10-14 部署验证期追加**：又发现第 3 个隐藏缺陷 —— `trusted_proxies` 因死引用
`get_config` 从未生效（详见 §9），已 2 行修复并本地实证。

## 2. 缺陷 #1：MCP over HTTP 500

### 2.1 症状与证据

服务器实测（容器 `llmwikify-test`，slim 镜像 0.40.2）：

| 请求 | 结果 | 判定 |
|---|---|---|
| `POST /mcp/mcp`（无 token）| `403 {"error":"auth_required",...}` | 安全侧 OK（中间件先拦）|
| `POST /mcp/mcp`（有效 PAT）| **500 Internal Server Error** | 🔴 功能坏 |

容器日志堆栈（节选）：

```
File "/usr/local/lib/python3.11/site-packages/fastmcp/server/http.py", line 108, in __call__
    raise RuntimeError(f"{new_error_message}\nOriginal error: {e}") from e
RuntimeError: FastMCP's StreamableHTTPSessionManager task group was not initialized.
This commonly occurs when the FastMCP application's lifespan is not passed to the
parent ASGI application (e.g. FastAPI or Starlette).
Please ensure you are setting `lifespan=mcp_app.lifespan` in your parent app's constructor.
Original error: Task group is not initialized. Make sure to use run().
```

### 2.2 根因链

1. FastMCP 的 Streamable HTTP transport 依赖 `StreamableHTTPSessionManager`；其 task group
   **必须在宿主应用 lifespan enter 后才初始化**（FastMCP ASGI 集成契约）。
2. `client.py`："`core.py:_build_app` 只用 `app.mount('/mcp', self.mcp.asgi_app)` 挂载" ——
   Starlette/FastAPI 的 `mount()` **不会传播子应用 lifespan**，父应用自带 lifespan
   （DreamScheduler/AutoCompact/maintenance）也**未组合** MCP 应用的 lifespan。
3. **实例身份坑**：`interfaces/mcp/adapter.py` 中 `asgi_app` 是 `@property`：
   `return self._mcp.http_app()` —— **每次访问都新建一个 app**。因此修复方案必须是
   "在 `_build_app` 内捕获一次实例，lifespan 与 mount 共用"，否则 lifespan 初始化的
   与实际挂载的是两个不同实例（仍 500）。
4. **端点路径注意**：挂载前缀 `/mcp` + `http_app()` 内部路径 `/mcp` → 实际端点为
   **`/mcp/mcp`**。现有 `docs/MCPORTER_DEPLOYMENT.md` / `MCP_SETUP.md` 写的 `:8765/mcp`
   是旧路径，需一并更正。

### 2.3 影响面

| 场景 | 状态 |
|---|---|
| MCP over HTTP（远程 agent 接入统一服务器）| 🔴 100% 不可用 |
| WebUI / REST API / CLI | ✅ 不受影响 |
| stdio MCP（本地 agent 子进程模式，`llmwikify mcp`）| ✅ 不受影响（不走挂载路径） |
| 安全性 | ✅ 无数据泄露（无 token 403；带 token 仅 500）|

### 2.4 修复设计（core.py ×3）

**Patch A** — `_build_app` 中、lifespan 定义之前，捕获实例 + 原函数重命名：

```python
        # 2026-10-14: capture the MCP ASGI app once. The ``asgi_app``
        # property builds a FRESH app per access, so the combined lifespan
        # below and app.mount() must share this exact instance.
        mcp_asgi_app = self.mcp.asgi_app if self.mcp is not None else None

        @asynccontextmanager
        async def _wiki_lifespan(app: FastAPI) -> None:
            """Phase 7+9+40 lifespan: start DreamScheduler + AutoCompact
            ...（原 docstring 与函数体保持不变）"""
```

**Patch B** — 原函数结束后（`app = FastAPI(` 之前）插入组合 lifespan：

```python
        @asynccontextmanager
        async def lifespan(app: FastAPI) -> None:
            """Combined lifespan (2026-10-14).

            Enter FastMCP's ASGI-app lifespan FIRST so its
            StreamableHTTPSessionManager task group initializes; Starlette's
            ``mount()`` does NOT run sub-app lifespans, which is why every
            /mcp request failed with "task group was not initialized" (500).
            Then delegate to the wiki subsystems lifespan.
            """
            from contextlib import AsyncExitStack

            async with AsyncExitStack() as stack:
                if mcp_asgi_app is not None:
                    await stack.enter_async_context(mcp_asgi_app.lifespan(app))
                await stack.enter_async_context(_wiki_lifespan(app))
                yield
```

**Patch C** — 挂载改用同一实例：

```python
        # Mount MCP endpoint (same instance whose lifespan is entered above)
        if mcp_asgi_app is not None:
            app.mount("/mcp", mcp_asgi_app)
```

> 注：`asynccontextmanager` 已在 `core.py` 顶部导入；`mcp_asgi_app` 为 `None` 时
> 组合 lifespan 对行为零影响（stdio 模式 / 无 MCP 场景完全兼容）。

## 3. 缺陷 #2：public_read 硬编码

### 3.1 证据

- `interfaces/cli/commands/serve.py:254-255`：

  ```python
  server_local_mode = local_mode
  server_public_read = True  # default; can be overridden later
  ```

- middleware（`JWTAuthMiddleware._deny_no_token`）**已完整支持** `public_read=False`
  → `401 {"error":"auth_required"}`；全库搜索**无任何** CLI 参数 / env / config 接线。
- 服务器实测：无 token `GET /api/wiki/status` → **200**（读全公开）。
- 设计出处：`docs/designs/auth-and-sharing-roadmap.md` 决策 1（"GET 公开 / POST/PUT/DELETE 403"，
  Phase 2a 为"本地开发友好"默认），本补丁 = 把预留开关接到 env（决策语义不变，默认仍 True）。

### 3.2 修复设计（serve.py ×1）

```python
    server_local_mode = local_mode
    # 2026-10-14: wire the previously hardcoded public_read flag to an env
    # switch so deployments can require authentication for reads too.
    # Default stays True (backward compatible). Set
    # LLMWIKIFY_PUBLIC_READ=false to make token-less GETs return 401.
    server_public_read = os.environ.get("LLMWIKIFY_PUBLIC_READ", "true") \
        .strip().lower() not in {"0", "false", "no", "off"}
```

## 4. 权限体系审计结论（前置盘点，2026-10-14）

**已具备**（源码核实 + 服务器实测）：PAT（服务端仅存 SHA-256）· JWT（30d TTL，httpOnly cookie）·
写操作 scope=write 强制 · per-wiki `claims.wikis` 逐请求校验（决策 7）· 吊销/过期过滤
（`get_by_hash` 条件查询）· 内建限流（默认 60 req/min/IP，`RATE_LIMIT_PER_MIN` 可调）·
首位 admin 引导（`/register` 随后自动关闭）· WebUI 登录页（`LoginPage.tsx`）。

| 缺口 | 影响 | 处置 |
|---|---|---|
| `public_read` 未接线 | 读全公开 | **本专项修复**（§3）|
| 单用户模型（PAT 同属 admin）| 无每人独立账号 | 本次沿用共享 PAT / 只读场景共用；多用户列为后续项 |
| 只读 PAT 无创建入口（`scopes` 列已存在）| — | 后续项（加 `--scopes read`）|
| MCP lifespan | MCP HTTP 全坏 | **本专项修复**（§2）|

## 5. 验证计划

1. `ruff check src/llmwikify/interfaces/server/core.py src/llmwikify/interfaces/cli/commands/serve.py`
2. pytest 定向（5 个文件）：
   - `tests/test_interfaces_server_autocompact_lifespan.py`
   - `tests/test_interfaces_server_confirmations_cleanup_lifespan.py`
   - `tests/test_maintenance_lifespan.py`
   - `tests/test_mcp_integration.py`
   - `tests/test_mcp_serve_merge.py`
3. 本地实弹（临时端口起补丁后服务）：
   - a) `fastmcp.Client` 连 `/mcp/mcp`：`initialize` + `tools/list` + 只读工具调用 → 全绿
   - b) `LLMWIKIFY_PUBLIC_READ=false`：无 token GET → 401；带本地 PAT → 200
   - c) 不设变量：读公开行为与修复前一致（回归）
4. 镜像级：重建 slim → 容器内复测 a/b/c + `docker ps` healthy + 日志 0 ERROR
5. 部署后：外网 E2E（登录页 → 粘贴 PAT → 阅读）

## 6. 公网服务化架构（内部小圈子）

```
用户（领导/同事）
   │  https://8.133.234.138:8443      ← Let's Encrypt IP 证书（2026-01 GA，6 天短周期自动续）
   ▼
nginx（服务器宿主）
   │  TLS 终止 · SSE 流式直通（proxy_buffering off）· limit_req 限流 · 访问日志
   ▼
127.0.0.1:8765  llmwikify-server:0.40.2-slim（restart: unless-stopped）
   │  env: WIKI_ROOT=/app/wiki · LLMWIKIFY_HOME=/app · HOME=/app
   │       LLMWIKIFY_PUBLIC_READ=false（登录后才可读）
   ▼
~/CKbase（知识库 442 页） + ~/.llmwikify（配置/凭据）
```

**备案说明**：服务器区域 `cn-shanghai`（大陆）——域名 + 80/443 需 ICP 备案；本方案走
**IP 证书 + 非标端口（8443）**规避。若 ACME 的 80 端口验证在大陆网络不可达 →
回退自签证书（浏览器一次性信任）。若后续需要正规域名服务 → 备案或换香港节点。

## 7. 执行步骤（7 步）

1. 打 4 处补丁（core.py ×3、serve.py ×1）→ ruff → pytest（§5.2）
2. 本地实弹验证（§5.3 a/b/c）全绿
3. 重建 `llmwikify-server:0.40.2-slim` → `docker save | xz` → rsync（~81MB）→ 远端 `docker load`
4. 远端测试容器替换为正式 compose（`LLMWIKIFY_PUBLIC_READ=false` + `restart: unless-stopped`）
5. 远端复测：容器内 MCP client 连通 + 无 token 401 + PAT 200
6. nginx + certbot → LE IP 证书（先实测 80 端口 ACME 可达性）→ 8443 站点配置
7. 阿里云安全组放行 8443 → 外网 E2E（手机流量）

## 8. 风险与回退

| 风险 | 回退预案 |
|---|---|
| ACME 80 端口验证在大陆被拦截 | 自签证书（浏览器手动信任一次）；或改备案域名路线 |
| 镜像回归问题 | 保留上一版 slim tag，compose 改 tag 即可回切（数据不动）|
| MCP 组合 lifespan 引入生命周期副作用 | `mcp_asgi_app=None` 时零操作；5 个既有测试覆盖 lifespan 场景 |
| `public_read=false` 影响本地开发 | 默认仍 `True`，仅显式设置 env 才改变 |
| 共享 PAT 的审计缺失 | 记录为已知限制；多用户支持（§4 后续项）|

---

## 9. 部署验证期追加发现（2026-10-14）：trusted_proxies 死引用

**症状**：nginx 反代上线后，应用日志的 client IP 始终为 docker 网桥地址（172.18.0.1），
即使正确配置了 `server.trusted_proxies` 也不解析 `X-Forwarded-For`；应用内限流将把
**所有用户**合并在同一个 60 req/min 桶里（多用户浏览会互相挤占）。

**根因**：`interfaces/server/http/middleware.py:_load_trusted_proxies` 中
`from llmwikify.foundation.config import get_config` —— **该符号在 `foundation.config`
中不存在**（模块导出的是单例 `config = Config()`，见 `config.py:223`）。ImportError 被
外层 `except Exception: return []` 静默吞掉（debug 级日志不可见）→ `trusted_proxies`
自引入以来从未生效。

**修复**（2 行）：

```python
        from llmwikify.foundation.config import config as _llmwikify_config
        cfg = _llmwikify_config.get()
```

**验证**（本地实弹，`LLMWIKIFY_PUBLIC_READ=false` 使 401 可观测）：
- `X-Forwarded-For: 203.0.113.7, 127.0.0.1` → 日志 `client=203.0.113.7` ✅
  （右侧回溯：跳过可信 127.0.0.1，取不可信真实 IP）
- 无 XFF → `client=127.0.0.1` ✅（回退 direct peer）
- `tests/test_interfaces_server_routes.py` 39 passed；ruff 通过

**影响**：修复后 nginx 反代下应用日志显示真实客户端 IP、应用内限流按真实客户端分桶
（此前全员共享一个桶）；服务器部署随后重建镜像并复验。

---

## 10. 上线完成记录（2026-10-14）

| 项 | 状态 |
|---|---|
| 正式服务 | `llmwikify-server:0.40.2-slim` @ `~/CKbase/deploy/docker-compose.yml`（`restart: unless-stopped`）— healthy |
| 读保护 | `LLMWIKIFY_PUBLIC_READ=false` — 无 token **401** / PAT **200**（经 nginx 实测） |
| MCP | `/mcp/mcp` 容器内实连 **20 tools** ✓（lifespan 修复生效） |
| trusted_proxies | 修复后经 nginx 实测 `client=203.0.113.7`（真实 IP 透传）✓ |
| nginx | 1.20.1；`:80` 仅 ACME 验证路径 + 301 跳转（非服务端口，用户决策保留）；`:8443` TLS 反代（SSE 直通 + `limit_req 300r/m`） |
| 证书 | **Let's Encrypt IP 证书**（`--ip-address` + `shortlived` profile，ECDSA），已签发并服务；浏览器零警告 |
| 续期 | root cron `17 */12 * * *` + `--deploy-hook "systemctl reload nginx"`；staging `renew --dry-run` 全链路成功 |
| 回滚点 | 本地 `llmwikify-server:0.40.2-slim-r0`（MCP 修复前版本） |
| 更新流程 | `~/llmwikify/scripts/sync_to_server.sh`：本地只读 rsync（wiki/ + wiki.md）→ 服务器容器内 `build-index` 重建索引（~9s）→ API 验证。**零停机**（实测 442→508 页无中断）；排除 .llmwikify.db / raw / reports_pipeline / log.md / .sink / reference_index.json |
| 运维入口 | `docker logs/compose` @ `~/CKbase/deploy`；证书 `/opt/certbot/bin/certbot certificates` |

---

*调查依据：服务器容器实测（2026-10-13/14）+ 源码逐行核实（`middleware.py` / `auth_routes.py` /
`serve.py` / `core.py` / `adapter.py` / `_jwt.py` / `db.py`）。*
