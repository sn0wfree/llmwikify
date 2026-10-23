#!/bin/bash
# Package, upload, load, switch to 0.40.4-slim; keep 0.40.3 for rollback.
set -u
export SSHPASS="${SSHPASS:?set SSHPASS}"
TAG=llmwikify-server:0.40.4-slim
RSSH=linlu@8.133.234.138
PKG=/mnt/c/Users/1/Documents/llmwikify-server-0.40.4-slim.tar.xz
REMOTE_PKG=/home/linlu/tmp/llmwikify-server-0.40.4-slim.tar.xz
SSH() { sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }
SCP() { sshpass -e scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }

echo "=== 1 save image ==="
docker image ls "$TAG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'
docker save "$TAG" | xz -T0 -c > "$PKG"
ls -lh "$PKG"

echo "=== 2 upload ==="
SSH "$RSSH" "mkdir -p /home/linlu/tmp"
SCP "$PKG" "$RSSH:$REMOTE_PKG"
SSH "$RSSH" "ls -lh $REMOTE_PKG"

echo "=== 3 load ==="
SSH "$RSSH" "xz -dc $REMOTE_PKG | docker load; docker image ls llmwikify-server"

echo "=== 4 switch compose (keep old image) ==="
SSH "$RSSH" 'bash -s' <<'EOS'
set -e
COMPOSE=/home/linlu/CKbase/deploy/docker-compose.yml
cp -a "$COMPOSE" "$COMPOSE.bak.$(date +%Y%m%d-%H%M%S)"
sed -i 's|image: llmwikify-server:0.40.[0-9]*-slim|image: llmwikify-server:0.40.4-slim|' "$COMPOSE"
grep image: "$COMPOSE"
# stop+rename old container to rollback name if present and running as llmwikify-server
if docker ps --format '{{.Names}}' | grep -qx llmwikify-server; then
  docker stop llmwikify-server || true
fi
# compose will recreate llmwikify-server; leave any bak container alone
cd /home/linlu/CKbase/deploy
docker compose up -d
sleep 10
for i in $(seq 1 15); do
  h=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-server 2>/dev/null || echo x)
  echo "health=$h"
  [ "$h" = healthy ] && break
  sleep 3
done
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "api %{http_code}\n" --max-time 10 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
curl -s -o /dev/null -w "graph %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/graph
docker exec llmwikify-server python3 -c "import llmwikify; print('ver', llmwikify.__version__)"
echo "--- inventory ---"
docker ps -a --filter name=llmwikify --format '{{.Names}} | {{.Status}} | {{.Image}}'
docker image ls llmwikify-server
EOS
echo DONE
