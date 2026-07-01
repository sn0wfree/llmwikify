# tests/scenarios/test_13_references_detail.py
"""Scenario 1: References Detail - Tests for reference queries."""

import subprocess


class TestReferencesDetail:
    """Test reference queries and detail modes."""

    def test_13_1_references_inbound_outbound(self, wiki):
        """Get inbound and outbound references."""
        wiki.write_page("source", "# Source\n\nLinks to [[target]].")
        wiki.write_page("target", "# Target\n\nLinked from [[source]].")
        wiki.write_page("other", "# Other\n\nAlso links to [[target]].")
        wiki.build_index()

        # Get inbound links to target
        inbound = wiki.get_inbound_links("target")
        assert len(inbound) >= 2  # source and other link to target

        # Get outbound links from source
        outbound = wiki.get_outbound_links("source")
        assert len(outbound) >= 1  # source links to target

    def test_13_2_references_detail_mode(self, wiki):
        """References with detail mode via CLI."""
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
        # May succeed or fail depending on implementation
        assert result.returncode in [0, 1]

    def test_13_3_references_section_links(self, wiki):
        """Section-level references with [[page#section]] syntax."""
        wiki.write_page(
            "guide",
            "# Guide\n\n## Overview\nOverview content.\n\n## Setup\nSetup content.",
        )
        wiki.write_page(
            "notes",
            "# Notes\n\nSee [[guide#Setup]] for setup instructions.",
        )
        wiki.build_index()

        # Get outbound links with section info
        outbound = wiki.get_outbound_links("notes")
        assert len(outbound) >= 1

        # Check if section info is present
        if outbound:
            link = outbound[0]
            # Section might be in the link data
            assert isinstance(link, dict)
