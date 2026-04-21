"""Tool Registry - Wraps MCP tools for Agent internal use.

Registers all 20+ MCP tools and provides a unified execution interface.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class WikiToolRegistry:
    """Registry of wiki tools that the Agent can call.

    Wraps existing MCP tools and Wiki methods into a unified interface.
    """

    def __init__(self, wiki: Any):
        self.wiki = wiki
        self._tools: dict[str, dict] = {}
        self._register_all_tools()

    def _register_all_tools(self) -> None:
        self._register(
            "wiki_init",
            lambda args: json.dumps(self.wiki.init(overwrite=args.get("overwrite", False))),
            description="Initialize a wiki",
            action_type="write",
        )
        self._register(
            "wiki_ingest",
            lambda args: self.wiki.ingest_source(args.get("source", "")),
            description="Ingest a source file",
            action_type="write",
        )
        self._register(
            "wiki_write_page",
            lambda args: self.wiki.write_page(
                args.get("page_name", ""), args.get("content", "")
            ),
            description="Write a wiki page",
            action_type="write",
        )
        self._register(
            "wiki_read_page",
            lambda args: self.wiki.read_page(args.get("page_name", "")),
            description="Read a wiki page",
            action_type="read",
        )
        self._register(
            "wiki_search",
            lambda args: self.wiki.search(
                args.get("query", ""), args.get("limit", 10)
            ),
            description="Full-text search across wiki pages",
            action_type="read",
        )
        self._register(
            "wiki_lint",
            lambda args: json.dumps(
                self.wiki.lint(
                    mode=args.get("mode", "check"),
                    limit=args.get("limit", 10),
                    force=args.get("force", False),
                    generate_investigations=args.get("generate_investigations", False),
                )
            ),
            description="Health-check the wiki",
            action_type="read",
        )
        self._register(
            "wiki_analyze_source",
            lambda args: json.dumps(
                self.wiki.analyze_source(
                    args.get("source_path", ""), force=args.get("force", False)
                )
            ),
            description="Analyze a source file",
            action_type="read",
        )
        self._register(
            "wiki_references",
            lambda args: json.dumps(self._get_references(args)),
            description="Show page references",
            action_type="read",
        )
        self._register(
            "wiki_status",
            lambda args: self.wiki.status(),
            description="Get wiki status summary",
            action_type="read",
        )
        self._register(
            "wiki_log",
            lambda args: self.wiki.append_log(
                args.get("operation", ""), args.get("details", "")
            ),
            description="Append entry to wiki log",
            action_type="write",
        )
        self._register(
            "wiki_recommend",
            lambda args: self.wiki.recommend(),
            description="Get wiki recommendations",
            action_type="read",
        )
        self._register(
            "wiki_build_index",
            lambda args: self.wiki.build_index(auto_export=args.get("auto_export", True)),
            description="Build reference index",
            action_type="write",
        )
        self._register(
            "wiki_read_schema",
            lambda args: self.wiki.read_schema(),
            description="Read wiki.md schema",
            action_type="read",
        )
        self._register(
            "wiki_synthesize",
            lambda args: json.dumps(
                self.wiki.synthesize_query(
                    query=args.get("query", ""),
                    answer=args.get("answer", ""),
                    source_pages=args.get("source_pages"),
                    raw_sources=args.get("raw_sources"),
                    page_name=args.get("page_name"),
                    auto_link=args.get("auto_link", True),
                    auto_log=args.get("auto_log", True),
                    mode=args.get("mode", "sink"),
                )
            ),
            description="Save query answer as wiki page",
            action_type="write",
        )
        self._register(
            "wiki_sink_status",
            lambda args: json.dumps(self.wiki.sink_status()),
            description="Overview of all query sinks",
            action_type="read",
        )
        self._register(
            "wiki_graph",
            lambda args: json.dumps(self._graph_action(args)),
            description="Query and modify knowledge graph",
            action_type="read",
        )
        self._register(
            "wiki_suggest_synthesis",
            lambda args: json.dumps(
                self.wiki.suggest_synthesis(source_name=args.get("source_name"))
            ),
            description="Cross-source synthesis suggestions",
            action_type="read",
        )
        self._register(
            "wiki_knowledge_gaps",
            lambda args: json.dumps(
                self.wiki.lint(generate_investigations=True, limit=args.get("limit", 20))
            ),
            description="Detect knowledge gaps",
            action_type="read",
        )
        self._register(
            "wiki_graph_analyze",
            lambda args: json.dumps(self.wiki.graph_analyze()),
            description="Analyze knowledge graph",
            action_type="read",
        )

    def _register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        action_type: str = "read",
    ) -> None:
        self._tools[name] = {
            "handler": handler,
            "description": description,
            "action_type": action_type,
        }

    def _get_references(self, args: dict) -> dict:
        page_name = args.get("page_name", "")
        detail = args.get("detail", False)
        inbound = args.get("inbound", False)
        outbound = args.get("outbound", False)
        result = {"page": page_name, "inbound": [], "outbound": []}
        if not outbound:
            result["inbound"] = self.wiki.get_inbound_links(page_name, include_context=detail)
        if not inbound:
            result["outbound"] = self.wiki.get_outbound_links(page_name, include_context=detail)
        return result

    def _graph_action(self, args: dict) -> dict:
        from ..core.relation_engine import RelationEngine

        engine = RelationEngine(self.wiki.index, wiki_root=self.wiki.root)
        action = args.get("action", "query")
        if action == "query":
            return engine.get_neighbors(
                concept=args.get("concept"),
                direction=args.get("direction", "both"),
                confidence=args.get("confidence"),
            )
        elif action == "path":
            return engine.get_path(
                source=args.get("source"),
                target=args.get("target"),
                max_length=args.get("max_length", 5),
            )
        elif action == "stats":
            return engine.get_stats()
        elif action == "write":
            relations = args.get("relations", [])
            source_file = args.get("source_file")
            for r in relations:
                r.setdefault("confidence", "EXTRACTED")
                if source_file and "source_file" not in r:
                    r["source_file"] = source_file
            return self.wiki.write_relations(relations, source_file=source_file)
        return {"status": "error", "error": f"Unknown action: {action}"}

    def get_tool(self, name: str) -> dict | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {"name": name, "description": info["description"], "action_type": info["action_type"]}
            for name, info in self._tools.items()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")
        return tool["handler"](arguments)
