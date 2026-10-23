#!/bin/bash
# Switch to 0.40.3-slim; KEEP old container stopped+renamed for rollback.
# Does NOT docker rm the old container.
set -u
export SSHPASS="${SSHPASS:?set SSHPASS}"
SSH() { sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }
RSSH=linlu@8.133.234.138

SSH "$RSSH" 'bash -s' <<'EOS'
set -euo pipefail
COMPOSE_DIR=/home/linlu/CKbase/deploy
COMPOSE=$COMPOSE_DIR/docker-compose.yml
OLD=llmwikify-server
BAK=llmwikify-server-bak-0.40.2
NEW_TAG=llmwikify-server:0.40.3-slim

echo "=== 0 snapshot ==="
docker ps --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'
cp -a "$COMPOSE" "$COMPOSE.bak.$(date +%Y%m%d-%H%M%S)"
echo "compose backed up"

echo "=== 1 stop + rename old (keep for rollback) ==="
if docker ps -a --format '{{.Names}}' | grep -qx "$OLD"; then
  docker stop "$OLD"
  # if bak already exists, leave it; rename current to bak
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$BAK"; then
    docker rename "$OLD" "$BAK"
  else
    echo "WARN $BAK already exists; leaving $OLD stopped"
  fi
fi
echo "-- stopped/renamed --"
docker ps -a --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'

echo "=== 2 compose image -> 0.40.3-slim ==="
sed -i 's|image: llmwikify-server:0.40.2-slim|image: llmwikify-server:0.40.3-slim|' "$COMPOSE"
grep -n 'image:' "$COMPOSE"

echo "=== 3 compose up new ==="
cd "$COMPOSE_DIR"
docker compose up -d
sleep 8
docker ps --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'

echo "=== 4 verify ==="
for i in 1 2 3 4 5 6 7 8 9 10; do
  h=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-server 2>/dev/null || echo x)
  echo "health=$h"
  [ "$h" = healthy ] && break
  sleep 3
done
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d '\n')
curl -s -o /dev/null -w "api_health %{http_code}\n" --max-time 10 \
  -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
curl -s -o /dev/null -w "graph %{http_code} %{time_total}s\n" --max-time 30 \
  -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/graph
docker exec llmwikify-server python3 -c "import llmwikify; print('ver', llmwikify.__version__)"

echo "=== 5 inventory for rollback ==="
docker ps -a --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'
echo "DONE"
EOS
