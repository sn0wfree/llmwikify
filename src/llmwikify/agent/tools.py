"""Tool Registry - Wraps MCP tools for Agent internal use.

Registers all 20+ MCP tools and provides a unified execution interface
with confirmation flow for write operations.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class WikiToolRegistry:
    """Registry of wiki tools that the Agent can call.

    Wraps existing MCP tools and Wiki methods into a unified interface.
    Supports confirmation flow for write operations:
    - requires_confirmation=False: execute directly
    - requires_confirmation="posthoc": execute and log for later review
    - requires_confirmation="pre": create confirmation, return confirmation_id
    """

    def __init__(self, wiki: Any, db: Any = None, wiki_id: str | None = None):
        self.wiki = wiki
        self.db = db
        self.wiki_id = wiki_id
        self._tools: dict[str, dict] = {}
        self._pending_confirmations: dict[str, dict] = {}
        self._ingest_log: list[dict] = []
        self._max_ingest_log = 100
        self._register_all_tools()
        if db and wiki_id:
            self._load_confirmations_from_db()

    def _load_confirmations_from_db(self) -> None:
        rows = self.db.get_confirmations(self.wiki_id, status="pending")
        for c in rows:
            self._pending_confirmations[c["id"]] = c

    def _register_all_tools(self) -> None:
        # No confirmation needed
        self._register(
            "wiki_init",
            lambda args: json.dumps(self.wiki.init(overwrite=args.get("overwrite", False))),
            description="Initialize a wiki",
            action_type="write",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "overwrite": {"type": "boolean", "description": "Whether to overwrite existing wiki", "default": False},
                },
                "required": [],
            },
        )
        self._register(
            "wiki_read_page",
            lambda args: self.wiki.read_page(args.get("page_name", "")),
            description="Read a wiki page",
            action_type="read",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "page_name": {"type": "string", "description": "Name or path of the page to read"},
                },
                "required": ["page_name"],
            },
        )
        self._register(
            "wiki_search",
            lambda args: self.wiki.search(
                args.get("query", ""), args.get("limit", 10)
            ),
            description="Full-text search across wiki pages",
            action_type="read",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query string"},
                    "limit": {"type": "integer", "description": "Max results to return", "default": 10},
                },
                "required": ["query"],
            },
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
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["check", "fix"], "description": "Lint mode", "default": "check"},
                    "limit": {"type": "integer", "description": "Max issues to return", "default": 10},
                    "force": {"type": "boolean", "description": "Force re-lint", "default": False},
                    "generate_investigations": {"type": "boolean", "description": "Generate investigation questions", "default": False},
                },
                "required": [],
            },
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
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Path to the source file to analyze"},
                    "force": {"type": "boolean", "description": "Force re-analysis", "default": False},
                },
                "required": ["source_path"],
            },
        )
        self._register(
            "wiki_references",
            lambda args: json.dumps(self._get_references(args)),
            description="Show page references (inbound/outbound links)",
            action_type="read",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "page_name": {"type": "string", "description": "Page to get references for"},
                    "detail": {"type": "boolean", "description": "Include context snippets", "default": False},
                    "inbound": {"type": "boolean", "description": "Only show inbound links", "default": False},
                    "outbound": {"type": "boolean", "description": "Only show outbound links", "default": False},
                },
                "required": ["page_name"],
            },
        )
        self._register(
            "wiki_status",
            lambda args: self.wiki.status(),
            description="Get wiki status summary",
            action_type="read",
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self._register(
            "wiki_recommend",
            lambda args: self.wiki.recommend(),
            description="Get wiki recommendations",
            action_type="read",
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self._register(
            "wiki_build_index",
            lambda args: self.wiki.build_index(auto_export=args.get("auto_export", True)),
            description="Build reference index",
            action_type="write",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "auto_export": {"type": "boolean", "description": "Auto-export after building", "default": True},
                },
                "required": [],
            },
        )
        self._register(
            "wiki_read_schema",
            lambda args: self.wiki.read_schema(),
            description="Read wiki.md schema",
            action_type="read",
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self._register(
            "wiki_sink_status",
            lambda args: json.dumps(self.wiki.sink_status()),
            description="Overview of all query sinks",
            action_type="read",
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self._register(
            "wiki_suggest_synthesis",
            lambda args: json.dumps(
                self.wiki.suggest_synthesis(source_name=args.get("source_name"))
            ),
            description="Cross-source synthesis suggestions",
            action_type="read",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "source_name": {"type": "string", "description": "Filter by source name"},
                },
                "required": [],
            },
        )
        self._register(
            "wiki_knowledge_gaps",
            lambda args: json.dumps(
                self.wiki.lint(generate_investigations=True, limit=args.get("limit", 20))
            ),
            description="Detect knowledge gaps",
            action_type="read",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max gaps to return", "default": 20},
                },
                "required": [],
            },
        )
        self._register(
            "wiki_graph_analyze",
            lambda args: json.dumps(self.wiki.graph_analyze()),
            description="Analyze knowledge graph",
            action_type="read",
            requires_confirmation=False,
            parameters={"type": "object", "properties": {}, "required": []},
        )
        self._register(
            "wiki_log",
            lambda args: self.wiki.append_log(
                args.get("operation", ""), args.get("details", "")
            ),
            description="Append entry to wiki log",
            action_type="write",
            requires_confirmation=False,
            parameters={
                "type": "object",
                "properties": {
                    "operation": {"type": "string", "description": "Operation name"},
                    "details": {"type": "string", "description": "Log entry details"},
                },
                "required": ["operation", "details"],
            },
        )

        # Post-hoc confirmation (execute and log)
        self._register(
            "wiki_ingest",
            lambda args: self.wiki.ingest_source(args.get("source", "")),
            description="Ingest a source file",
            action_type="write",
            requires_confirmation="posthoc",
            parameters={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Path or URL of the source to ingest"},
                },
                "required": ["source"],
            },
        )

        # Pre-confirmation (requires user approval before execution)
        self._register(
            "wiki_write_page",
            lambda args: self.wiki.write_page(
                args.get("page_name", ""), args.get("content", "")
            ),
            description="Write a wiki page",
            action_type="write",
            requires_confirmation="pre",
            parameters={
                "type": "object",
                "properties": {
                    "page_name": {"type": "string", "description": "Page path (e.g. entities/PersonName)"},
                    "content": {"type": "string", "description": "Markdown content to write"},
                },
                "required": ["page_name", "content"],
            },
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
            requires_confirmation="pre",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The original question"},
                    "answer": {"type": "string", "description": "The answer to save"},
                    "source_pages": {"type": "array", "items": {"type": "string"}, "description": "Source page names used"},
                    "raw_sources": {"type": "array", "items": {"type": "string"}, "description": "Raw source references"},
                    "page_name": {"type": "string", "description": "Target page name (auto-generated if omitted)"},
                    "auto_link": {"type": "boolean", "description": "Auto-create entity links", "default": True},
                    "auto_log": {"type": "boolean", "description": "Auto-log to wiki log", "default": True},
                    "mode": {"type": "string", "enum": ["sink", "entity", "concept"], "description": "Synthesis mode", "default": "sink"},
                },
                "required": ["query", "answer"],
            },
        )
        self._register(
            "wiki_graph",
            lambda args: json.dumps(self._graph_action(args)),
            description="Query and modify knowledge graph",
            action_type="read",
            requires_confirmation="pre",
            parameters={
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["query", "path", "stats", "write"], "description": "Graph action", "default": "query"},
                    "concept": {"type": "string", "description": "Concept name (for query action)"},
                    "direction": {"type": "string", "enum": ["inbound", "outbound", "both"], "description": "Link direction", "default": "both"},
                    "confidence": {"type": "string", "description": "Filter by confidence level"},
                    "source": {"type": "string", "description": "Source concept (for path action)"},
                    "target": {"type": "string", "description": "Target concept (for path action)"},
                    "max_length": {"type": "integer", "description": "Max path length", "default": 5},
                    "relations": {"type": "array", "items": {"type": "object"}, "description": "Relations to write (for write action)"},
                    "source_file": {"type": "string", "description": "Source file for relations"},
                },
                "required": [],
            },
        )

    def _register(
        self,
        name: str,
        handler: Callable,
        description: str = "",
        action_type: str = "read",
        requires_confirmation: bool | str = False,
        parameters: dict | None = None,
    ) -> None:
        self._tools[name] = {
            "handler": handler,
            "description": description,
            "action_type": action_type,
            "requires_confirmation": requires_confirmation,
            "parameters": parameters or {"type": "object", "properties": {}, "required": []},
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

    def _classify_page_group(self, arguments: dict) -> str:
        """Classify a tool call into a confirmation group."""
        page_name = arguments.get("page_name", "")
        if "/entities/" in page_name or page_name.startswith("entities/"):
            return "entity_pages"
        elif "/concepts/" in page_name or page_name.startswith("concepts/"):
            return "concept_pages"
        elif "/sources/" in page_name or page_name.startswith("sources/"):
            return "source_pages"
        elif "/models/" in page_name or page_name.startswith("models/"):
            return "model_pages"
        else:
            return "other_pages"

    def _analyze_impact(self, tool_name: str, arguments: dict) -> dict:
        """Analyze the impact of a tool call for confirmation preview."""
        if tool_name == "wiki_write_page":
            content = arguments.get("content", "")
            return {
                "page": arguments.get("page_name", ""),
                "change_type": "write",
                "chars": len(content),
            }
        elif tool_name == "wiki_synthesize":
            return {
                "page": arguments.get("page_name", arguments.get("query", "")),
                "change_type": "synthesize",
                "query": arguments.get("query", ""),
            }
        elif tool_name == "wiki_ingest":
            return {
                "source": arguments.get("source", ""),
                "change_type": "ingest",
            }
        elif tool_name == "wiki_graph":
            if arguments.get("action") == "write":
                return {
                    "change_type": "graph_write",
                    "relations_count": len(arguments.get("relations", [])),
                }
            return {"change_type": "graph_query"}
        return {"change_type": "unknown"}

    def get_tool(self, name: str) -> dict | None:
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": name,
                "description": info["description"],
                "action_type": info["action_type"],
                "requires_confirmation": info["requires_confirmation"],
                "parameters": info.get("parameters", {"type": "object", "properties": {}, "required": []}),
            }
            for name, info in self._tools.items()
        ]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name}")

        confirmation_mode = tool.get("requires_confirmation", False)

        if confirmation_mode is False:
            # Direct execution
            return tool["handler"](arguments)

        elif confirmation_mode == "posthoc":
            # Execute and log for post-hoc review
            result = tool["handler"](arguments)
            self._log_posthoc(name, arguments, result)
            return result

        else:
            impact = self._analyze_impact(name, arguments)
            group = self._classify_page_group(arguments)
            confirmation_id = str(uuid.uuid4())[:8]

            confirmation = {
                "id": confirmation_id,
                "tool": name,
                "arguments": arguments,
                "action_type": tool["action_type"],
                "impact": impact,
                "group": group,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "pending",
            }
            if self.db and self.wiki_id:
                confirmation["wiki_id"] = self.wiki_id
                self.db.save_confirmation(confirmation)
            self._pending_confirmations[confirmation_id] = confirmation

            return {
                "status": "confirmation_required",
                "confirmation_id": confirmation_id,
                "impact": impact,
                "group": group,
            }

    def _log_posthoc(self, tool_name: str, arguments: dict, result: Any) -> None:
        """Log a post-hoc confirmation for ingest operations."""
        log_entry = {
            "id": f"ingest-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}",
            "tool": tool_name,
            "arguments": arguments,
            "result_summary": str(result)[:500] if result else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "executed",
        }
        self._ingest_log.append(log_entry)
        if len(self._ingest_log) > self._max_ingest_log:
            self._ingest_log = self._ingest_log[-self._max_ingest_log:]

    def confirm_execution(self, confirmation_id: str) -> Any:
        if self.db:
            conf = self.db.get_confirmation(confirmation_id)
            if conf and conf.get("wiki_id") == self.wiki_id:
                if conf["status"] != "pending":
                    return {"status": "error", "error": f"Confirmation already {conf['status']}"}
                tool = self._tools.get(conf["tool"])
                if tool is None:
                    return {"status": "error", "error": f"Tool not found: {conf['tool']}"}
                try:
                    result = tool["handler"](json.loads(conf["arguments"]) if isinstance(conf["arguments"], str) else conf["arguments"])
                    self.db.update_confirmation_status(confirmation_id, "approved")
                    return {"status": "executed", "confirmation_id": confirmation_id, "result": result}
                except Exception as e:
                    self.db.update_confirmation_status(confirmation_id, "rejected")
                    return {"status": "error", "error": str(e)}

        confirmation = self._pending_confirmations.pop(confirmation_id, None)
        if confirmation is None:
            return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}
        tool = self._tools.get(confirmation["tool"])
        if tool is None:
            return {"status": "error", "error": f"Tool not found: {confirmation['tool']}"}
        try:
            result = tool["handler"](confirmation["arguments"])
            confirmation["status"] = "approved"
            return {"status": "executed", "confirmation_id": confirmation_id, "result": result}
        except Exception as e:
            confirmation["status"] = "rejected"
            return {"status": "error", "error": str(e)}

    def reject_execution(self, confirmation_id: str) -> dict:
        if self.db:
            conf = self.db.get_confirmation(confirmation_id)
            if conf and conf.get("wiki_id") == self.wiki_id:
                self.db.update_confirmation_status(confirmation_id, "rejected")
                self._pending_confirmations.pop(confirmation_id, None)
                return {"status": "rejected", "confirmation_id": confirmation_id}

        confirmation = self._pending_confirmations.pop(confirmation_id, None)
        if confirmation is None:
            return {"status": "error", "error": f"Invalid confirmation ID: {confirmation_id}"}
        confirmation["status"] = "rejected"
        return {"status": "rejected", "confirmation_id": confirmation_id}

    def confirm_batch(self, confirmation_ids: list[str]) -> list[dict]:
        """Execute multiple confirmed tool calls at once."""
        results = []
        for cid in confirmation_ids:
            result = self.confirm_execution(cid)
            results.append(result)
        return results

    def reject_batch(self, confirmation_ids: list[str]) -> list[dict]:
        """Reject multiple pending confirmations at once."""
        results = []
        for cid in confirmation_ids:
            result = self.reject_execution(cid)
            results.append(result)
        return results

    def get_pending_confirmations(self) -> list[dict]:
        """Get all pending confirmations."""
        return [c for c in self._pending_confirmations.values() if c["status"] == "pending"]

    def get_pending_by_group(self) -> dict[str, list[dict]]:
        """Get pending confirmations grouped by page type."""
        groups: dict[str, list[dict]] = {}
        for c in self._pending_confirmations.values():
            if c["status"] != "pending":
                continue
            group = c.get("group", "other_pages")
            if group not in groups:
                groups[group] = []
            groups[group].append(c)
        return groups

    def get_ingest_log(self, limit: int = 20) -> list[dict]:
        """Get recent ingest log entries."""
        return self._ingest_log[-limit:]

    def get_ingest_changes(self, ingest_id: str) -> dict | None:
        """Get detailed changes for a specific ingest."""
        for entry in self._ingest_log:
            if entry["id"] == ingest_id:
                return entry
        return None
