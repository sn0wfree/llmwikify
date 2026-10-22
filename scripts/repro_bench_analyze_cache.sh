#!/bin/bash
# Hot-patch analyzer cache and measure graph_analyze cold vs warm.
set -euo pipefail
REPO=/mnt/d/Github/llmwikify
AP=$(docker exec llmwikify-repro python -c "import llmwikify.kernel.graph.analyzer as m; print(m.__file__)")
echo "analyzer_path=$AP"

cp "$REPO/src/llmwikify/kernel/graph/analyzer.py" /tmp/analyzer_new.py
cp "$REPO/src/llmwikify/kernel/wiki/mixins/analysis/relation.py" /tmp/relation_new.py
RP=$(docker exec llmwikify-repro python -c "import llmwikify.kernel.wiki.mixins.analysis.relation as m; print(m.__file__)")
docker cp /tmp/analyzer_new.py "llmwikify-repro:$AP"
docker cp /tmp/relation_new.py "llmwikify-repro:$RP"
docker restart llmwikify-repro >/dev/null

for i in $(seq 1 15); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
  [ "$s" = "healthy" ] && break
  sleep 3
done
echo "health=$s"

TOKEN=$(docker exec llmwikify-repro cat /app/.llmwikify/pat | tr -d '\n')
for label in cold warm warm2; do
  curl -s -o /tmp/analyze_body -w "$label %{http_code} %{time_total}s %{size_download}B\n" \
    --max-time 300 -H "Authorization: Bearer ${TOKEN}" \
    "http://127.0.0.1:8765/api/wiki/graph_analyze"
  python3 -c "import json;d=json.load(open('/tmp/analyze_body'));print('  status',d.get('status'),'cached',d.get('cached'))"
done

echo "--- force=1 ---"
curl -s -o /tmp/analyze_body -w "force %{http_code} %{time_total}s\n" \
  --max-time 300 -H "Authorization: Bearer ${TOKEN}" \
  "http://127.0.0.1:8765/api/wiki/graph_analyze?force=1"
python3 -c "import json;d=json.load(open('/tmp/analyze_body'));print('  status',d.get('status'),'cached',d.get('cached'))"
