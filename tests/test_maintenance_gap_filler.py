"""Boundary tests for GapFiller (track B): priority, extraction, mechanical fix."""

from __future__ import annotations

import asyncio

import pytest

from llmwikify.apps.agent.maintenance.config import GapFillerConfig
from llmwikify.apps.agent.maintenance.gap_filler import (
    GapFiller,
    calc_priority,
    extract_gaps,
)

# ── priority + extraction (pure functions) ───────────────────────────


def test_calc_priority_table():
    assert calc_priority({"type": "unreferenced_entity", "mention_count": 3}) == 80
    assert calc_priority({"type": "unreferenced_entity", "mention_count": 9}) == 100
    assert calc_priority({"type": "missing_cross_ref", "mention_count": 2}) == 50
    assert calc_priority({"type": "missing_cross_ref", "mention_count": 9}) == 80
    assert calc_priority({"type": "isolated_source"}) == 20
    assert calc_priority({"type": "potentially_outdated"}) == 25


def test_extract_gaps_dedup_and_sort():
    lint_result = {
        "hints": {
            "informational": [
                {"type": "missing_cross_ref", "concept": "Alpha", "mention_count": 4, "mentioning_pages": ["p1", "p2", "p3", "p4"]},
                {"type": "topic_overlap", "concept": "Noise", "mention_count": 9},  # not a gap type
            ],
        },
        "investigations": {
            "knowledge_gaps": [
                {"type": "unreferenced_entity", "concept": "Beta"},
                {"type": "unreferenced_entity", "concept": "Alpha"},  # dedup vs hints impossible: different type
                {"type": "isolated_source", "page": "lonely"},
            ],
        },
    }
    gaps = extract_gaps(lint_result)
    types = [(g.gap_type, g.concept) for g in gaps]
    # sorted by priority desc: Alpha(70) > Beta(50+) > lonely(20)
    assert types[0] == ("missing_cross_ref", "Alpha")
    assert ("unreferenced_entity", "Beta") in types
    assert ("isolated_source", "lonely") in types
    assert ("missing_cross_ref", "Noise") not in types
    # same (type, concept) never appears twice
    assert len(types) == len(set(types))


# ── mechanical fix on a real wiki ────────────────────────────────────


def test_fix_missing_cross_ref_inserts_wikilink(wiki_instance):
    wiki_instance.write_page("Concept Alpha", "Alpha is a concept.\n")
    wiki_instance.write_page("Page One", "We discuss Concept Alpha here.\n")
    wiki_instance.write_page("Page Two", "Also Concept Alpha appears here.\n")

    filler = GapFiller(
        wiki=wiki_instance,
        wiki_id="test",
        config=GapFillerConfig(auto_approve_mechanical=True),
        llm_semaphore=asyncio.Semaphore(1),
    )
    gap = type("G", (), {
        "gap_type": "missing_cross_ref",
        "concept": "Concept Alpha",
        "priority": 50,
        "data": {"mentioning_pages": ["Page One", "Page Two"]},
    })()

    fixed = asyncio.run(filler._fix_missing_cross_ref(gap))
    assert fixed == 2

    c1 = wiki_instance.read_page("Page One")["content"]
    c2 = wiki_instance.read_page("Page Two")["content"]
    assert "[[Concept Alpha]]" in c1
    assert "[[Concept Alpha]]" in c2
    # exactly one link inserted per page (conservative first-occurrence)
    assert c1.count("[[Concept Alpha]]") == 1
    # the concept's own page untouched
    assert "[[" not in wiki_instance.read_page("Concept Alpha")["content"]


def test_link_first_occurrence_skips_existing_wikilinks():
    from llmwikify.apps.agent.maintenance.gap_filler import GapFiller as GF
    content = "See [[Concept Alpha|the docs]] first. Concept Alpha later.\n"
    pattern = __import__("re").compile(r"\bConcept Alpha\b", __import__("re").IGNORECASE)
    out = GF._link_first_occurrence(content, pattern, "Concept Alpha")
    # first occurrence is INSIDE an existing wikilink → must be skipped
    assert out.startswith("See [[Concept Alpha|the docs]] first. [[Concept Alpha]] later.")


def test_fix_missing_cross_ref_respects_auto_approve_off(wiki_instance):
    wiki_instance.write_page("Solo", "Mentions Concept X.\n")
    filler = GapFiller(
        wiki=wiki_instance,
        wiki_id="test",
        config=GapFillerConfig(auto_approve_mechanical=False),
        llm_semaphore=asyncio.Semaphore(1),
    )
    gap = type("G", (), {
        "gap_type": "missing_cross_ref",
        "concept": "Concept X",
        "priority": 50,
        "data": {"mentioning_pages": ["Solo"]},
    })()
    fixed = asyncio.run(filler._fix_missing_cross_ref(gap))
    assert fixed == 0
    assert "[[" not in wiki_instance.read_page("Solo")["content"]


def test_entity_gap_creates_proposal(wiki_instance):
    filler = GapFiller(
        wiki=wiki_instance,
        wiki_id="test",
        config=GapFillerConfig(),
        llm_semaphore=asyncio.Semaphore(1),
    )
    gap = type("G", (), {
        "gap_type": "unreferenced_entity",
        "concept": "Orphan Idea",
        "priority": 60,
        "data": {"concept": "Orphan Idea"},
    })()
    created = asyncio.run(filler._propose_entity_page(gap))
    assert created == 1
    stats = filler._proposal_manager.get_stats()
    assert stats.get("pending", 0) >= 1
    # no page was actually written (proposal-only)
    assert wiki_instance.read_page("Orphan Idea").get("error")
