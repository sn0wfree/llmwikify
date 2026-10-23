#!/bin/bash
# Rebuild slim 0.40.4 and verify cold/hot lint + quick API.
set -u
TAG=llmwikify-server:0.40.4-slim
CK=/mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase
NAME=llmwikify-v0404
cd /mnt/d/Github/llmwikify

echo "=== build $TAG ==="
DOCKER_BUILDKIT=1 docker build -f docker-tests/Dockerfile.production \
  -t "$TAG" -t llmwikify-server:latest . | tail -8

echo "=== identity ==="
docker run --rm --entrypoint python3 "$TAG" -c "import llmwikify; print('ver', llmwikify.__version__)"

echo "=== cold/hot lint on CKbase-test ==="
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v "$CK:/app/wiki:rw" -e WIKI_ROOT=/app/wiki "$TAG" 600
cat > /tmp/v404.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
wiki = Wiki(Path("/app/wiki"))
t0 = time.perf_counter()
r = wiki.lint(mode="check", limit=5)
print("lint_cold", round(time.perf_counter()-t0, 2), "cached", r.get("cached"), "issues", r.get("issue_count"))
t0 = time.perf_counter()
r = wiki.lint(mode="check", limit=5)
print("lint_hot", round(time.perf_counter()-t0, 4), "cached", r.get("cached"))
t0 = time.perf_counter()
r = wiki.lint(mode="check", limit=5)
print("lint_hot2", round(time.perf_counter()-t0, 4), "cached", r.get("cached"))
t0 = time.perf_counter()
g = wiki._detect_knowledge_gaps()
print("gaps", round(time.perf_counter()-t0, 4), "n", len(g))
PY
docker cp /tmp/v404.py "$NAME:/tmp/v404.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/v404.py
docker rm -f "$NAME" >/dev/null

echo "=== image size ==="
docker image ls "$TAG" --format '{{.Repository}}:{{.Tag}} {{.Size}}'
