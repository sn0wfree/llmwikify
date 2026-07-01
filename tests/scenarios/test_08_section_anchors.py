# tests/scenarios/test_08_section_anchors.py
"""Scenario 8: Section-Level Anchors - Feature playbook.

## Background
Demonstrates `[[page#section]]` and `[[page#section|display]]` wikilink
syntax, including get_inbound_links / get_outbound_links returning
section fields, include_context=True for surrounding text, and direct
DB queries on page_links table.

## Syntax
- `[[page]]` - whole page link
- `[[page#section]]` - link to specific section
- `[[page#section|display]]` - with custom display text

## Troubleshooting
- Section not in link data: ensure build_index() was run after writing
- Context empty: include_context=True was not passed
"""


class TestSectionAnchors:
    """Test section-level anchor tracking (feature playbook 08).

    Covers examples/08_section_anchor_tracking/.
    """

    def test_8_1_write_target_page(self, wiki):
        """Step 8.1: Write a target page with multiple sections.

        The target page must have named sections (## headings) for
        section-level linking to work.
        """
        wiki.write_page("python-style", """
# Python Style Guide

## Overview
Python emphasizes code readability.

## Naming
Use `snake_case` for functions.
""")

        result = wiki.read_page("python-style")
        assert "Naming" in result.get("content", "")

    def test_8_2_write_source_page(self, wiki):
        """Step 8.2: Write a source page with section-level wikilinks.

        Uses [[page#section]] syntax to link to a specific section.
        """
        wiki.write_page("notes", "# Notes\n\nFollow [[python-style#Naming]] rules.")
        result = wiki.read_page("notes")
        assert "python-style#Naming" in result.get("content", "")

    def test_8_3_inbound_links(self, wiki):
        """Step 8.3: Get inbound links with section info.

        Returns list of links pointing to this page, including which
        section is targeted.
        """
        wiki.write_page("python-style", """
# Python Style

## Naming
Use snake_case.
""")
        wiki.write_page("notes", "# Notes\n\nSee [[python-style#Naming]].")
        wiki.build_index()

        inbound = wiki.get_inbound_links("python-style")
        assert isinstance(inbound, list)

    def test_8_4_outbound_links(self, wiki):
        """Step 8.4: Get outbound links with section info.

        Returns list of links FROM this page, including target section.
        """
        wiki.write_page("python-style", """
# Python Style

## Naming
Use snake_case.
""")
        wiki.write_page("notes", "# Notes\n\nSee [[python-style#Naming]].")
        wiki.build_index()

        outbound = wiki.get_outbound_links("notes")
        assert isinstance(outbound, list)
        assert len(outbound) >= 1

    def test_8_5_include_context(self, wiki):
        """Step 8.5: Get links with surrounding context.

        include_context=True returns the sentence/paragraph around
        each link for disambiguation.
        """
        wiki.write_page("python-style", """
# Python Style

## Naming
Use snake_case.
""")
        wiki.write_page(
            "notes",
            "# Notes\n\nFor variable names, follow [[python-style#Naming]] rules.",
        )
        wiki.build_index()

        inbound = wiki.get_inbound_links("python-style", include_context=True)
        assert isinstance(inbound, list)
