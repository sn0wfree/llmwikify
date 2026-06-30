"""Unit tests for the dynamic-workflow DSL parser/validator.

Covers:
  - parse_yaml / parse_json
  - load_workflow from path
  - validate_workflow (actor refs, needs refs, cycle detection,
    $-reference shape, output uniqueness)
  - build_dag topological order
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from llmwikify.apps.chat.skills.workflows import (
    BudgetSpec,
    Dag,
    FanOutSpec,
    InputsSpec,
    LimitsSpec,
    WorkflowParseError,
    WorkflowSpec,
    WorkflowValidationError,
    build_dag,
    load_workflow,
    parse_json,
    parse_yaml,
    validate_workflow,
)

# ─── parse_yaml / parse_json ──────────────────────────────────


def test_parse_yaml_minimal():
    text = dedent(
        """
        version: 1
        workflow:
          name: tiny
          description: minimal test workflow
          actors:
            a:
              system_prompt: "You are A."
          phases:
            - id: only
              actor: a
        """
    )
    spec = parse_yaml(text)
    assert spec.name == "tiny"
    assert spec.version == 1
    assert "a" in spec.actors
    assert len(spec.phases) == 1


def test_parse_yaml_missing_name_raises():
    text = dedent(
        """
        version: 1
        workflow:
          description: no name
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p1
              actor: a
        """
    )
    # Spec construction calls __post_init__ which checks name
    with pytest.raises(WorkflowParseError):
        parse_yaml(text)


def test_parse_yaml_missing_version_defaults_to_1():
    """version is optional; absent → defaults to 1 (current)."""
    text = dedent(
        """
        workflow:
          name: no-version
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p1
              actor: a
        """
    )
    spec = parse_yaml(text)
    assert spec.version == 1


def test_parse_yaml_unsupported_version_raises():
    text = dedent(
        """
        version: 99
        workflow:
          name: future
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p1
              actor: a
        """
    )
    with pytest.raises(WorkflowValidationError):
        parse_yaml(text)


def test_parse_json_equivalent_to_yaml():
    obj = {
        "version": 1,
        "workflow": {
            "name": "from-json",
            "description": "x",
            "actors": {"a": {"system_prompt": "hi"}},
            "phases": [{"id": "p", "actor": "a"}],
        }
    }
    import json
    spec = parse_json(json.dumps(obj))
    assert spec.name == "from-json"


def test_parse_json_garbage_raises():
    with pytest.raises(WorkflowParseError):
        parse_json("{not: valid, json")


# ─── ActorSpec validation ─────────────────────────────────────


def test_actor_must_have_prompt_or_system_prompt():
    # Direct construction triggers __post_init__
    from llmwikify.apps.chat.skills.workflows.dag import ActorSpec
    with pytest.raises(WorkflowValidationError):
        ActorSpec(name="bad")


def test_actor_prompt_file_and_inline_are_mutually_exclusive():
    from llmwikify.apps.chat.skills.workflows.dag import ActorSpec
    with pytest.raises(WorkflowValidationError):
        ActorSpec(
            name="both",
            prompt_file="x.md",
            system_prompt="hi",
        )


def test_parse_yaml_actor_with_both_prompts_raises():
    text = dedent(
        """
        version: 1
        workflow:
          name: bad-actor
          description: x
          actors:
            a:
              prompt_file: x.md
              system_prompt: hi
          phases:
            - id: p
              actor: a
        """
    )
    with pytest.raises((WorkflowParseError, WorkflowValidationError)):
        parse_yaml(text)


# ─── PhaseSpec validation ─────────────────────────────────────


def test_phase_fan_out_and_count_mutually_exclusive():
    text = dedent(
        """
        version: 1
        workflow:
          name: bad-phase
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
              fan_out:
                from: $plan.list
                id_prefix: inst_
                actor: a
              count: 3
        """
    )
    with pytest.raises((WorkflowParseError, WorkflowValidationError)):
        parse_yaml(text)


# ─── validate_workflow ─────────────────────────────────────────


def _spec_plan_then_gather() -> WorkflowSpec:
    text = dedent(
        """
        version: 1
        workflow:
          name: plan-then-gather
          description: x
          actors:
            planner: {system_prompt: "plan"}
            researcher: {system_prompt: "research"}
          phases:
            - id: plan
              actor: planner
              outputs: plan
            - id: gather
              actor: researcher
              needs: [plan]
              fan_out:
                from: $plan.phases
                id_prefix: gather_
                actor: researcher
                inputs:
                  phase: $item
        """
    )
    return parse_yaml(text)


def test_validate_workflow_passes_on_good_spec():
    spec = _spec_plan_then_gather()
    validate_workflow(spec)  # should not raise


def test_validate_workflow_rejects_unknown_actor():
    text = dedent(
        """
        version: 1
        workflow:
          name: missing-actor
          description: x
          actors:
            planner: {system_prompt: "plan"}
          phases:
            - id: plan
              actor: ghost
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="unknown actor"):
        validate_workflow(spec)


def test_validate_workflow_rejects_unknown_need():
    text = dedent(
        """
        version: 1
        workflow:
          name: missing-need
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
              needs: [nonexistent]
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="unknown phase"):
        validate_workflow(spec)


def test_validate_workflow_detects_cycle():
    text = dedent(
        """
        version: 1
        workflow:
          name: cyclic
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p1
              actor: a
              needs: [p2]
            - id: p2
              actor: a
              needs: [p1]
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="cycle"):
        validate_workflow(spec)


def test_validate_workflow_rejects_duplicate_output_names():
    text = dedent(
        """
        version: 1
        workflow:
          name: dup-out
          description: x
          actors:
            a: {system_prompt: hi}
            b: {system_prompt: hi}
          phases:
            - id: p1
              actor: a
              outputs: shared
            - id: p2
              actor: b
              needs: [p1]
              outputs: shared
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="collides"):
        validate_workflow(spec)


def test_validate_workflow_rejects_unknown_dollar_ref():
    text = dedent(
        """
        version: 1
        workflow:
          name: bad-ref
          description: x
          inputs:
            type: object
            properties:
              q: {type: string}
            required: [q]
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
              inputs:
                bad: $inputs.nonexistent
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="unknown input"):
        validate_workflow(spec)


def test_validate_workflow_rejects_dollar_ref_to_unknown_output():
    text = dedent(
        """
        version: 1
        workflow:
          name: bad-out-ref
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
              inputs:
                bad: $ghost.x
        """
    )
    spec = parse_yaml(text)
    with pytest.raises(WorkflowValidationError, match="unknown phase output"):
        validate_workflow(spec)


# ─── build_dag ────────────────────────────────────────────────


def test_build_dag_topological_order_simple():
    spec = _spec_plan_then_gather()
    dag = build_dag(spec)
    # plan has no deps, so it must come first
    assert dag.topological_order[0] == "plan"
    assert "gather" in dag.topological_order


def test_build_dag_complex_ordering():
    text = dedent(
        """
        version: 1
        workflow:
          name: diamond
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: root
              actor: a
            - id: left
              actor: a
              needs: [root]
            - id: right
              actor: a
              needs: [root]
            - id: top
              actor: a
              needs: [left, right]
        """
    )
    spec = parse_yaml(text)
    validate_workflow(spec)
    dag = build_dag(spec)
    order = dag.topological_order
    assert order[0] == "root"
    assert order[-1] == "top"
    assert order.index("left") < order.index("top")
    assert order.index("right") < order.index("top")


def test_dag_ready_phases_filters_completed():
    spec = _spec_plan_then_gather()
    dag = build_dag(spec)
    ready = dag.ready_phases(set())
    assert {p.id for p in ready} == {"plan"}
    ready2 = dag.ready_phases({"plan"})
    # gather template is now ready (its only need is plan)
    assert {p.id for p in ready2} == {"gather"}


# ─── load_workflow from path ──────────────────────────────────


def test_load_workflow_yaml(tmp_path: Path):
    p = tmp_path / "wf.yaml"
    p.write_text(dedent("""
        version: 1
        workflow:
          name: from-file
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
    """))
    spec = load_workflow(p)
    assert spec.name == "from-file"
    assert spec.source_path == p.resolve()


def test_load_workflow_not_found(tmp_path: Path):
    with pytest.raises(WorkflowParseError, match="not found"):
        load_workflow(tmp_path / "nope.yaml")


# ─── budget / limits defaults ─────────────────────────────────


def test_budget_defaults_applied():
    text = dedent(
        """
        version: 1
        workflow:
          name: defaults
          description: x
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
        """
    )
    spec = parse_yaml(text)
    assert spec.budget.max_concurrent_agents == 8
    assert spec.budget.on_exceed == "halt"
    assert spec.limits.max_total_agents == 100
    assert spec.limits.max_wallclock_seconds == 14400


def test_budget_max_concurrent_agents_warns_above_16(caplog):
    text = dedent(
        """
        version: 1
        workflow:
          name: over-budget
          description: x
          budget:
            max_concurrent_agents: 32
          actors:
            a: {system_prompt: hi}
          phases:
            - id: p
              actor: a
        """
    )
    import logging
    with caplog.at_level(logging.WARNING, logger="llmwikify.apps.chat.skills.workflows.dag"):
        spec = parse_yaml(text)
    assert spec.budget.max_concurrent_agents == 32
    assert any("16-agent limit" in r.message for r in caplog.records)
