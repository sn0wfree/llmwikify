# 服务响应慢：诊断与修复方案（图谱接口 O(E²)）

| 项 | 内容 |
|---|---|
| 文档日期 | 2026-10-22 |
| 状态 | P0 已实施（本地）/ 服务器热修待部署 |
| 影响服务 | `https://8.133.234.138:8443`（llmwikify-server，版本 0.40.2） |
| 影响范围 | Web UI 图谱页 / 图谱分析；卡顿期间**全站**请求排队 |
| 代码变更 | 2 个文件（`kernel/graph/export.py`、`interfaces/server/http/wiki/wiki_routes.py`） |
| 关联提交 | 修复完成后回填 |

---

## 1. TL;DR

- **不是网络 / 数据库慢**：`/api/wiki/status` 69KB 仅 0.13s，`/api/wiki/page/*` 0.08s，ping 8.9ms / 0 丢包。
- **慢的是图谱接口**：`/api/wiki/graph` **25.4s**、`/api/wiki/graph_analyze` **24.9s**。
- **根因**：`build_graph()` 的边去重是 **O(E²)** 线性扫描。链接数在 2026-10-22 同步后从 6426 → 16869（2.6×），耗时恶化约 6.9×。
- **放大器**：接口是 `async def` 却执行 CPU 密集同步代码 → **阻塞单进程事件循环**，25s 内所有请求排队（整站"卡住"）。
- **修复**：去重改字典（O(E)）+ 重接口改同步 `def`（线程池执行）。服务器实测算法层 **24.14s → 0.019s**（约 1270 倍）。

---

## 2. 现象与影响

1. 用户反馈"服务反应有点慢"，表现为页面点击、状态刷新间歇性卡顿（数秒到数十秒）。
2. 卡顿呈**突发性**：服务器空闲时一切正常；一旦有人打开/刷新图谱视图，全站请求排队。
3. 卡顿期间容器 CPU 133%（单核跑满），空闲时 0.2%。

## 3. 环境拓扑

```
浏览器 --TLS--> nginx:8443 (0.0.0.0) --proxy--> 127.0.0.1:8765
                                              (docker: llmwikify-server, 单进程)
                                                    |
                                                    └─ /app/wiki → 宿主机 ~/CKbase
                                                       （DB: ~/CKbase/.llmwikify.db）
```

## 4. 测量数据（2026-10-22 13:00~13:20）

| 检查项 | 结果 | 结论 |
|---|---|---|
| ping（20 包） | 8.9ms，0% 丢包 | 网络正常 |
| TCP / TLS 握手 | 9ms / 55ms | 连接正常 |
| `/api/wiki/status`（69,365B） | 0.127~0.155s（连续 10 次稳定） | 正常 |
| `/api/wiki/page/symbols/镍`（40KB） | 0.082s | 正常 |
| `/api/wiki/sink/status` | 0.071s | 正常 |
| `/api/agent/status` | 0.075s | 正常 |
| **`/api/wiki/graph`** | **25.4s**（10KB） | **异常** |
| **`/api/wiki/graph?current_page=…`** | **24.0s**（52.6KB） | **异常** |
| **`/api/wiki/graph_analyze`** | **24.9s**（182B，返回 `status=empty`） | **异常且无效计算** |
| 容器进程 | 仅 1 个 `python -m llmwikify serve`（无 worker） | 单进程 |
| 容器 CPU | 空闲 0.2%；卡顿瞬时 133% | 单核饱和 |

**算法复现（同一份 DB，直接跑 `build_graph` 的去重逻辑）：**

| 环境 | 现有 O(E²) | 字典去重 O(E) | 唯一边数 |
|---|---|---|---|
| 开发机 | 2.28s | **0.007s** | 14,233 |
| 服务器宿主机 | **24.14s** | **0.019s** | 14,233 |

## 5. 根因分析

### 5.1 直接原因：O(E²) 边去重
`src/llmwikify/kernel/graph/export.py::build_graph()`（约 13-73 行）：

```python
for row in cursor.fetchall():                 # 16,869 条 page_links
    ...
    existing = next(
        (e for e in edges if e["source"] == src
         and e["target"] == tgt and e["type"] == "wikilink"),
        None,                                  # ← 每条链接都线性扫描已收集边表
    )
```

复杂度约 `E × 已收集边数 / 2 ≈ 1.35 亿次比较`。服务器单核较慢，实测 24s。

### 5.2 放大器：`async def` 中执行阻塞计算
`src/llmwikify/interfaces/server/http/wiki/wiki_routes.py`（约 139-152、246-260 行）：

```python
@wiki_router.get("/graph_analyze")
async def wiki_graph_analyze(...):      # async 端点内跑 25s 同步 CPU 代码
    return wiki.graph_analyze()

@wiki_router.get("/graph")
async def wiki_graph(...):
    return build_visualization_data(...)  # 同上
```

ASGI 单进程事件循环被占满 → 其他请求全部排队（这解释了"整站慢"而非仅图谱页慢）。

### 5.3 触发时点：同步后链接数 2.6 倍
| 时间 | page_links | 图谱耗时（实测/推算） |
|---|---|---|
| 10-22 12:21 同步前 | 6,426 | ~3-4s |
| 10-22 12:21 同步后 | **16,869** | **~25s** |

### 5.4 次要问题
- **networkx 未安装**：容器内 `import networkx` 失败；线上 `graph_analyze` 仍先花 25s 构图，再返回 `status=empty`（无效计算）。本地仓库新版已加 `missing_dependency` 快速返回，但服务器代码尚未包含该提交。
- 前端 401 轮询：`/api/wiki/status` 连续 `no token → 401`（鉴权/重试逻辑）。
- UI 路由 404：`/api/wiki/pages`、`/api/search`、`/api/wiki/wiki/graph_analyze`（前端与 API 版本不匹配）。
- 响应未 gzip：status 69KB；JWT 文件权限 640（应 600）。

## 6. 修复方案

### P0-1 `build_graph()` 字典去重（O(E)）— 已实施

用 `edge_index: dict[(src, tgt, type), edge]` 代替线性扫描。wikilink 重复边 `weight += 1`；relation 按 `(src,tgt,relation)` 真去重（更高 confidence 才抬权重），避免 PageRank 重复计权。

**预期**：算法层 24.14s → **0.019s**；HTTP 端到端（含序列化/类型映射/网络）目标 **<0.3s**。

### P0-2 重接口改为同步 `def`（不阻塞事件循环）— 已实施

`/graph`、`/graph_analyze`、`/{wiki_id}/graph` 三处 `async def` → `def`。FastAPI 会把同步端点放到线程池执行。

### P1-1（可选）图谱结果缓存
- 键：`(wiki_id, current_page, mode, index_version)`；TTL 60s；在 `build-index` / `ingest` / `write_page` 时失效。
- 收益：UI 反复刷新零计算。P0 修复后非必需，建议观察后再定。

### P1-2 nginx 开启 gzip

```nginx
gzip on;
gzip_types application/json text/css application/javascript;
gzip_min_length 1024;
```

收益：status 69KB → ~8KB，弱网首屏更快。

### P2 其他（另开任务）
- JWT 权限 640 → 600。
- 前端 401 轮询与 404 路由对齐（UI/API 版本）。
- 若需要图谱分析（PageRank/社区）：安装 `networkx`（`llmwikify[graph]`）或保持 `missing_dependency` 快速返回（新版已支持）。

## 7. 部署方案

| 方式 | 步骤 | 停机 | 适用 |
|---|---|---|---|
| **A. 热修（立即）** | 备份容器内 2 文件 → `docker cp` 覆盖 → `docker restart llmwikify-server`（~5s）→ 验证 | ~5s | 本次 |
| B. 重建镜像（规范） | 用更新后的源码重建镜像并替换容器 | ~5s | 后续（消除代码漂移） |

> 注意：服务器容器内代码为 0.40.2 快照（缺本地新提交，如 analyzer 的 `missing_dependency` 守卫）。热修只覆盖本次两个文件，**镜像重建**应排入后续计划。

**回滚**：恢复备份文件 + `docker restart`；或回退镜像。DB 不受影响。

## 8. 验收标准

| 指标 | 目标 |
|---|---|
| `/api/wiki/graph`（冷） | ≤ 1.5s |
| `/api/wiki/graph`（热） | ≤ 0.5s |
| `/api/wiki/graph_analyze` | networkx 缺失时 ≤ 0.2s 返回 `missing_dependency`（新版） |
| 并发：graph 请求进行中，10 个 status 请求 | p95 ≤ 0.5s（不再排队） |
| 单测 | `pytest tests/test_v023_graph.py -q` 全绿 |
| 回归 | 图谱节点/边数与修复前一致（14,233 唯一边） |

**压测命令（示例）**

```bash
# 后台发 3 个 graph 请求，同时测 status
for i in 1 2 3; do curl -s -o /dev/null -H "Authorization: Bearer $PAT" \
  "https://8.133.234.138:8443/api/wiki/graph" & done
for i in $(seq 1 10); do curl -s -o /dev/null -w "%{time_total}\n" \
  -H "Authorization: Bearer $PAT" "https://8.133.234.138:8443/api/wiki/status"; done
```

## 9. 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 线程池并发导致内存上涨 | 低 | 单请求内存 <50MB；默认线程池 40 |
| relations 去重改变边权重 | 低 | 与 wikilink 语义一致；图谱节点/唯一边不变（14,233） |
| 热修与镜像代码漂移 | 中 | 后续重建镜像；文档记录补丁清单 |
| networkx 缺失仍调用 analyze | 低 | 新版快速返回；UI 不依赖该接口 |

## 10. 附录 A：复现脚本

```python
import sqlite3, time
c = sqlite3.connect('CKbase/.llmwikify.db'); c.row_factory = sqlite3.Row
rows = c.execute("SELECT source_page, target_page FROM page_links").fetchall()

# 现有实现
edges = []
t0 = time.time()
for r in rows:
    src, tgt = r["source_page"], r["target_page"]
    if not any(e["source"] == src and e["target"] == tgt and e["type"] == "wikilink" for e in edges):
        edges.append({"source": src, "target": tgt, "type": "wikilink", "weight": 1})
print("O(E^2):", round(time.time()-t0, 2), "edges:", len(edges))

# 修复版
edges, seen = [], {}
t0 = time.time()
for r in rows:
    key = (r["source_page"], r["target_page"], "wikilink")
    e = seen.get(key)
    if e: e["weight"] += 1
    else:
        e = {"source": key[0], "target": key[1], "type": "wikilink", "weight": 1}
        seen[key] = e; edges.append(e)
print("O(E):", round(time.time()-t0, 3), "edges:", len(edges))
```

## 11. 附录 B：关键代码位置与补丁清单

| 文件 | 位置 | 改动 |
|---|---|---|
| `src/llmwikify/kernel/graph/export.py` | `build_graph()`（13-73 行） | 字典去重（wikilink + relations） |
| `src/llmwikify/interfaces/server/http/wiki/wiki_routes.py` | 139-152、246-260 行 | `async def` → `def`（3 个图接口） |
| （可选）服务器 nginx 配置 | `/etc/nginx/conf.d/llmwikify.conf` | gzip |

## 12. 待评审决策

1. P1 缓存是否本次一并做？（建议先不做，观察 P0 效果）
2. nginx gzip 是否一并改？（影响全站，建议做）
3. 部署走 A（热修）还是等 B（重建镜像）？（建议 A 立即 + B 排期）

---

## 13. 实施记录

| 日期 | 内容 |
|---|---|
| 2026-10-22 | P0-1 + P0-2 本地实施；`tests/test_v023_graph.py` 增补去重回归，15 全绿；`scripts/check_architecture.py` 0 violation |
| 2026-10-22 | **WSL Docker 本地复现通过**（CKbase-test 1439 页 / 16869 链接 / 14233 唯一边）：算法层 O(E²) **2.86s → 0.007s（~423×）**；HTTP `/api/wiki/graph` **旧 3.05s → 新 0.20s**。本地 CPU 快于线上，故旧码为秒级而非 25s，量级关系一致 |
| 2026-10-22 | 注意：`/api/wiki/graph_analyze` 在安装 networkx 后为 **~145s**（PageRank/社区全量分析），与 O(E²) 无关，需另案限流/缓存/异步 |
| 2026-10-22 | **graph_analyze 指纹缓存**（P1）：`GraphAnalyzer.analyze` 按 pages/page_links/relations 指纹缓存，数据变更即失效；`force=1` 可强制重算。容器实测 **冷 ~135s → 热 ~0.008s**（约 1.7 万倍） |
| 2026-10-22 | **启动预热 + viz 缓存**：lifespan 后台线程预热 `graph_analyze`（实测预热后首击 **0.05s cached**）；`/api/wiki/graph` 与 analyze 共用指纹缓存，viz TTL **60s**（冷 0.68s → 热 0.008s） |
| 2026-10-22 | **建议多进程预热** → 剖析发现真瓶颈是 `_page_exists` 对每个节点 `rglob` 全库（O(n×files)，65s）。改为一次建 page-name set：`analyze` **135s → 2.1s**，预热无需多进程 |
| — | 服务器热修 / 镜像重建 |
