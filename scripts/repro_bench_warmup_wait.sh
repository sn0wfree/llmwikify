#!/bin/bash
set -euo pipefail
docker restart llmwikify-repro >/dev/null
for i in $(seq 1 10); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
  [ "$s" = "healthy" ] && break
  sleep 3
done
echo "health=$s"
echo "waiting 160s for warmup..."
sleep 160
echo "--- logs ---"
docker logs --tail 50 llmwikify-repro 2>&1 | grep -iE 'warmup|graph_analyze' || echo "(no warmup line)"
TOKEN=$(docker exec llmwikify-repro cat /app/.llmwikify/pat | tr -d '\n')
curl -s -o /tmp/a -w "analyze %{http_code} %{time_total}s\n" \
  --max-time 300 -H "Authorization: Bearer ${TOKEN}" \
  "http://127.0.0.1:8765/api/wiki/graph_analyze"
python3 -c "import json;d=json.load(open('/tmp/a'));print('status',d.get('status'),'cached',d.get('cached'))"
