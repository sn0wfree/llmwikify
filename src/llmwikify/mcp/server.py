"""MCP server for llmwikify."""

import json
from pathlib import Path
from typing import Optional, Dict, Any

from ..core import Wiki


class MCPServer:
    """MCP server that exposes wiki tools."""
    
    # Default configuration
    DEFAULT_CONFIG = {
        "host": "127.0.0.1",
        "port": 8765,
        "transport": "stdio",  # or "http" or "sse"
    }
    
    def __init__(self, wiki: Wiki, config: Optional[Dict[str, Any]] = None):
        self.wiki = wiki
        self._mcp = None
        
        # Merge user config with defaults
        self.config = self.DEFAULT_CONFIG.copy()
        if config:
            self.config.update(config)
        else:
            # Auto-read from wiki's loaded configuration
            user_mcp = wiki.config.get("mcp", {})
            if user_mcp:
                self.config.update(user_mcp)
        
        self._register_mcp()
    
    def _register_mcp(self):
        """Register MCP tools."""
        try:
            import mcp.server.stdio
            import mcp.types as types
            from mcp.server import Server
            
            self._mcp = Server("llmwikify")
            
            @self._mcp.list_tools()
            def list_tools():
                return [
                    types.Tool(
                        name="wiki_init",
                        description="Initialize a wiki",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "overwrite": {"type": "boolean", "default": False, "description": "Recreate index.md and log.md if they exist. Always skips wiki.md and config example."}
                            }
                        }
                    ),
                    types.Tool(
                        name="wiki_ingest",
                        description="Ingest a source file",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "source": {"type": "string"}
                            },
                            "required": ["source"]
                        }
                    ),
                    types.Tool(
                        name="wiki_write_page",
                        description="Write a wiki page",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "page_name": {"type": "string"},
                                "content": {"type": "string"}
                            },
                            "required": ["page_name", "content"]
                        }
                    ),
                    types.Tool(
                        name="wiki_read_page",
                        description="Read a wiki page",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "page_name": {"type": "string"}
                            },
                            "required": ["page_name"]
                        }
                    ),
                    types.Tool(
                        name="wiki_search",
                        description="Search the wiki",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "limit": {"type": "integer", "default": 10}
                            },
                            "required": ["query"]
                        }
                    ),
                    types.Tool(
                        name="wiki_lint",
                        description="Health-check the wiki",
                        inputSchema={"type": "object", "properties": {}}
                    ),
                    types.Tool(
                        name="wiki_status",
                        description="Get wiki status",
                        inputSchema={"type": "object", "properties": {}}
                    ),
                    types.Tool(
                        name="wiki_log",
                        description="Append entry to wiki log",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "operation": {"type": "string"},
                                "details": {"type": "string"}
                            },
                            "required": ["operation", "details"]
                        }
                    ),
                    types.Tool(
                        name="wiki_recommend",
                        description="Get wiki recommendations (missing pages, orphans)",
                        inputSchema={"type": "object", "properties": {}}
                    ),
                    types.Tool(
                        name="wiki_build_index",
                        description="Build reference index from all wiki pages",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "auto_export": {"type": "boolean", "default": True}
                            }
                        }
                    ),
                    types.Tool(
                        name="wiki_read_schema",
                        description="Read wiki.md (schema/conventions file that tells the LLM how to maintain this wiki)",
                        inputSchema={
                            "type": "object",
                            "properties": {}
                        }
                    ),
                    types.Tool(
                        name="wiki_update_schema",
                        description="Update wiki.md with new conventions/workflows. Old version is NOT backed up automatically - read current content first if you need to preserve it.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "content": {"type": "string", "description": "New wiki.md content"}
                            },
                            "required": ["content"]
                        }
                    ),
                    types.Tool(
                        name="wiki_synthesize",
                        description="Save a query answer as a new wiki page. Answers compound in the knowledge base just like ingested sources — comparisons, analyses, and discoveries become persistent wiki pages.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Original question that was asked"},
                                "answer": {"type": "string", "description": "LLM-generated answer content (markdown). Will be saved as a wiki page with source citations."},
                                "source_pages": {"type": "array", "items": {"type": "string"}, "description": "Wiki pages referenced to generate this answer. Will be added as [[wikilinks]] in the Sources section."},
                                "raw_sources": {"type": "array", "items": {"type": "string"}, "description": "Raw source files referenced (e.g., 'raw/article.md'). Will be added as markdown links in Sources section."},
                                "page_name": {"type": "string", "description": "Custom page name. Auto-generated as 'Query: {topic}' if omitted."},
                                "auto_link": {"type": "boolean", "default": True, "description": "Automatically add source_pages and raw_sources as links in a Sources section"},
                                "auto_log": {"type": "boolean", "default": True, "description": "Automatically append to log.md"},
                                "merge_or_replace": {"type": "string", "enum": ["sink", "merge", "replace"], "default": "sink", "description": "Strategy when a similar query page exists: 'sink'=append to buffer (default), 'merge'=read old content then consolidate and replace, 'replace'=overwrite the formal page entirely"}
                            },
                            "required": ["query", "answer"]
                        }
                    ),
                    types.Tool(
                        name="wiki_sink_status",
                        description="Overview of all query sinks with entry counts. Returns topics with pending entries and their status. Use during lint to identify which sinks need review and merging.",
                        inputSchema={"type": "object", "properties": {}}
                    ),
                    types.Tool(
                        name="wiki_graph",
                        description="Query and modify the knowledge graph. Supports: query (concept neighbors), path (shortest path between concepts), stats (graph statistics), write (add relations). Use action parameter to select operation.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["query", "path", "stats", "write"],
                                    "description": "Operation to perform"
                                },
                                "concept": {"type": "string", "description": "Concept name (for query action)"},
                                "direction": {"type": "string", "enum": ["in", "out", "both"], "default": "both", "description": "Direction of relations (query action)"},
                                "confidence": {"type": "string", "enum": ["EXTRACTED", "INFERRED", "AMBIGUOUS"], "description": "Filter by confidence level (query action)"},
                                "source": {"type": "string", "description": "Starting concept (for path action)"},
                                "target": {"type": "string", "description": "Target concept (for path action)"},
                                "max_length": {"type": "integer", "default": 5, "description": "Maximum path length (path action)"},
                                "relations": {"type": "array", "items": {"type": "object", "properties": {
                                    "source": {"type": "string"},
                                    "target": {"type": "string"},
                                    "relation": {"type": "string", "enum": ["is_a", "uses", "related_to", "contradicts", "supports", "replaces", "optimizes", "extends"]},
                                    "confidence": {"type": "string", "enum": ["EXTRACTED", "INFERRED", "AMBIGUOUS"], "default": "EXTRACTED"},
                                    "context": {"type": "string"}
                                }, "required": ["source", "target", "relation"]}, "description": "List of relations to add (write action)"},
                                "source_file": {"type": "string", "description": "Source file these relations came from (write action)"}
                            },
                            "required": ["action"]
                        }
                    ),
                    types.Tool(
                        name="wiki_graph_analyze",
                        description="Analyze the knowledge graph. Supports: export (visualize as HTML/GraphML/SVG), detect (find communities with Leiden/Louvain), report (surprise score unexpected connections). Use action parameter to select operation.",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["export", "detect", "report"],
                                    "description": "Analysis operation to perform"
                                },
                                "format": {"type": "string", "enum": ["html", "graphml", "svg"], "default": "html", "description": "Output format (export action)"},
                                "output": {"type": "string", "description": "Output file path (export action). Default: graph.html, graph.graphml, or graph.svg"},
                                "min_degree": {"type": "integer", "default": 0, "description": "Filter nodes by minimum degree (export action, HTML only)"},
                                "algorithm": {"type": "string", "enum": ["leiden", "louvain"], "default": "leiden", "description": "Community detection algorithm (detect action)"},
                                "resolution": {"type": "number", "default": 1.0, "description": "Resolution parameter, higher = more granular (detect action)"},
                                "top": {"type": "integer", "default": 10, "description": "Number of top surprising connections to report (report action)"}
                            },
                            "required": ["action"]
                        }
                    ),
                ]
            
            @self._mcp.call_tool()
            def call_tool(name: str, arguments: dict):
                if name == "wiki_init":
                    return json.dumps(self.wiki.init(overwrite=arguments.get('overwrite', False)))
                elif name == "wiki_ingest":
                    return self.wiki.ingest_source(arguments['source'])
                elif name == "wiki_write_page":
                    return self.wiki.write_page(arguments['page_name'], arguments['content'])
                elif name == "wiki_read_page":
                    return self.wiki.read_page(arguments['page_name'])
                elif name == "wiki_search":
                    return self.wiki.search(arguments['query'], arguments.get('limit', 10))
                elif name == "wiki_lint":
                    return self.wiki.lint()
                elif name == "wiki_status":
                    return self.wiki.status()
                elif name == "wiki_log":
                    return self.wiki.append_log(arguments['operation'], arguments['details'])
                elif name == "wiki_recommend":
                    return self.wiki.recommend()
                elif name == "wiki_build_index":
                    return self.wiki.build_index(auto_export=arguments.get('auto_export', True))
                elif name == "wiki_read_schema":
                    return self.wiki.read_schema()
                elif name == "wiki_update_schema":
                    return self.wiki.update_schema(arguments['content'])
                elif name == "wiki_synthesize":
                    return json.dumps(self.wiki.synthesize_query(
                        query=arguments['query'],
                        answer=arguments['answer'],
                        source_pages=arguments.get('source_pages'),
                        raw_sources=arguments.get('raw_sources'),
                        page_name=arguments.get('page_name'),
                        auto_link=arguments.get('auto_link', True),
                        auto_log=arguments.get('auto_log', True),
                        merge_or_replace=arguments.get('merge_or_replace', 'sink'),
                    ))
                elif name == "wiki_sink_status":
                    return json.dumps(self.wiki.sink_status())
                elif name == "wiki_graph":
                    action = arguments.get("action")
                    if action == "query":
                        engine = self.wiki.get_relation_engine()
                        result = engine.get_neighbors(
                            concept=arguments['concept'],
                            direction=arguments.get('direction', 'both'),
                            confidence=arguments.get('confidence'),
                        )
                        return json.dumps(result)
                    elif action == "path":
                        engine = self.wiki.get_relation_engine()
                        result = engine.get_path(
                            source=arguments['source'],
                            target=arguments['target'],
                            max_length=arguments.get('max_length', 5),
                        )
                        return json.dumps(result)
                    elif action == "stats":
                        engine = self.wiki.get_relation_engine()
                        result = engine.get_stats()
                        return json.dumps(result)
                    elif action == "write":
                        relations = arguments['relations']
                        source_file = arguments.get('source_file')
                        for r in relations:
                            r.setdefault('confidence', 'EXTRACTED')
                            if source_file and 'source_file' not in r:
                                r['source_file'] = source_file
                        self.wiki.write_relations(relations, source_file=source_file)
                        return json.dumps({"status": "success", "count": len(relations)})
                    else:
                        return json.dumps({"status": "error", "error": f"Unknown action: {action}"})
                elif name == "wiki_graph_analyze":
                    action = arguments.get("action")
                    if action == "export":
                        from ..core.graph_export import build_graph, export_html, export_graphml, export_svg, detect_communities
                        fmt = arguments.get('format', 'html')
                        graph = build_graph(self.wiki.index)
                        communities_result = detect_communities(self.wiki.index)
                        communities = communities_result.get('communities')
                        if fmt == 'html':
                            output = Path(arguments.get('output', 'graph.html'))
                            result = export_html(graph, communities, output, min_degree=arguments.get('min_degree', 0))
                        elif fmt == 'graphml':
                            output = Path(arguments.get('output', 'graph.graphml'))
                            result = export_graphml(graph, output)
                        elif fmt == 'svg':
                            output = Path(arguments.get('output', 'graph.svg'))
                            result = export_svg(graph, output)
                        else:
                            result = {"status": "error", "error": f"Unknown format: {fmt}"}
                        return json.dumps(result)
                    elif action == "detect":
                        from ..core.graph_export import detect_communities
                        result = detect_communities(
                            self.wiki.index,
                            algorithm=arguments.get('algorithm', 'leiden'),
                            resolution=arguments.get('resolution', 1.0),
                        )
                        return json.dumps(result)
                    elif action == "report":
                        from ..core.graph_export import generate_report
                        result = generate_report(self.wiki.index, top_n=arguments.get('top', 10))
                        return result
                    else:
                        return json.dumps({"status": "error", "error": f"Unknown action: {action}"})
                else:
                    raise ValueError(f"Unknown tool: {name}")
            
        except ImportError:
            raise ImportError("MCP server requires 'mcp' package: pip install mcp")
    
    def serve(self, transport: Optional[str] = None, host: Optional[str] = None, port: Optional[int] = None):
        """Start MCP server.
        
        Args:
            transport: Transport protocol ("stdio", "http", or "sse")
                      Overrides config if provided
            host: Host address to bind to (for HTTP/SSE transports)
                 Overrides config if provided
            port: Port number to listen on (for HTTP/SSE transports)
                 Overrides config if provided
        """
        if self._mcp is None:
            self._register_mcp()
        
        # Use provided arguments or fall back to config
        transport = transport or self.config.get("transport", "stdio")
        host = host or self.config.get("host", "127.0.0.1")
        port = port or self.config.get("port", 8765)
        
        import mcp.server.stdio
        
        if transport == "stdio":
            # STDIO transport doesn't use host/port
            print(f"Starting MCP server with STDIO transport...")
            self._mcp.run(transport="stdio")
        elif transport in ("http", "sse"):
            # HTTP/SSE transport uses host and port
            print(f"Starting MCP server on {host}:{port} with {transport.upper()} transport...")
            self._mcp.run(transport=transport, host=host, port=port)
        else:
            raise ValueError(f"Unsupported transport: {transport}. Use 'stdio', 'http', or 'sse'")
