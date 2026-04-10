"""MCP server for llmwikify."""

from pathlib import Path
from typing import Optional

from ..core import Wiki


class MCPServer:
    """MCP server that exposes wiki tools."""
    
    def __init__(self, wiki: Wiki):
        self.wiki = wiki
        self._mcp = None
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
                                "agent": {"type": "string", "default": "claude"}
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
                ]
            
            @self._mcp.call_tool()
            def call_tool(name: str, arguments: dict):
                if name == "wiki_init":
                    return self.wiki.init(arguments.get('agent', 'claude'))
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
                else:
                    raise ValueError(f"Unknown tool: {name}")
            
        except ImportError:
            raise ImportError("MCP server requires 'mcp' package: pip install mcp")
    
    def serve(self, transport: str = "stdio"):
        """Start MCP server."""
        if self._mcp is None:
            self._register_mcp()
        
        import mcp.server.stdio
        self._mcp.run(transport=transport)
