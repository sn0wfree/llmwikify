# tests/scenarios/test_08_section_anchors.py
"""Scenario 8: Section-Level Anchors - No LLM required."""

import pytest


class TestSectionAnchors:
    """Test [[page#section]] wikilink syntax."""

    def test_8_1_write_target_page(self, wiki):
        """Write a target page with sections."""
        content = """# Python Style Guide

## Overview
Python emphasizes code readability.

## Naming
Use `snake_case` for functions.

## Imports
Group imports by type.
"""
        wiki.write_page("python-style", content)
        result = wiki.read_page("python-style")
        assert isinstance(result, dict)
        assert "Python Style Guide" in result.get("content", "")

    def test_8_2_write_source_page(self, wiki):
        """Write source page with [[target#section]] links."""
        wiki.write_page("python-style", "# Python\n\n## Naming\nUse snake_case.")
        wiki.write_page("notes", "# Notes\n\nFollow [[python-style#Naming]] rules.")

        result = wiki.read_page("notes")
        assert isinstance(result, dict)
        # Check that the link syntax is in the content
        assert "python-style#Naming" in result.get("content", "")

    def test_8_3_inbound_links(self, wiki):
        """Inbound links include section field."""
        wiki.write_page("target", "# Target\n\n## Section A\nContent.")
        wiki.write_page("source", "# Source\n\nSee [[target#Section A]].")
        wiki.build_index()

        inbound = wiki.get_inbound_links("target")
        assert len(inbound) > 0
        assert any("section" in link for link in inbound)

    def test_8_4_outbound_links(self, wiki):
        """Outbound links include section field."""
        wiki.write_page("target", "# Target\n\n## Section B\nContent.")
        wiki.write_page("source", "# Source\n\nSee [[target#Section B]].")
        wiki.build_index()

        outbound = wiki.get_outbound_links("source")
        assert len(outbound) > 0
        assert any("section" in link for link in outbound)

    def test_8_5_include_context(self, wiki):
        """include_context returns surrounding text."""
        wiki.write_page("target", "# Target\n\n## Naming\nUse snake_case.")
        wiki.write_page("source", "# Source\n\nFollow [[target#Naming]] rules.")
        wiki.build_index()

        inbound = wiki.get_inbound_links("target", include_context=True)
        assert len(inbound) > 0
        # Context should be non-empty (or at least present)
        assert any("context" in link for link in inbound)
