#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
echo "=== container ==="
docker ps --filter name=llmwikify-server --format "{{.Names}} {{.Status}} {{.Image}}"
echo "=== health ==="
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "health %{http_code} %{time_total}s\n" --max-time 15 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
curl -s -o /dev/null -w "status %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/status
curl -s -o /dev/null -w "graph %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/graph
echo "=== logs tail ==="
docker logs --tail 15 llmwikify-server 2>&1
'
