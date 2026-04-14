"""MCP server for llmwikify using FastMCP."""

from typing import Optional, Dict, Any, List
from pathlib import Path

from fastmcp import FastMCP

from ..core import Wiki


def create_mcp_server(wiki: Wiki, name: Optional[str] = None, config: Optional[Dict[str, Any]] = None) -> FastMCP:
    """Create a FastMCP server with all wiki tools registered.
    
    Args:
        wiki: Wiki instance to operate on
        name: Optional server name (defaults to directory name)
        config: Optional MCP configuration dict
        
    Returns:
        Configured FastMCP server instance
    """
    service_name = name or config.get("name") if config else None
    if not service_name:
        service_name = wiki.root.name
    
    mcp = FastMCP(service_name)

    # Config
    default_config = {"name": None, "host": "127.0.0.1", "port": 8765, "transport": "stdio"}
    server_config = default_config.copy()
    if config:
        server_config.update(config)
    else:
        user_mcp = wiki.config.get("mcp", {})
        if user_mcp:
            server_config.update(user_mcp)
    mcp._server_config = server_config  # Store for run() access

    @mcp.tool
    def wiki_init(overwrite: bool = False) -> str:
        """Initialize a wiki."""
        import json
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
    ) -> str:
        """Health-check the wiki (broken links, orphans, contradictions).
        
        Args:
            generate_investigations: If True, use LLM to suggest investigations.
            format: Output format - 'full', 'brief', or 'recommendations'.
        """
        import json
        result = wiki.lint(generate_investigations=generate_investigations)
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
    def wiki_references(
        page_name: str,
        detail: bool = False,
        inbound: bool = False,
        outbound: bool = False,
    ) -> str:
        """Show page references (inbound and outbound wikilinks)."""
        import json
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
        source_pages: Optional[List[str]] = None,
        raw_sources: Optional[List[str]] = None,
        page_name: Optional[str] = None,
        auto_link: bool = True,
        auto_log: bool = True,
        merge_or_replace: str = "sink",
    ) -> str:
        """Save a query answer as a new wiki page. Answers compound in the knowledge base."""
        import json
        return json.dumps(wiki.synthesize_query(
            query=query,
            answer=answer,
            source_pages=source_pages,
            raw_sources=raw_sources,
            page_name=page_name,
            auto_link=auto_link,
            auto_log=auto_log,
            merge_or_replace=merge_or_replace,
        ))

    @mcp.tool
    def wiki_sink_status() -> str:
        """Overview of all query sinks with entry counts."""
        import json
        return json.dumps(wiki.sink_status())

    @mcp.tool
    def wiki_graph(
        action: str,
        concept: Optional[str] = None,
        direction: str = "both",
        confidence: Optional[str] = None,
        source: Optional[str] = None,
        target: Optional[str] = None,
        max_length: int = 5,
        relations: Optional[List[dict]] = None,
        source_file: Optional[str] = None,
    ) -> str:
        """Query and modify the knowledge graph. Actions: query, path, stats, write."""
        import json
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
    def wiki_graph_analyze(
        action: str,
        format: str = "html",
        output: Optional[str] = None,
        min_degree: int = 0,
        algorithm: str = "leiden",
        resolution: float = 1.0,
        top: int = 10,
    ) -> str:
        """Analyze the knowledge graph. Actions: export, detect, report."""
        import json
        from ..core.graph_export import (
            build_graph, export_html, export_graphml, export_svg,
            detect_communities, generate_report,
        )
        if action == "export":
            graph = build_graph(wiki.index)
            communities_result = detect_communities(wiki.index)
            communities = communities_result.get('communities')
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

    return mcp


def serve_mcp(wiki: Wiki, name: Optional[str] = None, transport: Optional[str] = None,
              host: Optional[str] = None, port: Optional[int] = None,
              config: Optional[Dict[str, Any]] = None) -> None:
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
    srv_config = mcp._server_config
    service_name = mcp.name

    transport = transport or srv_config.get("transport", "stdio")
    host = host or srv_config.get("host", "127.0.0.1")
    port = port or srv_config.get("port", 8765)

    if transport == "stdio":
        print(f"Starting MCP server '{service_name}' with STDIO transport...")
        mcp.run(transport="stdio")
    elif transport in ("http", "sse"):
        print(f"Starting MCP server '{service_name}' on {host}:{port} with {transport.upper()} transport...")
        mcp.run(transport=transport, host=host, port=port)
    else:
        raise ValueError(f"Unsupported transport: {transport}. Use 'stdio', 'http', or 'sse'")
