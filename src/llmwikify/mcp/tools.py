"""MCP tool definitions for wiki operations."""

from __future__ import annotations

import json

from fastmcp import FastMCP

from llmwikify.core import Wiki


def register_wiki_tools(mcp: FastMCP, wiki: Wiki) -> None:
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
        return json.dumps(wiki.status(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_log(message: str) -> str:
        """Append a log entry to the wiki."""
        return wiki.log(message)

    @mcp.tool
    def wiki_recommend() -> str:
        """Get wiki recommendations (missing pages, orphan pages, etc.)."""
        return json.dumps(wiki.recommend(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_build_index() -> str:
        """Build or rebuild the reference index."""
        return json.dumps(wiki.build_index(), ensure_ascii=False, indent=2)

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
    def wiki_knowledge_gaps() -> str:
        """Detect knowledge gaps, outdated pages, and redundancy."""
        return json.dumps(wiki.knowledge_gaps(), ensure_ascii=False, indent=2)

    @mcp.tool
    def wiki_graph_analyze() -> str:
        """Analyze knowledge graph structure (PageRank, communities, suggestions)."""
        return json.dumps(wiki.graph_analyze(), ensure_ascii=False, indent=2)
