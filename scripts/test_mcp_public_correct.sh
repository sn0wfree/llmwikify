#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 'bash -s' <<'EOS'
set -u
PAT=$(cat /home/linlu/.llmwikify/pat | tr -d '\n')
BASE="https://8.133.234.138:8443/mcp/"
echo "BASE=$BASE"
curl -sD /tmp/h -o /tmp/i -w "init %{http_code} %{time_total}s\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"pub","version":"0"}}}'
SID=$(grep -i mcp-session-id /tmp/h | awk '{print $2}' | tr -d '\r')
echo "SID=${SID:-none}"
grep -q protocolVersion /tmp/i && echo "initialize_body_ok" || echo "initialize_body_BAD"
curl -s -o /dev/null -w "initialized %{http_code}\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl -s -o /tmp/t -w "tools/list %{http_code}\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
python3 -c "import re;raw=open('/tmp/t').read();n=re.findall(r'\"name\"\s*:\s*\"([^\"]+)\"',raw);print('tools',len(n),n[:6])"
curl -s -o /tmp/c -w "call %{http_code} %{time_total}s\n" -X POST "$BASE" \
  -H "Authorization: Bearer $PAT" -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"wiki_status","arguments":{}}}'
head -c 180 /tmp/c; echo
curl -s -o /dev/null -w "DELETE %{http_code}\n" -X DELETE "$BASE" \
  -H "Authorization: Bearer $PAT" -H "Mcp-Session-Id: $SID"
EOS
