#!/bin/bash
# One-shot acceptance: WebUI + REST + MCP on 0.40.3-slim
set -u
BASE=http://127.0.0.1:8766
IMG=llmwikify-server:0.40.3-slim
NAME=llmwikify-acc
PASS=0; FAIL=0
ok(){ echo "  PASS $1"; PASS=$((PASS+1)); }
bad(){ echo "  FAIL $1"; FAIL=$((FAIL+1)); }

docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" \
  --entrypoint /bin/bash \
  -e LLMWIKIFY_PUBLIC_READ=true \
  -p 127.0.0.1:8766:8765 \
  "$IMG" -lc '
python3 -m llmwikify auth init --email acc@local.test || true
python3 -m llmwikify init --agent generic || true
mkdir -p /app/data/wiki/wiki/concepts
printf "%s\n" "---" "title: Alpha" "---" "" "# Alpha" "" "[[Beta]]" > /app/data/wiki/wiki/concepts/Alpha.md
printf "%s\n" "---" "title: Beta" "---" "" "# Beta" "" "[[Alpha]]" > /app/data/wiki/wiki/concepts/Beta.md
python3 -m llmwikify build-index || true
exec python3 -m llmwikify serve --web --host 0.0.0.0 --port 8765
'

for i in $(seq 1 30); do
  s=$(docker inspect -f "{{.State.Health.Status}}" "$NAME" 2>/dev/null || echo missing)
  [ "$s" = "healthy" ] && break
  sleep 2
done
echo "container_health=$s"
if [ "$s" = "healthy" ]; then ok "container healthy"; else bad "container health=$s"; fi

# PAT lives under the runtime user's home
TOKEN=$(docker exec "$NAME" bash -c 'cat /home/llmuser/.llmwikify/pat 2>/dev/null || cat /app/.llmwikify/pat 2>/dev/null' | tr -d "\n")
echo "token_len=${#TOKEN}"
if [ -n "$TOKEN" ]; then ok "PAT present"; else bad "PAT missing"; fi

echo "=== WebUI ==="
code=$(curl -s -o /tmp/idx.html -w "%{http_code}" --max-time 20 "$BASE/")
if [ "$code" = "200" ]; then ok "GET / 200"; else bad "GET / $code"; fi
if grep -qi "script\|root" /tmp/idx.html; then ok "SPA shell"; else bad "SPA shell"; fi
ASSET=$(grep -oE "/assets/[^\"]+\.js" /tmp/idx.html | head -1)
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$BASE$ASSET")
if [ "$code" = "200" ]; then ok "JS asset $ASSET"; else bad "JS asset $code"; fi
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$BASE/docs")
if [ "$code" = "200" ]; then ok "GET /docs 200"; else bad "GET /docs $code"; fi
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$BASE/openapi.json")
if [ "$code" = "200" ]; then ok "GET /openapi.json 200"; else bad "openapi $code"; fi

echo "=== REST (Bearer PAT) ==="
for u in /api/health /api/wiki/status /api/wiki/graph /api/wiki/graph_analyze; do
  code=$(curl -s -o /tmp/r.json -w "%{http_code}" --max-time 60 -H "Authorization: Bearer ${TOKEN}" "$BASE$u")
  if [ "$code" = "200" ]; then ok "GET $u"; else bad "GET $u $code"; fi
done
if grep -q "status\|nodes\|pages" /tmp/r.json; then ok "graph_analyze payload"; else bad "graph_analyze payload"; fi

# discover page route from openapi
curl -s "$BASE/openapi.json" -o /tmp/oa.json
python3 - <<'PY'
import json
d=json.load(open("/tmp/oa.json"))
pages=[p for p in d.get("paths",{}) if "/page" in p]
print("page_paths", pages)
open("/tmp/page_paths.txt","w").write("\n".join(pages))
PY

# try page read using first matching path pattern
PAGE=$(head -1 /tmp/page_paths.txt | sed 's/{page_name.*//' )
for name in "concepts/Alpha" "Alpha" "concepts%2FAlpha"; do
  code=$(curl -s -o /tmp/pg -w "%{http_code}" --max-time 15 -H "Authorization: Bearer ${TOKEN}" "${BASE}${PAGE}${name}")
  echo "  probe ${PAGE}${name} -> $code"
  if [ "$code" = "200" ]; then ok "page read $name"; break; fi
done

echo "=== MCP ==="
# 307 -> /mcp/
code=$(curl -sI --max-time 10 "$BASE/mcp" | head -1 | tr -d "\r")
echo "  HEAD /mcp $code"
code=$(curl -sL -o /tmp/mcp_init -w "%{http_code}" --max-time 25 \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"acc","version":"0"}}}' \
  "$BASE/mcp/")
echo "  initialize $code"
head -c 220 /tmp/mcp_init; echo
if [ "$code" = "200" ]; then ok "MCP initialize"; else bad "MCP initialize $code"; fi

code=$(curl -sL -o /tmp/mcp_tools -w "%{http_code}" --max-time 25 \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
  "$BASE/mcp/")
echo "  tools/list $code"
python3 - <<'PY'
import re
raw=open("/tmp/mcp_tools","rb").read().decode("utf-8","replace")
names=re.findall(r'"name"\s*:\s*"([^"]+)"', raw)
print("  tools_count", len(names))
print("  tools_sample", names[:12])
open("/tmp/tool_names.txt","w").write("\n".join(names))
print("  raw", raw[:180].replace("\n"," "))
PY
TC=$(wc -l < /tmp/tool_names.txt)
if [ "$code" = "200" ] && [ "$TC" -gt 0 ]; then ok "MCP tools/list ($TC)"; else bad "MCP tools/list code=$code count=$TC"; fi

# pick a read tool to call
TOOL=$(grep -E "wiki_search|search|wiki_status|status" /tmp/tool_names.txt | head -1)
if [ -z "$TOOL" ]; then TOOL=$(head -1 /tmp/tool_names.txt); fi
echo "  calling tool=$TOOL"
if [ -n "$TOOL" ]; then
  code=$(curl -sL -o /tmp/mcp_call -w "%{http_code}" --max-time 30 \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d "{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"${TOOL}\",\"arguments\":{}}}" \
    "$BASE/mcp/")
  echo "  tools/call $TOOL $code"
  head -c 220 /tmp/mcp_call; echo
  if [ "$code" = "200" ]; then ok "MCP tools/call"; else bad "MCP tools/call $code"; fi
fi

echo "=== identity ==="
docker exec "$NAME" python3 -c "import llmwikify,pathlib; print('ver',llmwikify.__version__); print('webui',pathlib.Path('/app/ui/webui/dist/index.html').exists())"

echo
echo "RESULT PASS=$PASS FAIL=$FAIL"
exit $FAIL
