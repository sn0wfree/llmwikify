#!/bin/bash
# Full matrix with data on WSL-native disk (closer to server I/O).
set -u
IMG=llmwikify-server:0.40.3-slim
NAME=llmwikify-mcpcheck
CK_SRC=/mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase
CK=/tmp/ckbase-mcpcheck
WORKDIR=/tmp/mcpcheck-$$
mkdir -p "$WORKDIR"

if [ ! -d "$CK/wiki" ]; then
  echo "copying test KB to $CK ..."
  mkdir -p "$CK"
  cp -a "$CK_SRC/wiki" "$CK_SRC/wiki.md" "$CK_SRC/.llmwikify.db" "$CK/" 2>/dev/null || true
fi
echo "kb: $(find $CK/wiki -name '*.md' | wc -l) md files"

docker rm -f "$NAME" 2>/dev/null || true
docker run -d --name "$NAME" --entrypoint /bin/bash \
  -e LLMWIKIFY_PUBLIC_READ=true -e WIKI_ROOT=/app/wiki \
  -p 127.0.0.1:8766:8765 -v "$CK:/app/wiki:rw" \
  "$IMG" -lc 'python3 -m llmwikify auth init --email mcpcheck@local.test || true; exec python3 -m llmwikify serve --web --host 0.0.0.0 --port 8765' >/dev/null

for i in $(seq 1 40); do
  s=$(docker inspect -f '{{.State.Health.Status}}' "$NAME" 2>/dev/null || echo x)
  [ "$s" = healthy ] && break
  sleep 2
done
echo "health=$s"

cat > "$WORKDIR/toolcheck.py" <<'PY'
import httpx, json, time, sys

PAT = open("/home/llmuser/.llmwikify/pat").read().strip()
BASE = "http://127.0.0.1:8765/mcp/"
HEADERS = {
    "Authorization": f"Bearer {PAT}",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

def parse_sse(text):
    data = None
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[6:]
    try:
        return json.loads(data if data is not None else text)
    except Exception:
        return {"raw": text[:300]}

c = httpx.Client(timeout=300.0)
r = c.post(BASE, headers=HEADERS, json={
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "toolcheck-local", "version": "0"}}
})
sid = r.headers.get("mcp-session-id")
H = dict(HEADERS)
if sid:
    H["mcp-session-id"] = sid
c.post(BASE, headers=H, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
print(f"session_id={sid}")

_id = [0]
def call(name, args):
    _id[0] += 1
    t0 = time.time()
    r = c.post(BASE, headers=H, json={
        "jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    el = time.time() - t0
    d = parse_sse(r.text)
    if "error" in d:
        return "RPC_ERR", el, str(d["error"])[:100]
    res = d.get("result") or {}
    content = res.get("content") or []
    text = content[0].get("text") or "" if content else json.dumps(res, ensure_ascii=False)[:200]
    return ("TOOL_ERR" if res.get("isError") else "OK"), el, text

tests = [
    ("wiki_status", {}),
    ("wiki_read_schema", {}),
    ("wiki_read_page", {"page_name": "index"}),
    ("wiki_read_page", {"page_name": "metrics/尿素企业库存"}),
    ("wiki_search", {"query": "尿素", "limit": 3}),
    ("wiki_references", {"page_name": "index"}),
    ("wiki_knowledge_gaps", {}),
    ("wiki_lint", {"limit": 5}),
    ("wiki_graph", {}),
    ("wiki_graph_analyze", {}),
    ("wiki_recommend", {}),
    ("wiki_suggest_synthesis", {}),
    ("wiki_sink_status", {}),
    ("wiki_analyze_source", {"source_path": "raw/nonexistent_probe.pdf"}),
]

print(f"{'tool':28s} {'st':8s} {'el':>6s} {'size':>7s}  summary")
print("-" * 110)
ok = fail = 0
for name, args in tests:
    st, el, text = call(name, args)
    summary = text[:55].replace("\n", " ").replace("  ", " ")
    print(f"{name:28s} {st:8s} {el:6.1f}s {len(text):>7}  {summary}")
    if st == "OK":
        ok += 1
    else:
        fail += 1

try:
    c.request("DELETE", BASE, headers=H)
    print("session_deleted")
except Exception as e:
    print("session_delete", e)
print(f"\nTOTAL ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY

docker cp "$WORKDIR/toolcheck.py" "$NAME:/tmp/toolcheck.py"
echo "=== tool matrix ==="
docker exec "$NAME" python3 /tmp/toolcheck.py
RC=$?
echo "ver=$(docker exec "$NAME" python3 -c 'import llmwikify;print(llmwikify.__version__)')"
docker rm -f "$NAME" >/dev/null
exit $RC
