#!/bin/bash
set -u
NAME=llmwikify-b1
docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint sleep \
  -v /mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase:/app/wiki:rw \
  -e WIKI_ROOT=/app/wiki llmwikify-server:0.40.3-slim 300
cp /mnt/d/Github/llmwikify/src/llmwikify/kernel/graph/cache.py /tmp/cache.py
DST=$(docker exec "$NAME" python3 -c "import llmwikify.kernel.graph.cache as m; print(m.__file__)")
docker cp /tmp/cache.py "$NAME:$DST"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 -c "
import time
from pathlib import Path
from llmwikify.kernel.graph.cache import file_fingerprint
p=Path('/app/wiki/wiki')
if not p.exists():
    p=Path('/app/wiki')
t0=time.perf_counter(); fp=file_fingerprint(p); t1=time.perf_counter()-t0
t0=time.perf_counter(); fp=file_fingerprint(p); t2=time.perf_counter()-t0
print('fp_cold', round(t1,3), 'fp_warm', round(t2,3))
"
docker rm -f "$NAME" >/dev/null
