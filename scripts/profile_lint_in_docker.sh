#!/bin/bash
# Profile lint paths inside the slim image against CKbase-test.
set -u
IMG=llmwikify-server:0.40.3-slim
NAME=llmwikify-profile
CK=/tmp/ckbase-mcpcheck
if [ ! -d "$CK/wiki" ]; then
  CK=/mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase
fi
echo "using kb=$CK"
docker rm -f "$NAME" 2>/dev/null || true
docker run --rm --name "$NAME" --entrypoint python3 \
  -v "$CK:/app/wiki:rw" \
  -v /mnt/d/Github/llmwikify/scripts/profile_lint_paths.py:/tmp/profile_lint_paths.py:ro \
  -e WIKI_ROOT=/app/wiki \
  "$IMG" /tmp/profile_lint_paths.py --wiki /app/wiki
