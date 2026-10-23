#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 linlu@8.133.234.138 '
echo "=== llmwikify-server images ==="
docker image ls llmwikify-server
echo "=== 0.40.3-slim ==="
docker image inspect llmwikify-server:0.40.3-slim --format "id={{.Id}} created={{.Created}} size={{.Size}}" 2>&1 || echo "MISSING"
echo "=== running ==="
docker ps --filter name=llmwikify-server --format "{{.Names}} {{.Status}} {{.Image}}"
'
