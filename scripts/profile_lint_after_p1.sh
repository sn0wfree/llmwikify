#!/bin/bash
set -u
NAME=llmwikify-prof3
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki \
  llmwikify-server:0.40.3-slim 3600
for f in \
  llmwikify/kernel/wiki/engines/analyzer.py \
  llmwikify/kernel/wiki/lint/rules/missing_cross_refs.py
do
  AP=$(docker exec "$NAME" python3 -c "import ${f//\//.}.x as m" 2>/dev/null || true)
done
A=$(docker exec "$NAME" python3 -c "import llmwikify.kernel.wiki.engines.analyzer as m; print(m.__file__)")
M=$(docker exec "$NAME" python3 -c "import llmwikify.kernel.wiki.lint.rules.missing_cross_refs as m; print(m.__file__)")
cp /mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/engines/analyzer.py /tmp/a.py
cp /mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/lint/rules/missing_cross_refs.py /tmp/m.py
docker cp /tmp/a.py "$NAME:$A"
docker cp /tmp/m.py "$NAME:$M"
echo patched
cat > /tmp/p1prof.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
wiki = Wiki(Path("/app/wiki"))
an = wiki._analyzer
t0 = time.perf_counter()
issues = an._run_rule("missing_cross_ref")
print("missing_cross_ref_s", round(time.perf_counter()-t0, 2), "n", len(issues))
t0 = time.perf_counter()
res = wiki.lint(mode="check", limit=5)
print("lint_s", round(time.perf_counter()-t0, 2), "issues", res.get("issue_count"))
PY
docker cp /tmp/p1prof.py "$NAME:/tmp/p1prof.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/p1prof.py
docker rm -f "$NAME" >/dev/null
