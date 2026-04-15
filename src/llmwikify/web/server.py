"""Standalone Web UI server for llmwikify.

Provides a web interface that proxies JSON-RPC calls to the MCP server.
Run with: python -m llmwikify.web.server --mcp-url http://127.0.0.1:8765/mcp --port 8766
"""

import argparse
import json
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

# Global MCP URL, set at startup
MCP_URL: str = ""


def get_static_dir() -> Path:
    """Locate the static files directory."""
    # Try relative to this file first (installed package)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        return static_dir

    # Try project root (development)
    project_root = Path(__file__).parent.parent.parent.parent
    static_dir = project_root / "src" / "llmwikify" / "web" / "static"
    if static_dir.exists():
        return static_dir

    raise FileNotFoundError("Static files directory not found")


async def rpc_proxy(request) -> JSONResponse:
    """Proxy JSON-RPC calls to the MCP server.
    
    Handles batch calls for efficiency.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON"}, status_code=400
        )

    # Support both single and batch requests
    is_batch = isinstance(body, list)
    requests = body if is_batch else [body]

    results = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for req in requests:
            try:
                resp = await client.post(MCP_URL, json=req)
                result = resp.json()

                # MCP tools return JSON strings, we parse and re-stringify
                if "result" in result and isinstance(result["result"], dict):
                    pass  # Already parsed
                elif "result" in result and isinstance(result["result"], str):
                    try:
                        result["result"] = json.loads(result["result"])
                    except (json.JSONDecodeError, TypeError):
                        pass  # Keep as string

                results.append(result)
            except httpx.ConnectError:
                results.append({
                    "jsonrpc": "2.0",
                    "id": req.get("id"),
                    "error": {
                        "code": -32603,
                        "message": f"Cannot connect to MCP server at {MCP_URL}"
                    }
                })

    if is_batch:
        return JSONResponse(results)
    return JSONResponse(results[0])


async def health_check(request) -> JSONResponse:
    """Health check endpoint."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # Try a simple MCP call
            resp = await client.post(MCP_URL, json={
                "jsonrpc": "2.0",
                "id": 0,
                "method": "tools/list",
                "params": {}
            })
            if resp.status_code == 200:
                return JSONResponse({
                    "status": "healthy",
                    "mcp_url": MCP_URL,
                    "mcp_status": "connected"
                })
    except Exception:
        pass

    return JSONResponse(
        {
            "status": "degraded",
            "mcp_url": MCP_URL,
            "mcp_status": "disconnected"
        },
        status_code=503
    )


def create_app(mcp_url: str) -> Starlette:
    """Create the Starlette application."""
    global MCP_URL
    MCP_URL = mcp_url

    static_dir = get_static_dir()

    app = Starlette(
        debug=False,
        routes=[
            Route("/api/rpc", rpc_proxy, methods=["POST"]),
            Route("/api/health", health_check),
            Mount("/", StaticFiles(directory=str(static_dir), html=True), name="static"),
        ]
    )

    return app


def main():
    """CLI entry point for standalone web server."""
    parser = argparse.ArgumentParser(description="llmwikify Web UI Server")
    parser.add_argument(
        "--mcp-url",
        default="http://127.0.0.1:8765/mcp",
        help="MCP server URL (default: http://127.0.0.1:8765/mcp)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8766,
        help="Web UI port (default: 8766)"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind address (default: 127.0.0.1)"
    )

    args = parser.parse_args()

    import uvicorn

    app = create_app(args.mcp_url)

    print(f"Starting Web UI on http://{args.host}:{args.port}")
    print(f"MCP server: {args.mcp_url}")

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info"
    )


if __name__ == "__main__":
    main()
