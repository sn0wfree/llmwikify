#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
set -e
echo "=== docker load ==="
xz -dc /home/linlu/tmp/llmwikify-server-0.40.4-slim.tar.xz | docker load
docker image ls llmwikify-server
echo "=== switch compose ==="
COMPOSE=/home/linlu/CKbase/deploy/docker-compose.yml
cp -a "$COMPOSE" "$COMPOSE.bak.$(date +%Y%m%d-%H%M%S)"
sed -i "s|image: llmwikify-server:0.40.[0-9]*-slim|image: llmwikify-server:0.40.4-slim|" "$COMPOSE"
grep image: "$COMPOSE"
cd /home/linlu/CKbase/deploy
docker compose up -d
sleep 12
for i in 1 2 3 4 5 6 7 8 9 10; do
  h=$(docker inspect -f "{{.State.Health.Status}}" llmwikify-server 2>/dev/null || echo x)
  echo "health=$h"
  [ "$h" = healthy ] && break
  sleep 3
done
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "api %{http_code}\n" --max-time 10 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
curl -s -o /dev/null -w "graph %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/graph
docker exec llmwikify-server python3 -c "import llmwikify; print(\"ver\", llmwikify.__version__)"
echo "=== inventory ==="
docker ps -a --filter name=llmwikify --format "{{.Names}} | {{.Status}} | {{.Image}}"
'
