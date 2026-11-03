"""Boundary tests for KnowledgeEnricher (track C).

Covers unit collection from the operation list, cross-reference repair,
orphan-source repair, missing-page proposals, and the failure paths.
"""

from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.agent.maintenance.config import EnricherConfig
from llmwikify.apps.agent.maintenance.enricher import (
    KnowledgeEnricher,
    collect_units,
)


def _enricher(wiki, **overrides) -> KnowledgeEnricher:
    config = EnricherConfig(**overrides)
    return KnowledgeEnricher(
        wiki=wiki,
        wiki_id="test",
        config=config,
        llm_semaphore=asyncio.Semaphore(1),
    )


def _ops(*pages: str) -> dict:
    return {
        "results": [
            {"action": "write_page", "status": "done", "page": p} for p in pages
        ]
    }


# ── unit collection ──────────────────────────────────────────────────


def test_collect_units_splits_concepts_and_sources():
    concepts, sources, suggested = collect_units(
        _ops("concepts/Foo", "entities/Bar", "sources/Baz", "overview")
    )
    assert concepts == ["concepts/Foo", "entities/Bar"]
    assert sources == ["sources/Baz"]
    assert suggested == []


def test_collect_units_reads_cross_refs_and_suggestions():
    concepts, sources, suggested = collect_units(
        _ops("concepts/Foo"),
        {
            "cross_refs": ["concepts/Existing", "Risk Parity"],
            "suggested_pages": [{"name": "Brand New"}, {"name": "Another"}],
        },
    )
    assert concepts == ["concepts/Foo", "concepts/Existing", "Risk Parity"]
    assert suggested == ["Brand New", "Another"]


def test_collect_units_routes_source_cross_refs_to_sources():
    """A cross-reference naming a source page belongs in the source bucket."""
    concepts, sources, _ = collect_units(
        _ops("concepts/Foo"),
        {"cross_refs": ["sources/Old Paper", "Risk Parity"]},
    )
    assert concepts == ["concepts/Foo", "Risk Parity"]
    assert sources == ["sources/Old Paper"]


def test_collect_units_ignores_non_written_operations():
    concepts, sources, suggested = collect_units(
        {
            "results": [
                {"action": "write_page", "status": "skipped", "page": "concepts/X"},
                {"action": "log", "status": "done", "page": "concepts/Y"},
            ]
        }
    )
    assert concepts == []
    assert sources == []
    assert suggested == []


def test_collect_units_without_analysis_is_safe():
    concepts, sources, suggested = collect_units(_ops("concepts/Foo"), None)
    assert concepts == ["concepts/Foo"]
    assert sources == []
    assert suggested == []


# ── cross-reference repair ───────────────────────────────────────────


def test_concept_mentioned_in_plain_text_gets_linked(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")
    wiki_instance.write_page("sources/Baz", "# Baz\n\nAlso about Foo.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo"))
    )

    assert result.links_added == 2
    assert result.pages_touched == 2
    content = wiki_instance.read_page("sources/Bar")["content"]
    assert "[[concepts/Foo]]" in content


def test_already_linked_concept_is_not_relinked(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout [[concepts/Foo]] here.\n")
    wiki_instance.write_page("sources/Baz", "# Baz\n\nAlso about [[concepts/Foo]].\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo"))
    )

    assert result.links_added == 0


def test_link_is_inserted_only_once_per_page(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page(
        "sources/Bar", "# Bar\n\nAbout Foo, and again Foo later.\n"
    )

    asyncio.run(_enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo")))

    content = wiki_instance.read_page("sources/Bar")["content"]
    assert content.count("[[concepts/Foo]]") == 1


def test_mention_inside_existing_wikilink_is_not_doubled(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page(
        "sources/Bar", "# Bar\n\nSee [[Other|Foo]] then plain Foo.\n"
    )

    asyncio.run(_enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo")))

    content = wiki_instance.read_page("sources/Bar")["content"]
    assert content.count("[[") == 2  # the original link + the new one
    assert "[[concepts/Foo]]" in content


def test_max_links_per_unit_is_respected(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    for i in range(5):
        wiki_instance.write_page(f"sources/P{i}", f"# P{i}\n\nAbout Foo.\n")

    result = asyncio.run(
        _enricher(wiki_instance, max_links_per_unit=2).enrich(
            exec_result=_ops("concepts/Foo")
        )
    )

    assert result.links_added == 2


def test_max_units_per_doc_is_respected(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("concepts/Bar", "# Bar\n\nContent.\n")
    wiki_instance.write_page("sources/P", "# P\n\nAbout Foo and Bar.\n")

    result = asyncio.run(
        _enricher(wiki_instance, max_units_per_doc=1).enrich(
            exec_result=_ops("concepts/Foo", "concepts/Bar")
        )
    )

    assert result.concepts_checked == 2
    assert result.links_added == 1


# ── orphan source repair ─────────────────────────────────────────────


def test_orphan_source_gets_linked_from_mentioning_page(wiki_instance):
    wiki_instance.write_page("sources/Baz", "# Baz\n\nContent.\n")
    wiki_instance.write_page("concepts/Notes", "# Notes\n\nAbout Baz here.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(exec_result=_ops("sources/Baz"))
    )

    assert result.sources_checked == 1
    assert result.links_added == 1
    content = wiki_instance.read_page("concepts/Notes")["content"]
    assert "[[sources/Baz]]" in content


# ── missing page proposals ───────────────────────────────────────────


def test_suggested_page_without_page_becomes_proposal(wiki_instance):
    """A page the LLM suggested but that does not exist is queued."""
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")

    enricher = _enricher(wiki_instance)
    created: list[dict] = []

    class _Recorder:
        def create_proposal(self, *args, **kwargs):
            created.append({"args": args, "kwargs": kwargs})
            return {"id": "p1"}

    enricher._proposal_manager = _Recorder()

    result = asyncio.run(
        enricher.enrich(
            llm_result={"analysis": {"suggested_pages": [{"name": "Foo"}]}},
            exec_result=_ops("sources/Bar"),
        )
    )

    assert result.proposals_created == 1
    assert len(created) == 1
    assert created[0]["args"][0] == "Foo"
    assert created[0]["args"][1] == "create"


def test_suggested_page_that_exists_makes_no_proposal(wiki_instance):
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")

    enricher = _enricher(wiki_instance)
    created: list[dict] = []

    class _Recorder:
        def create_proposal(self, *args, **kwargs):
            created.append({"args": args})
            return {"id": "p1"}

    enricher._proposal_manager = _Recorder()

    result = asyncio.run(
        enricher.enrich(
            llm_result={"analysis": {"suggested_pages": [{"name": "Foo"}]}},
            exec_result=_ops("sources/Bar"),
        )
    )

    assert result.proposals_created == 0
    assert created == []


def test_suggested_page_resolved_by_title(wiki_instance):
    """The LLM may name a page by title instead of its qualified path."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")

    enricher = _enricher(wiki_instance)
    created: list[dict] = []

    class _Recorder:
        def create_proposal(self, *args, **kwargs):
            created.append({"args": args})
            return {"id": "p1"}

    enricher._proposal_manager = _Recorder()

    result = asyncio.run(
        enricher.enrich(
            llm_result={"analysis": {"suggested_pages": [{"name": "Foo"}]}},
        )
    )

    assert result.proposals_created == 0
    assert created == []


def test_propose_missing_pages_disabled(wiki_instance):
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Foo here.\n")

    enricher = _enricher(wiki_instance, propose_missing_pages=False)
    created: list[dict] = []

    class _Recorder:
        def create_proposal(self, *args, **kwargs):
            created.append({"args": args})
            return {"id": "p1"}

    enricher._proposal_manager = _Recorder()

    result = asyncio.run(
        enricher.enrich(
            llm_result={"analysis": {"suggested_pages": [{"name": "Foo"}]}},
        )
    )

    assert result.proposals_created == 0
    assert created == []


# ── failure paths ────────────────────────────────────────────────────


def test_cross_ref_page_gets_linked_into_mentioning_pages(wiki_instance):
    """A cross_ref the LLM named is linked from pages that mention it.

    This is the case the concept was never written by this ingest — it
    already existed, and the new document is what ties it to the rest.
    """
    wiki_instance.write_page("concepts/Risk Parity", "# Risk Parity\n\nContent.\n")
    wiki_instance.write_page("sources/Portfolio A", "# A\n\nSee Risk Parity here.\n")
    wiki_instance.write_page("sources/Portfolio B", "# B\n\nAlso see Risk Parity.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(
            llm_result={
                "analysis": {"cross_refs": ["concepts/Risk Parity"]},
            },
        )
    )

    assert result.links_added == 2
    content = wiki_instance.read_page("sources/Portfolio A")["content"]
    assert "[[concepts/Risk Parity]]" in content


def test_cross_ref_named_by_title_resolves_to_page(wiki_instance):
    """A bare title in cross_refs resolves to the real page path."""
    wiki_instance.write_page("concepts/Risk Parity", "# Risk Parity\n\nContent.\n")
    wiki_instance.write_page("sources/Portfolio A", "# A\n\nSee Risk Parity here.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(
            llm_result={"analysis": {"cross_refs": ["Risk Parity"]}},
        )
    )

    assert result.links_added == 1
    content = wiki_instance.read_page("sources/Portfolio A")["content"]
    assert "[[concepts/Risk Parity]]" in content


def test_unresolvable_cross_ref_writes_no_link(wiki_instance):
    """A name with no page must not become a link to a missing page."""
    wiki_instance.write_page("sources/Bar", "# Bar\n\nAbout Ghost Concept here.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(
            llm_result={"analysis": {"cross_refs": ["Ghost Concept"]}},
        )
    )

    assert result.links_added == 0
    assert result.skipped_units == 1
    content = wiki_instance.read_page("sources/Bar")["content"]
    assert "[[" not in content


def test_page_already_linking_target_is_skipped(wiki_instance):
    """A page that links the target must not get a second link."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page(
        "sources/Bar", "# Bar\n\nSee [[concepts/Foo]] first. Foo is also plain here.\n"
    )

    result = asyncio.run(
        _enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo"))
    )

    assert result.links_added == 0
    content = wiki_instance.read_page("sources/Bar")["content"]
    assert content.count("[[concepts/Foo]]") == 1


def test_bare_title_link_counts_as_linked(wiki_instance):
    """``[[Foo]]`` names the same page as ``concepts/Foo``."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nSee [[Foo]] first. Foo here.\n")

    result = asyncio.run(
        _enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo"))
    )

    assert result.links_added == 0


def test_title_inside_a_path_is_not_split(wiki_instance):
    """``concepts/Foo`` must not become ``concepts/[[concepts/Foo]]``."""
    wiki_instance.write_page("concepts/Foo", "# Foo\n\nContent.\n")
    wiki_instance.write_page("sources/Bar", "# Bar\n\nSee the concepts/Foo page.\n")

    asyncio.run(_enricher(wiki_instance).enrich(exec_result=_ops("concepts/Foo")))

    content = wiki_instance.read_page("sources/Bar")["content"]
    assert "concepts/[[concepts/Foo]]" not in content


def test_duplicate_suggestion_queues_one_proposal(wiki_instance):
    """The same suggestion must not queue two identical proposals."""
    enricher = _enricher(wiki_instance)
    created: list[dict] = []

    class _Recorder:
        def create_proposal(self, *args, **kwargs):
            created.append({"args": args})
            return {"id": "p1"}

    enricher._proposal_manager = _Recorder()

    analysis = {"suggested_pages": [{"name": "Brand New"}, {"name": "Brand New"}]}
    asyncio.run(enricher.enrich(llm_result={"analysis": analysis}))

    assert len(created) == 1


def test_disabled_enricher_skips(wiki_instance):
    result = asyncio.run(
        _enricher(wiki_instance, enabled=False).enrich(exec_result=_ops("concepts/Foo"))
    )
    assert result.skipped is True
    assert result.links_added == 0


def test_search_failure_is_isolated(wiki_instance):
    """A failing search must not abort the whole pass."""

    class _BrokenWiki:
        def search(self, *args, **kwargs):
            raise RuntimeError("index down")

        def read_page(self, *args, **kwargs):
            return {"content": ""}

        def write_page(self, *args, **kwargs):
            raise AssertionError("should not write")

    enricher = KnowledgeEnricher(
        wiki=_BrokenWiki(),
        wiki_id="test",
        config=EnricherConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )

    result = asyncio.run(enricher.enrich(exec_result=_ops("concepts/Foo")))

    assert result.errors == 0
    assert result.links_added == 0


def test_status_reports_last_run(wiki_instance):
    enricher = _enricher(wiki_instance)
    asyncio.run(enricher.enrich(exec_result=_ops()))
    status = enricher.status()
    assert status["wiki_id"] == "test"
    assert status["last_run"]["concepts_checked"] == 0


@pytest.mark.parametrize("pages", [(), ("concepts/Foo",)])
def test_empty_operation_list_is_safe(wiki_instance, pages):
    result = asyncio.run(_enricher(wiki_instance).enrich(exec_result=_ops(*pages)))
    assert result.errors == 0
