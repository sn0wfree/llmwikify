#!/bin/bash
# Bench from inside the container (avoids WSL/docker publish quirks).
set -u
TOKEN=$(tr -d '\n' < /app/.llmwikify/pat)
echo "token_len=${#TOKEN}"
for p in /api/health /api/wiki/status /api/wiki/graph /api/wiki/graph_analyze; do
  curl -s -o /tmp/bench_body -w "$p %{http_code} %{time_total}s %{size_download}B\n" \
    --max-time 180 -H "Authorization: Bearer ${TOKEN}" \
    "http://127.0.0.1:8765${p}"
done
