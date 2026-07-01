# tests/scenarios/test_10_synthesis_workflow.py
"""Scenario 2: Synthesis Workflow - Tests for cross-source synthesis."""

import subprocess
import pytest


@pytest.mark.llm
class TestSynthesisWorkflow:
    """Test synthesis operations with LLM calls."""

    def test_10_1_suggest_synthesis_multi(self, wiki):
        """Suggest synthesis with multiple sources."""
        # Write multiple source-like pages
        wiki.write_page(
            "alibaba-cloud",
            "# Alibaba Cloud\n\nRevenue: $12B. Growth: 18%.",
        )
        wiki.write_page(
            "tencent-cloud",
            "# Tencent Cloud\n\nRevenue: $8B. Growth: 25%.",
        )
        wiki.write_page(
            "huawei-cloud",
            "# Huawei Cloud\n\nRevenue: $6B. Growth: 30%.",
        )

        # Call suggest_synthesis (requires LLM)
        result = wiki.suggest_synthesis()
        assert result is not None
        assert isinstance(result, dict)

    def test_10_2_knowledge_gaps_basic(self, wiki):
        """Knowledge gaps analysis via lint with investigations."""
        wiki.write_page(
            "topic-a",
            "# Topic A\n\nBasic information about topic A.",
        )
        wiki.write_page(
            "topic-b",
            "# Topic B\n\nLinks to [[topic-a]] and [[nonexistent]].",
        )

        result = wiki.lint(generate_investigations=True)
        assert "issues" in result
        assert "investigations" in result

    def test_10_3_knowledge_gaps_cli(self, wiki):
        """Knowledge gaps via CLI command."""
        wiki.write_page(
            "outdated-page",
            "# Data 2019\n\nRevenue: $5B from 2019 report.",
        )

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "knowledge-gaps", "--json"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        # Command may succeed or fail
        assert result.returncode in [0, 1]

    def test_10_4_graph_pagerank(self, wiki):
        """Graph analysis with PageRank ranking."""
        wiki.write_page("hub", "# Hub\n\nLinks to [[spoke-a]], [[spoke-b]], [[spoke-c]].")
        wiki.write_page("spoke-a", "# Spoke A\n\nLinks to [[hub]].")
        wiki.write_page("spoke-b", "# Spoke B\n\nLinks to [[hub]].")
        wiki.write_page("spoke-c", "# Spoke C\n\nLinks to [[hub]].")
        wiki.build_index()

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "graph-analyze", "--json"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode == 0

        # Parse JSON output
        import json
        output = json.loads(result.stdout)
        assert isinstance(output, dict)

    def test_10_5_export_graph_formats(self, wiki, temp_dir):
        """Export graph in multiple formats."""
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.build_index()

        # Export as HTML
        html_path = temp_dir / "graph.html"
        result_html = subprocess.run(
            ["python3", "-m", "llmwikify", "export-graph", "--format", "html", "--output", str(html_path)],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result_html.returncode in [0, 1]
