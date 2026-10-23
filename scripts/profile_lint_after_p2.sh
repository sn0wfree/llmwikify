#!/bin/bash
set -u
NAME=llmwikify-prof4
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki \
  llmwikify-server:0.40.3-slim 3600
for pair in \
  "llmwikify.kernel.graph.cache:/mnt/d/Github/llmwikify/src/llmwikify/kernel/graph/cache.py" \
  "llmwikify.kernel.wiki.engines.analyzer:/mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/engines/analyzer.py" \
  "llmwikify.kernel.wiki.lint.rules.missing_cross_refs:/mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/lint/rules/missing_cross_refs.py"
do
  mod="${pair%%:*}"; src="${pair#*:}"
  dst=$(docker exec "$NAME" python3 -c "import $mod as m; print(m.__file__)")
  cp "$src" /tmp/hot.py
  docker cp /tmp/hot.py "$NAME:$dst"
  echo "ok $mod"
done
cat > /tmp/p2prof.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
wiki = Wiki(Path("/app/wiki"))
t0 = time.perf_counter()
r1 = wiki.lint(mode="check", limit=5)
print("lint1", round(time.perf_counter()-t0, 2), "cached", r1.get("cached"))
t0 = time.perf_counter()
r2 = wiki.lint(mode="check", limit=5)
print("lint2", round(time.perf_counter()-t0, 3), "cached", r2.get("cached"))
t0 = time.perf_counter()
r3 = wiki.lint(mode="check", limit=5, force=True)
print("lint_force", round(time.perf_counter()-t0, 2), "cached", r3.get("cached"))
PY
docker cp /tmp/p2prof.py "$NAME:/tmp/p2prof.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/p2prof.py
docker rm -f "$NAME" >/dev/null
