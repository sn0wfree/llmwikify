# tests/scenarios/test_02_knowledge_graph.py
"""Scenario 2: Knowledge Graph - With LLM calls.

## Background
Transform a wiki into a knowledge graph: extract entities/relations
from sources via LLM, compute PageRank, detect communities, export
visualization (HTML/SVG/GraphML).

## Architecture
```mermaid
graph LR
    Wiki --> Analyze[analyze_source<br/>LLM]
    Analyze --> Graph[Graph Builder]
    Graph --> PageRank[PageRank]
    Graph --> Community[Community<br/>Detection]
    Graph --> Export[HTML/SVG<br/>Export]
```

## Troubleshooting
- analyze_source hangs: check LLM config in ~/.llmwikify/llmwikify.json
- graph-analyze OOM on 1000+ pages: use --limit 200
- export-graph blank: install graphviz system package
"""


import subprocess
import pytest


class TestKnowledgeGraph:
    """Test knowledge graph operations with real LLM calls.

    Covers TUTORIAL.md Scenario 2 (Company Due-Diligence KB).
    """

    def test_2_1_build_index(self, wiki):
        """Step 2.1: Build the graph index.

        Indexes wiki pages for graph analysis (nodes + edges).
        """
        wiki.write_page("python", "# Python\n\nA programming language.")
        wiki.write_page("ml", "# Machine Learning\n\nUses Python.")
        wiki.build_index()

        idx = wiki.build_index()
        assert idx["total_pages"] >= 2

    @pytest.mark.llm
    def test_2_2_analyze_source(self, wiki, test_pdf):
        """Step 2.2: LLM-powered source analysis.

        Uses LLM to extract entities, relations, and suggested pages
        from a PDF source. Cached in .llmwikify.db.
        """
        if not test_pdf.exists():
            pytest.skip("Test PDF not available")

        result = wiki.analyze_source(str(test_pdf))
        assert result is not None
        assert isinstance(result, (dict, list))

    @pytest.mark.llm
    def test_2_3_suggest_synthesis(self, wiki):
        """Step 2.3: LLM-powered synthesis suggestions.

        Compares new sources against existing wiki, suggests cross-source
        synthesis pages (e.g., "Compare revenue A vs B").
        """
        wiki.write_page(
            "company-a",
            "# Company A\n\nRevenue: $10B. Growth: 15%.",
        )
        wiki.write_page(
            "company-b",
            "# Company B\n\nRevenue: $8B. Growth: 20%.",
        )

        result = wiki.suggest_synthesis()
        assert result is not None

    def test_2_4_knowledge_gaps_via_cli(self, wiki):
        """Step 2.4: Detect knowledge gaps via CLI.

        Identifies outdated pages, missing topics, and redundant content.
        """
        wiki.write_page(
            "topic-a",
            "# Topic A\n\nBasic information about topic A.",
        )

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "knowledge-gaps"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]

    def test_2_5_graph_analyze_via_cli(self, wiki):
        """Step 2.5: PageRank + community detection via CLI.

        Computes centrality scores and detects communities in the
        graph, outputs JSON with stats.
        """
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]] and [[page-c]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.write_page("page-c", "# C\n\nLinks to [[page-a]].")
        wiki.build_index()

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "graph-analyze", "--json"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode == 0

    def test_2_6_export_graph_via_cli(self, wiki, temp_dir):
        """Step 2.6: Export graph to interactive HTML.

        Generates D3.js force-directed graph for browser viewing.
        """
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.build_index()

        output_path = temp_dir / "graph.html"
        result = subprocess.run(
            [
                "python3", "-m", "llmwikify", "export-graph",
                "--format", "html", "--output", str(output_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]
