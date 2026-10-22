#!/bin/bash
docker run --rm --entrypoint /bin/bash llmwikify-server:0.40.3 -lc '
echo "=== top site-packages ==="
du -sh /usr/local/lib/python3.11/site-packages/* 2>/dev/null | sort -hr | head -25
echo "=== app ==="
du -sh /app/* 2>/dev/null
echo "=== total python ==="
du -sh /usr/local/lib/python3.11/site-packages
'
