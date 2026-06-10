"""Dynamic Workflows for the llmwikify chat agent.

Public surface:

  - ``load_workflow(path)``             — load a YAML/JSON workflow
  - ``parse_yaml(text)`` / ``parse_json(text)`` — inline parsing
  - ``validate_workflow(spec)``         — graph + schema checks
  - ``build_dag(spec)``                 — topological order
  - ``WorkflowExecutor``                — run a workflow to completion
  - ``DynamicWorkflowSkill``            — LLM-facing skill wrapper
  - ``RunStore`` / ``RunState``         — run persistence
  - ``list_builtin_names()`` / ``get_builtin(name)`` — built-in registry

Architecture
------------

The runtime lives in two layers:

  1. **In-process coordinator** (``executor.py``) — owns the DAG,
     resolves ``$`` references, schedules ready phases under a
     concurrency semaphore, and persists progress.

  2. **Out-of-process worker** (``subagent_runner.py``,
     ``subagent_worker.py``) — one Python subprocess per actor
     invocation. Subprocess isolation gives us genuine context
     separation, real concurrency (no GIL), and a hard crash
     boundary so a bad subagent cannot poison the chat session.

A typical run looks like:

    [WorkflowExecutor]
        │ fan-out materialize, $-refs, semaphore
        ▼
    [ThreadPoolExecutor] ──submit──▶ [mp.Process] ──pipe──▶ [subagent_worker]
                                                             │
                                                             ▼
                                                       [LlmClient or Mock]
                                                             │
                                                       [JSON result on stdout]
"""
from __future__ import annotations

from llmwikify.apps.chat.skills.workflows.dag import (
    ActorSpec,
    BudgetSpec,
    Dag,
    FanOutSpec,
    InputsSpec,
    LimitsSpec,
    PhaseSpec,
    WorkflowParseError,
    WorkflowSpec,
    WorkflowValidationError,
    build_dag,
    load_workflow,
    parse_json,
    parse_yaml,
    validate_workflow,
)
from llmwikify.apps.chat.skills.workflows.executor import (
    WorkflowExecutor,
    WorkflowInputs,
    WorkflowProgressEvent,
    WorkflowRunResult,
    resolve_dollar_refs,
)
from llmwikify.apps.chat.skills.workflows.run_store import RunState, RunStore
from llmwikify.apps.chat.skills.workflows.skill import DynamicWorkflowSkill

__all__ = [
    # DSL
    "WorkflowSpec",
    "ActorSpec",
    "PhaseSpec",
    "FanOutSpec",
    "BudgetSpec",
    "LimitsSpec",
    "InputsSpec",
    "Dag",
    "WorkflowParseError",
    "WorkflowValidationError",
    "parse_yaml",
    "parse_json",
    "load_workflow",
    "validate_workflow",
    "build_dag",
    # Runtime
    "WorkflowExecutor",
    "WorkflowInputs",
    "WorkflowRunResult",
    "WorkflowProgressEvent",
    "resolve_dollar_refs",
    # Persistence
    "RunState",
    "RunStore",
    # LLM-facing
    "DynamicWorkflowSkill",
]
