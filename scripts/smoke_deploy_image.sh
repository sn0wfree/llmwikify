#!/bin/bash
# Smoke 0.40.3 image with auth bootstrap (matches first-boot / empty volume).
set -euo pipefail
TAG=llmwikify-server:0.40.3
docker rm -f llmwikify-smoke 2>/dev/null || true
docker run -d --name llmwikify-smoke \
  --entrypoint /bin/bash \
  -e LLMWIKIFY_PUBLIC_READ=true \
  -p 127.0.0.1:8766:8765 \
  "$TAG" \
  -lc 'python3 -m llmwikify auth init --email smoke@local.test || true; exec python3 -m llmwikify serve --web --host 0.0.0.0 --port 8765'

for i in $(seq 1 25); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-smoke 2>/dev/null || echo missing)
  echo "try $i $s"
  [ "$s" = "healthy" ] && break
  sleep 3
done

docker exec llmwikify-smoke python3 -c "import llmwikify,pathlib; p=pathlib.Path(llmwikify.__file__).parents[5]/'ui/webui/dist/index.html'; print('version', llmwikify.__version__); print('webui', p.exists())"
curl -s -o /dev/null -w "health %{http_code} %{time_total}s\n" --max-time 15 http://127.0.0.1:8766/api/health || true
docker logs --tail 12 llmwikify-smoke 2>&1 | tail -12
docker rm -f llmwikify-smoke >/dev/null
