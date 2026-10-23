#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
echo "=== all llmwikify containers ==="
docker ps -a --filter name=llmwikify --format "{{.Names}} | {{.Status}} | {{.Image}}"
echo "=== bak inspect ==="
docker inspect llmwikify-server-bak-0.40.2 --format "image={{.Config.Image}} status={{.State.Status}} exit={{.State.ExitCode}}" 2>&1 || echo bak_missing
echo "=== current ==="
docker inspect llmwikify-server --format "image={{.Config.Image}} status={{.State.Status}} health={{.State.Health.Status}}"
echo "=== compose image ==="
grep image: /home/linlu/CKbase/deploy/docker-compose.yml
echo "=== api ==="
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "health %{http_code}\n" -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
'
