# llmwikify 服务完整测试流程

| 项 | 内容 |
|---|---|
| 日期 | 2026-10-23 |
| 适用 | 生产 `0.40.6-slim` / 本地 slim 复现 |
| 入口 | `https://8.133.234.138:8443` · MCP `https://8.133.234.138:8443/mcp/` |

---

## 0. 前置

```bash
# 服务器
ssh linlu@8.133.234.138
PAT=$(cat ~/.llmwikify/pat)
docker ps --filter name=llmwikify-server   # healthy + 目标镜像 tag
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $PAT" \
  http://127.0.0.1:8765/api/health        # 期望 200
```

- 确认镜像版本：`docker exec llmwikify-server python3 -c "import llmwikify;print(llmwikify.__version__)"`
- 变更回滚：compose 备份 `docker-compose.yml.bak.*` + 旧镜像 tag

---

## 1. REST（外网/本机）

| 接口 | 期望 | 基线 |
|---|---|---|
| `GET /api/health` | 200 | &lt;0.2s |
| `GET /api/wiki/status` | 200 | &lt;0.5s |
| `GET /api/wiki/graph` | 200 | **&lt;0.5s** |
| `GET /api/wiki/graph_analyze` | 200 | **&lt;1s**（热） |
| `GET /api/wiki/page/<name>` | 200 | &lt;1s |
| `GET /`（WebUI） | 200 HTML | SPA 壳 |
| `GET /docs` | 200 | OpenAPI |

```bash
for p in /api/health /api/wiki/status /api/wiki/graph /api/wiki/graph_analyze /docs; do
  curl -s -o /dev/null -w "$p %{http_code} %{time_total}s\n" \
    -H "Authorization: Bearer $PAT" "https://8.133.234.138:8443$p"
done
```

---

## 2. MCP 会话

```bash
BASE=https://8.133.234.138:8443/mcp/
# initialize → SID
# initialized (202)
# tools/list → ≥20 tools
# tools/call wiki_status
# DELETE
```

**通过**：session id 存在；tools/list 非空；call 返回 `result` 非 HTML。

---

## 3. 工具矩阵（14 项，对照上线前）

| 工具 | 期望 | 备注 |
|---|---|---|
| wiki_status | OK | |
| wiki_read_schema | OK | |
| wiki_read_page | OK | 中文页名也要测 |
| wiki_search | OK | |
| wiki_references | OK | |
| wiki_graph / graph_analyze | OK | 热 &lt;1s |
| recommend / synthesis / sink | OK | |
| analyze_source 错误路径 | OK | Source not found |
| wiki_lint ×2 | OK | 冷 20–40s / **热 &lt;0.5s** |
| wiki_knowledge_gaps ×2 | OK | 首含 LLM / **二 &lt;1s** |

写工具（write_page / ingest）**默认不测**，保护生产库。

---

## 4. 缓存与失效

| 检查 | 操作 | 期望 |
|---|---|---|
| 热路径 | 连续 lint / gaps | 二次 &lt;1s |
| force | `wiki_lint` 带 force 或 API `?force=1` | 必重算 |
| 写失效 | 应用内写一页 | 下次 lint 非 cached |
| watcher | 宿主机改 md | 内 10min 内失效（或立即） |

---

## 5. 性能基线（0.40.6）

| 指标 | 基线 |
|---|---|
| graph | 0.01–0.2s |
| graph_analyze | &lt;0.1s（预热后） |
| lint 冷 / 热 | ~20–30s / **~0.1s** |
| gaps 热 | **~0.1s** |
| 并发 status + graph | 不应全站挂死 |

---

## 6. 异常处置

| 现象 | 动作 |
|---|---|
| MCP 404 / HTML | 查 URL 是否 `/mcp/`；是否被 SPA |
| lint 卡死全站 | `docker restart llmwikify-server`；勿在峰期跑 lint |
| 缓存过新/过旧 | `force=1`；写路径是否 invalidate |
| 回滚 | compose image 改回上一 tag → `up -d` |

---

## 7. 一键脚本（仓库）

```bash
# 本地/容器矩阵
bash scripts/mcp_tool_matrix_retest.sh
# WebUI+REST+MCP 全链路
bash scripts/rebuild_and_accept.sh
# 生产 lint/gaps 对比
bash scripts/test_prod_0_40_4.sh   # 或 0.40.6 部署脚本内嵌
```

**验收**：第 1–3 节全绿；第 4 节热路径达标；第 5 节在基线内。
