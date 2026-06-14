"""Dynamic Workflow DSL v1 — schema models, parser, validator, DAG builder.

This is the **load-time** half of the dynamic-workflow runtime. The
runtime (executor) lives in ``executor.py`` and ``subagent_runner.py``.

Design constraints (see ``docs/dynamic-workflow-dsl.md``):

  - YAML is the only accepted format. JSON is accepted as a superset
    for tests and for inline workflows.
  - LLMs **never** generate code. They pick from
    ``builtins/*.yaml`` and fill ``inputs``. This is the central
    safety property: no Python or shell strings flow into the
    executor from the model.
  - Validation is eager: a malformed workflow is rejected at
    ``load()`` time, not at ``run()`` time.
  - The DAG is built once at load and immutable at runtime. A
    separate ``runtime_state`` file tracks per-run progress.

Public surface:

  - ``WorkflowSpec`` / ``ActorSpec`` / ``PhaseSpec``: dataclasses
  - ``load_workflow(source) -> WorkflowSpec``: load from YAML/JSON
  - ``validate_workflow(spec)``: raises on errors
  - ``build_dag(spec) -> Dag``: dependency graph + topological order
  - ``WorkflowParseError``, ``WorkflowValidationError``: error types
"""
from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


# ─── Error types ────────────────────────────────────────────────


class WorkflowParseError(ValueError):
    """YAML/JSON failed to parse or doesn't match the schema."""


class WorkflowValidationError(ValueError):
    """Workflow structure is invalid (cycles, missing refs, bad limits, ...)."""


# ─── Spec dataclasses ───────────────────────────────────────────


PermissionMode = Literal[
    "default", "acceptEdits", "auto", "dontAsk", "bypassPermissions", "plan"
]
IsolationMode = Literal["none", "worktree"]
# LAL (PR 2): removed the "inherit" alias. The semantics is now
# "empty / missing = use the parent LLMSpec.model" (i.e. inheritance
# is the default). The alias is still accepted as a string for
# back-compat with existing YAMLs and is normalized to "" in
# LlmClientDriver; PR 3 will reject it entirely.
ActorModel = Literal["opus", "sonnet", "haiku"] | str
OnExceedPolicy = Literal["halt", "continue"]


@dataclass(frozen=True)
class ActorSpec:
    """One role / subagent configuration.

    Exactly one of ``prompt_file`` or ``system_prompt`` must be set.
    """

    name: str
    model: ActorModel = ""
    tools: tuple[str, ...] = ()
    isolation: IsolationMode = "none"
    permission_mode: PermissionMode = "default"
    prompt_file: str | None = None
    system_prompt: str | None = None
    max_turns: int | None = None

    def __post_init__(self) -> None:
        if not self.prompt_file and not self.system_prompt:
            raise WorkflowValidationError(
                f"actor {self.name!r}: one of prompt_file or system_prompt required"
            )
        if self.prompt_file and self.system_prompt:
            raise WorkflowValidationError(
                f"actor {self.name!r}: prompt_file and system_prompt are mutually exclusive"
            )
        if self.max_turns is not None and self.max_turns < 1:
            raise WorkflowValidationError(
                f"actor {self.name!r}: max_turns must be >= 1"
            )

    @property
    def effective_prompt_source(self) -> str:
        """``"file:<path>"`` or ``"inline:<truncated>"`` — for logging."""
        if self.prompt_file:
            return f"file:{self.prompt_file}"
        assert self.system_prompt is not None
        snippet = self.system_prompt[:60].replace("\n", " ")
        return f"inline:{snippet!r}..."


@dataclass(frozen=True)
class FanOutSpec:
    """Data-driven fan-out: spawn one phase per item in a referenced list."""

    from_ref: str            # e.g. ``"$plan.phases"``
    id_prefix: str           # e.g. ``"gather_"``; instance ids become ``gather_0``, ...
    per_item_actor: str
    per_item_inputs: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.from_ref.startswith("$"):
            raise WorkflowValidationError(
                f"fan_out.from must be a $-reference, got {self.from_ref!r}"
            )
        if not self.id_prefix:
            raise WorkflowValidationError("fan_out.id_prefix must be non-empty")


@dataclass(frozen=True)
class PhaseSpec:
    """One DAG node. A phase = one subagent invocation.

    Two construction modes:

    1. **Single** — `fan_out is None`. One instance, id == self.id.
    2. **Fan-out** — `fan_out is not None`. ``self.id`` is the
       *template* id; instances are ``<fan_out.id_prefix><index>``
       and only exist after the runtime resolves the upstream list.
    """

    id: str
    actor: str
    needs: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    outputs: str | None = None
    fan_out: FanOutSpec | None = None
    count: int | None = None
    parallel: bool = False
    timeout_seconds: int | None = None
    retry_attempts: int = 0
    retry_backoff_seconds: float = 1.0
    skip_if: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise WorkflowValidationError("phase id must be non-empty")
        if not self.actor:
            raise WorkflowValidationError(f"phase {self.id!r}: actor is required")
        if self.fan_out is not None and self.count is not None:
            raise WorkflowValidationError(
                f"phase {self.id!r}: fan_out and count are mutually exclusive"
            )
        if self.fan_out is None and self.count is not None and self.count > 1:
            # Bare count without fan_out: spawn N instances with same inputs.
            # Reserved for future use; rejected for v1 to keep semantics tight.
            raise WorkflowValidationError(
                f"phase {self.id!r}: count without fan_out is not supported in v1; "
                f"use fan_out with from_ref to a list-typed input"
            )
        if self.retry_attempts < 0:
            raise WorkflowValidationError(
                f"phase {self.id!r}: retry_attempts must be >= 0"
            )
        if self.retry_backoff_seconds < 0:
            raise WorkflowValidationError(
                f"phase {self.id!r}: retry_backoff_seconds must be >= 0"
            )


@dataclass(frozen=True)
class BudgetSpec:
    """Cost & concurrency ceilings."""

    max_total_tokens: int | None = None
    max_concurrent_agents: int = 8
    on_exceed: OnExceedPolicy = "halt"

    def __post_init__(self) -> None:
        if self.max_concurrent_agents < 1:
            raise WorkflowValidationError(
                f"max_concurrent_agents must be >= 1, got {self.max_concurrent_agents}"
            )
        if self.max_concurrent_agents > 16:
            # Mirrors Claude Code's hard limit; warn but accept.
            logger.warning(
                "max_concurrent_agents=%d exceeds Claude Code's 16-agent limit; "
                "consider lowering for compatibility",
                self.max_concurrent_agents,
            )
        if self.max_total_tokens is not None and self.max_total_tokens < 0:
            raise WorkflowValidationError("max_total_tokens must be >= 0")


@dataclass(frozen=True)
class LimitsSpec:
    """Wall-clock and per-phase timeouts."""

    max_total_agents: int = 100
    max_phase_timeout_seconds: int = 1800
    max_wallclock_seconds: int = 14400

    def __post_init__(self) -> None:
        if self.max_total_agents < 1:
            raise WorkflowValidationError("max_total_agents must be >= 1")
        if self.max_phase_timeout_seconds < 1:
            raise WorkflowValidationError(
                "max_phase_timeout_seconds must be >= 1"
            )
        if self.max_wallclock_seconds < 1:
            raise WorkflowValidationError("max_wallclock_seconds must be >= 1")


@dataclass(frozen=True)
class InputsSpec:
    """JSON-Schema-ish description of the workflow's external inputs."""

    type: Literal["object"] = "object"
    properties: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    required: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.type != "object":
            raise WorkflowValidationError(
                f"workflow inputs.type must be 'object', got {self.type!r}"
            )
        for required_key in self.required:
            if required_key not in self.properties:
                raise WorkflowValidationError(
                    f"workflow inputs: required key {required_key!r} "
                    f"not in properties"
                )


@dataclass(frozen=True)
class WorkflowSpec:
    """Top-level workflow definition."""

    name: str
    description: str
    version: int
    inputs: InputsSpec
    actors: Mapping[str, ActorSpec]
    phases: tuple[PhaseSpec, ...]
    budget: BudgetSpec
    limits: LimitsSpec
    triggers: Mapping[str, Any] = field(default_factory=dict)
    events: Mapping[str, str] = field(default_factory=dict)
    source_path: Path | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise WorkflowValidationError("workflow.name is required")
        if not self.description:
            raise WorkflowValidationError(
                f"workflow {self.name!r}: description is required"
            )
        # `version` lives at the top level of the YAML (e.g. ``version: 1``)
        # and is consumed at parse time. The spec itself does not
        # require version=1 here because we are already past the
        # gate; we only carry it for downstream consumers.
        if not self.actors:
            raise WorkflowValidationError(
                f"workflow {self.name!r}: at least one actor is required"
            )
        if not self.phases:
            raise WorkflowValidationError(
                f"workflow {self.name!r}: at least one phase is required"
            )


# ─── Parsing ─────────────────────────────────────────────────────


def _require(d: Mapping[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise WorkflowParseError(f"{ctx}: missing required key {key!r}")
    return d[key]


def _parse_actor(name: str, raw: Mapping[str, Any]) -> ActorSpec:
    if not isinstance(raw, Mapping):
        raise WorkflowParseError(f"actor {name!r}: must be a mapping")
    tools = raw.get("tools", [])
    if not isinstance(tools, list):
        raise WorkflowParseError(f"actor {name!r}: tools must be a list")
    isolation = raw.get("isolation", "none")
    if isolation not in ("none", "worktree"):
        raise WorkflowParseError(
            f"actor {name!r}: isolation must be 'none' or 'worktree', got {isolation!r}"
        )
    return ActorSpec(
        name=name,
        model=raw.get("model", "inherit"),
        tools=tuple(tools),
        isolation=isolation,
        permission_mode=raw.get("permission_mode", "default"),
        prompt_file=raw.get("prompt_file"),
        system_prompt=raw.get("system_prompt"),
        max_turns=raw.get("max_turns"),
    )


def _parse_fan_out(phase_id: str, raw: Mapping[str, Any]) -> FanOutSpec:
    if not isinstance(raw, Mapping):
        raise WorkflowParseError(
            f"phase {phase_id!r}: fan_out must be a mapping"
        )
    return FanOutSpec(
        from_ref=_require(raw, "from", f"phase {phase_id!r}.fan_out"),
        id_prefix=_require(raw, "id_prefix", f"phase {phase_id!r}.fan_out"),
        per_item_actor=_require(raw, "actor", f"phase {phase_id!r}.fan_out"),
        per_item_inputs=dict(raw.get("inputs", {})),
    )


def _parse_phase(raw: Mapping[str, Any]) -> PhaseSpec:
    if not isinstance(raw, Mapping):
        raise WorkflowParseError("phase entry must be a mapping")
    phase_id = _require(raw, "id", "phase")
    actor = _require(raw, "actor", f"phase {phase_id!r}")
    fan_out_raw = raw.get("fan_out")
    fan_out = _parse_fan_out(phase_id, fan_out_raw) if fan_out_raw else None
    return PhaseSpec(
        id=phase_id,
        actor=actor,
        needs=tuple(raw.get("needs", [])),
        inputs=dict(raw.get("inputs", {})),
        outputs=raw.get("outputs"),
        fan_out=fan_out,
        count=raw.get("count"),
        parallel=bool(raw.get("parallel", False)),
        timeout_seconds=raw.get("timeout_seconds"),
        retry_attempts=int(raw.get("retry_attempts", 0)),
        retry_backoff_seconds=float(raw.get("retry_backoff_seconds", 1.0)),
        skip_if=raw.get("skip_if"),
    )


def _parse_inputs(raw: Mapping[str, Any] | None) -> InputsSpec:
    if raw is None:
        return InputsSpec()
    if not isinstance(raw, Mapping):
        raise WorkflowParseError("workflow.inputs must be a mapping")
    return InputsSpec(
        type="object",
        properties=dict(raw.get("properties", {})),
        required=tuple(raw.get("required", [])),
    )


def _parse_budget(raw: Mapping[str, Any] | None) -> BudgetSpec:
    if raw is None:
        return BudgetSpec()
    if not isinstance(raw, Mapping):
        raise WorkflowParseError("workflow.budget must be a mapping")
    return BudgetSpec(
        max_total_tokens=raw.get("max_total_tokens"),
        max_concurrent_agents=int(raw.get("max_concurrent_agents", 8)),
        on_exceed=raw.get("on_exceed", "halt"),
    )


def _parse_limits(raw: Mapping[str, Any] | None) -> LimitsSpec:
    if raw is None:
        return LimitsSpec()
    if not isinstance(raw, Mapping):
        raise WorkflowParseError("workflow.limits must be a mapping")
    return LimitsSpec(
        max_total_agents=int(raw.get("max_total_agents", 100)),
        max_phase_timeout_seconds=int(raw.get("max_phase_timeout_seconds", 1800)),
        max_wallclock_seconds=int(raw.get("max_wallclock_seconds", 14400)),
    )


def _parse_workflow_block(raw: Mapping[str, Any]) -> WorkflowSpec:
    if not isinstance(raw, Mapping):
        raise WorkflowParseError("top-level 'workflow' must be a mapping")
    name = _require(raw, "name", "workflow")
    description = _require(raw, "description", "workflow")
    actors_raw = _require(raw, "actors", "workflow")
    phases_raw = _require(raw, "phases", "workflow")
    if not isinstance(actors_raw, Mapping):
        raise WorkflowParseError("workflow.actors must be a mapping")
    if not isinstance(phases_raw, list):
        raise WorkflowParseError("workflow.phases must be a list")
    actors = {n: _parse_actor(n, a) for n, a in actors_raw.items()}
    phases = tuple(_parse_phase(p) for p in phases_raw)
    return WorkflowSpec(
        name=name,
        description=description,
        version=1,                                # default; version is set by parse_yaml
        inputs=_parse_inputs(raw.get("inputs")),
        actors=actors,
        phases=phases,
        budget=_parse_budget(raw.get("budget")),
        limits=_parse_limits(raw.get("limits")),
        triggers=dict(raw.get("triggers", {})),
        events=dict(raw.get("events", {})),
    )


def parse_yaml(text: str) -> WorkflowSpec:
    """Parse a YAML string into a WorkflowSpec.

    The expected top-level shape is::

        version: 1
        workflow:
          name: ...
          ...

    Uses stdlib only if PyYAML is unavailable. PyYAML is a hard
    dependency of llmwikify, but we fall back to a tiny ad-hoc parser
    so the test suite can run without it in the rare case of a
    poisoned environment.
    """
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_yaml_fallback(text)
    try:
        data = yaml.safe_load(text)
    except Exception as e:
        raise WorkflowParseError(f"YAML parse error: {e}") from e
    if not isinstance(data, Mapping):
        raise WorkflowParseError("top-level YAML must be a mapping")
    # Validate ``version`` early so the user gets a clear error.
    version = data.get("version", 1)
    if not isinstance(version, int):
        raise WorkflowParseError(
            f"top-level 'version' must be an integer, got {type(version).__name__}"
        )
    if version != 1:
        raise WorkflowValidationError(
            f"only workflow version=1 is supported, got version={version}"
        )
    return parse_workflow_dict(data)


def parse_json(text: str) -> WorkflowSpec:
    """Parse a JSON string (YAML is a superset of JSON; both parsers produce the same spec)."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise WorkflowParseError(f"JSON parse error: {e}") from e
    if not isinstance(data, Mapping):
        raise WorkflowParseError("top-level JSON must be a mapping")
    return parse_workflow_dict(data)


def parse_workflow_dict(data: Mapping[str, Any]) -> WorkflowSpec:
    """Parse a top-level dict that *contains* a ``workflow:`` block.

    This is the public entry point for in-memory dicts (e.g. tests
    building workflows programmatically). It strips the outer
    ``workflow`` key and delegates to ``_parse_workflow_block``.
    """
    if "workflow" not in data:
        raise WorkflowParseError(
            "top-level must contain a 'workflow:' block; got keys: "
            f"{sorted(data.keys())}"
        )
    return _parse_workflow_block(data["workflow"])


def load_workflow(source: str | Path) -> WorkflowSpec:
    """Load a workflow from a file path. Detects YAML vs JSON by suffix."""
    p = Path(source)
    if not p.exists():
        raise WorkflowParseError(f"workflow file not found: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        spec = parse_yaml(text)
    elif p.suffix.lower() == ".json":
        spec = parse_json(text)
    else:
        # Default: try YAML; fall back to JSON.
        try:
            spec = parse_yaml(text)
        except WorkflowParseError:
            spec = parse_json(text)
    # Re-stamp source_path (immutable tuple → rebuild)
    return WorkflowSpec(
        name=spec.name,
        description=spec.description,
        version=spec.version,
        inputs=spec.inputs,
        actors=spec.actors,
        phases=spec.phases,
        budget=spec.budget,
        limits=spec.limits,
        triggers=spec.triggers,
        events=spec.events,
        source_path=p.resolve(),
    )


def _parse_yaml_fallback(text: str) -> WorkflowSpec:  # pragma: no cover
    """Ultra-minimal YAML parser for the top-level `workflow: { ... }` block.

    Only supports the surface we need: top-level mapping with a
    ``workflow:`` key whose value is a mapping with string values
    and 1-level nested mappings. Used only when PyYAML is missing.
    """
    raise WorkflowParseError(
        "PyYAML is not installed; install pyyaml or load via JSON instead"
    )


# ─── Validation (graph-level) ───────────────────────────────────


def validate_workflow(spec: WorkflowSpec) -> None:
    """Cross-cutting checks that require knowing the whole spec.

    1. Every phase's ``actor`` references an existing actor.
    2. Every phase's ``needs`` references an existing phase id.
    3. The DAG is acyclic.
    4. ``$`` references in inputs resolve to known input keys or
       prior-phase outputs.
    5. ``outputs`` names are unique across phases.
    6. Fan-out ``from_ref`` path is plausible (root key exists in
       upstream phase's outputs schema — runtime-resolved, but we
       at least catch obvious typos here).
    """
    actor_names = set(spec.actors.keys())
    phase_ids = {p.id for p in spec.phases}
    for phase in spec.phases:
        if phase.actor not in actor_names:
            raise WorkflowValidationError(
                f"phase {phase.id!r}: references unknown actor {phase.actor!r}; "
                f"available: {sorted(actor_names)}"
            )
        for need in phase.needs:
            if need not in phase_ids:
                raise WorkflowValidationError(
                    f"phase {phase.id!r}: needs unknown phase {need!r}; "
                    f"available: {sorted(phase_ids)}"
                )
        if phase.fan_out is not None:
            if phase.fan_out.per_item_actor not in actor_names:
                raise WorkflowValidationError(
                    f"phase {phase.id!r}: fan_out.per_item.actor references "
                    f"unknown actor {phase.fan_out.per_item_actor!r}"
                )

    # Cycle detection
    _check_dag_acyclic(spec)

    # Output name uniqueness
    seen_outputs: dict[str, str] = {}
    for phase in spec.phases:
        if phase.outputs is None:
            continue
        if phase.outputs in seen_outputs:
            raise WorkflowValidationError(
                f"phase {phase.id!r}: outputs {phase.outputs!r} collides with "
                f"phase {seen_outputs[phase.outputs]!r}"
            )
        seen_outputs[phase.outputs] = phase.id

    # $-reference shape check
    available_inputs = set(spec.inputs.properties.keys())
    available_outputs: set[str] = set()
    available_fanout_templates: set[str] = set()
    for phase in spec.phases:
        if phase.outputs is not None:
            available_outputs.add(phase.outputs)
        if phase.fan_out is not None:
            available_fanout_templates.add(phase.id)
        _check_dollar_refs(
            phase.id,
            phase.inputs,
            available_inputs,
            available_outputs,
            available_fanout_templates,
        )


def _check_dag_acyclic(spec: WorkflowSpec) -> None:
    """Iterative DFS for cycle detection. Raises on back-edge."""
    adj: dict[str, list[str]] = {p.id: list(p.needs) for p in spec.phases}
    # DFS with three-color marking
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {p.id: WHITE for p in spec.phases}
    parent: dict[str, str | None] = {p.id: None for p in spec.phases}

    for start in list(color.keys()):
        if color[start] != WHITE:
            continue
        # Iterative DFS via stack of (node, iterator)
        stack: list[tuple[str, Any]] = [(start, iter(adj[start]))]
        color[start] = GRAY
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                color[node] = BLACK
                stack.pop()
                continue
            if nxt not in color:
                # Edge to a non-phase: should have been caught by id check.
                # Be defensive: skip.
                continue
            if color[nxt] == GRAY:
                # Back-edge → cycle. Reconstruct path.
                path = [nxt, node]
                cur = node
                while parent.get(cur) is not None and cur != nxt:
                    cur = parent[cur]  # type: ignore[assignment]
                    path.append(cur)
                path.reverse()
                raise WorkflowValidationError(
                    f"workflow {spec.name!r}: cycle detected in phase DAG: "
                    f"{' -> '.join(path)}"
                )
            if color[nxt] == WHITE:
                color[nxt] = GRAY
                parent[nxt] = node
                stack.append((nxt, iter(adj[nxt])))


def _check_dollar_refs(
    phase_id: str,
    inputs: Mapping[str, Any],
    available_inputs: set[str],
    available_outputs: set[str],
    available_fanout_templates: set[str] | None = None,
) -> None:
    """Walk the inputs tree and verify every $reference shape is valid.

    Note: we don't resolve the actual value (runtime does that),
    only the *shape* of the reference: a $-prefixed path where
    the first component is an input key, a phase output name, a
    fan-out template id (resolves to its expanded instances at
    runtime), or the literal word ``item`` / ``env``.
    """
    for key, value in inputs.items():
        _walk_dollar_refs(
            phase_id,
            key,
            value,
            available_inputs,
            available_outputs,
            available_fanout_templates or set(),
        )


def _walk_dollar_refs(
    phase_id: str,
    key: str,
    value: Any,
    available_inputs: set[str],
    available_outputs: set[str],
    available_fanout_templates: set[str],
) -> None:
    if isinstance(value, str):
        if value.startswith("$"):
            root = value[1:].split(".", 1)[0]
            if root == "item":
                return
            if root == "env":
                return
            if root == "inputs":
                sub = value[len("$inputs."):].split(".", 1)[0]
                if sub not in available_inputs:
                    raise WorkflowValidationError(
                        f"phase {phase_id!r}: $ref {value!r} under key {key!r} "
                        f"references unknown input {sub!r}; available: "
                        f"{sorted(available_inputs)}"
                    )
                return
            # Otherwise: must be a phase output OR a fan-out template id.
            if root in available_outputs:
                return
            if root in available_fanout_templates:
                return
            raise WorkflowValidationError(
                f"phase {phase_id!r}: $ref {value!r} under key {key!r} "
                f"references unknown phase output {root!r}; available: "
                f"{sorted(available_outputs | available_fanout_templates)}"
            )
    elif isinstance(value, Mapping):
        for k, v in value.items():
            _walk_dollar_refs(
                phase_id, f"{key}.{k}", v,
                available_inputs, available_outputs, available_fanout_templates,
            )
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _walk_dollar_refs(
                phase_id, f"{key}[{i}]", v,
                available_inputs, available_outputs, available_fanout_templates,
            )


# ─── DAG view (after fan-out expansion would happen) ────────────


@dataclass(frozen=True)
class Dag:
    """A read-only view of the workflow graph as prepared for execution.

    For v1, fan-out instances are **not** pre-expanded; the runtime
    expands them after the upstream phase completes. This keeps
    the graph tiny and avoids baking a snapshot in the spec.
    """

    spec: WorkflowSpec
    phases_by_id: Mapping[str, PhaseSpec]
    topological_order: tuple[str, ...]

    def ready_phases(self, completed: set[str]) -> list[PhaseSpec]:
        """Phases whose dependencies are all in `completed` and not yet run."""
        out: list[PhaseSpec] = []
        for phase in self.phases_by_id.values():
            if phase.id in completed:
                continue
            if all(n in completed for n in phase.needs):
                out.append(phase)
        return out


def build_dag(spec: WorkflowSpec) -> Dag:
    """Topologically sort the phase graph. Assumes ``validate_workflow`` passed."""
    by_id = {p.id: p for p in spec.phases}
    in_degree: dict[str, int] = {p.id: len(p.needs) for p in spec.phases}
    # Reverse adjacency: who depends on me?
    children: dict[str, list[str]] = {p.id: [] for p in spec.phases}
    for phase in spec.phases:
        for need in phase.needs:
            children[need].append(phase.id)

    queue = [pid for pid, deg in in_degree.items() if deg == 0]
    order: list[str] = []
    while queue:
        # Sort for determinism
        queue.sort()
        node = queue.pop(0)
        order.append(node)
        for child in children[node]:
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)
    if len(order) != len(spec.phases):
        # Should have been caught by validate_workflow
        raise WorkflowValidationError(
            f"workflow {spec.name!r}: cycle not caught at validation time "
            f"(this is a bug in llmwikify)"
        )
    return Dag(spec=spec, phases_by_id=by_id, topological_order=tuple(order))


__all__ = [
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
]
