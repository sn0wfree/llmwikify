#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
echo "=== pkg ==="
ls -lh /home/linlu/tmp/llmwikify-server-0.40.4-slim.tar.xz 2>&1
echo "=== images ==="
docker image ls llmwikify-server
echo "=== containers ==="
docker ps -a --filter name=llmwikify --format "{{.Names}} | {{.Status}} | {{.Image}}"
echo "=== compose ==="
grep image: /home/linlu/CKbase/deploy/docker-compose.yml
'
