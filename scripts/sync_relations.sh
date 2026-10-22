#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════
# sync_relations.sh — 把知识图谱（relations / entity_aliases）同步到服务器
#
# 为什么需要它：
#   sync_to_server.sh 的服务器端 build-index 只重建 pages / page_links /
#   pages_fts（从 markdown 解析），**不会重建 relations / entity_aliases**。
#   这两张表只存在于内容库 .llmwikify.db，不随 markdown 传输，因此每次
#   文件同步后必须单独跑本脚本，否则服务器会出现"页面新、图谱旧"。
#
# 机制：
#   1) 本地导出 relations + entity_aliases 为 JSONL（显式列名）
#   2) scp 到服务器 /tmp
#   3) 服务器端单事务导入（BEGIN IMMEDIATE → DELETE → INSERT → COMMIT，
#      busy_timeout=5000；WAL 下与在服进程并发安全，无需停服）
#   4) 校验计数并清理临时文件
#
# 配置：与 sync_to_server.sh 共用 ~/.llmwikify/sync_to_server.env
#   SYNC_HOST / SYNC_LOCAL_ROOT / SYNC_REMOTE_DB(默认 CKbase/.llmwikify.db)
#
# 用法：
#   ./sync_relations.sh            # 正式导入
#   ./sync_relations.sh --dry-run  # 只导出+上传，不写服务器 DB
# ════════════════════════════════════════════════════════════════════════
set -euo pipefail

CONF_FILE="${SYNC_CONF:-$HOME/.llmwikify/sync_to_server.env}"
if [[ -f "$CONF_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONF_FILE"
fi

SYNC_HOST="${SYNC_HOST:-}"
LOCAL_ROOT="${SYNC_LOCAL_ROOT:-$HOME/Public/CKbase}"
REMOTE_DB="${SYNC_REMOTE_DB:-CKbase/.llmwikify.db}"
LOCAL_DB="${LOCAL_ROOT}/.llmwikify.db"
DRY=""

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --help|-h) sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg (支持: --dry-run --help)"; exit 2 ;;
  esac
done

[[ -n "$SYNC_HOST" ]] || { echo "✗ 未配置 SYNC_HOST（见 sync_to_server.env）"; exit 1; }
[[ -f "$LOCAL_DB" ]] || { echo "✗ 本地内容库不存在: $LOCAL_DB"; exit 1; }

echo "═══ relations → 服务器   $(date '+%F %T') ═══"
echo "  本地: $LOCAL_DB"
echo "  远端: $SYNC_HOST:~/$REMOTE_DB"
[ -n "$DRY" ] && echo "  模式: 预演（不写服务器 DB）"
echo

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

# ── [1/4] 本地导出 ─────────────────────────────────────────────────
echo "── [1/4] 导出本地图谱 ──"
python3 - "$LOCAL_DB" "$TMP_DIR" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

db, out = sys.argv[1], Path(sys.argv[2])
rels_cols = ["source", "target", "relation", "confidence",
             "source_file", "context", "wiki_pages", "created_at"]
alias_cols = ["alias", "canonical", "confidence", "source", "created_at"]

conn = sqlite3.connect(db)
rels = [dict(zip(rels_cols, r)) for r in
        conn.execute("SELECT " + ",".join(rels_cols) + " FROM relations")]
aliases = [dict(zip(alias_cols, r)) for r in
           conn.execute("SELECT " + ",".join(alias_cols) + " FROM entity_aliases")]
conn.close()

(out / "relations.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in rels), encoding="utf-8")
(out / "entity_aliases.jsonl").write_text(
    "\n".join(json.dumps(r, ensure_ascii=False) for r in aliases), encoding="utf-8")
print(f"  exported: relations={len(rels)}, entity_aliases={len(aliases)}")
PY

# ── [2/4] 上传 ────────────────────────────────────────────────────
echo "── [2/4] 上传到服务器 /tmp ──"
scp -q "$TMP_DIR/relations.jsonl" "$TMP_DIR/entity_aliases.jsonl" "$SYNC_HOST:/tmp/"
echo "  uploaded"

if [[ -n "$DRY" ]]; then
  echo
  echo "预演完成（文件已上传 /tmp 供检查，未写服务器 DB）"
  exit 0
fi

# ── [3/4] 服务器端事务导入 ────────────────────────────────────────
echo "── [3/4] 服务器端事务导入 ──"
ssh -o BatchMode=yes "$SYNC_HOST" python3 - "$REMOTE_DB" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

arg = sys.argv[1]
db = arg if arg.startswith("/") else str(Path.home() / arg)
rels = [json.loads(line) for line in
        Path("/tmp/relations.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
aliases = [json.loads(line) for line in
           Path("/tmp/entity_aliases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]

conn = sqlite3.connect(db, timeout=10)
conn.execute("PRAGMA busy_timeout=5000")
cur = conn.cursor()
cur.execute("BEGIN IMMEDIATE")
cur.execute("DELETE FROM relations")
cur.executemany(
    "INSERT INTO relations (source,target,relation,confidence,source_file,context,wiki_pages,created_at) "
    "VALUES (?,?,?,?,?,?,?,?)",
    [(r["source"], r["target"], r["relation"], r["confidence"],
      r["source_file"], r["context"], r["wiki_pages"], r["created_at"]) for r in rels])
cur.execute("DELETE FROM entity_aliases")
cur.executemany(
    "INSERT INTO entity_aliases (alias,canonical,confidence,source,created_at) VALUES (?,?,?,?,?)",
    [(r["alias"], r["canonical"], r["confidence"], r["source"], r["created_at"])
     for r in aliases])
conn.commit()

n_rel = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
n_alias = conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0]
print(f"  imported: relations={n_rel}, entity_aliases={n_alias}")
print("  by relation:")
for rel, n in conn.execute(
        "SELECT relation, COUNT(*) FROM relations GROUP BY relation ORDER BY 2 DESC"):
    print(f"    {rel}: {n}")
conn.close()
PY

# ── [4/4] 清理 ────────────────────────────────────────────────────
echo "── [4/4] 清理服务器临时文件 ──"
ssh -o BatchMode=yes "$SYNC_HOST" 'rm -f /tmp/relations.jsonl /tmp/entity_aliases.jsonl'
echo "  cleaned"
echo
echo "完成 → 图谱已同步（如需核对 API：/api/wiki/status 的 graph_stats.total_relations）"
