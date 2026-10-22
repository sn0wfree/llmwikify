# Scripts

Standalone scripts for the llmwikify project.

> **Note:** These scripts are utilities, not part of the runtime. They run from the project root
> and add `src/` to `sys.path` so they can `import llmwikify.*`.

---

## Available Scripts

| Script | Purpose | Needs LLM? |
|---|---|---|
| `check_architecture.py` | Verify 4-layer architecture contracts | No |
| `check_prompt_principles.py` | Validate prompt design principles | No |
| `migrate_autoresearch_v3_to_v4.py` | AutoResearch migration helper | No |
| `unified_tutorial_generator.py` | Parse test files (AST) → generate TUTORIAL.md | No |
| `sync_to_server.sh` | 零停机 wiki 同步到生产服务器（rsync + 容器内 build-index） | No |
| `sync_relations.sh` | 同步知识图谱 relations/entity_aliases 到服务器（build-index 不重建） | No |
| `downgrade_to_v11513.sh` | Downgrade opencode to v1.15.13 (fix SPA 500 bug) | No |
| `install_opencode_fast.sh` | OpenCode 安装（加速 + mirror + SHA256 校验） | No |
| `install_opencode_manual.sh` | OpenCode 安装（本地 binary） | No |

---

## sync_to_server.sh

Zero-downtime wiki sync to a production llmwikify server:

- **本地只读**: rsync 源读取，不触碰内容 db / 不加锁 / 不影响本地生成
- **零停机**: 服务器端容器内 build-index 从 markdown 重建索引（~9s，服务不断）
- **幂等**: 二次运行 0 变更；排除 db/raw/管线目录/log.md/.sink/reference_index.json
- **配置外置**: `SYNC_HOST` 等经 `~/.llmwikify/sync_to_server.env` 或环境变量注入，
  仓库内零硬编码
- **并发安全**: 脚本顶部 flock 互斥锁，防 cron + 手动并发

> ⚠️ **cron 注意**：不要再在 crontab 外层包 `flock -n .../sync.lock`（与脚本内置锁冲突，
> 会导致每次启动即判定"另一实例在跑"并退出，静默跳过同步）。
>
> ⚠️ **图谱注意**：本脚本的服务器端 `build-index` 只重建 pages / page_links / pages_fts，
> **不重建 relations / entity_aliases**。每次同步必须追加：
>
> ```bash
> sync_to_server.sh && sync_relations.sh
> ```
>
> 完整运维手册见 [`docs/ops/kb-sync.md`](../docs/ops/kb-sync.md)。

---

## sync_relations.sh

把本地知识图谱同步到服务器内容库（`.llmwikify.db`）：

- **导出**: relations + entity_aliases → JSONL（显式列名，防 schema 漂移）
- **导入**: 服务器端单事务 `BEGIN IMMEDIATE → DELETE → INSERT → COMMIT`，
  `busy_timeout=5000`；WAL 下与在服进程并发安全，无需停服
- **预演**: `--dry-run` 只导出+上传，不写服务器 DB
- **验证**: 导入后打印计数与按 relation 类型分布，应与本地逐类一致
