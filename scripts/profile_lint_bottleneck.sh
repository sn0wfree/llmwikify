#!/bin/bash
# Segment profile of current lint path (P0+P1+P2 code).
set -u
NAME=llmwikify-bottleneck
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
  cp "$src" /tmp/hot.py && docker cp /tmp/hot.py "$NAME:$dst"
done
cat > /tmp/bottleneck.py <<'PY'
import time
from pathlib import Path
from llmwikify.kernel.wiki.wiki import Wiki
from llmwikify.kernel.graph.cache import combined_fingerprint

wiki = Wiki(Path("/app/wiki"))
an = wiki._analyzer

def T(label, fn):
    t0 = time.perf_counter()
    r = fn()
    el = time.perf_counter() - t0
    extra = ""
    if isinstance(r, (list, dict, set)):
        extra = f" n={len(r)}"
    print(f"{label:32s} {el:7.2f}s{extra}")
    return r

print("=== cold components ===")
T("file_fingerprint", lambda: combined_fingerprint(wiki.index.conn, wiki.wiki_dir))
T("_wiki_pages rglob", lambda: wiki._wiki_pages())
T("_scan_all_pages", lambda: an._scan_all_pages())
rules = an._lint_engine.rule_names
for name in rules:
    T(f"rule:{name}", lambda n=name: an._run_rule(n))
T("_run_all_rules", lambda: an._run_all_rules())
T("_build_lint_context", lambda: an._build_lint_context())
T("_llm/fallback_gaps", lambda: an._fallback_detect_gaps())
T("_generate_hints", lambda: an._generate_hints())
T("wiki.lint cold", lambda: wiki.lint(mode="check", limit=5))
T("wiki.lint warm", lambda: wiki.lint(mode="check", limit=5))
T("wiki.lint warm2", lambda: wiki.lint(mode="check", limit=5))
T("knowledge_gaps cold", lambda: wiki._detect_knowledge_gaps())
T("knowledge_gaps warm", lambda: wiki._detect_knowledge_gaps())
print("=== done ===")
PY
docker cp /tmp/bottleneck.py "$NAME:/tmp/bottleneck.py"
docker exec -e WIKI_ROOT=/app/wiki "$NAME" python3 /tmp/bottleneck.py
docker rm -f "$NAME" >/dev/null
