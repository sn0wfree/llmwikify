#!/bin/bash
export SSHPASS="${SSHPASS:?set SSHPASS}"
sshpass -e ssh -o StrictHostKeyChecking=accept-new linlu@8.133.234.138 '
echo "=== compose ==="
cat /home/linlu/CKbase/deploy/docker-compose.yml
echo
echo "=== container inspect (runtime) ==="
docker inspect llmwikify-server --format "
Name={{.Name}}
Image={{.Config.Image}}
Cmd={{json .Config.Cmd}}
Entrypoint={{json .Config.Entrypoint}}
User={{.Config.User}}
WorkingDir={{.Config.WorkingDir}}
"
echo "-- Env --"
docker inspect llmwikify-server --format "{{range .Config.Env}}{{println .}}{{end}}"
echo "-- Ports --"
docker port llmwikify-server
echo "-- Mounts --"
docker inspect llmwikify-server --format "{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}} ({{.Mode}}){{println}}{{end}}"
echo "-- Restart --"
docker inspect llmwikify-server --format "{{.HostConfig.RestartPolicy.Name}}"
echo "-- Health --"
docker inspect llmwikify-server --format "{{json .Config.Healthcheck}}"
echo
echo "=== image 0.40.2 entrypoint/cmd/env ==="
docker image inspect llmwikify-server:0.40.2-slim --format "Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}} User={{.Config.User}}"
echo "-- image Env --"
docker image inspect llmwikify-server:0.40.2-slim --format "{{range .Config.Env}}{{println .}}{{end}}"
echo
echo "=== image 0.40.3-slim entrypoint/cmd/env ==="
docker image inspect llmwikify-server:0.40.3-slim --format "Entrypoint={{json .Config.Entrypoint}} Cmd={{json .Config.Cmd}} User={{.Config.User}}"
echo "-- image Env --"
docker image inspect llmwikify-server:0.40.3-slim --format "{{range .Config.Env}}{{println .}}{{end}}"
'
