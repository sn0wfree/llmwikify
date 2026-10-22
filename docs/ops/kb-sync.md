# 知识库同步到服务器（Ops Runbook）

> 适用：CKbase 研报知识库（本地 `~/Public/CKbase`）→ 生产服务器（`linlu@8.133.234.138:~/CKbase`，容器 `llmwikify-server`）
> 脚本：`scripts/sync_to_server.sh`（文件+索引）、`scripts/sync_relations.sh`（知识图谱）
> 最近修订：2026-10-22

---

## 1. 数据分层：哪些会同步、哪些必须重建

| 层 | 存放位置 | 同步方式 | 说明 |
|---|---|---|---|
| 页面正文（源真相） | `wiki/**/*.md` + `wiki.md` | rsync 增量 | 页面/观点/指标/品种/sector 全部是 markdown |
| 全文索引（pages / page_links / pages_fts） | 内容库 `.llmwikify.db` | **服务器端 build-index 重建** | `build_index_from_files()`：先 DELETE 三张表，再从 md 重新解析 |
| 参考索引（`index.md` / `reference_index.json`） | `wiki/` | build-index 生成 | `reference_index.json` 不参与 rsync（服务器自行生成） |
| **知识图谱（relations）** | 内容库 `.llmwikify.db` | **不随 md 同步、build-index 也不重建** | 必须用 `sync_relations.sh` 显式导入 |
| 实体别名（entity_aliases） | 同上 | 同上 | 随 relations 一起导入 |
| `log.md` | `wiki/log.md` | **不同步** | 各端独立维护 |
| `raw/`、`reports_pipeline/`、`.sink/`、`*.bak*` | — | **不同步** | 数据管线与备份不进服务器 |

**结论：同步 = ① rsync markdown → ② 服务器 build-index（自动）→ ③ relations/aliases 导入（手动脚本）→ ④ 验证。**

## 2. 正常流程（日常）

```bash
# ① + ②（脚本自带服务器 build-index 与 API 验证）
~/llmwikify/scripts/sync_to_server.sh

# ③ 图谱（build-index 不覆盖 relations，必须单独跑）
~/llmwikify/scripts/sync_relations.sh
```

- 预演：`sync_to_server.sh --dry-run` / `sync_relations.sh --dry-run`
- `--prune` 仅在服务器为纯发布镜像时使用（默认不删除服务器文件）
- 预计耗时：文件同步秒级 + build-index ~20-50s（零停机）+ 图谱事务 <1s

## 3. 验证基线（2026-10-22）

| 指标 | 期望值（本地=服务器） |
|---|---|
| 页面数（md） | 1439 |
| `pages` / `page_links` | 1439 / 16869 |
| `relations` | 6073（按 relation 类型分布与本地逐类一致） |
| `entity_aliases` | 4 |

验证命令：

```bash
# 服务器 API
curl -sS -H "Authorization: Bearer $(cat ~/.llmwikify/pat)" \
  https://8.133.234.138:8443/api/wiki/status \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["page_count"], d["indexed_pages"], d["total_links"], d["graph_stats"]["total_relations"])'

# 服务器文件数
ssh linlu@8.133.234.138 'find ~/CKbase/wiki -name "*.md" | wc -l'

# 服务器 DB 计数
ssh linlu@8.133.234.138 python3 -c "
import sqlite3, pathlib
c = sqlite3.connect(str(pathlib.Path.home()/'CKbase/.llmwikify.db'))
print('pages', c.execute('select count(*) from pages').fetchone()[0])
print('links', c.execute('select count(*) from page_links').fetchone()[0])
print('relations', c.execute('select count(*) from relations').fetchone()[0])"
```

## 4. 已知故障与修复（避免复发）

### 4.1 cron 双重 flock（2026-10-13 ~ 10-22，8 天未同步）
crontab 外层 `flock -n .../sync.lock` 与脚本内部 `exec 9>lock; flock -n 9` **同一把锁** →
脚本启动即判定"另一个实例在跑"并退出 0，日志只留 `[!] 另一个同步实例正在跑`。
**修复**：crontab 只保留脚本内置锁，不要外层再包 flock。

### 4.2 rsync 会把 0 字节占位 DB 带到服务器
本地 `wiki/.llmwikify.db`、`wiki/index.db` 是 0 字节占位文件；同步脚本的 exclude 未覆盖 `*.db`，
会在服务器 `wiki/` 下新建同名空文件（当前无害，但存在误覆盖风险）。
**修复**：`sync_to_server.sh` 的 rsync 已增加 `--exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm'`。

### 4.3 build-index 不重建图谱
`build_index_from_files()` 只清空/重建 `pages`、`page_links`、`pages_fts`，**不触碰 `relations`**。
长期只跑 `sync_to_server.sh` 会造成"页面新、图谱旧"。
**修复**：每次同步固定追加 `sync_relations.sh`。

## 5. 回滚

```bash
# 服务器 DB 备份（执行同步前必须做）
ssh linlu@8.133.234.138 'cp ~/CKbase/.llmwikify.db ~/CKbase/.llmwikify.db.bak.$(date +%Y%m%d-%H%M%S)'

# 回滚 = 还原备份 + 重建索引
ssh linlu@8.133.234.138 'cp ~/CKbase/.llmwikify.db.bak.<ts> ~/CKbase/.llmwikify.db'
ssh linlu@8.133.234.138 'docker exec llmwikify-server python -m llmwikify build-index'
```

markdown 为增量覆盖、只增不删（未使用 `--prune`），回滚页面只需重新同步旧版本文件。

## 6. 安全边界

- 本地 `wiki/` 只读；脚本不写本地任何文件
- 不同步 `.llmwikify.db`（内容库）→ 避免 WAL 一致性问题；服务器索引由 md 重建
- relations 导入使用**单事务**（`BEGIN IMMEDIATE … COMMIT`）+ `busy_timeout=5000`，WAL 下与在服进程并发安全
- 同步期间不要并行跑批量解析（避免 md 半写状态）
