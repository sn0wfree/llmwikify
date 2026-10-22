#!/bin/bash
set -euo pipefail
TAG=llmwikify-server:0.40.3-slim
OUT=/mnt/c/Users/1/Documents/llmwikify-server-0.40.3-slim.tar.xz

docker rm -f llmwikify-smoke 2>/dev/null || true
docker run -d --name llmwikify-smoke \
  --entrypoint /bin/bash \
  -e LLMWIKIFY_PUBLIC_READ=true \
  -p 127.0.0.1:8766:8765 \
  "$TAG" \
  -lc 'python3 -m llmwikify auth init --email smoke@local.test || true; exec python3 -m llmwikify serve --web --host 0.0.0.0 --port 8765'

for i in $(seq 1 25); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-smoke 2>/dev/null || echo missing)
  echo "health_try $i $s"
  [ "$s" = "healthy" ] && break
  sleep 3
done

docker exec llmwikify-smoke python3 -c 'import llmwikify, pathlib; print("ver", llmwikify.__version__); print("webui", pathlib.Path("/app/ui/webui/dist/index.html").exists())'
curl -s -o /dev/null -w "health %{http_code} %{time_total}s\n" --max-time 15 http://127.0.0.1:8766/api/health
docker rm -f llmwikify-smoke >/dev/null

echo "=== save $OUT ==="
docker save "$TAG" | xz -T0 -c > "$OUT"
ls -lh "$OUT"
docker image ls "$TAG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'
