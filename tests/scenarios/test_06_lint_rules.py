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


def _rule_types(result: dict) -> set[str]:
    """Collect every rule ``type`` surfaced anywhere in a lint result."""
    types: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            if "type" in obj and isinstance(obj["type"], str):
                types.add(obj["type"])
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(result)
    return types


class TestLintRules:
    """Test 5 of the 8 lint rule triggers (feature playbook 06).

    Covers examples/06_lint_8_rules/. Each test asserts the *specific*
    rule type fires — not just ``"issues" in result`` (a key that is
    always present and made these tests vacuous).
    """

    def test_6_1_dated_claim(self, wiki):
        """Step 6.1: dated_claim rule fires on old year references.

        DatedClaimsRule needs a raw source with a recent year so
        ``latest_source_year`` is set; the page year must lag by
        YEAR_GAP_THRESHOLD (3+).
        """
        from datetime import datetime, timezone

        current = datetime.now(timezone.utc).year
        # Raw source anchors "latest" at current year
        raw_dir = wiki.raw_dir
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / "recent.txt").write_text(
            f"Report published in {current}.", encoding="utf-8"
        )
        # Page claims an old year — gap >= 3 triggers dated_claim
        wiki.write_page(
            "old-report", f"# Report {current - 5}\n\nRevenue: $10B."
        )
        result = wiki.lint(force=True)
        assert "issues" in result
        types = _rule_types(result)
        assert "dated_claim" in types, (
            f"dated_claim did not fire; types seen: {sorted(types)}"
        )

    def test_6_2_potentially_outdated(self, wiki):
        """Step 6.2: potentially_outdated rule fires on old data refs.

        Pages referencing old data sources are flagged for review.
        """
        from datetime import datetime, timezone

        old_year = datetime.now(timezone.utc).year - 5
        wiki.write_page(
            "outdated",
            f"# Data\n\nFigures from (raw/old-report.pdf) cite {old_year}.",
        )
        result = wiki.lint(force=True)
        assert "issues" in result
        types = _rule_types(result)
        assert "potentially_outdated" in types, (
            f"potentially_outdated did not fire; types seen: {sorted(types)}"
        )

    def test_6_3_unsourced_claims(self, wiki):
        """Step 6.3: unsourced_claims rule fires on missing citations.

        Pages making claims without [[Source]] or [Source](path) refs
        are flagged.
        """
        wiki.write_page(
            "claims",
            "# Claims\n\n"
            "Market grew fifteen percent across the entire region.\n"
            "Revenue hit ten billion dollars in the last quarter.\n"
            "Analysts forecast continued consolidation next year.\n",
        )
        result = wiki.lint(force=True)
        assert "issues" in result
        types = _rule_types(result)
        assert "unsourced_claims" in types, (
            f"unsourced_claims did not fire; types seen: {sorted(types)}"
        )

    def test_6_4_orphan_page(self, wiki):
        """Step 6.4: orphan_page check (inline in WikiAnalyzer.lint).

        Pages with zero inbound links are flagged as orphans.
        """
        wiki.write_page("orphan", "# Orphan\n\nNo one links to me.")
        result = wiki.lint(force=True)
        assert "issues" in result
        types = _rule_types(result)
        assert "orphan_page" in types, (
            f"orphan_page did not fire; types seen: {sorted(types)}"
        )

    def test_6_5_brief_mode(self, wiki):
        """Step 6.5: lint --brief returns counts only.

        Fast mode for CI pipelines: just total issue count.
        """
        wiki.write_page("page", "# Page\n\nSome content.")
        result = wiki.lint(mode="brief", force=True)
        assert "issue_count" in result
        assert isinstance(result["issue_count"], int)
