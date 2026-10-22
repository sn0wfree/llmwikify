#!/bin/bash
# A/B: old O(E^2) vs fixed build_graph on HTTP /api/wiki/graph
set -euo pipefail
REPO=/mnt/d/Github/llmwikify
cd "$REPO"

wait_healthy() {
  local i s
  for i in $(seq 1 15); do
    s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
    if [ "$s" = "healthy" ]; then echo "healthy"; return 0; fi
    sleep 3
  done
  echo "not_healthy:$s"; return 1
}

EP=$(docker exec llmwikify-repro python -c "import llmwikify.kernel.graph.export as m; print(m.__file__)")
echo "export_path=$EP"

wait_healthy
TOKEN=$(docker exec llmwikify-repro cat /app/.llmwikify/pat | tr -d '\n')
echo "token_len=${#TOKEN}"

echo "=== FIXED ==="
for p in /api/wiki/status /api/wiki/graph; do
  curl -s -o /dev/null -w "FIXED $p %{http_code} %{time_total}s %{size_download}B\n" \
    --max-time 180 -H "Authorization: Bearer ${TOKEN}" \
    "http://127.0.0.1:8765${p}"
done

echo "=== swap to OLD ==="
git -C "$REPO" show 6f44e8b8^:src/llmwikify/kernel/graph/export.py > /tmp/export_old.py
docker cp /tmp/export_old.py "llmwikify-repro:$EP"
docker restart llmwikify-repro >/dev/null
wait_healthy

echo "=== OLD ==="
for p in /api/wiki/status /api/wiki/graph; do
  curl -s -o /dev/null -w "OLD $p %{http_code} %{time_total}s %{size_download}B\n" \
    --max-time 180 -H "Authorization: Bearer ${TOKEN}" \
    "http://127.0.0.1:8765${p}"
done

echo "=== restore FIXED ==="
git -C "$REPO" show 6f44e8b8:src/llmwikify/kernel/graph/export.py > /tmp/export_fixed.py
docker cp /tmp/export_fixed.py "llmwikify-repro:$EP"
docker restart llmwikify-repro >/dev/null
wait_healthy
echo DONE
