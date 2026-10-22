#!/bin/bash
# Upload + load + verify. Additive only — no container/compose changes.
set -u
PKG=/mnt/c/Users/1/Documents/llmwikify-server-0.40.3-slim.tar.xz
RSSH=linlu@8.133.234.138
REMOTE_PKG=/home/linlu/tmp/llmwikify-server-0.40.3-slim.tar.xz
TAG=llmwikify-server:0.40.3-slim
export SSHPASS="${SSHPASS:?set SSHPASS env — do not hardcode passwords}"
SSH() { sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }
SCP() { sshpass -e scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 "$@"; }

echo "===1 pkg==="
ls -lh "$PKG" || exit 1

echo "===2 preflight==="
SSH "$RSSH" "mkdir -p /home/linlu/tmp; df -h /home | tail -1; echo '--imgs--'; docker image ls llmwikify-server; echo '--ctr--'; docker ps -a --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'"
echo "preflight_rc=$?"

echo "===3 scp==="
SCP "$PKG" "$RSSH:$REMOTE_PKG"
echo "scp_rc=$?"
SSH "$RSSH" "ls -lh $REMOTE_PKG"

echo "===4 load==="
SSH "$RSSH" "xz -dc $REMOTE_PKG | docker load; echo '--imgs--'; docker image ls llmwikify-server; docker image inspect $TAG --format 'loaded={{.Id}}'"
echo "load_rc=$?"

echo "===5 verify untouched==="
SSH "$RSSH" "echo '--ctr--'; docker ps -a --filter name=llmwikify --format '{{.Names}} {{.Status}} {{.Image}}'; curl -s -o /dev/null -w 'api %{http_code}\n' --max-time 5 http://127.0.0.1:8765/api/health"
echo "DONE"
