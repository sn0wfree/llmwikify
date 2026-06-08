"""Unit tests for Phase 5: 23 base actions.

Covers:

  - All 14 base actions (#1-#14) — happy path + error path
  - All 8 detect actions (#15-#22) — base + DetectActionSkill
    subclass contract
  - The 1 clarify action (#23) — rule-based fallback
  - register_all_actions / unregister_all_actions
  - The "23 actions" contract assertion (inventory integrity)
  - The detect base class (action_name auto-derived from
    DETECT_METHOD)
  - The reason action's rule-based decision tree
  - The observe action's 4 observation categories

Target: 80+ tests, no I/O, no real LLM calls.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills import (
    SkillContext,
    SkillRegistry,
    SkillResult,
    SkillRuntime,
)
from llmwikify.apps.chat.skills.actions import (
    ALL_ACTIONS,
    ALL_DETECT_SKILLS,
    register_all_actions,
    unregister_all_actions,
    search_skill,
    extract_skill,
    read_skill,
    write_skill,
    lint_skill,
    plan_skill,
    analyze_skill,
    summarize_skill,
    score_skill,
    revise_skill,
    filter_skill,
    graph_skill,
    reason_skill,
    observe_skill,
    clarify_skill,
)
from llmwikify.apps.chat.skills.actions.detect import (
    detect_knowledge_gaps_skill,
    detect_data_gaps_skill,
    detect_outdated_pages_skill,
    detect_dated_claims_skill,
    detect_query_page_overlap_skill,
    detect_missing_cross_refs_skill,
    detect_potential_contradictions_skill,
    detect_redundancy_skill,
)
from llmwikify.apps.chat.skills.actions.reason_action import _rule_based_reason
from llmwikify.apps.chat.skills.actions.observe_action import _observe_research_state
from llmwikify.apps.chat.skills.actions.clarify_action import _clarify_fallback


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext()


@pytest.fixture
def fresh_registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def populated_registry(fresh_registry: SkillRegistry) -> SkillRegistry:
    register_all_actions(fresh_registry)
    return fresh_registry


@pytest.fixture
def runtime(populated_registry: SkillRegistry) -> SkillRuntime:
    return SkillRuntime(populated_registry)


# ─── Inventory & registration ───────────────────────────────────


class TestInventory:
    def test_exactly_23_actions(self) -> None:
        assert len(ALL_ACTIONS) == 23

    def test_all_8_detect_actions(self) -> None:
        assert len(ALL_DETECT_SKILLS) == 8

    def test_14_base_actions(self) -> None:
        base = ALL_ACTIONS[:15]  # 14 base + clarify
        assert len([s for s in base if s.name != "clarify"]) == 14

    def test_clarify_in_inventory(self) -> None:
        assert clarify_skill in ALL_ACTIONS

    def test_all_action_names_unique(self) -> None:
        names = [s.name for s in ALL_ACTIONS]
        assert len(names) == len(set(names))

    def test_each_action_has_one_action_declared(self) -> None:
        for s in ALL_ACTIONS:
            assert len(s.actions) == 1, f"{s.name} has {len(s.actions)} actions"

    def test_register_all_returns_23(self, fresh_registry: SkillRegistry) -> None:
        n = register_all_actions(fresh_registry)
        assert n == 23
        assert len(fresh_registry) == 23

    def test_unregister_all_returns_23(self, populated_registry: SkillRegistry) -> None:
        n = unregister_all_actions(populated_registry)
        assert n == 23
        assert len(populated_registry) == 0

    def test_all_skills_have_unique_qualified_actions(self, populated_registry: SkillRegistry) -> None:
        qualified = [
            f"{s.name}.{a.name}"
            for s in populated_registry
            for a in s.actions.values()
        ]
        assert len(qualified) == 23
        assert len(set(qualified)) == 23


# ─── Each action invocation (error path: no wiki) ───────────────


class TestBaseActionNoWiki:
    """All wiki-bound actions must gracefully fail when ctx.wiki is None."""

    @pytest.mark.asyncio
    async def test_search_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("search", "search", {"query": "x"}, ctx)
        assert r.status == "error"
        assert "wiki" in r.error.lower()

    @pytest.mark.asyncio
    async def test_read_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("read", "read", {"page_name": "x"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_write_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("write", "write", {"page_name": "x", "content": "y"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_lint_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("lint", "lint", {}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_analyze_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("analyze", "analyze", {"source_path": "x"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_graph_no_wiki(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("graph", "graph", {}, ctx)
        assert r.status == "error"


# ─── Standalone actions (no wiki needed) ────────────────────────


class TestStandaloneActions:
    @pytest.mark.asyncio
    async def test_clarify_minimal(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("clarify", "clarify", {"query": "What is X?"}, ctx)
        assert r.status == "ok"
        d = r.data
        assert "context" in d
        assert "boundaries" in d
        assert "premises" in d
        assert d["scope_check"] is True
        assert d["_source"] == "rule_based_fallback"

    @pytest.mark.asyncio
    async def test_clarify_missing_query(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("clarify", "clarify", {}, ctx)
        assert r.status == "error"
        assert "query" in r.error.lower()

    @pytest.mark.asyncio
    async def test_plan_minimal(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("plan", "plan", {"query": "What is X?"}, ctx)
        assert r.status == "ok"
        assert "sub_queries" in r.data
        assert "rationale" in r.data

    @pytest.mark.asyncio
    async def test_plan_missing_query(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("plan", "plan", {}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_summarize_minimal(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute(
            "summarize", "summarize",
            {"sources": [{"id": "s1", "content": "x"}]},
            ctx,
        )
        assert r.status == "ok"
        assert "claims" in r.data
        assert "narrative" in r.data

    @pytest.mark.asyncio
    async def test_summarize_empty(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("summarize", "summarize", {"sources": []}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_score_short_text(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("score", "score", {"text": "hello"}, ctx)
        assert r.status == "ok"
        d = r.data
        assert 0.0 <= d["score"] <= 1.0
        assert "length" in d["by_dimension"]
        assert "structure" in d["by_dimension"]
        assert "citations" in d["by_dimension"]

    @pytest.mark.asyncio
    async def test_score_with_citations(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        text = "## Section\n\n[[Source:abc-123]]\nSee http://example.com"
        r = await runtime.execute("score", "score", {"text": text}, ctx)
        assert r.status == "ok"
        assert r.data["by_dimension"]["citations"] >= 0.7

    @pytest.mark.asyncio
    async def test_score_empty_text(self, runtime: SkillRuntime, ctx: SkillContext) -> None:
        r = await runtime.execute("score", "score", {"text": ""}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_revise_low_score_adds_structure(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "revise", "revise",
            {"text": "raw text", "score": 0.3},
            ctx,
        )
        assert r.status == "ok"
        d = r.data
        assert "##" in d["revised"]
        assert any("structure" in c for c in d["changes"])

    @pytest.mark.asyncio
    async def test_revise_high_score_keeps_text(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "revise", "revise",
            {"text": "good text", "score": 0.9},
            ctx,
        )
        assert r.status == "ok"
        assert r.data["revised"] == "good text"
        assert r.data["changes"] == []


# ─── filter action ──────────────────────────────────────────────


class TestFilterAction:
    @pytest.mark.asyncio
    async def test_filter_dedupes_by_url(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "filter", "filter",
            {"sources": [
                {"url": "a", "score": 0.8},
                {"url": "a", "score": 0.9},  # dup
                {"url": "b", "score": 0.5},
            ]},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["filtered"]) == 2
        assert r.data["dropped"] == 1

    @pytest.mark.asyncio
    async def test_filter_drops_low_score(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "filter", "filter",
            {"sources": [
                {"url": "a", "score": 0.5},
                {"url": "b", "score": 0.1},
            ], "min_score": 0.3},
            ctx,
        )
        assert r.status == "ok"
        assert len(r.data["filtered"]) == 1
        assert r.data["filtered"][0]["url"] == "a"
        assert r.data["dropped"] == 1

    @pytest.mark.asyncio
    async def test_filter_default_min_score(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "filter", "filter",
            {"sources": [{"url": "a", "score": 0.2}]},
            ctx,
        )
        assert r.status == "ok"
        # Default min_score=0.3; 0.2 dropped
        assert r.data["dropped"] == 1

    @pytest.mark.asyncio
    async def test_filter_non_list_sources(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute("filter", "filter", {"sources": "not a list"}, ctx)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_filter_empty_list(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute("filter", "filter", {"sources": []}, ctx)
        assert r.status == "ok"
        assert r.data["filtered"] == []
        assert r.data["dropped"] == 0


# ─── reason action (rule-based decision tree) ──────────────────


class TestReasonAction:
    def test_empty_state_plans(self) -> None:
        d = _rule_based_reason({})
        assert d["action"] == "plan"

    def test_state_with_sub_queries_gathers(self) -> None:
        d = _rule_based_reason({"sub_queries": [{"q": "x"}]})
        assert d["action"] == "gather"

    def test_state_with_sources_analyzes(self) -> None:
        d = _rule_based_reason({
            "sub_queries": [{"q": "x"}],
            "sources": [{"url": "a"}],
        })
        assert d["action"] == "analyze"

    def test_state_with_analysis_synthesizes(self) -> None:
        d = _rule_based_reason({
            "sub_queries": [{"q": "x"}],
            "sources": [{"url": "a"}],
            "analysis": {"entities": []},
        })
        assert d["action"] == "synthesize"

    def test_state_with_synthesis_reports(self) -> None:
        d = _rule_based_reason({
            "sub_queries": [{"q": "x"}],
            "sources": [{"url": "a"}],
            "analysis": {"entities": []},
            "synthesis": {"claims": []},
        })
        assert d["action"] == "report"

    def test_state_with_report_low_score_revis(self) -> None:
        d = _rule_based_reason({
            "sub_queries": [{"q": "x"}],
            "sources": [{"url": "a"}],
            "analysis": {"entities": []},
            "synthesis": {"claims": []},
            "report_md": "## report",
            "score": 0.3,
        })
        assert d["action"] == "revise"

    def test_state_with_high_score_done(self) -> None:
        d = _rule_based_reason({
            "sub_queries": [{"q": "x"}],
            "sources": [{"url": "a"}],
            "analysis": {"entities": []},
            "synthesis": {"claims": []},
            "report_md": "## report",
            "score": 0.9,
        })
        assert d["action"] == "done"

    @pytest.mark.asyncio
    async def test_reason_runtime_invocation(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "reason", "reason_research",
            {"state": {"sub_queries": [{"q": "x"}]}},
            ctx,
        )
        assert r.status == "ok"
        assert r.data["action"] == "gather"


# ─── observe action (4 observation categories) ─────────────────


class TestObserveAction:
    def test_empty_state_no_observations(self) -> None:
        obs = _observe_research_state({})
        assert obs == []

    def test_source_type_counts(self) -> None:
        obs = _observe_research_state({"sources": [
            {"source_type": "web"}, {"source_type": "web"},
            {"source_type": "wiki"},
        ]})
        assert any("web=2" in o and "wiki=1" in o for o in obs)

    def test_failed_sub_queries_warning(self) -> None:
        obs = _observe_research_state({"sub_queries": [
            {"q": "a", "status": "failed"},
            {"q": "b", "status": "failed"},
            {"q": "c", "status": "done"},
        ]})
        assert any("2 sub-queries failed" in o for o in obs)

    def test_wiki_vs_web_ratio(self) -> None:
        obs = _observe_research_state({"sources": [
            {"source_type": "wiki"},
            {"source_type": "wiki"},
            {"source_type": "web"},
        ]})
        assert any("Local wiki: 2, Web: 1" in o for o in obs)

    def test_knowledge_gap_alert(self) -> None:
        obs = _observe_research_state({"synthesis": {
            "knowledge_gaps": ["g1", "g2", "g3", "g4", "g5"],
        }})
        assert any("5 knowledge gaps" in o for o in obs)

    def test_no_gap_alert_for_few_gaps(self) -> None:
        obs = _observe_research_state({"synthesis": {
            "knowledge_gaps": ["g1", "g2"],
        }})
        assert not any("knowledge gaps" in o for o in obs)

    @pytest.mark.asyncio
    async def test_observe_runtime_invocation(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "observe", "observe_research_state",
            {"state": {"sources": [{"source_type": "web"}]}},
            ctx,
        )
        assert r.status == "ok"
        assert "observations" in r.data


# ─── detect actions (8) ─────────────────────────────────────────


class TestDetectActions:
    """Test the 8 detect actions + their DetectActionSkill base."""

    @pytest.mark.parametrize("skill", ALL_DETECT_SKILLS)
    def test_each_detect_skill_has_correct_name(self, skill) -> None:
        assert skill.name.startswith("detect_")

    @pytest.mark.parametrize("skill", ALL_DETECT_SKILLS)
    def test_each_detect_skill_has_one_action(self, skill) -> None:
        assert len(skill.actions) == 1

    @pytest.mark.parametrize("skill", ALL_DETECT_SKILLS)
    def test_each_detect_action_name_no_underscore_prefix(self, skill) -> None:
        # Auto-derived name: "_detect_X" → "detect_X"
        action_name = next(iter(skill.actions.keys()))
        assert action_name.startswith("detect_")
        assert not action_name.startswith("_")

    @pytest.mark.parametrize("skill,method", [
        (detect_knowledge_gaps_skill, "_detect_knowledge_gaps"),
        (detect_data_gaps_skill, "_detect_data_gaps"),
        (detect_outdated_pages_skill, "_detect_outdated_pages"),
        (detect_dated_claims_skill, "_detect_dated_claims"),
        (detect_query_page_overlap_skill, "_detect_query_page_overlap"),
        (detect_missing_cross_refs_skill, "_detect_missing_cross_refs"),
        (detect_potential_contradictions_skill, "_detect_potential_contradictions"),
        (detect_redundancy_skill, "_detect_redundancy"),
    ])
    @pytest.mark.asyncio
    async def test_detect_action_invocation_no_wiki(
        self, runtime: SkillRuntime, ctx: SkillContext, skill, method
    ) -> None:
        action_name = method.lstrip("_")
        r = await runtime.execute(skill.name, action_name, {}, ctx)
        assert r.status == "error"
        assert "wiki" in r.error.lower()

    @pytest.mark.asyncio
    async def test_detect_knowledge_gaps_specific(
        self, runtime: SkillRuntime, ctx: SkillContext
    ) -> None:
        r = await runtime.execute(
            "detect_knowledge_gaps", "detect_knowledge_gaps", {}, ctx,
        )
        assert r.status == "error"
        assert "_detect_knowledge_gaps" in r.error or "wiki" in r.error.lower()

    @pytest.mark.asyncio
    async def test_detect_invocation_with_wiki(
        self, populated_registry: SkillRegistry
    ) -> None:
        """With a mock wiki that has a _detect_* method, the
        detect action should return a 'findings' dict."""
        rt = SkillRuntime(populated_registry)

        class MockWiki:
            def _detect_knowledge_gaps(self):
                return [{"page": "foo", "gap": "missing entity X"}]

        ctx = SkillContext(wiki=MockWiki())
        r = await rt.execute(
            "detect_knowledge_gaps", "detect_knowledge_gaps", {}, ctx,
        )
        assert r.status == "ok"
        assert r.data == {"findings": [{"page": "foo", "gap": "missing entity X"}]}

    @pytest.mark.asyncio
    async def test_detect_invocation_wiki_lacks_method(
        self, populated_registry: SkillRegistry
    ) -> None:
        """A wiki without the _detect_* method returns a clean error."""
        rt = SkillRuntime(populated_registry)

        class BareWiki:
            pass

        ctx = SkillContext(wiki=BareWiki())
        r = await rt.execute(
            "detect_knowledge_gaps", "detect_knowledge_gaps", {}, ctx,
        )
        assert r.status == "error"
        assert "_detect_knowledge_gaps" in r.error

    @pytest.mark.asyncio
    async def test_detect_invocation_method_raises(
        self, populated_registry: SkillRegistry
    ) -> None:
        """An exception in _detect_* is converted to SkillResult.fail."""
        rt = SkillRuntime(populated_registry)

        class BrokenWiki:
            def _detect_knowledge_gaps(self):
                raise RuntimeError("analyzer offline")

        ctx = SkillContext(wiki=BrokenWiki())
        r = await rt.execute(
            "detect_knowledge_gaps", "detect_knowledge_gaps", {}, ctx,
        )
        assert r.status == "error"
        assert "analyzer offline" in r.error


# ─── Manifests ───────────────────────────────────────────────────


class TestManifests:
    def test_all_manifests_have_descriptions(self) -> None:
        reg = SkillRegistry()
        register_all_actions(reg)
        for m in reg.all_manifests():
            assert m.description, f"{m.name} has no description"
            assert m.action_count == 1

    def test_manifests_sorted(self) -> None:
        reg = SkillRegistry()
        register_all_actions(reg)
        names = [m.name for m in reg.all_manifests()]
        assert names == sorted(names)


# ─── _clarify_fallback direct test ──────────────────────────────


class TestClarifyFallback:
    def test_minimal_fallback(self) -> None:
        d = _clarify_fallback("What is X?")
        assert d["context"].startswith("Research scope for:")
        assert d["scope_check"] is True
        assert isinstance(d["premises"], list)
        assert len(d["premises"]) >= 1

    def test_fallback_with_wiki_context(self) -> None:
        d = _clarify_fallback("query", "wiki context here")
        # wiki context not currently used by the fallback, but
        # the function should still return valid shape
        assert "context" in d
        assert d["scope_check"] is True
