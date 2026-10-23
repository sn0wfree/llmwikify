#!/bin/bash
set -u
NAME=llmwikify-core-cache
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki llmwikify-server:0.40.4-slim 300
A=$(docker exec "$NAME" python3 -c "import llmwikify.kernel.wiki.engines.analyzer as m; print(m.__file__)")
cp /mnt/d/Github/llmwikify/src/llmwikify/kernel/wiki/engines/analyzer.py /tmp/a.py
docker cp /tmp/a.py "$NAME:$A"
cat > /tmp/corecache.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
wiki = Wiki(Path("/app/wiki"))
for label, kwargs in [
    ("lint_geninv_1", dict(generate_investigations=True)),
    ("lint_geninv_2", dict(generate_investigations=True)),
    ("lint_plain_1", dict()),
    ("lint_plain_2", dict()),
    ("lint_geninv_3", dict(generate_investigations=True)),
]:
    t0 = time.perf_counter()
    r = wiki.lint(mode="check", limit=5, **kwargs)
    print(f"{label:16s} {time.perf_counter()-t0:7.2f}s cached={r.get('cached')}")
PY
docker cp /tmp/corecache.py "$NAME:/tmp/corecache.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/corecache.py
docker rm -f "$NAME" >/dev/null
