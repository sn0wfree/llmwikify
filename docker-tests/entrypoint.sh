#!/bin/bash
# docker-tests/entrypoint.sh
# Test runner entry point for llmwikify Docker test image.

set -e

echo "=== llmwikify Test Runner ==="
echo "Python:  $(python3 --version 2>&1)"
echo "Date:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "TZ:      ${TZ:-UTC}"
echo "LLM:     ${LLM_PROVIDER:-minimax} / ${LLM_MODEL:-minimax-M3}"
echo "API key: ${LLM_API_KEY:+set (${#LLM_API_KEY} chars)}${LLM_API_KEY:-NOT SET}"
echo "Workdir: $(pwd)"
echo "=================================="

# Prepare test results dir
mkdir -p /app/test-results

# Default pytest args if no args passed
if [ $# -eq 0 ]; then
    set -- pytest tests/scenarios/ -v --tb=short \
        --junit-xml=/app/test-results/junit.xml
fi

exec "$@"
