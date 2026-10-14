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
