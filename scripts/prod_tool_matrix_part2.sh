#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 'docker exec -i llmwikify-server python3 -' <<'PY'
import httpx, json, time, sys

PAT = open("/app/.llmwikify/pat").read().strip()
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

c = httpx.Client(timeout=600.0)
r = c.post(BASE, headers=HEADERS, json={
    "jsonrpc": "2.0", "id": 0, "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {},
               "clientInfo": {"name": "toolcheck-prod2", "version": "0"}}
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

# remaining matrix (lint limit=1 to keep under timeout; gaps already done)
tests = [
    ("wiki_lint", {"limit": 1}),
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
print(f"\nPART2 ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
