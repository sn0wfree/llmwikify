#!/bin/bash
set -u
NAME=llmwikify-s4
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki llmwikify-server:0.40.3-slim 300
for pair in \
  "llmwikify.kernel.graph.cache:/mnt/d/Github/llmwikify/src/llmwikify/kernel/graph/cache.py" \
  "llmwikify.kernel.wiki.engines.analyzer:/mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/engines/analyzer.py"
do
  mod="${pair%%:*}"; src="${pair#*:}"
  dst=$(docker exec "$NAME" python3 -c "import $mod as m; print(m.__file__)")
  cp "$src" /tmp/h.py && docker cp /tmp/h.py "$NAME:$dst"
done
cat > /tmp/s4.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
from llmwikify.kernel.graph.cache import cache_invalidate
wiki = Wiki(Path("/app/wiki"))
t0=time.perf_counter(); r=wiki.lint(mode="check", limit=5); t1=time.perf_counter()-t0
print("lint1", round(t1,2), "cached", r.get("cached"))
t0=time.perf_counter(); r=wiki.lint(mode="check", limit=5); t2=time.perf_counter()-t0
print("lint2", round(t2,4), "cached", r.get("cached"))
t0=time.perf_counter(); r=wiki.lint(mode="check", limit=5); t3=time.perf_counter()-t0
print("lint3", round(t3,4), "cached", r.get("cached"))
# simulate external write
p = wiki.wiki_dir / "wiki" / "concepts" / "Alpha.md"
if not p.exists():
    p = wiki.wiki_dir / "concepts" / "Alpha.md"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("# Alpha changed\n", encoding="utf-8")
# file write bypasses put_page → force via invalidate (watcher would do this)
cache_invalidate()
t0=time.perf_counter(); r=wiki.lint(mode="check", limit=5); t4=time.perf_counter()-t0
print("lint_after_invalidate", round(t4,2), "cached", r.get("cached"))
PY
docker cp /tmp/s4.py "$NAME:/tmp/s4.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/s4.py
docker rm -f "$NAME" >/dev/null
