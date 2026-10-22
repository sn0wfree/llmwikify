#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
# sync_all.sh — 一键完整同步：markdown/索引 + 知识图谱
#
# 为什么需要它：
#   sync_to_server.sh 只负责 wiki/*.md 与服务器端 build-index；
#   build-index 不会重建 relations/entity_aliases（见 docs/ops/kb-sync.md）。
#   两步必须按顺序执行，cron 也应调用本脚本而不是只调 sync_to_server.sh。
#
# 用法：
#   ./sync_all.sh            # 文件同步（含服务器 build-index）+ 图谱同步
#   ./sync_all.sh --dry-run  # 预演：文件只列变更；图谱只导出+上传，不写 DB
# ════════════════════════════════════════════════════════════════════════
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

"$DIR/sync_to_server.sh" "$@"
"$DIR/sync_relations.sh" "$@"
