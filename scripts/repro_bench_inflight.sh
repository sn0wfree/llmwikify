#!/bin/bash
# Concurrent status while a graph request is in flight.
set -u
TOKEN=$(tr -d '\n' < /app/.llmwikify/pat)
AUTH="Authorization: Bearer ${TOKEN}"

curl -s -o /dev/null -w "graph_alone %{http_code} %{time_total}s\n" \
  --max-time 180 -H "$AUTH" http://127.0.0.1:8765/api/wiki/graph &

GPID=$!
sleep 0.05
echo "status_while_graph:"
for i in $(seq 1 10); do
  curl -s -o /dev/null -w "  #$i %{http_code} %{time_total}s\n" \
    --max-time 30 -H "$AUTH" http://127.0.0.1:8765/api/wiki/status &
done
wait
