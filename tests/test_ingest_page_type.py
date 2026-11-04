"""Regression: ingest operations must honour the LLM's page_type.

The generate_wiki_ops prompt tells the LLM to emit a bare page name plus
a page_type ("Risk Parity" + "Concept"). execute_operations dropped
page_type, so every page landed at the wiki root instead of
concepts/ — and the enricher classifies units by directory prefix, so
it found nothing to enrich.
"""

from __future__ import annotations

from llmwikify.apps.agent.maintenance.enricher import collect_units


def _op(page_name: str, page_type: str | None = None, content: str = "# x\n") -> dict:
    op = {"action": "write_page", "page_name": page_name, "content": content}
    if page_type is not None:
        op["page_type"] = page_type
    return op


class TestExecuteOperationsPageType:
    def test_page_type_lands_page_in_type_directory(self, wiki_instance):
        """write_page must receive the operation's page_type."""
        expected = wiki_instance._resolve_page_path("Risk Parity", "Concept")
        wiki_instance.execute_operations([_op("Risk Parity", "Concept")])
        assert (wiki_instance.wiki_dir / f"{expected}.md").exists()

    def test_standard_mapping_lands_in_concepts(self, wiki_instance):
        """With the shipped Page Types table, Concept → concepts/."""
        (wiki_instance.root / "wiki.md").write_text(
            "# Wiki\n\n## Page Types\n\n"
            "| Type | Location | Purpose |\n"
            "|------|----------|---------|\n"
            "| Source | wiki/sources/{slug}.md | Source summary |\n"
            "| Concept | wiki/concepts/{name}.md | Concept page |\n",
            encoding="utf-8",
        )
        wiki_instance.execute_operations([_op("Risk Parity", "Concept")])
        assert (wiki_instance.wiki_dir / "concepts" / "Risk Parity.md").exists()

    def test_source_page_type_lands_in_sources(self, wiki_instance):
        expected = wiki_instance._resolve_page_path("Some Doc", "Source")
        wiki_instance.execute_operations([_op("Some Doc", "Source")])
        assert (wiki_instance.wiki_dir / f"{expected}.md").exists()

    def test_qualified_name_ignores_page_type(self, wiki_instance):
        """A name that already has a path keeps it."""
        wiki_instance.execute_operations([_op("concepts/Risk Parity", "Source")])
        assert (wiki_instance.wiki_dir / "concepts" / "Risk Parity.md").exists()

    def test_no_page_type_still_writes(self, wiki_instance):
        wiki_instance.execute_operations([_op("Bare Name")])
        assert (wiki_instance.wiki_dir / "Bare Name.md").exists()

    def test_result_reports_resolved_path(self, wiki_instance):
        """The result must report where the page actually landed."""
        expected = wiki_instance._resolve_page_path("Risk Parity", "Concept")
        result = wiki_instance.execute_operations([_op("Risk Parity", "Concept")])
        written = [r for r in result["results"] if r.get("action") == "write_page"]
        assert written
        assert written[0]["page"] == expected
        assert written[0]["status"] == "done"


class TestCollectUnitsWithResolvedPaths:
    def test_concept_bucket_from_resolved_path(self):
        exec_result = {
            "results": [
                {"action": "write_page", "page": "concepts/Risk Parity", "status": "done"}
            ]
        }
        concepts, sources, suggested = collect_units(exec_result, None)
        assert concepts == ["concepts/Risk Parity"]
        assert sources == []

    def test_source_bucket_from_resolved_path(self):
        exec_result = {
            "results": [
                {"action": "write_page", "page": "sources/Some Doc", "status": "done"}
            ]
        }
        concepts, sources, _ = collect_units(exec_result, None)
        assert sources == ["sources/Some Doc"]
        assert concepts == []

    def test_bare_written_name_still_counted_as_concept(self):
        """LLM omitted page_type → page at wiki root → still a unit."""
        exec_result = {
            "results": [
                {"action": "write_page", "page": "Bare Name", "status": "done"}
            ]
        }
        concepts, sources, _ = collect_units(exec_result, None)
        assert concepts == ["Bare Name"]
        assert sources == []

    def test_skipped_write_is_ignored(self):
        exec_result = {
            "results": [
                {"action": "write_page", "page": "concepts/X", "status": "skipped"}
            ]
        }
        concepts, sources, _ = collect_units(exec_result, None)
        assert concepts == []
        assert sources == []
