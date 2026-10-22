#!/bin/bash
docker run --rm --entrypoint python3 llmwikify-server:0.40.3 -c '
import llmwikify, pathlib, os
p = pathlib.Path(llmwikify.__file__)
print("file", p)
print("ver", llmwikify.__version__)
print("dist_exists", pathlib.Path("/app/ui/webui/dist/index.html").exists())
print("app_dirs", os.listdir("/app"))
'
