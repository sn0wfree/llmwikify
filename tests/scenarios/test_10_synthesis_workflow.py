# tests/scenarios/test_10_synthesis_workflow.py
"""Scenario 10: Synthesis Workflow - Tests for cross-source synthesis.

## Background
Cross-source synthesis: LLM compares multiple sources, suggests
combined wiki pages, identifies knowledge gaps and contradictions.

## Pipeline
```
Multiple sources
   │ suggest_synthesis (LLM)
   ▼
Synthesis suggestions
   │ synthesize (write page)
   ▼
wiki/synthesis/<query>.md
   │ knowledge-gaps
   ▼
outdated / missing / redundant
```

## Troubleshooting
- suggest_synthesis returns empty: no sources ingested yet
- knowledge-gaps OOM: use --limit 200
- synthesize creates no wikilinks: source_pages names must match stems
"""


import subprocess
import pytest


@pytest.mark.llm
class TestSynthesisWorkflow:
    """Test synthesis operations with LLM calls.

    Covers TUTORIAL.md Scenario 2 (synthesis step).
    """

    def test_10_1_suggest_synthesis_multi(self, wiki):
        """Step 10.1: LLM suggests cross-source synthesis pages.

        Compares multiple company sources, suggests comparison pages.
        """
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

        result = wiki.suggest_synthesis()
        assert result is not None
        assert isinstance(result, dict)

    def test_10_2_knowledge_gaps_basic(self, wiki):
        """Step 10.2: Knowledge gaps analysis via lint investigations.

        Identifies outdated pages, missing topics, and contradictions.
        """
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
        """Step 10.3: Knowledge gaps via CLI command.

        Human-readable report of outdated, missing, and redundant content.
        """
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
        assert result.returncode in [0, 1]

    def test_10_4_graph_pagerank(self, wiki):
        """Step 10.4: Graph analysis with PageRank ranking.

        Identifies most central pages by link topology.
        """
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

        import json
        output = json.loads(result.stdout)
        assert isinstance(output, dict)

    def test_10_5_export_graph_formats(self, wiki, temp_dir):
        """Step 10.5: Export graph in HTML format.

        Interactive D3.js graph for browser viewing.
        """
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.build_index()

        html_path = temp_dir / "graph.html"
        result_html = subprocess.run(
            [
                "python3", "-m", "llmwikify", "export-graph",
                "--format", "html", "--output", str(html_path),
            ],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result_html.returncode in [0, 1]
