#!/bin/bash
# 0.40.5: build slim → package → upload → deploy → compare test
set -u
export SSHPASS="${SSHPASS:?set SSHPASS}"
TAG=llmwikify-server:0.40.5-slim
PKG=/mnt/c/Users/1/Documents/llmwikify-server-0.40.5-slim.tar.xz
RSSH=linlu@8.133.234.138
REMOTE_PKG=/home/linlu/tmp/llmwikify-server-0.40.5-slim.tar.xz
SSH() { sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }
SCP() { sshpass -e scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }

cd /mnt/d/Github/llmwikify
echo "=== build ==="
DOCKER_BUILDKIT=1 docker build -f docker-tests/Dockerfile.production -t "$TAG" -t llmwikify-server:latest . | tail -6
docker run --rm --entrypoint python3 "$TAG" -c "import llmwikify; print('ver', llmwikify.__version__)"

echo "=== save ==="
docker save "$TAG" | xz -T0 -c > "$PKG"
ls -lh "$PKG"

echo "=== upload ==="
SCP "$PKG" "$RSSH:$REMOTE_PKG"
SSH "$RSSH" "ls -lh $REMOTE_PKG"

echo "=== load + switch ==="
SSH "$RSSH" 'bash -s' <<EOS
set -e
xz -dc $REMOTE_PKG | docker load
COMPOSE=/home/linlu/CKbase/deploy/docker-compose.yml
cp -a "\$COMPOSE" "\$COMPOSE.bak.\$(date +%Y%m%d-%H%M%S)"
sed -i 's|image: llmwikify-server:0.40.[0-9]*-slim|image: $TAG|' "\$COMPOSE"
grep image: "\$COMPOSE"
cd /home/linlu/CKbase/deploy
docker compose up -d
sleep 12
for i in 1 2 3 4 5 6 7 8; do
  h=\$(docker inspect -f '{{.State.Health.Status}}' llmwikify-server 2>/dev/null || echo x)
  echo health=\$h
  [ "\$h" = healthy ] && break
  sleep 3
done
TOKEN=\$(cat /home/linlu/.llmwikify/pat | tr -d '\n')
curl -s -o /dev/null -w "api %{http_code}\n" --max-time 10 -H "Authorization: Bearer \$TOKEN" http://127.0.0.1:8765/api/health
docker exec llmwikify-server python3 -c "import llmwikify; print('ver', llmwikify.__version__)"
docker ps -a --filter name=llmwikify --format '{{.Names}} | {{.Status}} | {{.Image}}'
EOS

echo "=== compare test ==="
SSH "$RSSH" 'docker exec -i llmwikify-server python3 -' <<'PY'
import httpx, json, time, sys
PAT = open("/app/.llmwikify/pat").read().strip()
BASE = "http://127.0.0.1:8765/"
H = {"Authorization": f"Bearer {PAT}", "Content-Type": "application/json",
     "Accept": "application/json, text/event-stream"}

def parse_sse(text):
    data=None
    for line in text.splitlines():
        if line.startswith("data:"): data=line[6:]
    try: return json.loads(data if data is not None else text)
    except Exception: return {"raw": text[:150]}

c = httpx.Client(timeout=300.0)
print("REST graph", end=" ")
t0=time.time(); r=c.get(BASE+"api/wiki/graph", headers={"Authorization": f"Bearer {PAT}"}); print(f"{r.status_code} {time.time()-t0:.3f}s")

r = c.post(BASE+"mcp/", headers=H, json={"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"c","version":"0"}}})
H["mcp-session-id"] = r.headers.get("mcp-session-id")
c.post(BASE+"mcp/", headers=H, json={"jsonrpc":"2.0","method":"notifications/initialized"})

_id=[0]
def call(name, args):
    _id[0]+=1
    t0=time.time()
    r=c.post(BASE+"mcp/", headers=H, json={"jsonrpc":"2.0","id":_id[0],"method":"tools/call","params":{"name":name,"arguments":args}})
    el=time.time()-t0
    d=parse_sse(r.text)
    res=d.get("result") or {}
    return ("TOOL_ERR" if res.get("isError") else "OK"), el

for label, name, args in [
    ("gaps1", "wiki_knowledge_gaps", {}),
    ("gaps2", "wiki_knowledge_gaps", {}),
    ("lint1", "wiki_lint", {"limit": 5}),
    ("lint2", "wiki_lint", {"limit": 5}),
    ("gaps3", "wiki_knowledge_gaps", {}),
]:
    st, el = call(name, args)
    print(f"{label:8s} {st:8s} {el:7.2f}s")
c.request("DELETE", BASE+"mcp/", headers=H)
print("DONE")
PY
