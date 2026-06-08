"""wiki_query_skill — 28-action aggregator for all wiki operations.

Per ``v0.32-execution-plan.md`` Phase 12 (#27): aggregates
all wiki-facing operations into a single Skill with 28
actions. Each action delegates to the underlying wiki
method via ``ctx.wiki``.

The 28 actions map 1:1 to the 28 MCP ``@mcp.tool``
definitions in ``interfaces/mcp/tools.py``. This skill
provides the same functionality via the Skill framework
instead of MCP.

Actions (28):

  Core wiki (20):
    1.  init              — initialize wiki
    2.  ingest            — ingest a source file
    3.  write_page        — write a wiki page
    4.  read_page         — read a wiki page
    5.  search            — full-text search
    6.  lint              — health-check wiki
    7.  analyze_source    — analyze source file
    8.  references        — show page references
    9.  status            — wiki status summary
    10. log               — append to wiki log
    11. recommend         — get recommendations
    12. build_index       — build reference index
    13. read_schema       — read wiki.md schema
    14. update_schema     — update wiki.md schema
    15. synthesize        — save query answer as page
    16. sink_status       — query sink buffer status
    17. suggest_synthesis — cross-source synthesis
    18. knowledge_gaps    — detect knowledge gaps
    19. graph_analyze     — analyze graph structure
    20. graph             — graph visualization data

  Multi-wiki (8):
    21. wiki_list         — list all wikis
    22. wiki_switch       — switch active wiki
    23. wiki_register     — register a new wiki
    24. wiki_unregister   — unregister a wiki
    25. wiki_status       — get wiki status by ID
    26. wiki_search       — search by wiki ID
    27. wiki_search_cross — cross-wiki search
    28. wiki_scan         — scan for wikis

Design ref: ``v0.32-skill-restructure.md`` §6.3
"""

from __future__ import annotations

import json
import logging
from typing import Any

from llmwikify.apps.chat.skills.base import (
    Skill,
    SkillAction,
    SkillContext,
    SkillResult,
)

logger = logging.getLogger(__name__)


# ─── Helper ──────────────────────────────────────────────────────


def _wiki(ctx: SkillContext) -> Any | SkillResult:
    """Extract wiki from context, or return error SkillResult."""
    wiki = ctx.wiki
    if wiki is None:
        return SkillResult.fail("No wiki in context (ctx.wiki is None)")
    return wiki


def _json(obj: Any) -> str:
    """Serialize to JSON string (matches MCP tool output format)."""
    return json.dumps(obj, ensure_ascii=False, indent=2)


# ─── 20 core wiki action handlers ────────────────────────────────


async def _init(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.init(overwrite=args.get("overwrite", False))
    return SkillResult.ok({"result": result})


async def _ingest(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    source = args.get("source", "")
    if not source:
        return SkillResult.fail("source is required")
    result = wiki.ingest_source(source)
    return SkillResult.ok({"result": result})


async def _write_page(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    page_name = args.get("page_name", "")
    content = args.get("content", "")
    if not page_name or not content:
        return SkillResult.fail("page_name and content are required")
    result = wiki.write_page(page_name, content)
    return SkillResult.ok({"result": result})


async def _read_page(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    page_name = args.get("page_name", "")
    if not page_name:
        return SkillResult.fail("page_name is required")
    result = wiki.read_page(page_name)
    return SkillResult.ok({"result": result})


async def _search(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    limit = args.get("limit", 10)
    backend = args.get("backend", "fts5")
    result = wiki.search(query, limit, backend=backend)
    return SkillResult.ok({"result": result})


async def _lint(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.lint(
        mode=args.get("mode", "check"),
        limit=args.get("limit", 10),
        force=args.get("force", False),
        generate_investigations=args.get("generate_investigations", False),
    )
    fmt = args.get("format", "full")
    if fmt == "brief":
        return SkillResult.ok({
            "hints": result.get("hints", {}),
            "issue_count": result.get("issue_count", 0),
            "total_pages": result.get("total_pages", 0),
        })
    elif fmt == "recommendations":
        return SkillResult.ok({
            "missing_pages": result.get("investigations", {}).get("missing_pages", []),
            "orphan_pages": result.get("issues", []),
        })
    return SkillResult.ok({"result": result})


async def _analyze_source(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    source_path = args.get("source_path", "")
    if not source_path:
        return SkillResult.fail("source_path is required")
    result = wiki.analyze_source(source_path, force=args.get("force", False))
    return SkillResult.ok({"result": result})


async def _references(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    page_name = args.get("page_name", "")
    if not page_name:
        return SkillResult.fail("page_name is required")
    detail = args.get("detail", False)
    inbound = args.get("inbound", False)
    outbound = args.get("outbound", False)
    result = {"page": page_name, "inbound": [], "outbound": []}
    if not outbound:
        result["inbound"] = wiki.get_inbound_links(page_name, include_context=detail)
    if not inbound:
        result["outbound"] = wiki.get_outbound_links(page_name, include_context=detail)
    return SkillResult.ok(result)


async def _status(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.status()
    return SkillResult.ok({"result": result})


async def _log(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    operation = args.get("operation", "")
    details = args.get("details", "")
    if not operation or not details:
        return SkillResult.fail("operation and details are required")
    result = wiki.append_log(operation, details)
    return SkillResult.ok({"result": result})


async def _recommend(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.recommend()
    return SkillResult.ok({"result": result})


async def _build_index(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.build_index()
    return SkillResult.ok({"result": result})


async def _read_schema(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.read_schema()
    return SkillResult.ok({"result": result})


async def _update_schema(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    content = args.get("content", "")
    if not content:
        return SkillResult.fail("content is required")
    result = wiki.update_schema(content)
    return SkillResult.ok({"result": result})


async def _synthesize(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    query = args.get("query", "")
    answer = args.get("answer", "")
    if not query or not answer:
        return SkillResult.fail("query and answer are required")
    result = wiki.synthesize_query(
        query=query,
        answer=answer,
        source_pages=args.get("source_pages"),
        raw_sources=args.get("raw_sources"),
        page_name=args.get("page_name"),
        auto_link=args.get("auto_link", True),
        auto_log=args.get("auto_log", True),
        merge_or_replace=args.get("merge_or_replace", "sink"),
    )
    return SkillResult.ok({"result": result})


async def _sink_status(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.sink_status()
    return SkillResult.ok({"result": result})


async def _suggest_synthesis(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.suggest_synthesis(source_name=args.get("source_name"))
    return SkillResult.ok({"result": result})


async def _knowledge_gaps(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.lint(
        generate_investigations=True,
        limit=args.get("limit", 20),
    )
    return SkillResult.ok({"result": result})


async def _graph_analyze(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    result = wiki.graph_analyze()
    return SkillResult.ok({"result": result})


async def _graph(args: dict, ctx: SkillContext) -> SkillResult:
    wiki = _wiki(ctx)
    if isinstance(wiki, SkillResult):
        return wiki
    from llmwikify.core.graph_visualizer import build_visualization_data
    result = build_visualization_data(
        wiki.index, wiki,
        args.get("current_page"),
        args.get("mode", "auto"),
    )
    return SkillResult.ok({"result": result})


# ─── 8 multi-wiki action handlers ────────────────────────────────


async def _wiki_list(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    wikis = registry.list_wikis()
    return SkillResult.ok({
        "wikis": [w.to_dict() for w in wikis],
        "default_wiki_id": registry.get_default_wiki_id(),
    })


async def _wiki_switch(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    wiki_id = args.get("wiki_id", "")
    if not wiki_id:
        return SkillResult.fail("wiki_id is required")
    try:
        instance = registry.get_wiki_instance(wiki_id)
        return SkillResult.ok({
            "message": f"Switched to wiki: {instance.name}",
            "wiki": instance.to_dict(),
        })
    except KeyError:
        return SkillResult.fail(f"Wiki not found: {wiki_id}")


async def _wiki_register(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    wiki_id = args.get("wiki_id", "")
    name = args.get("name", "")
    if not wiki_id or not name:
        return SkillResult.fail("wiki_id and name are required")
    wiki_type = args.get("wiki_type", "local")
    try:
        if wiki_type == "remote":
            url = args.get("url", "")
            if not url:
                return SkillResult.fail("url required for remote wiki")
            instance = registry.register_remote(
                wiki_id=wiki_id, name=name, url=url,
                api_key=args.get("api_key"),
            )
        else:
            from pathlib import Path
            root = args.get("root", "")
            if not root:
                return SkillResult.fail("root required for local wiki")
            instance = registry.register_wiki(
                wiki_id=wiki_id, name=name, root=Path(root),
            )
        return SkillResult.ok({
            "message": f"Registered wiki: {wiki_id}",
            "wiki": instance.to_dict(),
        })
    except Exception as e:
        return SkillResult.fail(f"register failed: {e!r}")


async def _wiki_unregister(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    wiki_id = args.get("wiki_id", "")
    if not wiki_id:
        return SkillResult.fail("wiki_id is required")
    try:
        registry.unregister_wiki(wiki_id)
        return SkillResult.ok({"message": f"Unregistered wiki: {wiki_id}"})
    except KeyError:
        return SkillResult.fail(f"Wiki not found: {wiki_id}")


async def _wiki_status_by_id(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    wiki_id = args.get("wiki_id", "")
    try:
        if wiki_id:
            status = registry.get_wiki_status(wiki_id)
        else:
            default_id = registry.get_default_wiki_id()
            if not default_id:
                return SkillResult.fail("No default wiki configured")
            status = registry.get_wiki_status(default_id)
        return SkillResult.ok({"result": status})
    except KeyError:
        return SkillResult.fail(f"Wiki not found: {wiki_id}")


async def _wiki_search_by_id(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    wiki_id = args.get("wiki_id", "")
    limit = args.get("limit", 10)
    try:
        if wiki_id:
            from llmwikify.core.wiki_instance import WikiType
            instance = registry.get_wiki_instance(wiki_id)
            if instance.wiki_type == WikiType.REMOTE:
                client = registry._remote_clients.get(wiki_id)
                if client:
                    results = client.search(query, limit)
                else:
                    return SkillResult.fail("Remote wiki client not available")
            else:
                w = registry.get_wiki(wiki_id)
                results = w.search(query, limit)
        else:
            results = registry.cross_wiki_search(query, limit=limit)
        return SkillResult.ok({"result": results})
    except KeyError:
        return SkillResult.fail(f"Wiki not found: {wiki_id}")


async def _wiki_search_cross(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    query = args.get("query", "")
    if not query:
        return SkillResult.fail("query is required")
    wiki_ids_str = args.get("wiki_ids", "")
    ids = [x.strip() for x in wiki_ids_str.split(",")] if wiki_ids_str else None
    limit = args.get("limit", 10)
    results = registry.cross_wiki_search(query, ids, limit)
    return SkillResult.ok({
        "results": results,
        "total_results": len(results),
        "searched_wikis": ids or [w.wiki_id for w in registry.list_wikis()],
    })


async def _wiki_scan(args: dict, ctx: SkillContext) -> SkillResult:
    registry = ctx.config.get("wiki_registry") if ctx.config else None
    if registry is None:
        return SkillResult.fail("wiki_registry not configured")
    scan_paths_str = args.get("scan_paths", ".")
    scan_depth = args.get("scan_depth", 2)
    paths = [p.strip() for p in scan_paths_str.split(",")]
    new_wikis = registry.scan_directories(paths, scan_depth)
    return SkillResult.ok({
        "new_wikis": [w.to_dict() for w in new_wikis],
        "count": len(new_wikis),
    })


# ─── Skill declaration ─────────────────────────────────────────


class WikiQuerySkill(Skill):
    """28-action aggregator for all wiki operations.

    Each action wraps a wiki method and returns SkillResult.
    The 28 actions map 1:1 to the 28 MCP @mcp.tool definitions.
    """

    name = "wiki_query"
    description = "Complete wiki operations: read, write, search, lint, graph, multi-wiki management"
    actions = {
        # Core wiki (20)
        "init": SkillAction(
            name="init",
            description="Initialize a wiki",
            handler=_init,
            input_schema={"type": "object", "properties": {"overwrite": {"type": "boolean", "default": False}}},
        ),
        "ingest": SkillAction(
            name="ingest",
            description="Ingest a source file, extract content",
            handler=_ingest,
            input_schema={"type": "object", "properties": {"source": {"type": "string"}}, "required": ["source"]},
        ),
        "write_page": SkillAction(
            name="write_page",
            description="Write a wiki page",
            handler=_write_page,
            input_schema={"type": "object", "properties": {"page_name": {"type": "string"}, "content": {"type": "string"}}, "required": ["page_name", "content"]},
            action_type="write",
        ),
        "read_page": SkillAction(
            name="read_page",
            description="Read a wiki page (supports wiki/.sink/ files)",
            handler=_read_page,
            input_schema={"type": "object", "properties": {"page_name": {"type": "string"}}, "required": ["page_name"]},
        ),
        "search": SkillAction(
            name="search",
            description="Full-text search across wiki pages (fts5 or qmd backend)",
            handler=_search,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}, "backend": {"type": "string", "default": "fts5"}}, "required": ["query"]},
        ),
        "lint": SkillAction(
            name="lint",
            description="Health-check wiki (broken links, orphans, schema gaps)",
            handler=_lint,
            input_schema={"type": "object", "properties": {"generate_investigations": {"type": "boolean", "default": False}, "format": {"type": "string", "default": "full"}, "mode": {"type": "string", "default": "check"}, "limit": {"type": "integer", "default": 10}, "force": {"type": "boolean", "default": False}}},
        ),
        "analyze_source": SkillAction(
            name="analyze_source",
            description="Analyze a source file and cache structured extraction results",
            handler=_analyze_source,
            input_schema={"type": "object", "properties": {"source_path": {"type": "string"}, "force": {"type": "boolean", "default": False}}, "required": ["source_path"]},
        ),
        "references": SkillAction(
            name="references",
            description="Show page references (inbound and outbound wikilinks)",
            handler=_references,
            input_schema={"type": "object", "properties": {"page_name": {"type": "string"}, "detail": {"type": "boolean", "default": False}, "inbound": {"type": "boolean", "default": False}, "outbound": {"type": "boolean", "default": False}}, "required": ["page_name"]},
        ),
        "status": SkillAction(
            name="status",
            description="Get wiki status summary",
            handler=_status,
            input_schema={"type": "object", "properties": {}},
        ),
        "log": SkillAction(
            name="log",
            description="Append entry to wiki log",
            handler=_log,
            input_schema={"type": "object", "properties": {"operation": {"type": "string"}, "details": {"type": "string"}}, "required": ["operation", "details"]},
            action_type="write",
        ),
        "recommend": SkillAction(
            name="recommend",
            description="Get wiki recommendations (missing pages, orphan pages, etc.)",
            handler=_recommend,
            input_schema={"type": "object", "properties": {}},
        ),
        "build_index": SkillAction(
            name="build_index",
            description="Build or rebuild the reference index",
            handler=_build_index,
            input_schema={"type": "object", "properties": {}},
            action_type="write",
        ),
        "read_schema": SkillAction(
            name="read_schema",
            description="Read the wiki.md schema file",
            handler=_read_schema,
            input_schema={"type": "object", "properties": {}},
        ),
        "update_schema": SkillAction(
            name="update_schema",
            description="Update the wiki.md schema file",
            handler=_update_schema,
            input_schema={"type": "object", "properties": {"content": {"type": "string"}}, "required": ["content"]},
            action_type="write",
        ),
        "synthesize": SkillAction(
            name="synthesize",
            description="Save a query answer as a persistent wiki page",
            handler=_synthesize,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "answer": {"type": "string"}, "source_pages": {"type": "array", "items": {"type": "string"}}, "raw_sources": {"type": "array", "items": {"type": "string"}}, "page_name": {"type": "string"}, "auto_link": {"type": "boolean", "default": True}, "auto_log": {"type": "boolean", "default": True}, "merge_or_replace": {"type": "string", "default": "sink"}}, "required": ["query", "answer"]},
            action_type="write",
        ),
        "sink_status": SkillAction(
            name="sink_status",
            description="Query the sink buffer status",
            handler=_sink_status,
            input_schema={"type": "object", "properties": {}},
        ),
        "suggest_synthesis": SkillAction(
            name="suggest_synthesis",
            description="Analyze sources and generate cross-source synthesis suggestions",
            handler=_suggest_synthesis,
            input_schema={"type": "object", "properties": {"source_name": {"type": "string"}}},
        ),
        "knowledge_gaps": SkillAction(
            name="knowledge_gaps",
            description="Detect knowledge gaps, outdated pages, and redundancy across the wiki",
            handler=_knowledge_gaps,
            input_schema={"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}},
        ),
        "graph_analyze": SkillAction(
            name="graph_analyze",
            description="Analyze knowledge graph structure (PageRank, communities, suggestions)",
            handler=_graph_analyze,
            input_schema={"type": "object", "properties": {}},
        ),
        "graph": SkillAction(
            name="graph",
            description="Return graph data optimized for visualization",
            handler=_graph,
            input_schema={"type": "object", "properties": {"current_page": {"type": "string"}, "mode": {"type": "string", "default": "auto"}}},
        ),
        # Multi-wiki (8)
        "wiki_list": SkillAction(
            name="wiki_list",
            description="List all registered wikis",
            handler=_wiki_list,
            input_schema={"type": "object", "properties": {}},
        ),
        "wiki_switch": SkillAction(
            name="wiki_switch",
            description="Switch to a different wiki",
            handler=_wiki_switch,
            input_schema={"type": "object", "properties": {"wiki_id": {"type": "string"}}, "required": ["wiki_id"]},
        ),
        "wiki_register": SkillAction(
            name="wiki_register",
            description="Register a new wiki (local or remote)",
            handler=_wiki_register,
            input_schema={"type": "object", "properties": {"wiki_id": {"type": "string"}, "name": {"type": "string"}, "wiki_type": {"type": "string", "default": "local"}, "root": {"type": "string"}, "url": {"type": "string"}, "api_key": {"type": "string"}}, "required": ["wiki_id", "name"]},
            action_type="write",
        ),
        "wiki_unregister": SkillAction(
            name="wiki_unregister",
            description="Unregister a wiki",
            handler=_wiki_unregister,
            input_schema={"type": "object", "properties": {"wiki_id": {"type": "string"}}, "required": ["wiki_id"]},
            action_type="write",
        ),
        "wiki_status": SkillAction(
            name="wiki_status",
            description="Get wiki status by ID (or default wiki)",
            handler=_wiki_status_by_id,
            input_schema={"type": "object", "properties": {"wiki_id": {"type": "string"}}},
        ),
        "wiki_search": SkillAction(
            name="wiki_search",
            description="Search wiki pages by wiki ID (or cross-wiki search)",
            handler=_wiki_search_by_id,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}, "wiki_id": {"type": "string"}}, "required": ["query"]},
        ),
        "wiki_search_cross": SkillAction(
            name="wiki_search_cross",
            description="Search across multiple wikis",
            handler=_wiki_search_cross,
            input_schema={"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}, "wiki_ids": {"type": "string"}}, "required": ["query"]},
        ),
        "wiki_scan": SkillAction(
            name="wiki_scan",
            description="Scan directories for wikis",
            handler=_wiki_scan,
            input_schema={"type": "object", "properties": {"scan_paths": {"type": "string", "default": "."}, "scan_depth": {"type": "integer", "default": 2}}},
        ),
    }


wiki_query_skill = WikiQuerySkill()


__all__ = ["WikiQuerySkill", "wiki_query_skill"]
