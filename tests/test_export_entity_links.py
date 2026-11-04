"""Regression: exported graph entity links must resolve to real pages.

Entity pages are written with the page name verbatim
(``entities/Machine Learning.md``). The export used to look for a
*slugified* name (``entities/machine-learning.md``), so the link never
resolved — for any name with a space or non-ASCII character.
"""

from __future__ import annotations

import pytest

from llmwikify.kernel.graph.export import _entity_href, _entity_page_names


class TestEntityPageNames:
    def test_verbatim_name_is_first(self):
        assert _entity_page_names("Machine Learning")[0] == "Machine Learning"

    def test_slug_is_a_fallback_candidate(self):
        candidates = _entity_page_names("Machine Learning")
        assert "machine-learning" in candidates

    def test_chinese_name_is_kept(self):
        candidates = _entity_page_names("人工智能")
        assert candidates[0] == "人工智能"

    def test_ascii_single_word_keeps_verbatim_first(self):
        candidates = _entity_page_names("Gold")
        assert candidates[0] == "Gold"
        assert len(candidates) <= 2


class TestEntityHref:
    def test_space_is_percent_encoded(self):
        assert _entity_href("Machine Learning") == (
            "../wiki/entities/Machine%20Learning.md"
        )

    def test_chinese_is_percent_encoded(self):
        href = _entity_href("人工智能")
        assert href.startswith("../wiki/entities/")
        assert href.endswith(".md")
        assert "人工智能" not in href  # encoded, not raw

    def test_plain_name_unchanged(self):
        assert _entity_href("Gold") == "../wiki/entities/Gold.md"


class TestExportResolvesEntityFiles:
    """The export must find the page that is actually on disk."""

    def _wiki_with_entity(self, tmp_path, name: str):
        from llmwikify.kernel.wiki import Wiki

        wiki = Wiki(tmp_path)
        wiki.init()
        wiki.write_page(name, f"# {name}\n", page_type="Entity")
        return wiki

    def test_space_in_name_is_found(self, tmp_path):
        """entities/Machine Learning.md must be linked."""
        wiki = self._wiki_with_entity(tmp_path, "Machine Learning")
        entity_dir = wiki.wiki_dir / "entities"
        base_name = "Machine Learning"
        candidates = _entity_page_names(base_name)
        assert (entity_dir / f"{candidates[0]}.md").exists()

    def test_chinese_name_is_found(self, tmp_path):
        wiki = self._wiki_with_entity(tmp_path, "人工智能")
        entity_dir = wiki.wiki_dir / "entities"
        candidates = _entity_page_names("人工智能")
        assert (entity_dir / f"{candidates[0]}.md").exists()

    def test_export_html_marks_nodes_with_pages(self, tmp_path):
        """export_html reports entity_pages_linked for resolvable nodes."""
        pytest.importorskip("networkx")
        pytest.importorskip("pyvis")
        from llmwikify.kernel.graph.export import export_html

        wiki = self._wiki_with_entity(tmp_path, "Machine Learning")
        # The export resolves pages relative to output_path.parent.parent
        out = wiki.root / "exports"
        out.mkdir()
        result = export_html(
            {
                "nodes": [{"id": "Machine Learning", "source_type": "wiki_page"}],
                "links": [],
            },
            None,
            out / "graph.html",
        )
        assert result["status"] == "success"
        # The node's page exists under entities/ → it must be counted.
        assert result["entity_pages_linked"] == 1
