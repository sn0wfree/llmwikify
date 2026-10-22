#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
set -e
echo "=== docker load ==="
xz -dc /home/linlu/tmp/llmwikify-server-0.40.3-slim.tar.xz | docker load
echo "=== images ==="
docker image ls llmwikify-server
echo "=== new image inspect ==="
docker image inspect llmwikify-server:0.40.3-slim --format "id={{.Id}} created={{.Created}}"
echo "=== containers (must still be 0.40.2-slim healthy) ==="
docker ps -a --filter name=llmwikify --format "{{.Names}} {{.Status}} {{.Image}}"
echo "=== api ==="
curl -s -o /dev/null -w "api %{http_code}\n" --max-time 5 http://127.0.0.1:8765/api/health
'
