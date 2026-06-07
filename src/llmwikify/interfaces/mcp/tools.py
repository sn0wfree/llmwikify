"""MCP tool definitions for wiki operations."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from llmwikify.core import Wiki
from llmwikify.core.graph_visualizer import build_visualization_data


def register_wiki_tools(mcp: FastMCP, wiki: Wiki) -> None:
    """Register all wiki tools on the MCP server."""

    @mcp.tool
    def wiki_init(overwrite: bool = False) -> str:
        """Initialize a wiki."""
        return json.dumps(wiki.init(overwrite=overwrite))

    @mcp.tool
    def wiki_ingest(source: str) -> str:
        """Ingest a source file, extract content."""
        result = wiki.ingest_source(source)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_write_page(page_name: str, content: str) -> str:
        """Write a wiki page."""
        result = wiki.write_page(page_name, content)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_read_page(page_name: str) -> str:
        """Read a wiki page (supports wiki/.sink/ files)."""
        result = wiki.read_page(page_name)
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_search(query: str, limit: int = 10, backend: str = "fts5") -> str:
        """Full-text search across wiki pages.

        Args:
            query: Search query string
            limit: Maximum number of results (default: 10)
            backend: Search backend - "fts5" (fast, default) or "qmd" (semantic)
        """
        return json.dumps(wiki.search(query, limit, backend=backend), ensure_ascii=False, indent=2)

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
        return json.dumps(wiki.status(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_log(operation: str, details: str) -> str:
        """Append entry to wiki log.

        Args:
            operation: Operation name (e.g., 'ingest', 'edit', 'lint')
            details: Human-readable description of what happened
        """
        return wiki.append_log(operation, details)

    @mcp.tool
    def wiki_recommend() -> str:
        """Get wiki recommendations (missing pages, orphan pages, etc.)."""
        return json.dumps(wiki.recommend(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_build_index() -> str:
        """Build or rebuild the reference index."""
        return json.dumps(wiki.build_index(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_read_schema() -> str:
        """Read the wiki.md schema file."""
        return json.dumps(wiki.read_schema(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_update_schema(content: str) -> str:
        """Update the wiki.md schema file.

        Args:
            content: Full markdown content for wiki.md
        """
        return json.dumps(wiki.update_schema(content), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_synthesize(
        query: str,
        answer: str,
        source_pages: list[str] | None = None,
        raw_sources: list[str] | None = None,
        page_name: str | None = None,
        auto_link: bool = True,
        auto_log: bool = True,
        merge_or_replace: str = "sink",
    ) -> str:
        """Save a query answer as a persistent wiki page.

        Args:
            query: The original question/query
            answer: The LLM-generated answer
            source_pages: List of wiki page names used as context
            raw_sources: List of raw file paths
            page_name: Optional custom page name (otherwise auto-generated)
            auto_link: Automatically wikilink content (default: True)
            auto_log: Log this operation to wiki log (default: True)
            merge_or_replace: Strategy - "sink", "merge", or "replace" (default: "sink")
        """
        result = wiki.synthesize_query(
            query=query,
            answer=answer,
            source_pages=source_pages,
            raw_sources=raw_sources,
            page_name=page_name,
            auto_link=auto_link,
            auto_log=auto_log,
            merge_or_replace=merge_or_replace,
        )
        return json.dumps(result, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_sink_status() -> str:
        """Query the sink buffer status."""
        return json.dumps(wiki.sink_status(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_suggest_synthesis(source_name: str | None = None) -> str:
        """Analyze sources and generate cross-source synthesis suggestions.

        Args:
            source_name: Optional specific source to analyze (default: all unanalyzed)
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
    def wiki_graph_analyze() -> str:
        """Analyze knowledge graph structure (PageRank, communities, suggestions)."""
        return json.dumps(wiki.graph_analyze(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_graph(
        current_page: str | None = None,
        mode: str = "auto",
    ) -> str:
        """Return graph data optimized for visualization.

        Args:
            current_page: Optional page name to center around
            mode: Display mode: 'auto', 'full', 'focused', or 'minimal'
        """
        result = build_visualization_data(wiki.index, wiki, current_page, mode)
        return json.dumps(result, ensure_ascii=False, indent=2)


def register_multi_wiki_tools(mcp: FastMCP, registry: Any) -> None:
    """Register multi-wiki tools on the MCP server.

    Args:
        mcp: FastMCP server instance
        registry: WikiRegistry instance
    """
    from llmwikify.core.wiki_instance import WikiType

    @mcp.tool
    def wiki_list() -> str:
        """List all registered wikis."""
        wikis = registry.list_wikis()
        return json.dumps({
            "wikis": [w.to_dict() for w in wikis],
            "default_wiki_id": registry.get_default_wiki_id(),
        }, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_switch(wiki_id: str) -> str:
        """Switch to a different wiki.

        Args:
            wiki_id: ID of the wiki to switch to
        """
        try:
            instance = registry.get_wiki_instance(wiki_id)
            return json.dumps({
                "message": f"Switched to wiki: {instance.name}",
                "wiki": instance.to_dict(),
            }, ensure_ascii=False, indent=2)
        except KeyError:
            return json.dumps({"error": f"Wiki not found: {wiki_id}"})

    @mcp.tool
    def wiki_register(
        wiki_id: str,
        name: str,
        wiki_type: str = "local",
        root: str | None = None,
        url: str | None = None,
        api_key: str | None = None,
    ) -> str:
        """Register a new wiki.

        Args:
            wiki_id: Unique identifier for the wiki
            name: Display name
            wiki_type: Type of wiki - "local" or "remote"
            root: Root directory path (for local wikis)
            url: Server URL (for remote wikis)
            api_key: Optional API key (for remote wikis)
        """
        from pathlib import Path

        if wiki_type == "remote":
            if not url:
                return json.dumps({"error": "url required for remote wiki"})
            instance = registry.register_remote(
                wiki_id=wiki_id,
                name=name,
                url=url,
                api_key=api_key,
            )
        else:
            if not root:
                return json.dumps({"error": "root required for local wiki"})
            instance = registry.register_wiki(
                wiki_id=wiki_id,
                name=name,
                root=Path(root),
            )

        return json.dumps({
            "message": f"Registered wiki: {wiki_id}",
            "wiki": instance.to_dict(),
        }, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_unregister(wiki_id: str) -> str:
        """Unregister a wiki.

        Args:
            wiki_id: ID of the wiki to remove
        """
        try:
            registry.unregister_wiki(wiki_id)
            return json.dumps({"message": f"Unregistered wiki: {wiki_id}"})
        except KeyError:
            return json.dumps({"error": f"Wiki not found: {wiki_id}"})

    @mcp.tool
    def wiki_status(wiki_id: str | None = None) -> str:
        """Get wiki status.

        Args:
            wiki_id: Optional wiki ID (uses default if not specified)
        """
        if wiki_id:
            try:
                status = registry.get_wiki_status(wiki_id)
                return json.dumps(status, ensure_ascii=False, indent=2)
            except KeyError:
                return json.dumps({"error": f"Wiki not found: {wiki_id}"})
        else:
            # Default wiki status
            default_id = registry.get_default_wiki_id()
            if not default_id:
                return json.dumps({"error": "No default wiki configured"})
            status = registry.get_wiki_status(default_id)
            return json.dumps(status, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_search(query: str, limit: int = 10, wiki_id: str | None = None) -> str:
        """Search wiki pages.

        Args:
            query: Search query string
            limit: Maximum number of results (default: 10)
            wiki_id: Optional wiki ID (uses default if not specified)
        """
        if wiki_id:
            try:
                from llmwikify.core.wiki_instance import WikiType
                instance = registry.get_wiki_instance(wiki_id)
                if instance.wiki_type == WikiType.REMOTE:
                    client = registry._remote_clients.get(wiki_id)
                    if client:
                        results = client.search(query, limit)
                        return json.dumps(results, ensure_ascii=False, indent=2)
                    return json.dumps({"error": "Remote wiki client not available"})
                else:
                    wiki = registry.get_wiki(wiki_id)
                    results = wiki.search(query, limit)
                    return json.dumps(results, ensure_ascii=False, indent=2)
            except KeyError:
                return json.dumps({"error": f"Wiki not found: {wiki_id}"})
        else:
            # Cross-wiki search
            results = registry.cross_wiki_search(query, limit=limit)
            return json.dumps(results, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_search_cross(query: str, limit: int = 10, wiki_ids: str | None = None) -> str:
        """Search across multiple wikis.

        Args:
            query: Search query string
            limit: Results per wiki (default: 10)
            wiki_ids: Comma-separated wiki IDs (empty = all wikis)
        """
        ids = wiki_ids.split(",") if wiki_ids else None
        results = registry.cross_wiki_search(query, ids, limit)
        return json.dumps({
            "results": results,
            "total_results": len(results),
            "searched_wikis": ids or [w.wiki_id for w in registry.list_wikis()],
        }, ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_scan(scan_paths: str = ".", scan_depth: int = 2) -> str:
        """Scan directories for wikis.

        Args:
            scan_paths: Comma-separated directory paths to scan
            scan_depth: Maximum recursion depth (default: 2)
        """
        paths = [p.strip() for p in scan_paths.split(",")]
        new_wikis = registry.scan_directories(paths, scan_depth)
        return json.dumps({
            "new_wikis": [w.to_dict() for w in new_wikis],
            "count": len(new_wikis),
        }, ensure_ascii=False, indent=2)
