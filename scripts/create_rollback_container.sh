#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
set -e
NAME=llmwikify-rollback-0.40.2
# recreate stopped rollback snapshot from old image if missing
if ! docker ps -a --format "{{.Names}}" | grep -qx "$NAME"; then
  docker create --name "$NAME" \
    -e WIKI_ROOT=/app/wiki \
    -e LLMWIKIFY_HOME=/app \
    -e HOME=/app \
    -e LLMWIKIFY_PUBLIC_READ=false \
    -e TZ=Asia/Shanghai \
    -p 127.0.0.1:8765:8765 \
    -v /home/linlu/CKbase:/app/wiki:rw \
    -v /home/linlu/.llmwikify:/app/.llmwikify:rw \
    --restart unless-stopped \
    llmwikify-server:0.40.2-slim \
    serve --web --host 0.0.0.0 --port 8765
fi
echo "=== containers ==="
docker ps -a --filter name=llmwikify --format "{{.Names}} | {{.Status}} | {{.Image}}"
echo "=== images ==="
docker image ls llmwikify-server
echo "=== running ==="
docker ps --filter name=llmwikify-server --format "{{.Names}} | {{.Status}} | {{.Image}}"
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "api %{http_code}\n" -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
'
