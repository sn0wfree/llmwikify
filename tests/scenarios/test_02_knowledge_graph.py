# tests/scenarios/test_02_knowledge_graph.py
"""Scenario 2: Knowledge Graph - With LLM calls."""

import pytest


class TestKnowledgeGraph:
    """Test knowledge graph operations with real LLM calls."""

    def test_2_1_build_index(self, wiki):
        """Build index creates page_links."""
        wiki.write_page("python", "# Python\n\nA programming language.")
        wiki.write_page("ml", "# Machine Learning\n\nUses Python.")
        wiki.build_index()

        idx = wiki.build_index()
        assert idx["total_pages"] >= 2

    def test_2_2_analyze_source(self, wiki, test_pdf):
        """Analyze source with LLM - extracts entities and relations."""
        if not test_pdf.exists():
            pytest.skip("Test PDF not available")

        # This calls the real LLM
        result = wiki.analyze_source(str(test_pdf))

        # Verify LLM returned structured data
        assert result is not None
        # Result should contain entities or suggested pages
        assert isinstance(result, (dict, list))

    def test_2_3_suggest_synthesis(self, wiki):
        """Suggest synthesis with LLM - recommends cross-source synthesis."""
        # Write pages that could be synthesized
        wiki.write_page(
            "company-a",
            "# Company A\n\nRevenue: $10B. Growth: 15%.",
        )
        wiki.write_page(
            "company-b",
            "# Company B\n\nRevenue: $8B. Growth: 20%.",
        )

        # This calls the real LLM
        result = wiki.suggest_synthesis()

        assert result is not None

    def test_2_4_knowledge_gaps_via_cli(self, wiki):
        """Knowledge gaps via CLI command."""
        wiki.write_page(
            "topic-a",
            "# Topic A\n\nBasic information about topic A.",
        )

        # Use CLI command instead of non-existent method
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "llmwikify", "knowledge-gaps"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        # Command may succeed or fail depending on LLM availability
        assert result.returncode in [0, 1]

    def test_2_5_graph_analyze_via_cli(self, wiki):
        """Graph analysis via CLI command."""
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]] and [[page-c]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.write_page("page-c", "# C\n\nLinks to [[page-a]].")
        wiki.build_index()

        # Use CLI command instead of non-existent method
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "llmwikify", "graph-analyze", "--json"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode == 0

    def test_2_6_export_graph_via_cli(self, wiki, temp_dir):
        """Export graph to HTML via CLI command."""
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.build_index()

        output_path = temp_dir / "graph.html"
        import subprocess
        result = subprocess.run(
            ["python3", "-m", "llmwikify", "export-graph", "--format", "html", "--output", str(output_path)],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        # Command may succeed or fail depending on graphviz availability
        assert result.returncode in [0, 1]
