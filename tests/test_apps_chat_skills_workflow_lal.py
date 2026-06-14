"""Tests for LAL PR 3: workflow DSL strict validation + alias rejection.

Covers:
  - autoresearch-compound.yaml loads without legacy model aliases
  - llmwikify-research.yaml loads without legacy model aliases
  - validate_workflow rejects sonnet/opus/haiku aliases by default
  - LLM_ALLOW_ALIAS_MODEL gradient switch permits aliases
  - empty / missing model still means "inherit" (always allowed)
  - _check_actor_models is called from validate_workflow
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.skills.workflows.dag import (
    _LEGACY_MODEL_ALIASES,
    ActorSpec,
    BudgetSpec,
    InputsSpec,
    LimitsSpec,
    PhaseSpec,
    WorkflowSpec,
    WorkflowValidationError,
    _alias_model_allowed,
    _check_actor_models,
    load_workflow,
    validate_workflow,
)

BUILTINS = Path(__file__).resolve().parent.parent / "src/llmwikify/apps/chat/skills/workflows/builtins"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("LLM_ALLOW_ALIAS_MODEL", raising=False)
    yield


def _wrap(actors: dict[str, ActorSpec]) -> WorkflowSpec:
    return WorkflowSpec(
        name="t",
        description="d",
        version=1,
        inputs=InputsSpec(),
        budget=BudgetSpec(),
        limits=LimitsSpec(),
        actors=actors,
        phases=(PhaseSpec(id="p1", actor="a"),),
    )


# ─── Builtin workflow YAMLs no longer carry legacy aliases ─────────────


class TestBuiltinWorkflowYAMLs:
    def test_autoresearch_compound_no_legacy_aliases(self):
        spec = load_workflow(BUILTINS / "autoresearch-compound.yaml")
        for name, actor in spec.actors.items():
            model = (actor.model or "").strip()
            assert model not in _LEGACY_MODEL_ALIASES, (
                f"actor {name!r} still has legacy alias model {model!r}"
            )
            # The default is "inherit from parent LLMSpec"
            assert model == "", (
                f"actor {name!r} has explicit model {model!r}; expected "
                f"empty (inherit from LLMSpec)"
            )

    def test_llmwikify_research_no_legacy_aliases(self):
        spec = load_workflow(BUILTINS / "llmwikify-research.yaml")
        for _name, actor in spec.actors.items():
            model = (actor.model or "").strip()
            assert model not in _LEGACY_MODEL_ALIASES
            assert model == ""

    def test_autoresearch_compound_actors_count(self):
        spec = load_workflow(BUILTINS / "autoresearch-compound.yaml")
        assert len(spec.actors) == 6  # clarifier, planner, evidence_extractor,
                                       # finding_extractor, wiki_proposer, synthesizer

    def test_llmwikify_research_actors_count(self):
        spec = load_workflow(BUILTINS / "llmwikify-research.yaml")
        assert len(spec.actors) == 4  # planner, researcher, verifier, synthesizer


# ─── _check_actor_models alias rejection ───────────────────────────────


class TestCheckActorModels:
    def test_empty_model_passes(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x")})
        _check_actor_models(spec)  # no raise

    def test_real_model_passes(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="minimax-M3")})
        _check_actor_models(spec)  # no raise

    def test_sonnet_rejected_by_default(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="sonnet")})
        with pytest.raises(WorkflowValidationError, match="legacy alias"):
            _check_actor_models(spec)

    def test_opus_rejected_by_default(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="opus")})
        with pytest.raises(WorkflowValidationError, match="legacy alias"):
            _check_actor_models(spec)

    def test_haiku_rejected_by_default(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="haiku")})
        with pytest.raises(WorkflowValidationError, match="legacy alias"):
            _check_actor_models(spec)

    def test_alias_allowed_via_gradient_switch(self, monkeypatch):
        monkeypatch.setenv("LLM_ALLOW_ALIAS_MODEL", "true")
        assert _alias_model_allowed() is True
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="sonnet")})
        _check_actor_models(spec)  # no raise

    def test_gradient_switch_default_off(self):
        assert _alias_model_allowed() is False


# ─── validate_workflow calls _check_actor_models ────────────────────────


class TestValidateWorkflowIntegration:
    def test_validate_workflow_rejects_sonnet(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="sonnet")})
        with pytest.raises(WorkflowValidationError, match="legacy alias"):
            validate_workflow(spec)

    def test_validate_workflow_accepts_empty(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x")})
        validate_workflow(spec)  # no raise

    def test_validate_workflow_accepts_real_model(self):
        spec = _wrap({"a": ActorSpec(name="a", system_prompt="x", model="minimax-M3")})
        validate_workflow(spec)  # no raise


# ─── _parse_actor default value ────────────────────────────────────────


class TestParseActorDefault:
    def test_yaml_without_model_field_loads_with_empty(self):
        # The YAML files in builtins/ no longer have `model:` lines,
        # so the parser must default to "" (not the legacy "inherit").
        spec = load_workflow(BUILTINS / "autoresearch-compound.yaml")
        for actor in spec.actors.values():
            assert actor.model == ""
