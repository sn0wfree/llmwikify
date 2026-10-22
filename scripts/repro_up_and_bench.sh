#!/bin/bash
set -euo pipefail
cd /mnt/d/Github/llmwikify
export CKBASE_HOST=/mnt/c/Users/1/Documents/CKbase-test-2026-10-22/CKbase
docker compose -f docker-tests/docker-compose.repro.yml up -d --force-recreate
for i in $(seq 1 12); do
  s=$(docker inspect -f '{{.State.Health.Status}}' llmwikify-repro 2>/dev/null || echo missing)
  echo "health_try $i $s"
  [ "$s" = "healthy" ] && break
  sleep 5
done
tr -d '\r' < scripts/repro_bench_in_container.sh > /tmp/bench.sh
docker cp /tmp/bench.sh llmwikify-repro:/tmp/bench.sh
docker exec llmwikify-repro bash /tmp/bench.sh
