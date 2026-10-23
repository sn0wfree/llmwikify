#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
set -e
echo "=== restart to clear CPU block ==="
docker restart llmwikify-server
for i in $(seq 1 20); do
  h=$(docker inspect -f "{{.State.Health.Status}}" llmwikify-server 2>/dev/null || echo x)
  echo "health=$h"
  [ "$h" = healthy ] && break
  sleep 3
done
TOKEN=$(cat /home/linlu/.llmwikify/pat | tr -d "\n")
curl -s -o /dev/null -w "health %{http_code} %{time_total}s\n" --max-time 15 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/health
curl -s -o /dev/null -w "graph %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/graph
curl -s -o /dev/null -w "status %{http_code} %{time_total}s\n" --max-time 30 -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8765/api/wiki/status
echo "=== fast MCP tools only ==="
docker exec -i llmwikify-server python3 - <<PY
import httpx, json, time, sys
PAT = open("/app/.llmwikify/pat").read().strip()
BASE = "http://127.0.0.1:8765/mcp/"
H = {"Authorization": f"Bearer {PAT}", "Content-Type": "application/json",
     "Accept": "application/json, text/event-stream"}
def parse_sse(text):
    data=None
    for line in text.splitlines():
        if line.startswith("data:"): data=line[6:]
    try: return json.loads(data if data is not None else text)
    except Exception: return {"raw": text[:200]}
c=httpx.Client(timeout=60)
r=c.post(BASE, headers=H, json={"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"0"}}})
sid=r.headers.get("mcp-session-id"); H["mcp-session-id"]=sid
c.post(BASE, headers=H, json={"jsonrpc":"2.0","method":"notifications/initialized"})
def call(name, args):
    t0=time.time()
    r=c.post(BASE, headers=H, json={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":name,"arguments":args}})
    el=time.time()-t0
    d=parse_sse(r.text)
    res=d.get("result") or {}
    text=(res.get("content") or [{}])[0].get("text") or ""
    return ("TOOL_ERR" if res.get("isError") else "OK"), el, text[:40]
tests=[("wiki_status",{}),("wiki_read_schema",{}),("wiki_read_page",{"page_name":"index"}),
       ("wiki_search",{"query":"尿素","limit":3}),("wiki_graph",{}),("wiki_graph_analyze",{}),
       ("wiki_recommend",{}),("wiki_suggest_synthesis",{}),("wiki_sink_status",{}),
       ("wiki_analyze_source",{"source_path":"raw/nonexistent_probe.pdf"})]
ok=fail=0
for n,a in tests:
    st,el,t=call(n,a)
    print(f"{n:24s} {st:8s} {el:6.2f}s  {t}")
    ok += st=="OK"; fail += st!="OK"
c.request("DELETE", BASE, headers=H)
print(f"FAST_TOOLS ok={ok} fail={fail}")
sys.exit(1 if fail else 0)
PY
'
