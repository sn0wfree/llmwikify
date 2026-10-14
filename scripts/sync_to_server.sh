#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
# sync_to_server.sh — llmwikify wiki 零停机同步工具
#
# 特性:
#   · 本地只读    — 对本地 wiki 根只做 rsync 源读取; 不触碰内容数据库 /
#                   不加锁 / 不影响本地生成与运行中的服务
#   · 零停机      — 服务器端从 markdown 全量重建索引 (build-index),
#                   全程无需重启容器 (实测索引重建 ~9s, 服务不断)
#   · 不传输      — 内容数据库 / raw / 数据管线目录 / 备份文件
#   · 热生效      — wiki/*.md 到达即被读路径直接服务; build-index 后
#                   搜索/链接/页面列表同步刷新
#
# 配置 (二选一; 环境变量优先):
#   1) 本机配置文件 (推荐, 不入库): ~/.llmwikify/sync_to_server.env
#        SYNC_HOST="user@your-server"            # 必填
#        SYNC_BASE_URL="https://host:8443"       # 可选; 默认 https://<host>:8443
#        SYNC_LOCAL_ROOT="/path/to/wiki_root"    # 可选; 默认 ~/Public/CKbase
#        SYNC_REMOTE_ROOT="CKbase"               # 可选; 远端 ~ 下相对路径
#        SYNC_CONTAINER="llmwikify-server"       # 可选
#   2) 直接导出环境变量 SYNC_HOST / SYNC_BASE_URL / ...
#
# 命令:
#   ./sync_to_server.sh              增量同步 + 重建索引 + 验证 (日常)
#   ./sync_to_server.sh --dry-run    预演: 只显示会改什么, 不实际执行
#   ./sync_to_server.sh --prune      同步删除服务器上本地已删除的页面
#                                    (仅当服务器为纯发布镜像时使用!)
#   ./sync_to_server.sh --no-index   只同步文件, 跳过索引重建
#   ./sync_to_server.sh --help       显示本帮助
#
# 注意:
#   · wiki/log.md 各端独立维护, 不同步
#   · wiki/.sink/ 是查询产物, 不同步
#   · wiki/reference_index.json 由服务器 build-index 自行生成, 不同步
#   · 本地 wiki 根目录只读, 本脚本不写入其中任何文件
# ════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── 配置加载 (环境变量优先; 否则读本机配置文件) ──────────────────────
CONF_FILE="${SYNC_CONF:-$HOME/.llmwikify/sync_to_server.env}"
if [[ -f "$CONF_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONF_FILE"
fi

SYNC_HOST="${SYNC_HOST:-}"
LOCAL_ROOT="${SYNC_LOCAL_ROOT:-$HOME/Public/CKbase}"
REMOTE_ROOT="${SYNC_REMOTE_ROOT:-CKbase}"
CONTAINER="${SYNC_CONTAINER:-llmwikify-server}"
BASE_URL="${SYNC_BASE_URL:-}"
PAT_FILE="${SYNC_PAT_FILE:-$HOME/.llmwikify/pat}"

if [[ -z "$SYNC_HOST" ]]; then
  cat >&2 <<'EOF'
✗ 未配置同步目标 (SYNC_HOST)。二选一:
  方式 1 (推荐): 创建本机配置文件 ~/.llmwikify/sync_to_server.env:
      SYNC_HOST="user@your-server"
      SYNC_BASE_URL="https://your-server:8443"    # 可选
  方式 2: export SYNC_HOST=user@your-server
EOF
  exit 1
fi
[[ -z "$BASE_URL" ]] && BASE_URL="https://${SYNC_HOST##*@}:8443"

PRUNE=""
DRY=""
REINDEX=1
for arg in "$@"; do
  case "$arg" in
    --prune)    PRUNE="--delete" ;;
    --dry-run)  DRY="--dry-run" ;;
    --no-index) REINDEX=0 ;;
    --help|-h)  sed -n '2,46p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg (支持: --prune --dry-run --no-index --help)"; exit 2 ;;
  esac
done

echo "═══ wiki → 服务器   $(date '+%F %T') ═══"
echo "  本地 (只读):  $LOCAL_ROOT"
echo "  远端:         $SYNC_HOST:~/$REMOTE_ROOT"
[ -n "$PRUNE" ] && echo "  模式:         同步删除 (--prune)"
[ -n "$DRY" ]   && echo "  模式:         预演 (--dry-run)"
echo

# ── 预检 ────────────────────────────────────────────────────────────
[[ -d "$LOCAL_ROOT/wiki" ]] || { echo "✗ 本地 wiki/ 不存在: $LOCAL_ROOT/wiki"; exit 1; }
ssh -o BatchMode=yes -o ConnectTimeout=8 "$SYNC_HOST" true 2>/dev/null \
  || { echo "✗ SSH 不可达: $SYNC_HOST"; exit 1; }

# ── [1/3] 同步 wiki/ (增量; 权限一步到位: 目录 2775 文件 664 组 admin) ──
echo "── [1/3] rsync wiki/ ──"
rsync -a --info=stats2 ${DRY} ${PRUNE} \
  --chmod=D2775,F664 --group=admin \
  --exclude='log.md' --exclude='.sink/' --exclude='*.bak*' \
  --exclude='reference_index.json' \
  "$LOCAL_ROOT/wiki/" "$SYNC_HOST:$REMOTE_ROOT/wiki/"

# ── [2/3] 同步 wiki.md (schema) ─────────────────────────────────────
echo
echo "── [2/3] rsync wiki.md ──"
rsync -a --info=stats2 ${DRY} --chmod=F664 --group=admin \
  "$LOCAL_ROOT/wiki.md" "$SYNC_HOST:$REMOTE_ROOT/wiki.md"

# ── [3/3] 服务器端重建索引 (零停机) ─────────────────────────────────
if [[ "$REINDEX" == "1" && -z "$DRY" ]]; then
  echo
  echo "── [3/3] 服务器端重建索引 (容器内, ~20s, 服务不停) ──"
  ssh -o BatchMode=yes "$SYNC_HOST" \
    "docker exec $CONTAINER python -m llmwikify build-index" 2>&1 | tail -8
fi

# ── 验证 ────────────────────────────────────────────────────────────
if [[ -z "$DRY" && -f "$PAT_FILE" ]]; then
  echo
  echo "── 验证 (服务器 API) ──"
  curl -sS -m 10 -H "Authorization: Bearer $(cat "$PAT_FILE")" \
    "$BASE_URL/api/wiki/status" \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("  ✓ indexed_pages=%s  total_links=%s" % (d.get("indexed_pages"), d.get("total_links")))' \
    || echo "  ⚠ API 验证失败 (服务可能仍在重建, 稍后手动重试)"
fi

echo
if [[ -n "$DRY" ]]; then
  echo "预演完成 (未做任何变更)"
else
  echo "完成 → $BASE_URL   (浏览器 Ctrl+Shift+R 强制刷新可见最新内容)"
fi
