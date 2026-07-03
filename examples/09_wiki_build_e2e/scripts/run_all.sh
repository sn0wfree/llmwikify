#!/bin/bash
# examples/09_wiki_build_e2e/scripts/run_all.sh
# Run all 4 e2e scripts in order. Exit 0 only if all pass.
#
# Usage:
#   bash examples/09_wiki_build_e2e/scripts/run_all.sh
#
# In Docker (set by e2e-entrypoint.sh via TEST_SCRIPT), this file is
# exec'd directly. On a host, you can also run it manually.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================="
echo " llmwikify e2e suite (00 -> 03)"
echo "=========================================="

for s in 00_install_check.py 01_cli_only.py 02_chat_sse.py 03_agent_real.py; do
    echo
    echo "▶ Running $s"
    echo "------------------------------------------"
    python3 "$SCRIPT_DIR/$s"
    echo "✅ $s passed"
done

echo
echo "=========================================="
echo " All 4 e2e scripts passed."
echo "=========================================="
