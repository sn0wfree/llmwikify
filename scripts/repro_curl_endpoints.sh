#!/bin/bash
set -u
BASE="${1:-http://127.0.0.1:8765}"
TOKEN="${2:-}"
if [ -z "$TOKEN" ] && [ -f /app/.llmwikify/pat ]; then
  TOKEN=$(tr -d '\n' < /app/.llmwikify/pat)
fi
AUTH=()
if [ -n "$TOKEN" ]; then
  AUTH=(-H "Authorization: Bearer ${TOKEN}")
fi
for p in /api/health /api/wiki/status /api/wiki/graph /api/wiki/graph_analyze; do
  curl -s -o /tmp/bench_body -w "$p %{http_code} %{time_total}s %{size_download}B\n" \
    --max-time 180 "${AUTH[@]}" "${BASE}${p}"
done
