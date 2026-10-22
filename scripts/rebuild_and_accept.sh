#!/bin/bash
# Rebuild slim image with MCP + SPA fixes, then one-shot acceptance.
set -u
cd /mnt/d/Github/llmwikify
IMG=llmwikify-server:0.40.3-slim
NAME=llmwikify-acc
BASE=http://127.0.0.1:8766
PASS=0; FAIL=0
ok(){ echo "  PASS $1"; PASS=$((PASS+1)); }
bad(){ echo "  FAIL $1"; FAIL=$((FAIL+1)); }

echo "=== rebuild $IMG ==="
DOCKER_BUILDKIT=1 docker build -f docker-tests/Dockerfile.production \
  -t "$IMG" -t llmwikify-server:latest . | tail -8

echo "=== start container ==="
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint /bin/bash -e LLMWIKIFY_PUBLIC_READ=true \
  -p 127.0.0.1:8766:8765 "$IMG" -lc '
python3 -m llmwikify auth init --email acc@local.test || true
python3 -m llmwikify init --agent generic || true
mkdir -p /app/data/wiki/wiki/concepts
printf "%s\n" "---" "title: Alpha" "---" "" "# Alpha" "" "[[Beta]]" > /app/data/wiki/wiki/concepts/Alpha.md
printf "%s\n" "---" "title: Beta" "---" "" "# Beta" "" "[[Alpha]]" > /app/data/wiki/wiki/concepts/Beta.md
python3 -m llmwikify build-index || true
exec python3 -m llmwikify serve --web --host 0.0.0.0 --port 8765
'
for i in $(seq 1 35); do s=$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo x); [ "$s" = healthy ] && break; sleep 2; done
echo "health=$s"
[ "$s" = healthy ] && ok "container" || bad "container $s"

TOKEN=$(docker exec "$NAME" bash -c 'cat /home/llmuser/.llmwikify/pat' | tr -d '\n')
[ -n "$TOKEN" ] && ok "PAT" || bad "PAT"

echo "=== WebUI ==="
curl -s -o /tmp/idx -w "GET / %{http_code}\n" "$BASE/"
grep -q script /tmp/idx && ok "SPA shell" || bad "SPA shell"
ASSET=$(grep -oE '/assets/[^"]+\.js' /tmp/idx | head -1)
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE$ASSET"); [ "$code" = 200 ] && ok "asset" || bad "asset $code"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/docs"); [ "$code" = 200 ] && ok "docs" || bad "docs $code"
code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/openapi.json"); [ "$code" = 200 ] && ok "openapi" || bad "openapi $code"

echo "=== REST ==="
for u in /api/health /api/wiki/status /api/wiki/graph /api/wiki/graph_analyze /api/wiki/page/concepts/Alpha; do
  code=$(curl -s -o /tmp/r -w '%{http_code}' --max-time 60 -H "Authorization: Bearer $TOKEN" "$BASE$u")
  [ "$code" = 200 ] && ok "$u" || bad "$u $code"
done

echo "=== MCP ==="
curl -sD /tmp/mcp_hdrs -o /tmp/i -w "initialize %{http_code} %{content_type}\n" --max-time 25 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"acc","version":"0"}}}' \
  "$BASE/mcp/"
head -c 240 /tmp/i; echo
SID=$(grep -i 'mcp-session-id' /tmp/mcp_hdrs | awk '{print $2}' | tr -d '\r')
echo "sid=$SID"
grep -q protocolVersion /tmp/i && ok "MCP initialize" || bad "MCP initialize"
[ -n "${SID:-}" ] && ok "MCP session" || bad "MCP session"

curl -s -o /dev/null -w "initialized %{http_code}\n" --max-time 15 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' "$BASE/mcp/"

curl -s -o /tmp/t -w "tools/list %{http_code}\n" --max-time 25 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' "$BASE/mcp/"
python3 -c "import re;raw=open('/tmp/t','rb').read().decode('utf-8','replace');n=re.findall(r'\"name\"\s*:\s*\"([^\"]+)\"',raw);print('tools',len(n),n[:12]);open('/tmp/tools.txt','w').write('\n'.join(n))"
TC=$(wc -l < /tmp/tools.txt)
[ "$TC" -gt 0 ] && ok "MCP tools/list ($TC)" || bad "MCP tools/list"

TOOL=$(grep -E 'wiki_search|search|status' /tmp/tools.txt | head -1)
[ -z "$TOOL" ] && TOOL=$(head -1 /tmp/tools.txt)
echo "call $TOOL"
curl -s -o /tmp/c -w "tools/call %{http_code}\n" --max-time 30 \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' -H "Mcp-Session-Id: $SID" \
  -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"$TOOL\",\"arguments\":{}}}" \
  "$BASE/mcp/"
head -c 220 /tmp/c; echo
grep -qE 'result|content' /tmp/c && ok "MCP tools/call" || bad "MCP tools/call"

echo
echo "RESULT PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
