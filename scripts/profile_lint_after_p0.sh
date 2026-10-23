#!/bin/bash
set -u
NAME=llmwikify-prof2
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki \
  llmwikify-server:0.40.3-slim 3600
AP=$(docker exec "$NAME" python3 -c "import llmwikify.kernel.wiki.engines.analyzer as m; print(m.__file__)")
cp /mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/engines/analyzer.py /tmp/analyzer_p0.py
docker cp /tmp/analyzer_p0.py "$NAME:$AP"
echo patched="$AP"
cat > /tmp/p0prof.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
wiki = Wiki(Path("/app/wiki"))
t0 = time.perf_counter()
res = wiki.lint(mode="check", limit=5)
print("lint_once_s", round(time.perf_counter()-t0, 2), "issues", res.get("issue_count"))
t0 = time.perf_counter()
res = wiki.lint(mode="check", limit=5)
print("lint_twice_s", round(time.perf_counter()-t0, 2))
t0 = time.perf_counter()
wiki._analyzer._run_all_rules()
print("run_all_s", round(time.perf_counter()-t0, 2))
t0 = time.perf_counter()
wiki._analyzer._scan_all_pages()
print("scan_s", round(time.perf_counter()-t0, 2))
PY
docker cp /tmp/p0prof.py "$NAME:/tmp/p0prof.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/p0prof.py
docker rm -f "$NAME" >/dev/null
