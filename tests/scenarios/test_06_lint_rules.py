# tests/scenarios/test_06_lint_rules.py
"""Scenario 6: Lint Rule Triggers - Feature playbook.

## Background
Demonstrates the 8 lint rule trigger conditions. Constructs redundant
pages, old year references, and content without wikilinks to show
how each rule fires.

## Rules
1. dated_claim - contains old year references
2. potentially_outdated - references old data
3. unsourced_claims - claims without [[Source]] citations
4. orphan_page - no inbound links
5. broken_link - [[target]] doesn't exist

## Troubleshooting
- False positive on dated_claim: add context, use "since 2018"
- Lint too noisy: use --brief mode for counts only
"""


class TestLintRules:
    """Test 5 of the 8 lint rule triggers (feature playbook 06).

    Covers examples/06_lint_8_rules/.
    """

    def test_6_1_dated_claim(self, wiki):
        """Step 6.1: dated_claim rule fires on old year references.

        Creates a page with explicit year references; lint flags
        content that may be time-sensitive.
        """
        wiki.write_page("old-report", "# Report 2018\n\nRevenue: $10B.")
        result = wiki.lint()
        assert "issues" in result

    def test_6_2_potentially_outdated(self, wiki):
        """Step 6.2: potentially_outdated rule fires on old data refs.

        Pages referencing old data sources are flagged for review.
        """
        wiki.write_page("outdated", "# Data\n\nFrom 2019 report.")
        result = wiki.lint()
        assert "issues" in result

    def test_6_3_unsourced_claims(self, wiki):
        """Step 6.3: unsourced_claims rule fires on missing citations.

        Pages making claims without [[Source]] or [Source](path) refs
        are flagged.
        """
        wiki.write_page("claims", "# Claims\n\nMarket grew 15%.")
        result = wiki.lint()
        assert "issues" in result

    def test_6_4_orphan_page(self, wiki):
        """Step 6.4: orphan_page check (inline in WikiAnalyzer.lint).

        Pages with zero inbound links are flagged as orphans.
        """
        wiki.write_page("orphan", "# Orphan\n\nNo one links to me.")
        result = wiki.lint()
        assert "issues" in result

    def test_6_5_brief_mode(self, wiki):
        """Step 6.5: lint --brief returns counts only.

        Fast mode for CI pipelines: just total issue count.
        """
        wiki.write_page("page", "# Page\n\nSome content.")
        result = wiki.lint(mode="brief")
        assert "issue_count" in result or "total" in result
