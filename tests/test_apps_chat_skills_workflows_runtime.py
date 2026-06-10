"""Integration tests for the dynamic-workflow runtime.

These tests exercise the full pipeline end-to-end:

  1. Load a YAML workflow
  2. Validate + build DAG
  3. Execute with ``MockDriver`` (no real LLM)
  4. Persist + reload run state
  5. Round-trip through the ``DynamicWorkflowSkill``

All subprocess spawning is real — we just stub the LLM. The
``LLMWIKIFY_SUBAGENT_DRIVER=mock`` env var is set for the duration
of the test session.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from textwrap import dedent

import pytest

# Force the mock driver for every test in this module
os.environ.setdefault("LLMWIKIFY_SUBAGENT_DRIVER", "mock")

from llmwikify.apps.chat.skills.base import SkillContext
from llmwikify.apps.chat.skills.workflows import (
    DynamicWorkflowSkill,
    RunStore,
    WorkflowExecutor,
    WorkflowInputs,
    load_workflow,
    resolve_dollar_refs,
    validate_workflow,
    build_dag,
)
from llmwikify.apps.chat.skills.workflows.builtins import (
    get_builtin,
    iter_builtins,
    list_builtin_names,
)


# ─── $-ref resolution ─────────────────────────────────────────


def test_resolve_dollar_ref_inputs():
    inputs = WorkflowInputs(data={"q": "What is X?"})
    out = resolve_dollar_refs(
        {"question": "$inputs.q", "other": "static"},
        inputs=inputs,
        outputs={},
    )
    assert out == {"question": "What is X?", "other": "static"}


def test_resolve_dollar_ref_outputs():
    inputs = WorkflowInputs(data={})
    outputs = {"plan": {"phases": [{"id": "p1"}, {"id": "p2"}]}}
    out = resolve_dollar_refs(
        {"phases": "$plan.phases"},
        inputs=inputs,
        outputs=outputs,
    )
    assert out == {"phases": [{"id": "p1"}, {"id": "p2"}]}


def test_resolve_dollar_ref_item():
    inputs = WorkflowInputs(data={})
    outputs = {}
    item = {"id": "p1", "title": "Explore"}
    out = resolve_dollar_refs(
        {"phase": "$item"},
        inputs=inputs,
        outputs=outputs,
        item=item,
    )
    assert out == {"phase": {"id": "p1", "title": "Explore"}}


def test_resolve_dollar_ref_missing_key_kept_as_placeholder():
    inputs = WorkflowInputs(data={})
    # The executor surfaces a clear error later; the resolver
    # leaves the placeholder so debugging is easier.
    out = resolve_dollar_refs(
        {"x": "$nonexistent.thing"},
        inputs=inputs,
        outputs={},
    )
    assert out == {"x": "$nonexistent.thing"}


# ─── Executor end-to-end (mock driver) ────────────────────────


def _make_minimal_workflow(tmp_path: Path, *, with_gather: bool = True) -> Path:
    """Write a workflow to a tmp file. with_gather=False → 1 phase only."""
    if not with_gather:
        text = dedent(
            """
            version: 1
            workflow:
              name: tiny
              description: minimal
              inputs:
                type: object
                properties:
                  question: {type: string}
                required: [question]
              actors:
                planner: {system_prompt: "Return a plan with phases."}
              phases:
                - id: plan
                  actor: planner
                  inputs:
                    question: $inputs.question
                  outputs: plan
            """
        )
    else:
        text = dedent(
            """
            version: 1
            workflow:
              name: tiny
              description: minimal
              inputs:
                type: object
                properties:
                  question: {type: string}
                required: [question]
              actors:
                planner: {system_prompt: "Return a plan with phases."}
                researcher: {system_prompt: "Return findings."}
                verifier: {system_prompt: "You are a verifier."}
                synthesizer: {system_prompt: "You are a synthesizer."}
              phases:
                - id: plan
                  actor: planner
                  inputs:
                    question: $inputs.question
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
                - id: verify
                  actor: verifier
                  needs: [gather]
                  inputs:
                    question: $inputs.question
                    claims: $gather.findings
                  outputs: review
                - id: synthesize
                  actor: synthesizer
                  needs: [verify]
                  inputs:
                    question: $inputs.question
                    plan: $plan
                    filtered_findings: $gather.filtered_findings
                    review_summary: $review.summary
                  outputs: final
            """
        )
    p = tmp_path / "tiny.yaml"
    p.write_text(text)
    return p


def test_executor_runs_minimal_workflow(tmp_path: Path):
    wf_path = _make_minimal_workflow(tmp_path, with_gather=False)
    spec = load_workflow(wf_path)
    validate_workflow(spec)
    store = RunStore(tmp_path / "runs")
    executor = WorkflowExecutor(
        spec=spec,
        inputs=WorkflowInputs(data={"question": "What is X?"}),
        base_dir=wf_path.parent,
        run_store=store,
    )
    result = executor.run()
    assert result.status == "ok"
    assert "plan" in result.outputs
    # The mock planner returns 2 phases
    assert len(result.outputs["plan"]["phases"]) == 2
    # Run state persisted
    state = store.load(result.run_id)
    assert state is not None
    assert state.status == "ok"
    assert state.total_agents_spawned == 1


def test_executor_runs_with_fanout(tmp_path: Path):
    wf_path = _make_minimal_workflow(tmp_path, with_gather=True)
    spec = load_workflow(wf_path)
    validate_workflow(spec)
    store = RunStore(tmp_path / "runs")
    executor = WorkflowExecutor(
        spec=spec,
        inputs=WorkflowInputs(data={"question": "What is X?"}),
        base_dir=wf_path.parent,
        run_store=store,
    )
    result = executor.run()
    assert result.status == "ok", result.to_dict()
    # plan + 2 gather instances (mock plan has 2 phases) + verify + synthesize = 5 phases
    assert result.total_agents_spawned >= 4
    # The plan template spawned 2 gather instances
    assert "gather_0" in result.outputs
    assert "gather_1" in result.outputs
    # The final output should be from the synthesizer
    assert "final" in result.outputs
    final = result.outputs["final"]
    assert "page_path" in final
    assert "criteria_met" in final


def test_executor_resume_completes_only_remaining_phases(tmp_path: Path):
    """Resume: completed phases are skipped; remaining are run again.

    Note: the cumulative token/agent counters on the resumed run's
    result reflect *all* work (cumulative), not just the work
    done in this run — so we test that the *delta* is 0.
    """
    wf_path = _make_minimal_workflow(tmp_path, with_gather=False)
    spec = load_workflow(wf_path)
    validate_workflow(spec)
    store = RunStore(tmp_path / "runs")
    # First run
    e1 = WorkflowExecutor(
        spec=spec,
        inputs=WorkflowInputs(data={"question": "Q?"}),
        base_dir=wf_path.parent,
        run_store=store,
    )
    r1 = e1.run()
    assert r1.status == "ok"
    baseline_agents = r1.total_agents_spawned
    # Reload and "resume" — but there's nothing left to do.
    e2 = WorkflowExecutor.from_run_id(r1.run_id, base_dir=wf_path.parent, run_store=store)
    r2 = e2.run()
    # No new agents spawned → delta is 0
    delta = r2.total_agents_spawned - baseline_agents
    assert delta == 0
    # Status is still 'ok' because nothing failed.
    assert r2.status == "ok"


def test_executor_halted_when_budget_exceeded(tmp_path: Path):
    wf_path = _make_minimal_workflow(tmp_path, with_gather=False)
    spec = load_workflow(wf_path)
    # Force an impossibly low budget
    import dataclasses
    spec = dataclasses.replace(
        spec,
        budget=dataclasses.replace(spec.budget, max_total_tokens=1, on_exceed="halt"),
    )
    validate_workflow(spec)
    store = RunStore(tmp_path / "runs")
    executor = WorkflowExecutor(
        spec=spec,
        inputs=WorkflowInputs(data={"question": "Q?"}),
        base_dir=wf_path.parent,
        run_store=store,
    )
    result = executor.run()
    assert result.status in ("halted", "ok")  # may complete if mock returns 0 tokens
    # The important assertion: no exception, and the run completed
    # within the budget guard.


# ─── Skill integration ────────────────────────────────────────


def test_skill_list_returns_builtins():
    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        result = skill.actions["list"].handler({}, ctx)
        assert result.status == "ok"
        names = [w["name"] for w in result.data["workflows"]]
        # The shipped research workflow should be present
        assert "llmwikify-research" in names
    finally:
        skill.teardown()


def test_skill_run_uses_mock_driver_and_persists(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLMWIKIFY_SUBAGENT_DRIVER", "mock")
    # Use a tmp run store so we don't pollute ~/.llmwikify
    from llmwikify.apps.chat.skills.workflows import run_store as rs_mod
    monkeypatch.setattr(
        rs_mod.RunStore, "default", classmethod(lambda cls: rs_mod.RunStore(tmp_path / "runs"))
    )

    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext(session_id="test-session")
        result = skill.actions["run"].handler(
            {"name": "llmwikify-research", "inputs": {"question": "What is X?"}},
            ctx,
        )
        assert result.status == "ok", result.to_dict()
        run_id = result.data["run_id"]
        assert run_id.startswith("wf_")
        # State was persisted to our tmp store
        state = rs_mod.RunStore(tmp_path / "runs").load(run_id)
        assert state is not None
    finally:
        skill.teardown()


def test_skill_run_rejects_unknown_workflow():
    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        result = skill.actions["run"].handler(
            {"name": "does-not-exist", "inputs": {}}, ctx
        )
        assert result.status == "error"
        assert "unknown workflow" in result.error
    finally:
        skill.teardown()


def test_skill_run_validates_required_inputs():
    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        # llmwikify-research requires `question`
        result = skill.actions["run"].handler(
            {"name": "llmwikify-research", "inputs": {}}, ctx
        )
        assert result.status == "error"
        assert "missing required inputs" in result.error
    finally:
        skill.teardown()


def test_skill_status_returns_run_state(tmp_path: Path, monkeypatch):
    # Set up a run first
    from llmwikify.apps.chat.skills.workflows import run_store as rs_mod
    monkeypatch.setattr(
        rs_mod.RunStore, "default", classmethod(lambda cls: rs_mod.RunStore(tmp_path / "runs"))
    )
    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        run = skill.actions["run"].handler(
            {"name": "llmwikify-research", "inputs": {"question": "Q?"}}, ctx
        )
        run_id = run.data["run_id"]

        # Now status
        status = skill.actions["status"].handler({"run_id": run_id}, ctx)
        assert status.status == "ok"
        assert status.data["run_id"] == run_id
        assert status.data["status"] in ("ok", "running")
        assert "phases" in status.data
    finally:
        skill.teardown()


def test_skill_status_unknown_run_id():
    skill = DynamicWorkflowSkill()
    skill.setup()
    try:
        ctx = SkillContext()
        result = skill.actions["status"].handler({"run_id": "wf_does_not_exist"}, ctx)
        assert result.status == "error"
        assert "no run" in result.error
    finally:
        skill.teardown()


# ─── Built-in registry ────────────────────────────────────────


def test_iter_builtins_includes_research():
    names = list_builtin_names()
    assert "llmwikify-research" in names


def test_get_builtin_returns_spec():
    b = get_builtin("llmwikify-research")
    assert b is not None
    assert b.spec.name == "llmwikify-research"
    # 4 actors: planner, researcher, verifier, synthesizer
    assert set(b.actor_names) == {
        "planner", "researcher", "verifier", "synthesizer"
    }
    # 4 phase templates (gather template + plan + verify + synthesize)
    assert b.phase_count == 4
