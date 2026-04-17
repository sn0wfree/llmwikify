"""Tests for wikilink resolution and auto-fix (v0.26.0)."""

import tempfile
from pathlib import Path

from llmwikify.core.index import WikiIndex
from llmwikify.core.wiki import Wiki


class TestResolveByName:
    """Test WikiIndex.resolve_by_name method."""

    def test_resolve_by_exact_match(self, temp_wiki):
        """Exact match returns file_path."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("concepts/Factor Investing", "# Factor Investing\n\nContent",
                          "concepts/Factor Investing.md")

        result = index.resolve_by_name("concepts/Factor Investing")
        assert result == "concepts/Factor Investing.md"
        index.close()

    def test_resolve_by_no_match(self, temp_wiki):
        """Non-existent page returns None. Bare names do NOT match prefixed pages."""
        db_path = temp_wiki / ".llm-wiki-kit.db"
        index = WikiIndex(db_path)
        index.initialize()

        index.upsert_page("concepts/Gold", "# Gold\n\nContent", "concepts/Gold.md")

        # Exact mismatch
        result = index.resolve_by_name("concepts/Silver")
        assert result is None

        # Bare name does NOT match — no fallback
        result = index.resolve_by_name("Gold")
        assert result is None
        index.close()


class TestWikilinkResolution:
    """Test _resolve_wikilink_target with new two-layer strategy."""

    def test_resolve_direct_path(self, temp_wiki):
        """Direct path resolution works."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        page = wiki.wiki_dir / "concepts" / "Factor Investing.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Factor Investing")

        result = wiki._resolve_wikilink_target("concepts/Factor Investing")
        assert result == page
        wiki.close()

    def test_resolve_via_index(self, temp_wiki):
        """Index lookup resolves wikilink with directory prefix."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        page = wiki.wiki_dir / "concepts" / "Risk Parity.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("# Risk Parity\n\nContent about [[concepts/Portfolio Construction]].")

        wiki.index.upsert_page("concepts/Risk Parity", page.read_text(),
                               "concepts/Risk Parity.md")
        wiki.index.upsert_page("concepts/Portfolio Construction", "# Portfolio Construction",
                               "concepts/Portfolio Construction.md")

        result = wiki._resolve_wikilink_target("concepts/Portfolio Construction")
        assert result == wiki.wiki_dir / "concepts" / "Portfolio Construction.md"
        wiki.close()

    def test_resolve_returns_none_for_missing(self, temp_wiki):
        """Missing link returns None."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        result = wiki._resolve_wikilink_target("concepts/NonExistent")
        assert result is None
        wiki.close()


class TestFixWikilinks:
    """Test fix_wikilinks auto-repair method."""

    def _setup_wiki_with_broken_links(self, temp_wiki):
        """Create a wiki with broken wikilinks that have matching pages."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        # Create concept pages (but DON'T index them yet)
        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity")
        (concepts / "Factor Investing.md").write_text("# Factor Investing")

        # Create a page with broken links (no directory prefix)
        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text(
            "# Overview\n\n"
            "Related to [[Risk Parity]] and [[Factor Investing]].\n"
            "Also see [[NonExistent]] which is truly missing.\n"
        )

        # Initialize the index tables by touching a page
        wiki.index.upsert_page("overview", broken_page.read_text(), "overview.md")

        return wiki

    def test_fix_wikilinks_dry_run(self, temp_wiki):
        """Dry run reports changes without modifying files."""
        wiki = self._setup_wiki_with_broken_links(temp_wiki)

        result = wiki.fix_wikilinks(dry_run=True)

        assert result["fixed"] == 2
        assert result["skipped"] == 1  # NonExistent
        assert result["ambiguous"] == 0

        # Verify file not modified
        content = (wiki.wiki_dir / "overview.md").read_text()
        assert "[[Risk Parity]]" in content
        assert "[[Factor Investing]]" in content
        wiki.close()

    def test_fix_wikilinks_actual_fix(self, temp_wiki):
        """Actual fix modifies files and adds directory prefix."""
        wiki = self._setup_wiki_with_broken_links(temp_wiki)

        result = wiki.fix_wikilinks(dry_run=False)

        assert result["fixed"] == 2

        content = (wiki.wiki_dir / "overview.md").read_text()
        assert "[[concepts/Risk Parity]]" in content
        assert "[[concepts/Factor Investing]]" in content
        assert "[[NonExistent]]" in content  # Unchanged
        wiki.close()

    def test_fix_wikilinks_preserves_section_links(self, temp_wiki):
        """Section links are preserved during fix."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity\n\n## Types")

        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text("# Overview\n\nSee [[Risk Parity#Types]].")

        # Only index the overview, NOT the concept page
        wiki.index.upsert_page("overview", broken_page.read_text(), "overview.md")

        result = wiki.fix_wikilinks(dry_run=False)

        assert result["fixed"] == 1
        content = broken_page.read_text()
        assert "[[concepts/Risk Parity#Types]]" in content
        wiki.close()

    def test_fix_wikilinks_preserves_alias(self, temp_wiki):
        """Alias links are preserved during fix."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity")

        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text("# Overview\n\nSee [[Risk Parity|RP]].")

        # Only index the overview, NOT the concept page
        wiki.index.upsert_page("overview", broken_page.read_text(), "overview.md")

        result = wiki.fix_wikilinks(dry_run=False)

        assert result["fixed"] == 1
        content = broken_page.read_text()
        assert "[[concepts/Risk Parity|RP]]" in content
        wiki.close()

    def test_fix_wikilinks_ambiguous(self, temp_wiki):
        """Ambiguous matches (multiple pages with same basename) are reported."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        # Create two pages with same basename in different directories
        concepts = wiki.wiki_dir / "concepts"
        entities = wiki.wiki_dir / "entities"
        concepts.mkdir(parents=True, exist_ok=True)
        entities.mkdir(parents=True, exist_ok=True)
        (concepts / "Gold.md").write_text("# Gold")
        (entities / "Gold.md").write_text("# Gold")

        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text("# Overview\n\n[[Gold]]")

        # Only index the overview
        wiki.index.upsert_page("overview", broken_page.read_text(), "overview.md")

        result = wiki.fix_wikilinks(dry_run=False)

        assert result["ambiguous"] == 1
        assert result["fixed"] == 0
        assert result["changes"][0]["status"] == "ambiguous"
        wiki.close()


class TestLintModeFix:
    """Test lint with mode=fix."""

    def test_lint_mode_fix_triggers_autofix(self, temp_wiki):
        """mode=fix runs fix_wikilinks and reports results."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity")

        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text("# Overview\n\n[[Risk Parity]]")

        # Only index the overview
        wiki.index.upsert_page("overview", broken_page.read_text(), "overview.md")

        result = wiki.lint(mode="fix")

        assert "auto_fix" in result
        assert result["auto_fix"]["fixed"] == 1

        # Verify file was modified
        content = broken_page.read_text()
        assert "[[concepts/Risk Parity]]" in content
        wiki.close()


class TestFixWikilinksReindex:
    """Test that fix_wikilinks correctly updates page_links after re-indexing."""

    def test_fix_updates_page_links_target_format(self, temp_wiki):
        """After fix + re-index, page_links.target_page uses full path format."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)

        # Source page with OLD format wikilink (no directory prefix)
        source = concepts / "Factor Investing.md"
        source.write_text(
            "# Factor Investing\n\nRelated to [[Risk Parity]]."
        )
        (concepts / "Risk Parity.md").write_text("# Risk Parity")

        # Build index — page_links.target_page will store bare name "Risk Parity"
        wiki.index.build_index_from_files(wiki.wiki_dir)

        # Verify old format in page_links
        cursor = wiki.index.conn.execute(
            "SELECT target_page FROM page_links WHERE source_page LIKE '%Factor%'"
        )
        row = cursor.fetchone()
        assert row["target_page"] == "Risk Parity"

        # Inbound links with full path won't match old format
        inbound_before = wiki.index.get_inbound_links("concepts/Risk Parity")
        assert len(inbound_before) == 0

        # Run fix_wikilinks
        result = wiki.fix_wikilinks(dry_run=False)

        assert result["fixed"] == 1

        # Verify file was updated
        content = source.read_text()
        assert "[[concepts/Risk Parity]]" in content

        # Verify page_links.target_page was updated via re-index
        cursor = wiki.index.conn.execute(
            "SELECT target_page FROM page_links WHERE source_page LIKE '%Factor%'"
        )
        row = cursor.fetchone()
        assert row["target_page"] == "concepts/Risk Parity"

        # Now inbound links with full path should match
        inbound_after = wiki.index.get_inbound_links("concepts/Risk Parity")
        assert len(inbound_after) == 1
        assert inbound_after[0]["source"] == "concepts/Factor Investing"

        wiki.close()

    def test_fix_multiple_links_in_same_page(self, temp_wiki):
        """Fixing a page with multiple broken links updates all targets."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity")
        (concepts / "Factor Investing.md").write_text("# Factor Investing")

        broken_page = wiki.wiki_dir / "overview.md"
        broken_page.write_text(
            "# Overview\n\n"
            "See [[Risk Parity]] and [[Factor Investing]].\n"
            "Also [[Risk Parity]] again."
        )

        wiki.index.build_index_from_files(wiki.wiki_dir)

        # Before fix: all targets are bare names
        cursor = wiki.index.conn.execute(
            "SELECT target_page FROM page_links WHERE source_page = 'overview'"
        )
        targets = [row["target_page"] for row in cursor.fetchall()]
        assert "Risk Parity" in targets
        assert "Factor Investing" in targets

        # Run fix
        result = wiki.fix_wikilinks(dry_run=False)
        assert result["fixed"] == 3

        # After fix: all targets are full paths
        cursor = wiki.index.conn.execute(
            "SELECT target_page FROM page_links WHERE source_page = 'overview'"
        )
        targets = sorted([row["target_page"] for row in cursor.fetchall()])
        assert targets == [
            "concepts/Factor Investing",
            "concepts/Risk Parity",
            "concepts/Risk Parity",
        ]

        # Inbound links should now work for both pages
        rp_inbound = wiki.index.get_inbound_links("concepts/Risk Parity")
        assert len(rp_inbound) == 2

        fi_inbound = wiki.index.get_inbound_links("concepts/Factor Investing")
        assert len(fi_inbound) == 1

        wiki.close()


class TestIndexPageNameConsistency:
    """Test that page_name in index is full relative path."""

    def test_build_index_uses_full_path(self, temp_wiki):
        """build_index_from_files stores full relative path as page_name."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Factor Investing.md").write_text("# Factor Investing\n\nContent")

        wiki.index.build_index_from_files(wiki.wiki_dir)

        # Verify page_name is full path
        cursor = wiki.index.conn.execute(
            "SELECT page_name FROM pages WHERE page_name LIKE '%Factor%'"
        )
        row = cursor.fetchone()
        assert row['page_name'] == "concepts/Factor Investing"
        wiki.close()

    def test_write_page_uses_full_path(self, temp_wiki):
        """write_page stores full relative path as page_name."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        wiki.write_page("Risk Parity", "# Risk Parity", page_type="Concept")

        cursor = wiki.index.conn.execute(
            "SELECT page_name FROM pages WHERE page_name LIKE '%Risk%'"
        )
        row = cursor.fetchone()
        assert row['page_name'] == "concepts/Risk Parity"
        wiki.close()


class TestMissingCrossRefDetection:
    """Test that _detect_missing_cross_refs does not produce false positives
    from wikilink substring matches."""

    def test_no_false_positive_from_wikilink_substring(self, temp_wiki):
        """[[concepts/Volatility Surface]] should NOT trigger missing ref for
        concepts/Volatility."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Volatility.md").write_text("# Volatility\n\nContent.")
        (concepts / "Volatility Surface.md").write_text(
            "# Volatility Surface\n\nRelated: [[concepts/Volatility]]."
        )
        # Trend Following mentions Volatility Surface via wikilink only
        (concepts / "Trend Following.md").write_text(
            "# Trend Following\n\nUses [[concepts/Volatility Surface]]."
        )

        hints = wiki._detect_missing_cross_refs()

        # concepts/Volatility should NOT be reported as missing
        missing_concepts = [
            h["concept"]
            for h in hints
            if h["type"] == "missing_cross_ref"
        ]
        assert "concepts/Volatility" not in missing_concepts
        wiki.close()

    def test_detects_actual_plain_text_mention(self, temp_wiki):
        """Plain text mention of page name (not in wikilink) IS reported."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Risk Parity.md").write_text("# Risk Parity\n\nContent.")
        # Two pages mention "concepts/Risk Parity" in plain text without linking
        (concepts / "Portfolio A.md").write_text(
            "# Portfolio A\n\nSee concepts/Risk Parity for details."
        )
        (concepts / "Portfolio B.md").write_text(
            "# Portfolio B\n\nAlso check concepts/Risk Parity."
        )

        hints = wiki._detect_missing_cross_refs()

        missing_concepts = [
            h["concept"]
            for h in hints
            if h["type"] == "missing_cross_ref"
        ]
        assert "concepts/Risk Parity" in missing_concepts
        wiki.close()

    def test_linked_page_not_reported(self, temp_wiki):
        """A page that already links to the candidate is not reported."""
        wiki = Wiki(temp_wiki)
        wiki.init(overwrite=True)

        concepts = wiki.wiki_dir / "concepts"
        concepts.mkdir(parents=True, exist_ok=True)
        (concepts / "Gold.md").write_text("# Gold\n\nContent.")
        (concepts / "Silver.md").write_text(
            "# Silver\n\nSee [[concepts/Gold]] for details."
        )
        (concepts / "Copper.md").write_text(
            "# Copper\n\nAlso see [[concepts/Gold]]."
        )

        hints = wiki._detect_missing_cross_refs()

        missing_concepts = [
            h["concept"]
            for h in hints
            if h["type"] == "missing_cross_ref"
        ]
        assert "concepts/Gold" not in missing_concepts
        wiki.close()
