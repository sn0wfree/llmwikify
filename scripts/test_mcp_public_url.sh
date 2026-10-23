#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
# Test MCP via public HTTPS URL (as external client would).
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 'bash -s' <<'EOS'
set -u
PAT=$(cat /home/linlu/.llmwikify/pat | tr -d '\n')
BASE="https://8.133.234.138:8443/mcp/mcp/"
echo "=== 1 initialize ==="
curl -sD /tmp/mcp_h -o /tmp/mcp_i -w "http %{http_code} %{time_total}s\n" \
  -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl-check","version":"0"}}}'
echo "--- headers (session) ---"
grep -i mcp-session-id /tmp/mcp_h || echo "NO SESSION HEADER"
echo "--- body ---"
head -c 300 /tmp/mcp_i; echo
SID=$(grep -i mcp-session-id /tmp/mcp_h | awk '{print $2}' | tr -d '\r')
echo "SID=$SID"

echo "=== 2 initialized ==="
curl -s -o /dev/null -w "http %{http_code}\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

echo "=== 3 tools/list ==="
curl -s -o /tmp/mcp_t -w "http %{http_code}\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
python3 -c "import re;raw=open('/tmp/mcp_t').read();n=re.findall(r'\"name\"\s*:\s*\"([^\"]+)\"',raw);print('tools',len(n),n[:8])"

echo "=== 4 tools/call wiki_status ==="
curl -s -o /tmp/mcp_c -w "http %{http_code} %{time_total}s\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"wiki_status","arguments":{}}}'
head -c 200 /tmp/mcp_c; echo

echo "=== 5 DELETE session ==="
curl -s -o /dev/null -w "http %{http_code}\n" -X DELETE "$BASE" \
  -H "Authorization: Bearer $PAT" \
  -H "Mcp-Session-Id: $SID"

echo "=== 6 wrong path check (should not be HTML) ==="
curl -s -o /tmp/mcp_w -w "http %{http_code} ctype=%{content_type}\n" -X POST \
  "https://8.133.234.138:8443/mcp/" \
  -H "Authorization: Bearer $PAT" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"x","version":"0"}}}'
head -c 120 /tmp/mcp_w; echo
EOS
