#!/bin/bash
set -euo pipefail
REPO=/mnt/d/Github/llmwikify
WP=$(docker exec llmwikify-repro python -c "import llmwikify.interfaces.server.http.wiki.wiki_routes as m; print(m.__file__)")
cp "$REPO/src/llmwikify/interfaces/server/http/wiki/wiki_routes.py" /tmp/routes_new.py
docker cp /tmp/routes_new.py "llmwikify-repro:$WP"
docker restart llmwikify-repro >/dev/null
for i in $(seq 1 15); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
  [ "$s" = "healthy" ] && break
  sleep 3
done
TOKEN=$(docker exec llmwikify-repro cat /app/.llmwikify/pat | tr -d '\n')
for label in after_restart force force_again; do
  url="http://127.0.0.1:8765/api/wiki/graph_analyze"
  [ "$label" != "after_restart" ] && url="$url?force=1"
  curl -s -o /tmp/analyze_body -w "$label %{http_code} %{time_total}s\n" \
    --max-time 300 -H "Authorization: Bearer ${TOKEN}" "$url"
  python3 -c "import json;d=json.load(open('/tmp/analyze_body'));print('  status',d.get('status'),'cached',d.get('cached'))"
done
