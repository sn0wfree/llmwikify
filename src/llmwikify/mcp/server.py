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
