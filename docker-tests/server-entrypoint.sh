#!/bin/bash
# docker-tests/server-entrypoint.sh
# llmwikify server container entry point.

set -e

echo "=== llmwikify Server ==="
echo "Python:  $(python3 --version 2>&1)"
echo "Date:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "TZ:      ${TZ:-UTC}"
echo "Wiki:    ${WIKI_ROOT}"
echo "Host:    ${HOST:-0.0.0.0}:${PORT:-8765}"
echo "Auth:    ${AUTH_TOKEN:+set (${#AUTH_TOKEN} chars)}${AUTH_TOKEN:-disabled}"
echo "LLM:     ${LLM_PROVIDER:-minimax} / ${LLM_MODEL:-minimax-M3}"
echo "=================================="

# Ensure wiki root exists
mkdir -p "${WIKI_ROOT}"

# Run the server
exec python -m llmwikify "$@"
