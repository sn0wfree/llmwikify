#!/bin/bash
# Build production deploy image (WebUI + full extras) and save for upload.
set -euo pipefail
cd /mnt/d/Github/llmwikify
TAG="${1:-llmwikify-server:0.40.3}"
OUT="${2:-/tmp/llmwikify-server-0.40.3.tar.xz}"

export DOCKER_BUILDKIT=1
echo "=== build $TAG ==="
docker build -f docker-tests/Dockerfile.production \
  -t "$TAG" -t llmwikify-server:latest .

echo "=== smoke: image layers ==="
docker image ls "$TAG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'

echo "=== smoke: run container ==="
docker rm -f llmwikify-smoke 2>/dev/null || true
docker run -d --name llmwikify-smoke \
  -e LLMWIKIFY_PUBLIC_READ=true \
  -p 127.0.0.1:8766:8765 \
  "$TAG"
for i in $(seq 1 30); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-smoke 2>/dev/null || echo missing)
  if [ "$s" = "healthy" ]; then echo "smoke health=healthy"; break; fi
  if [ "$s" = "unhealthy" ]; then echo "smoke UNHEALTHY"; docker logs --tail 30 llmwikify-smoke; break; fi
  sleep 3
done
docker exec llmwikify-smoke python3 -c "import llmwikify, pathlib; p=pathlib.Path(llmwikify.__file__).parents[5]/'ui/webui/dist/index.html'; print('webui', p, p.exists())" || true
docker logs --tail 15 llmwikify-smoke 2>&1 | tail -15
docker rm -f llmwikify-smoke >/dev/null

echo "=== save $OUT ==="
docker save "$TAG" | xz -T0 -c > "$OUT"
ls -lh "$OUT"
echo DONE
