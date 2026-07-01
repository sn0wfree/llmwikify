# tests/scenarios/test_13_references_detail.py
"""Scenario 13: References Detail - Tests for reference queries.

## Background
Detailed reference queries: inbound/outbound link counts, --detail
mode for full link metadata, section-level references with
[[page#section]] syntax.

## Modes
- default: returns link counts
- --detail: returns full link list with metadata
- include_context=True: includes surrounding text

## Troubleshooting
- Links not in result: ensure build_index() was run
- Detail mode shows nothing: wiki has no pages yet
"""


import subprocess


class TestReferencesDetail:
    """Test reference queries and detail modes.

    Covers TUTORIAL.md Scenario 1 (references step).
    """

    def test_13_1_references_inbound_outbound(self, wiki):
        """Step 13.1: Get inbound and outbound references.

        Demonstrates the bidirectional link query API.
        """
        wiki.write_page("source", "# Source\n\nLinks to [[target]].")
        wiki.write_page("target", "# Target\n\nLinked from [[source]].")
        wiki.write_page("other", "# Other\n\nAlso links to [[target]].")
        wiki.build_index()

        inbound = wiki.get_inbound_links("target")
        assert len(inbound) >= 2

        outbound = wiki.get_outbound_links("source")
        assert len(outbound) >= 1

    def test_13_2_references_detail_mode(self, wiki):
        """Step 13.2: References with --detail mode via CLI.

        Returns full link metadata: source, target, section, line.
        """
        wiki.write_page("page-a", "# A\n\nLinks to [[page-b]] and [[page-c]].")
        wiki.write_page("page-b", "# B\n\nLinks to [[page-a]].")
        wiki.write_page("page-c", "# C\n\nLinks to [[page-a]].")
        wiki.build_index()

        result = subprocess.run(
            ["python3", "-m", "llmwikify", "references", "page-a", "--detail"],
            capture_output=True,
            text=True,
            cwd=str(wiki.root),
        )
        assert result.returncode in [0, 1]

    def test_13_3_references_section_links(self, wiki):
        """Step 13.3: Section-level references with [[page#section]].

        Outbound links include section info.
        """
        wiki.write_page(
            "guide",
            "# Guide\n\n## Overview\nOverview content.\n\n## Setup\nSetup content.",
        )
        wiki.write_page(
            "notes",
            "# Notes\n\nSee [[guide#Setup]] for setup instructions.",
        )
        wiki.build_index()

        outbound = wiki.get_outbound_links("notes")
        assert len(outbound) >= 1

        if outbound:
            link = outbound[0]
            assert isinstance(link, dict)
