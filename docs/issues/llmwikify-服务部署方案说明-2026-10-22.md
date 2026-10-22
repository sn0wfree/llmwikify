# llmwikify 知识库服务：部署方案说明

| 项 | 内容 |
|---|---|
| 文档日期 | 2026-10-22 |
| 适用服务 | CKbase 研报知识库（llmwikify 0.40.2） |
| 服务地址 | `https://8.133.234.138:8443`（内部小圈子，PAT 登录后只读） |
| 部署形态 | 单机 Docker + nginx 反向代理 + Let's Encrypt IP 证书 |
| 关联文档 | `llmwikify/docs/ops/kb-sync.md`（同步运维）、`llmwikify/docs/diagnostics/mcp-lifespan-auth-gate-2026-10.md`（上线记录） |

---

## 1. 服务概览

- 面向领导/同事的内部知识库 Web 服务（研报解析 → wiki → 检索/图谱）。
- 访问方式：浏览器打开 `https://8.133.234.138:8443` → 登录（粘贴 PAT）→ 只读浏览/搜索/图谱。
- 读保护：`LLMWIKIFY_PUBLIC_READ=false`，无 token 一律 401。
- 服务为**单进程**（无 worker），见 §12 已知限制。

## 2. 架构总览

```
                        用户（领导/同事）
                              │  https://8.133.234.138:8443
                              ▼
        ┌──────────────────────────────────────────────┐
        │ nginx（服务器宿主，CentOS Stream 9）          │
        │  :80  → ACME 验证 + 301 跳 8443               │
        │  :8443 → TLS 终止 · SSE 直通 · limit_req 限流 │
        │          证书：Let's Encrypt IP 证书（ECDSA） │
        └───────────────────┬──────────────────────────┘
                            │  proxy_pass http://127.0.0.1:8765
                            ▼
        ┌──────────────────────────────────────────────┐
        │ Docker: llmwikify-server（镜像 0.40.2-slim）  │
        │ 入口：tini → server-entrypoint.sh             │
        │ 进程：python -m llmwikify serve --web ...     │
        │ 端口：8765（仅绑定 127.0.0.1）                │
        │ 健康检查：GET /api/health（5s 间隔）          │
        └───────────────────┬──────────────────────────┘
                            │  挂载（rw）
              ┌─────────────┴──────────────┐
              ▼                            ▼
   /app/wiki → ~/CKbase           /app/.llmwikify → ~/.llmwikify
   （知识库正文 + 内容 DB）        （auth.db / JWT / 凭据）
```

## 3. 服务器基础环境

| 项 | 值 |
|---|---|
| 公网 IP | `8.133.234.138`（腾讯云，cn-shanghai） |
| 系统 | CentOS Stream 9 |
| 规格 | 4 vCPU / 7.3 GiB 内存 / 70 GB 磁盘（已用 16%） |
| nginx | 1.20.1（`/etc/nginx/conf.d/llmwikify.conf`） |
| Docker | 容器运行时；compose 项目 `deploy` |
| 登录用户 | `linlu`（SSH 免密已配置，供同步脚本使用） |

## 4. 镜像与容器

### 4.1 镜像
| 项 | 值 |
|---|---|
| 使用镜像 | `llmwikify-server:0.40.2-slim`（约 680 MB） |
| 备用/回滚 | 本地 `llmwikify-server:0.40.2-slim-r0`（上线前版本） |
| 构建文件 | `llmwikify/docker-tests/Dockerfile.server`（`python:3.11-slim` + tini） |
| 构建命令（本地） | `docker build -f docker-tests/Dockerfile.server -t llmwikify-server:0.40.2-slim .` |
| 发布方式 | `docker save ... \| xz -T0` → `rsync` 到服务器 → `xz -dc \| docker load` → `docker compose up -d` |

### 4.2 容器
| 项 | 值 |
|---|---|
| 容器名 | `llmwikify-server` |
| 创建时间 | 2026-10-14（镜像构建 8 天前） |
| 重启策略 | `unless-stopped` |
| 健康状态 | healthy（healthcheck：`curl -f http://localhost:8765/api/health`，5s 间隔 / 20 次重试） |
| 端口 | `127.0.0.1:8765 → 8765`（不对公网直接暴露） |
| 入口 | `tini -- /app/server-entrypoint.sh` |
| 启动命令 | `serve --web --host 0.0.0.0 --port 8765` |

### 4.3 `docker-compose.yml`（服务器 `~/CKbase/deploy/docker-compose.yml`）

```yaml
services:
  server:
    image: llmwikify-server:0.40.2-slim
    container_name: llmwikify-server
    environment:
      - WIKI_ROOT=/app/wiki
      - LLMWIKIFY_HOME=/app
      - HOME=/app
      - LLMWIKIFY_PUBLIC_READ=false
      - TZ=Asia/Shanghai
    ports:
      - "127.0.0.1:8765:8765"
    volumes:
      - /home/linlu/CKbase:/app/wiki:rw
      - /home/linlu/.llmwikify:/app/.llmwikify:rw
    restart: unless-stopped
```

## 5. 反向代理与 TLS

`/etc/nginx/conf.d/llmwikify.conf` 要点：

| 配置 | 值 | 说明 |
|---|---|---|
| `:80` | ACME webroot `/var/www/acme` + 301 → 8443 | 证书续期验证入口 |
| `:8443 ssl` | `ssl_protocols TLSv1.2 TLSv1.3` | 对外服务 |
| 证书 | `/etc/letsencrypt/live/8.133.234.138/{fullchain,privkey}.pem` | Let's Encrypt **IP 证书**（ECDSA，shortlived profile） |
| 反代 | `proxy_pass http://127.0.0.1:8765` | 透传 `X-Real-IP` / `X-Forwarded-For` / `X-Forwarded-Proto` |
| SSE | `proxy_buffering off`、`proxy_http_version 1.1`、`Connection ""`、读写超时 600s | 流式对话/事件不被缓冲 |
| 限流 | `limit_req zone=llmwiki rate=300r/m burst=60 nodelay` | 单 IP 300 请求/分钟，突发 60 |
| 上传 | `client_max_body_size 50m` | PDF 上传 |
| 证书续期 | root cron `17 */12 * * *` + `--deploy-hook "systemctl reload nginx"` | 6 天短周期自动续 |
| gzip | **未开启**（待优化） | JSON 响应 69KB 未压缩 |

## 6. 数据布局

### 服务器
| 路径 | 内容 | 是否用户数据 |
|---|---|---|
| `~/CKbase/wiki/**/*.md` | 知识库全部页面（2026-10-22：1439 篇） | ✅ 源真相 |
| `~/CKbase/wiki.md` | schema 说明 | ✅ |
| `~/CKbase/.llmwikify.db` | 内容库：pages / page_links / pages_fts / relations / entity_aliases（38MB） | ✅ |
| `~/CKbase/wiki/index.md` | 参考索引（由 build-index 生成） | 生成物 |
| `~/CKbase/wiki/reference_index.json` | 参考索引导出（服务器本地生成，不同步） | 生成物 |
| `~/CKbase/deploy/docker-compose.yml` | 部署编排 | 配置 |
| `~/CKbase/raw/`、`~/CKbase/reports_pipeline/` | 研报原始 PDF 与解析管线（随目录挂载存在，但**不参与同步**） | 数据管线 |
| `~/.llmwikify/auth.db` | 用户/Token | 凭据 |
| `~/.llmwikify/jwt_secret` | JWT 签名密钥（权限 640，建议 600） | 凭据 |

### 本地（`/home/ll/Public/CKbase`）
同上结构；本地另存 `reports_pipeline/state/processed.jsonl`（处理注册表）、`tmp/`（中间产物）等。

## 7. 知识库同步链路（本地 → 服务器）

```
本地 CKbase（解析产出）
   │ 1) rsync wiki/ + wiki.md（排除 log.md/.sink/*.bak*/reference_index.json/*.db）
   ▼
服务器 ~/CKbase/wiki/
   │ 2) docker exec llmwikify-server python -m llmwikify build-index
   ▼
服务器 DB：pages / page_links / pages_fts 重建（~50s，零停机）
   │ 3) sync_relations.sh：relations + entity_aliases 单事务导入
   ▼
服务器 DB：知识图谱与本地一致
   │ 4) 验证：/api/wiki/status（indexed_pages / total_links / graph total_relations）
```

- **一键脚本**：`~/llmwikify/scripts/sync_all.sh`（= `sync_to_server.sh` + `sync_relations.sh`）
- **定时**：本机 cron 每日 **03:00** 执行 `sync_all.sh`（不要外层再加 `flock`，脚本内置锁）
- **关键约束**：`build-index` 不重建 `relations`，必须配套 `sync_relations.sh`（详见 `docs/ops/kb-sync.md`）
- **同步范围**：只同步 markdown；**不同步**内容 DB、raw、reports_pipeline、log.md、.sink、备份文件

## 8. 认证与访问控制

| 项 | 说明 |
|---|---|
| 只读保护 | `LLMWIKIFY_PUBLIC_READ=false`：未登录 GET → 401 |
| 用户/Token | `~/.llmwikify/auth.db`（挂载 `/app/.llmwikify/auth.db`） |
| API 验证 | `Authorization: Bearer <PAT>`（PAT 文件 `~/.llmwikify/pat`） |
| JWT | `~/.llmwikify/jwt_secret`（当前权限 640，建议收紧 600） |
| 网络 | 仅暴露 8443（TLS）；8765 只绑定 127.0.0.1 |
| 限流 | nginx 300 req/min/IP（burst 60） |

## 9. 日常运维手册

```bash
# 状态 / 健康
cd ~/CKbase/deploy && docker compose ps
curl -s https://8.133.234.138:8443/api/health

# 日志（实时）
docker logs -f --tail 100 llmwikify-server

# 重启
cd ~/CKbase/deploy && docker compose restart

# 重建索引（零停机）
docker exec llmwikify-server python -m llmwikify build-index

# API 状态（含页面数/链接数/图谱统计）
curl -sS -H "Authorization: Bearer $(cat ~/.llmwikify/pat)" \
  https://8.133.234.138:8443/api/wiki/status | python3 -m json.tool | head -40

# 证书检查
/opt/certbot/bin/certbot certificates

# 资源
free -h; df -h /; docker stats --no-stream
```

## 10. 变更与发布流程

### 10.1 常规发布（推荐）
1. 本地改代码 → ruff / pytest → git 提交
2. 本地构建：`docker build -f docker-tests/Dockerfile.server -t llmwikify-server:0.40.2-slim .`
3. 打包传输：`docker save llmwikify-server:0.40.2-slim | xz -T0 > /tmp/llmwikify-slim.tar.xz`
4. `rsync` 到服务器 → `xz -dc /tmp/llmwikify-slim.tar.xz | docker load`
5. `cd ~/CKbase/deploy && docker compose up -d`（~5s 停机）
6. 验证：`/api/health`、`/api/wiki/status`、关键接口耗时

### 10.2 热修（紧急，不重建镜像）

以本次图谱 O(E²) 修复为例（2 文件）：

```bash
# 0) 确认容器内代码位置（普通 pip 安装在 site-packages，editable 才在 /app/src）
docker exec llmwikify-server python -c \
  "import llmwikify.kernel.graph.export as m; print(m.__file__)"

# 1) 备份
mkdir -p ~/hotfix-bak/graph-oE2-20261022
docker cp llmwikify-server:<上一步打印的 export.py 路径> ~/hotfix-bak/graph-oE2-20261022/export.py
docker cp llmwikify-server:<同目录上级>/interfaces/server/http/wiki/wiki_routes.py \
  ~/hotfix-bak/graph-oE2-20261022/wiki_routes.py

# 2) 覆盖（源文件来自本仓库工作区）
docker cp src/llmwikify/kernel/graph/export.py \
  llmwikify-server:<export.py 路径>
docker cp src/llmwikify/interfaces/server/http/wiki/wiki_routes.py \
  llmwikify-server:<wiki_routes.py 路径>

# 3) 重启 + 验收
cd ~/CKbase/deploy && docker compose restart
curl -o /dev/null -s -w "%{time_total}\n" \
  -H "Authorization: Bearer $(cat ~/.llmwikify/pat)" \
  https://8.133.234.138:8443/api/wiki/graph
```

> 热修会造成「容器代码 ≠ 镜像代码」，需尽快用 §10.1 重建镜像收敛。
> **路径坑**：`Dockerfile.server` 为普通安装，`import llmwikify...__file__` 通常在
> `.../site-packages/llmwikify/...`；`Dockerfile.production` 才是 editable（`/app/src`）。
> 必须以容器内 `__file__` 为准，不要写死 `/app/src`。

### 10.3 数据侧变更
- 知识库内容：本地写页 → `sync_all.sh`（见 §7）
- 索引重建：`build-index`（可随时执行，零停机）
- DB 备份：`cp ~/CKbase/.llmwikify.db ~/CKbase/.llmwikify.db.bak.$(date +%Y%m%d-%H%M%S)`

## 11. 回滚

| 场景 | 操作 |
|---|---|
| 镜像回归 | compose 中改回 `llmwikify-server:0.40.2-slim-r0` → `docker compose up -d` |
| 热修回滚 | 用 §10.2 备份文件覆盖回去 → 重启 |
| DB 异常 | 还原 `.llmwikify.db.bak.*` → `build-index` 重建索引 |
| 页面内容异常 | 本地修正后重新 `sync_all.sh`（rsync 只增改不删，异常页可覆盖） |

## 12. 已知问题与限制

1. **单进程服务**：容器内仅 1 个 Python 进程，无 worker。单个长请求会阻塞事件循环（详见《服务响应慢诊断与修复方案-2026-10-22》）。
2. **图谱接口 O(E²)**：`/api/wiki/graph` 在 16869 条链接下耗时 25s；根因为 `build_graph()` 线性去重。**本地 P0 已修复**（字典去重 O(E) + 图接口改同步 `def`），见《服务响应慢诊断与修复方案-2026-10-22》；**服务器待热修/重建镜像**。
3. **networkx 未安装**：`graph_analyze` 会先耗时构图再返回 `empty`；新版代码将快速返回 `missing_dependency`。
4. **镜像代码漂移**：容器内为 0.40.2 快照，缺本地后续提交（如 analyzer 守卫）；需重建镜像收敛。
5. **JWT 文件权限** 640（安全警告，建议 600）。
6. **nginx 未开 gzip**：status 响应 69KB 未压缩。
7. **cron 双重锁历史**：曾因 crontab 外层 flock + 脚本内置锁导致同步静默跳过 8 天（2026-10-22 已修复，现为 `sync_all.sh` 单入口）。
8. **页面 404 路由**：`/api/wiki/pages`、`/api/search`、`/api/wiki/wiki/graph_analyze` 等为前端与 API 版本不匹配所致（不影响核心功能）。

## 13. 容量与状态基线（2026-10-22）

| 指标 | 值 |
|---|---|
| wiki 页面 | 1439 |
| page_links | 16,869 |
| 知识图谱 relations | 6,073（entity_aliases 4） |
| 内容库大小 | 38 MB（备份 14 MB @10-21） |
| 容器内存 | ~227 MB / 7.3 GB |
| 服务器磁盘 | 12 GB / 70 GB（16%） |
| 图谱接口耗时 | 25s（本地已修，待部署） |
| 常用接口耗时 | status 0.13s / page 0.08s / health 0.13s |

## 14. 参考

- 同步运维手册：`llmwikify/docs/ops/kb-sync.md`
- 上线与认证排障记录：`llmwikify/docs/diagnostics/mcp-lifespan-auth-gate-2026-10.md`
- 性能诊断：`~/Public/llmwikify-服务响应慢诊断与修复方案-2026-10-22.md`
- 服务代码：`llmwikify` 仓库（v0.40.2）；构建文件 `docker-tests/Dockerfile.server`
