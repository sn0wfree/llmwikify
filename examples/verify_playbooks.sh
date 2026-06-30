#!/usr/bin/env bash
# examples/verify_playbooks.sh
#
# 跑所有不依赖 server / LLM 的剧本。04 需要先启 server，跳过。
#
# 用法：
#   bash examples/verify_playbooks.sh
#
# 退出码：所有剧本通过 = 0，任一失败 = 1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use python3 (python may not exist on all systems)
PYTHON="${PYTHON:-python3}"

PLAYBOOKS=(01_personal_reading_notes 02_company_research_kb
           03_multi_wiki_registry 05_paper_to_factor)
SKIPPED=(04_chat_sse_client)

PASS=0
FAIL=0

for pb in "${PLAYBOOKS[@]}"; do
    echo "===== $pb ====="
    if (cd "$pb" && PYTHONPATH=../.. "$PYTHON" play.py); then
        echo "✓ $pb passed"
        PASS=$((PASS + 1))
    else
        echo "✗ $pb FAILED"
        FAIL=$((FAIL + 1))
    fi
    echo
done

echo "===== Skipped (require running server) ====="
for s in "${SKIPPED[@]}"; do
    echo "⊘ $s"
done

echo
echo "Summary: $PASS passed, $FAIL failed"
exit "$FAIL"
