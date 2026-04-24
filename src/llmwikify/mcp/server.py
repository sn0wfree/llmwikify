"""MCP server for llmwikify using FastMCP."""

import json
import logging
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from ..core import Wiki
from ..core.graph_export import build_graph

logger = logging.getLogger(__name__)


def create_mcp_server(wiki: Wiki, name: str | None = None, config: dict[str, Any] | None = None) -> FastMCP:
    """Create a FastMCP server with all wiki tools registered.

    Args:
        wiki: Wiki instance to operate on
        name: Optional server name (defaults to directory name)
        config: Optional MCP configuration dict

    Returns:
        Configured FastMCP server instance
    """
    service_name = name
    if not service_name and config:
        service_name = config.get("name")
    if not service_name:
        service_name = wiki.root.name

    mcp = FastMCP(service_name)

    default_config = {"name": None, "host": "127.0.0.1", "port": 8765, "transport": "stdio"}
    server_config = default_config.copy()
    if config:
        server_config.update(config)
    else:
        user_mcp = wiki.config.get("mcp", {})
        if user_mcp:
            server_config.update(user_mcp)
    mcp._server_config = server_config  # type: ignore[attr-defined]

    _register_wiki_tools(mcp, wiki)
    return mcp


def _register_wiki_tools(mcp: FastMCP, wiki: Wiki) -> None:
    """Register all wiki tools on the MCP server."""

    @mcp.tool
    def wiki_init(overwrite: bool = False) -> str:
        """Initialize a wiki."""
        return json.dumps(wiki.init(overwrite=overwrite))

    @mcp.tool
    def wiki_ingest(source: str) -> str:
        """Ingest a source file, extract content."""
        return wiki.ingest_source(source)

    @mcp.tool
    def wiki_write_page(page_name: str, content: str) -> str:
        """Write a wiki page."""
        return wiki.write_page(page_name, content)

    @mcp.tool
    def wiki_read_page(page_name: str) -> str:
        """Read a wiki page (supports wiki/.sink/ files)."""
        return wiki.read_page(page_name)

    @mcp.tool
    def wiki_search(query: str, limit: int = 10) -> list:
        """Full-text search across wiki pages."""
        return wiki.search(query, limit)

    @mcp.tool
    def wiki_lint(
        generate_investigations: bool = False,
        format: str = "full",
        mode: str = "check",
        limit: int = 10,
        force: bool = False,
    ) -> str:
        """Health-check the wiki (broken links, orphans, schema gaps).

        Args:
            generate_investigations: If True, use LLM to suggest investigations.
            format: Output format - 'full', 'brief', or 'recommendations'.
            mode: Lint mode - 'check' (detect only) or 'fix' (suggest repairs).
            limit: Max LLM-detected issues to return (default: 10).
            force: Force re-detection (ignore cache).
        """
        result = wiki.lint(
            mode=mode, limit=limit, force=force,
            generate_investigations=generate_investigations,
        )
        if format == "brief":
            return json.dumps({
                "hints": result.get("hints", {}),
                "issue_count": result.get("issue_count", 0),
                "total_pages": result.get("total_pages", 0),
            }, ensure_ascii=False, indent=2)
        elif format == "recommendations":
            return json.dumps({
                "missing_pages": result.get("investigations", {}).get("missing_pages", []),
                "orphan_pages": result.get("issues", []),
            }, ensure_ascii=False, indent=2)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_analyze_source(source_path: str, force: bool = False) -> str:
        """Analyze a source file and cache structured extraction results.

        Extracts entities, relations, topics, and suggested pages from
        a raw source file. Results are cached in the Source summary page.

        Args:
            source_path: Path relative to root, e.g., 'raw/article.md'
            force: Force re-analysis even if cached

        Returns:
            JSON with analysis results: topics, entities, relations, suggested_pages, etc.
        """
        result = wiki.analyze_source(source_path, force=force)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_references(
        page_name: str,
        detail: bool = False,
        inbound: bool = False,
        outbound: bool = False,
    ) -> str:
        """Show page references (inbound and outbound wikilinks)."""
        result = {"page": page_name, "inbound": [], "outbound": []}
        if not outbound:
            result["inbound"] = wiki.get_inbound_links(page_name, include_context=detail)
        if not inbound:
            result["outbound"] = wiki.get_outbound_links(page_name, include_context=detail)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_status() -> str:
        """Get wiki status summary."""
        return wiki.status()

    @mcp.tool
    def wiki_log(operation: str, details: str) -> str:
        """Append entry to wiki log."""
        return wiki.append_log(operation, details)

    @mcp.tool
    def wiki_recommend() -> list:
        """Get wiki recommendations (missing pages, orphans)."""
        return wiki.recommend()

    @mcp.tool
    def wiki_build_index(auto_export: bool = True) -> str:
        """Build reference index from all wiki pages."""
        return wiki.build_index(auto_export=auto_export)

    @mcp.tool
    def wiki_read_schema() -> str:
        """Read wiki.md (schema/conventions file that tells the LLM how to maintain this wiki)."""
        return wiki.read_schema()

    @mcp.tool
    def wiki_update_schema(content: str) -> str:
        """Update wiki.md with new conventions/workflows. Old version is NOT backed up."""
        return wiki.update_schema(content)

    @mcp.tool
    def wiki_synthesize(
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
        page_name: str | None = None,
        auto_link: bool = True,
        auto_log: bool = True,
        mode: str = "sink",
    ) -> str:
        """Save a query answer as a wiki page. mode="sink" buffers, mode="update" overwrites."""
        return json.dumps(wiki.synthesize_query(
            query=query,
            answer=answer,
            source_pages=source_pages,
            raw_sources=raw_sources,
            page_name=page_name,
            auto_link=auto_link,
            auto_log=auto_log,
            mode=mode,
        ))

    @mcp.tool
    def wiki_sink_status() -> str:
        """Overview of all query sinks with entry counts."""
        return json.dumps(wiki.sink_status())

    @mcp.tool
    def wiki_graph(
        action: str,
        concept: str | None = None,
        direction: str = "both",
        confidence: str | None = None,
        source: str | None = None,
        target: str | None = None,
        max_length: int = 5,
        relations: list[dict] | None = None,
        source_file: str | None = None,
    ) -> str:
        """Query and modify the knowledge graph. Actions: query, path, stats, write."""
        engine = wiki.get_relation_engine()
        if action == "query":
            return json.dumps(engine.get_neighbors(
                concept=concept, direction=direction, confidence=confidence,
            ))
        elif action == "path":
            return json.dumps(engine.get_path(
                source=source, target=target, max_length=max_length,
            ))
        elif action == "stats":
            return json.dumps(engine.get_stats())
        elif action == "write":
            if not relations:
                return json.dumps({"status": "error", "error": "relations required for write action"})
            for r in relations:
                r.setdefault('confidence', 'EXTRACTED')
                if source_file and 'source_file' not in r:
                    r['source_file'] = source_file
            result = wiki.write_relations(relations, source_file=source_file)
            return json.dumps(result)
        else:
            return json.dumps({"status": "error", "error": f"Unknown action: {action}"})

    @mcp.tool
    def wiki_suggest_synthesis(source_name: str | None = None) -> str:
        """Cross-source synthesis suggestions — detects contradictions, gaps, reinforced claims.

        Args:
            source_name: Specific source to analyze (relative path), or None for all unanalyzed sources.

        Returns:
            JSON with synthesis suggestions per source.
        """
        result = wiki.suggest_synthesis(source_name=source_name)
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_knowledge_gaps(limit: int = 20) -> str:
        """Detect knowledge gaps, outdated pages, and redundancy across the wiki.

        Args:
            limit: Max LLM-detected issues to return (default: 20).

        Returns:
            JSON with knowledge gap analysis results including:
            outdated_pages, knowledge_gaps, redundant_pages, contradictions, data_gaps.
        """
        result = wiki.lint(
            generate_investigations=True,
            limit=limit,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_graph_analyze(
        action: str,
        format: str = "html",
        output: str | None = None,
        min_degree: int = 0,
        algorithm: str = "leiden",
        resolution: float = 1.0,
        top: int = 10,
    ) -> str:
        """Analyze the knowledge graph. Actions: export, detect, report, analyze.

        Actions:
            export: Export graph visualization (html/svg/graphml).
            detect: Detect communities in the graph.
            report: Generate surprise score report.
            analyze: Run PageRank, community analysis, and generate page suggestions (P1.3).
        """

        if action == "analyze":
            result = wiki.graph_analyze()
            return json.dumps(result, ensure_ascii=False, indent=2)

        from ..core.graph_export import (
            build_graph,
            detect_communities,
            export_graphml,
            export_html,
            export_svg,
            generate_report,
        )
        if action == "export":
            graph = build_graph(wiki.index)
            communities_result = detect_communities(wiki.index)
            communities = communities_result.get('communities') if communities_result else None
            if format == 'html':
                out = Path(output or 'graph.html')
                result = export_html(graph, communities, out, min_degree=min_degree)
            elif format == 'graphml':
                out = Path(output or 'graph.graphml')
                result = export_graphml(graph, out)
            elif format == 'svg':
                out = Path(output or 'graph.svg')
                result = export_svg(graph, out)
            else:
                result = {"status": "error", "error": f"Unknown format: {format}"}
            return json.dumps(result)
        elif action == "detect":
            result = detect_communities(
                wiki.index, algorithm=algorithm, resolution=resolution,
            )
            return json.dumps(result)
        elif action == "report":
            result = generate_report(wiki.index, top_n=top)
            return json.dumps(result)
        else:
            return json.dumps({"status": "error", "error": f"Unknown action: {action}"})


def _auto_register_mcporter(service_name: str, host: str, port: int) -> None:
    """Auto-register this MCP server with the global mcporter registry.

    Writes to ~/.mcporter/mcporter.json so mcporter-bridge and opencode can
    discover the service.  Skips silently if the name is already registered.
    Best-effort — failures are logged but never block startup.
    """

    config_dir = Path.home() / ".mcporter"
    config_file = config_dir / "mcporter.json"

    try:
        config_dir.mkdir(parents=True, exist_ok=True)

        # Read existing config
        if config_file.exists():
            config = json.loads(config_file.read_text())
        else:
            config = {"mcpServers": {}}

        if "mcpServers" not in config:
            config["mcpServers"] = {}

        # Skip if already registered
        if service_name in config["mcpServers"]:
            print(f"  ⚠ Service '{service_name}' already registered in mcporter, skipping")
            return

        # Register
        url = f"http://{host}:{port}/mcp"
        config["mcpServers"][service_name] = {
            "type": "remote",
            "url": url,
            "description": f"llmwikify MCP server ({service_name})",
        }

        config_file.write_text(json.dumps(config, indent=2) + "\n")
        print(f"  ✓ Registered with mcporter: {service_name} -> {url}")

    except Exception as e:
        print(f"  ⚠ Auto-registration failed: {e}")


def serve_mcp(wiki: Wiki, name: str | None = None, transport: str | None = None,
              host: str | None = None, port: int | None = None,
              config: dict[str, Any] | None = None) -> None:
    """Create and run the MCP server.

    Args:
        wiki: Wiki instance
        name: Optional server name (defaults to directory name)
        transport: Transport protocol ("stdio", "http", or "sse")
        host: Host address (for HTTP/SSE)
        port: Port number (for HTTP/SSE)
        config: Optional MCP config dict
    """
    mcp = create_mcp_server(wiki, name=name, config=config)
    srv_config = mcp._server_config  # type: ignore[attr-defined]
    service_name = mcp.name

    transport = transport or srv_config.get("transport", "stdio")
    host = host or srv_config.get("host", "127.0.0.1")
    port = port or srv_config.get("port", 8765)

    if transport == "stdio":
        print(f"Starting MCP server '{service_name}' with STDIO transport...")
        mcp.run(transport="stdio")
    elif transport in ("http", "sse"):
        _auto_register_mcporter(service_name, host, port)
        print(f"Starting MCP server '{service_name}' on {host}:{port} with {transport.upper()} transport...")
        mcp.run(transport=transport, host=host, port=port)
    else:
        raise ValueError(f"Unsupported transport: {transport}. Use 'stdio', 'http', or 'sse'")


# ============================================================================
# Unified Server (Single-process: MCP + REST API + WebUI)
# ============================================================================

EXCLUDED_AUTH_PATHS = ["/", "/mcp", "/api/health", "/favicon.ico"]
EXCLUDED_AUTH_PREFIXES = ["/assets/"]


class AuthMiddleware(BaseHTTPMiddleware):
    """Simple API Key authentication middleware.

    验证方式（优先级）:
    1. Header: Authorization: Bearer <token>
    2. Query param: ?token=<token> (fallback)

    排除路径（无需鉴权）:
    - / (首页)
    - /mcp (MCP 端点)
    - /api/health (健康检查)
    - /assets/ (静态资源)
    - /favicon.ico
    """

    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        # Check if path is excluded from auth
        if path in EXCLUDED_AUTH_PATHS:
            return await call_next(request)
        for prefix in EXCLUDED_AUTH_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)

        # Extract token
        auth_header = request.headers.get("Authorization", "")
        token = auth_header.replace("Bearer ", "") if auth_header.startswith("Bearer ") else ""
        if not token:
            token = request.query_params.get("token", "")

        if token != self.api_key:
            return JSONResponse({"error": "Unauthorized", "status_code": 401}, status_code=401)

        return await call_next(request)


def _register_rest_routes(mcp: FastMCP, wiki: Wiki, agent: Any | None = None) -> None:
    """Register all REST API routes to FastMCP's _additional_http_routes."""

    # -- Wiki endpoints --

    async def wiki_status(request: Request) -> JSONResponse:
        status = wiki.status()
        if 'pages_by_type' in status:
            status['all_types'] = list(status['pages_by_type'].keys())
        return JSONResponse(status)

    async def wiki_search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "")
        limit = int(request.query_params.get("limit", "10"))
        return JSONResponse(wiki.search(q, limit))

    async def wiki_read_page(request: Request) -> JSONResponse:
        page_name = request.path_params.get("page_name", "")
        try:
            page_data = wiki.read_page(page_name)
            if "error" in page_data:
                return JSONResponse(page_data, status_code=404)
            sink_info = wiki.query_sink.get_info_for_page(page_name)
            return JSONResponse({**page_data, **sink_info})
        except Exception as e:
            return JSONResponse({"error": str(e), "status_code": 404}, status_code=404)

    async def wiki_write_page(request: Request) -> JSONResponse:
        body = await request.json()
        page_name = body.get("page_name", "")
        content = body.get("content", "")
        if not page_name:
            return JSONResponse({"error": "page_name required", "status_code": 400}, status_code=400)
        result = wiki.write_page(page_name, content)
        return JSONResponse({"message": result, "page_name": page_name})

    async def wiki_sink_status(request: Request) -> JSONResponse:
        return JSONResponse(wiki.sink_status())

    async def wiki_lint(request: Request) -> JSONResponse:
        mode = request.query_params.get("mode", "check")
        limit = int(request.query_params.get("limit", "10"))
        force = request.query_params.get("force", "false").lower() == "true"
        result = wiki.lint(mode=mode, limit=limit, force=force)
        return JSONResponse(result)

    async def wiki_recommend(request: Request) -> JSONResponse:
        return JSONResponse(wiki.recommend())

    async def wiki_suggest_synthesis(request: Request) -> JSONResponse:
        source_name = request.query_params.get("source_name")
        result = wiki.suggest_synthesis(source_name=source_name if source_name else None)
        return JSONResponse(result)

    async def wiki_graph_analyze(request: Request) -> JSONResponse:
        result = wiki.graph_analyze()
        return JSONResponse(result)

    async def wiki_graph(request: Request) -> JSONResponse:
        """Return graph data optimized for visualization."""
        current_page = request.query_params.get("current_page")
        mode = request.query_params.get("mode", "auto")

        try:
            graph_data = build_graph(
                wiki.index, include_wikilinks=True, include_relations=False
            )
        except Exception:
            return JSONResponse({"nodes": [], "edges": [], "stats": {"total_nodes": 0, "displayed_nodes": 0, "mode": "empty"}})

        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])
        total_nodes = len(nodes)

        # Determine display strategy based on wiki size
        if total_nodes < 50 or mode == "full":
            display_nodes = nodes
            display_mode = "full"
        elif total_nodes < 200 or mode == "focused":
            # Current page + 1-degree neighbors + hub nodes
            if current_page:
                neighbors = set()
                neighbors.add(current_page)
                for e in edges:
                    if e["source"] == current_page:
                        neighbors.add(e["target"])
                    if e["target"] == current_page:
                        neighbors.add(e["source"])
                # Add hub nodes (nodes with high degree)
                degree_count = {}
                for e in edges:
                    degree_count[e["source"]] = degree_count.get(e["source"], 0) + 1
                    degree_count[e["target"]] = degree_count.get(e["target"], 0) + 1
                hubs = sorted(degree_count.keys(), key=lambda x: -degree_count[x])[:10]
                for h in hubs:
                    neighbors.add(h)
                display_nodes = [n for n in nodes if n["id"] in neighbors]
                display_edges = [e for e in edges if e["source"] in neighbors and e["target"] in neighbors]
            else:
                display_nodes = nodes[:50]
                display_edges = edges
            display_mode = "focused"
        else:
            # Large wiki: current page + 1-degree neighbors only
            if current_page:
                neighbors = set()
                neighbors.add(current_page)
                for e in edges:
                    if e["source"] == current_page:
                        neighbors.add(e["target"])
                    if e["target"] == current_page:
                        neighbors.add(e["source"])
                display_nodes = [n for n in nodes if n["id"] in neighbors]
                display_edges = [e for e in edges if e["source"] in neighbors and e["target"] in neighbors]
            else:
                display_nodes = nodes[:30]
                display_edges = edges
            display_mode = "minimal"

        if mode == "full":
            display_nodes = nodes
            display_edges = edges
            display_mode = "full"

        node_ids = {n["id"] for n in display_nodes}
        display_edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

        # Calculate degree for each node
        degree_count = {}
        for e in display_edges:
            degree_count[e["source"]] = degree_count.get(e["source"], 0) + 1
            degree_count[e["target"]] = degree_count.get(e["target"], 0) + 1

        # Get page types for coloring
        page_types = {}
        try:
            type_map = wiki._load_page_type_mapping()
            page_types = type_map
        except Exception:
            pass

        # Build response
        result_nodes = []
        for n in display_nodes:
            nid = n["id"]
            in_deg = sum(1 for e in display_edges if e["target"] == nid)
            out_deg = sum(1 for e in display_edges if e["source"] == nid)

            # Determine page type for coloring
            page_type = n.get("source_type", "wiki_page")
            for type_name, type_dir in page_types.items():
                if nid.startswith(type_dir + "/") or nid == type_dir:
                    page_type = type_name
                    break

            result_nodes.append({
                "id": nid,
                "label": n.get("label", nid),
                "in_degree": in_deg,
                "out_degree": out_deg,
                "is_current": nid == current_page,
                "page_type": page_type,
            })

        return JSONResponse({
            "nodes": result_nodes,
            "edges": display_edges,
            "stats": {
                "total_nodes": total_nodes,
                "displayed_nodes": len(result_nodes),
                "mode": display_mode,
            },
            "all_types": list(page_types.keys()),
        })

    # -- Agent endpoints --

    async def agent_chat(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        body = await request.json()
        message = body.get("message", "")
        try:
            result = await agent.chat(message)
            return JSONResponse(result)
        except Exception as e:
            return JSONResponse({"error": str(e), "status_code": 500}, status_code=500)

    async def agent_status(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        return JSONResponse(agent.get_status())

    async def agent_tools(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        return JSONResponse(agent.get_tools())

    async def agent_notifications(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        return JSONResponse(agent.notifications.list_all())

    async def notification_mark_read(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        notif_id = request.path_params.get("id", "")
        result = agent.notifications.mark_read(notif_id)
        return JSONResponse({"success": result, "id": notif_id})

    # -- Confirmation endpoints --

    async def confirmations_list(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        return JSONResponse(agent.get_pending_confirmations())

    async def confirmation_approve(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        conf_id = request.path_params.get("id", "")
        result = await agent.confirm_action(conf_id)
        return JSONResponse(result)

    async def confirmation_reject(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        conf_id = request.path_params.get("id", "")
        result = agent.tool_registry.reject_execution(conf_id)
        return JSONResponse(result)

    async def confirmations_batch(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        body = await request.json()
        ids = body.get("ids", [])
        results = await agent.confirm_batch(ids)
        return JSONResponse(results)

    # -- Dream endpoints --

    async def dream_log(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        limit = int(request.query_params.get("limit", "20"))
        return JSONResponse(agent.dream_editor.get_edit_log(limit))

    async def dream_run(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        result = agent.dream_editor.run_dream()
        return JSONResponse(result)

    async def dream_proposals(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        return JSONResponse(agent.get_dream_proposals())

    async def dream_proposal_approve(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        prop_id = request.path_params.get("id", "")
        result = agent.dream_editor.proposal_manager.approve(prop_id)
        if result:
            return JSONResponse(result)
        return JSONResponse({"error": "Proposal not found", "status_code": 404}, status_code=404)

    async def dream_proposal_reject(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        prop_id = request.path_params.get("id", "")
        result = agent.dream_editor.proposal_manager.reject(prop_id)
        if result:
            return JSONResponse(result)
        return JSONResponse({"error": "Proposal not found", "status_code": 404}, status_code=404)

    async def dream_proposals_batch_approve(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        body = await request.json()
        ids = body.get("ids", [])
        results = agent.dream_editor.proposal_manager.batch_approve(ids)
        return JSONResponse({"approved": len(results), "results": results})

    async def dream_proposals_apply(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        body = await request.json()
        ids = body.get("ids", None)
        result = await agent.apply_dream_proposals(ids)
        return JSONResponse(result)

    # -- Ingest log endpoints --

    async def ingest_log_list(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        limit = int(request.query_params.get("limit", "20"))
        return JSONResponse(agent.get_ingest_log(limit))

    async def ingest_log_detail(request: Request) -> JSONResponse:
        if agent is None:
            return JSONResponse({"error": "Agent not enabled", "status_code": 503}, status_code=503)
        ingest_id = request.path_params.get("id", "")
        result = agent.tool_registry.get_ingest_changes(ingest_id)
        if result:
            return JSONResponse(result)
        return JSONResponse({"error": "Ingest not found", "status_code": 404}, status_code=404)

    async def ingest_log_revert(request: Request) -> JSONResponse:
        return JSONResponse({"error": "Revert not implemented yet (requires git integration)", "status_code": 501}, status_code=501)

    # -- Health endpoint --

    async def health_check(request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy", "wiki": str(wiki.root)})

    # Register routes
    routes = [
        Route("/api/health", health_check, methods=["GET"]),
        Route("/api/wiki/status", wiki_status, methods=["GET"]),
        Route("/api/wiki/search", wiki_search, methods=["GET"]),
        Route("/api/wiki/page/{page_name:path}", wiki_read_page, methods=["GET"]),
        Route("/api/wiki/page", wiki_write_page, methods=["POST"]),
        Route("/api/wiki/sink/status", wiki_sink_status, methods=["GET"]),
        Route("/api/wiki/lint", wiki_lint, methods=["GET"]),
        Route("/api/wiki/recommend", wiki_recommend, methods=["GET"]),
        Route("/api/wiki/suggest_synthesis", wiki_suggest_synthesis, methods=["GET"]),
        Route("/api/wiki/graph_analyze", wiki_graph_analyze, methods=["GET"]),
        Route("/api/wiki/graph", wiki_graph, methods=["GET"]),
        Route("/api/agent/chat", agent_chat, methods=["POST"]),
        Route("/api/agent/status", agent_status, methods=["GET"]),
        Route("/api/agent/tools", agent_tools, methods=["GET"]),
        Route("/api/agent/notifications", agent_notifications, methods=["GET"]),
        Route("/api/agent/notifications/{id}/read", notification_mark_read, methods=["POST"]),
        Route("/api/agent/confirmations", confirmations_list, methods=["GET"]),
        Route("/api/agent/confirmations/{id}", confirmation_approve, methods=["POST"]),
        Route("/api/agent/confirmations/{id}", confirmation_reject, methods=["DELETE"]),
        Route("/api/agent/confirmations/batch", confirmations_batch, methods=["POST"]),
        Route("/api/agent/dream/log", dream_log, methods=["GET"]),
        Route("/api/agent/dream/run", dream_run, methods=["POST"]),
        Route("/api/agent/dream/proposals", dream_proposals, methods=["GET"]),
        Route("/api/agent/dream/proposals/{id}/approve", dream_proposal_approve, methods=["POST"]),
        Route("/api/agent/dream/proposals/{id}/reject", dream_proposal_reject, methods=["POST"]),
        Route("/api/agent/dream/proposals/batch-approve", dream_proposals_batch_approve, methods=["POST"]),
        Route("/api/agent/dream/proposals/apply", dream_proposals_apply, methods=["POST"]),
        Route("/api/agent/ingest/log", ingest_log_list, methods=["GET"]),
        Route("/api/agent/ingest/log/{id}", ingest_log_detail, methods=["GET"]),
        Route("/api/agent/ingest/log/{id}/revert", ingest_log_revert, methods=["POST"]),
    ]

    mcp._additional_http_routes.extend(routes)


def _mount_webui(mcp: FastMCP) -> None:
    """Mount React static files with multi-level fallback."""

    # Try multiple locations for the webui dist
    candidates = []

    # 1. Installed mode: <package>/web/webui/dist/
    pkg_dir = Path(__file__).parent.parent
    candidates.append(pkg_dir / "web" / "webui" / "dist")

    # 2. Dev mode: <repo>/src/llmwikify/web/webui/dist/
    candidates.append(pkg_dir.parent.parent / "web" / "webui" / "dist")

    # 3. Legacy static directory
    candidates.append(pkg_dir / "web" / "static")

    dist_dir = None
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            dist_dir = candidate
            break

    if dist_dir is None:
        logger.warning("No WebUI dist found, serving without static files")
        return

    async def spa_fallback(request: Request) -> Response:
        """Serve index.html for SPA fallback."""
        index_file = dist_dir / "index.html"
        if index_file.exists():
            return Response(
                content=index_file.read_bytes(),
                media_type="text/html",
            )
        return JSONResponse({"error": "Not found", "status_code": 404}, status_code=404)

    # Mount static files
    static_route = Mount(
        "/",
        app=StaticFiles(directory=str(dist_dir), html=True),
        name="static",
    )
    mcp._additional_http_routes.append(static_route)


def create_unified_server(
    wiki: Wiki,
    agent: Any | None = None,
    api_key: str | None = None,
    mcp_name: str | None = None,
) -> Any:
    """Create a unified FastAPI server with MCP, REST API, and WebUI.

    DEPRECATED: Use llmwikify.server.WikiServer instead. This wrapper
    is maintained for backward compatibility.

    Args:
        wiki: Wiki instance
        agent: Optional WikiAgent instance
        api_key: Optional API key for authentication
        mcp_name: Optional MCP server name

    Returns:
        FastAPI application
    """
    from llmwikify.server import WikiServer

    server = WikiServer(
        wiki,
        agent=agent,
        api_key=api_key,
        mcp_name=mcp_name,
        enable_mcp=True,
        enable_rest=True,
        enable_webui=True,
    )
    return server.app
