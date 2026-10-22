#!/bin/bash
set -e
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'JSON'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://docker.nju.edu.cn",
    "https://docker.mirrors.ustc.edu.cn"
  ]
}
JSON
cat /etc/docker/daemon.json
systemctl restart docker
sleep 4
docker info | grep -i -A5 -E 'mirror|Registry' || true
