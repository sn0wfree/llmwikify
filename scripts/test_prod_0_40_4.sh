#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 'docker exec -i llmwikify-server python3 -' <<'PY'
import httpx, json, time, sys

PAT = open("/app/.llmwikify/pat").read().strip()
BASE = "http://127.0.0.1:8765/"
H = {
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
        return {"raw": text[:200]}

c = httpx.Client(timeout=300.0)

print("=== REST ===")
for p in ("api/health", "api/wiki/status", "api/wiki/graph", "api/wiki/graph_analyze"):
    t0 = time.time()
    r = c.get(BASE + p, headers={"Authorization": f"Bearer {PAT}"})
    print(f"{p:24s} {r.status_code} {time.time()-t0:.3f}s {len(r.content)}B")

print("=== MCP session ===")
r = c.post(BASE + "mcp/", headers=H, json={
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "check-0404", "version": "0"}}
})
sid = r.headers.get("mcp-session-id")
H["mcp-session-id"] = sid
c.post(BASE + "mcp/", headers=H, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
print("sid", sid)

_id = [0]
def call(name, args):
    _id[0] += 1
    t0 = time.time()
    r = c.post(BASE + "mcp/", headers=H, json={
        "jsonrpc": "2.0", "id": _id[0], "method": "tools/call",
        "params": {"name": name, "arguments": args},
    })
    el = time.time() - t0
    d = parse_sse(r.text)
    if "error" in d:
        return "RPC_ERR", el, str(d["error"])[:80]
    res = d.get("result") or {}
    content = res.get("content") or []
    text = content[0].get("text") or "" if content else json.dumps(res, ensure_ascii=False)[:120]
    return ("TOOL_ERR" if res.get("isError") else "OK"), el, text

tests = [
    ("wiki_status", {}),
    ("wiki_read_schema", {}),
    ("wiki_read_page", {"page_name": "index"}),
    ("wiki_search", {"query": "尿素", "limit": 3}),
    ("wiki_references", {"page_name": "index"}),
    ("wiki_graph", {}),
    ("wiki_graph_analyze", {}),
    ("wiki_recommend", {}),
    ("wiki_suggest_synthesis", {}),
    ("wiki_sink_status", {}),
    ("wiki_analyze_source", {"source_path": "raw/nonexistent_probe.pdf"}),
    ("wiki_lint", {"limit": 5}),
    ("wiki_lint", {"limit": 5}),
    ("wiki_knowledge_gaps", {}),
]
print(f"{'tool':28s} {'st':8s} {'el':>7s}  summary")
print("-" * 100)
ok = fail = 0
for name, args in tests:
    st, el, text = call(name, args)
    print(f"{name:28s} {st:8s} {el:7.2f}s  {text[:50].replace(chr(10),' ')}")
    ok += st == "OK"
    fail += st != "OK"
c.request("DELETE", BASE + "mcp/", headers=H)
print(f"\nTOTAL ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
