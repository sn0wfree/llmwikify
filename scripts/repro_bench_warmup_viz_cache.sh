#!/bin/bash
# Verify analyze warmup + viz cache in the repro container.
set -euo pipefail
REPO=/mnt/d/Github/llmwikify

AP=$(docker exec llmwikify-repro python -c "import llmwikify.kernel.graph.analyzer as m; print(m.__file__)")
GRAPH_DIR=$(dirname "$AP")
cp "$REPO/src/llmwikify/kernel/graph/cache.py" /tmp/cache.py
docker cp /tmp/cache.py "llmwikify-repro:$GRAPH_DIR/cache.py"
echo "copied cache.py -> $GRAPH_DIR/cache.py"

for mod in \
  "llmwikify.kernel.graph.analyzer:$REPO/src/llmwikify/kernel/graph/analyzer.py" \
  "llmwikify.kernel.graph.visualizer:$REPO/src/llmwikify/kernel/graph/visualizer.py" \
  "llmwikify.interfaces.server.core:$REPO/src/llmwikify/interfaces/server/core.py"
do
  name="${mod%%:*}"
  src="${mod#*:}"
  path=$(docker exec llmwikify-repro python -c "import $name as m; print(m.__file__)")
  cp "$src" "/tmp/$(basename "$src")"
  docker cp "/tmp/$(basename "$src")" "llmwikify-repro:$path"
  echo "patched $name"
done

docker restart llmwikify-repro >/dev/null
for i in $(seq 1 20); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
  [ "$s" = "healthy" ] && break
  sleep 3
done
echo "health=$s"
echo "waiting 160s for warmup thread (full analyze is ~135s)..."
sleep 160
docker logs --tail 50 llmwikify-repro 2>&1 | grep -i 'warmup\|graph_analyze' || true

TOKEN=$(docker exec llmwikify-repro cat /app/.llmwikify/pat | tr -d '\n')
echo "=== graph (viz cache) ==="
for i in 1 2 3; do
  curl -s -o /tmp/g -w "viz#$i %{http_code} %{time_total}s\n" \
    --max-time 60 -H "Authorization: Bearer ${TOKEN}" \
    "http://127.0.0.1:8765/api/wiki/graph"
  python3 -c "import json;d=json.load(open('/tmp/g'));print('  cached',d.get('cached'),'nodes',d.get('stats',{}).get('total_nodes'))"
done

echo "=== graph_analyze (expect warm/cached after warmup) ==="
curl -s -o /tmp/a -w "analyze %{http_code} %{time_total}s\n" \
  --max-time 300 -H "Authorization: Bearer ${TOKEN}" \
  "http://127.0.0.1:8765/api/wiki/graph_analyze"
python3 -c "import json;d=json.load(open('/tmp/a'));print('  status',d.get('status'),'cached',d.get('cached'))"
