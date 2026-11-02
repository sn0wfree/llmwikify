"""Contract tests for the chat SSE event vocabulary.

The backend owns the event contract; ``scripts/gen_webui_types.py``
renders it into the WebUI types. These tests guard the three ways that
contract can silently break:

1. a new event constant without a spec entry (the frontend would never
   learn about it);
2. the generated TypeScript drifting from the spec (the frontend would
   type-check against a stale union);
3. a second copy of the vocabulary appearing somewhere else (that is
   how the 17-vs-12 mismatch happened in the first place).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from llmwikify.apps.chat.agent import events, research_runner

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATOR = REPO_ROOT / "scripts" / "gen_webui_types.py"
TS_FILE = REPO_ROOT / "ui" / "webui" / "src" / "generated" / "events.ts"
SCHEMA_FILE = REPO_ROOT / "docs" / "api" / "events.schema.json"

#: The event constants — the spec types are not events.
_NON_EVENTS = {"EventField", "EventSpec", "EVENT_SPECS", "EVENT_NAMES"}


def _event_constants() -> set[str]:
    """The names of the event constants exported by ``events.py``."""
    return {
        name
        for name in events.__all__
        if name.isupper() and name not in _NON_EVENTS
    }


def _load_generator():
    """Load the generator module by path (it is a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_gen_webui_types", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_gen_webui_types"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return _load_generator()


# ── the spec covers every constant ───────────────────────────────


def test_every_event_constant_has_a_spec() -> None:
    """A constant without a spec entry would never reach the frontend."""
    spec_consts = {spec.const for spec in events.EVENT_SPECS}
    missing = _event_constants() - spec_consts
    assert not missing, f"constants without an EVENT_SPECS entry: {sorted(missing)}"


def test_every_spec_has_a_constant() -> None:
    """A spec entry without a constant cannot be imported by the emitters."""
    for spec in events.EVENT_SPECS:
        assert hasattr(events, spec.const), f"{spec.const} is missing from events.py"
        assert isinstance(getattr(events, spec.const), str)


def test_spec_consts_are_exported() -> None:
    """Every spec constant is part of the public surface."""
    for spec in events.EVENT_SPECS:
        assert spec.const in events.__all__


def test_event_names_are_unique() -> None:
    """Two specs sharing a wire name would collapse in the frontend."""
    names = list(events.EVENT_NAMES)
    assert len(names) == len(set(names))


def test_spec_const_is_in_all() -> None:
    """``EVENT_NAMES`` resolves every spec, so the spec cannot be stale."""
    assert len(events.EVENT_NAMES) == len(events.EVENT_SPECS)


# ── the generated files are in sync ───────────────────────────────


def test_generated_ts_is_up_to_date(generator) -> None:
    """The checked-in TypeScript matches the spec."""
    expected = generator.render_ts(events)
    assert TS_FILE.exists(), "run: python scripts/gen_webui_types.py"
    assert TS_FILE.read_text(encoding="utf-8") == expected, (
        "ui/webui/src/generated/events.ts is stale — "
        "run: python scripts/gen_webui_types.py"
    )


def test_generated_schema_is_up_to_date(generator) -> None:
    """The checked-in JSON Schema matches the spec."""
    expected = generator.render_schema(events)
    assert SCHEMA_FILE.exists(), "run: python scripts/gen_webui_types.py"
    assert SCHEMA_FILE.read_text(encoding="utf-8") == expected


def test_generated_ts_covers_every_event() -> None:
    """Every wire name appears in the generated union."""
    ts = TS_FILE.read_text(encoding="utf-8")
    for name in events.EVENT_NAMES:
        assert f"'{name}'" in ts, f"{name} is missing from the generated types"


def test_generated_schema_is_valid_json() -> None:
    """The JSON Schema parses and has one variant per event."""
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    assert schema["$schema"].startswith("https://json-schema.org/")
    variants = schema["oneOf"]
    assert len(variants) == len(events.EVENT_SPECS)
    names = {v["properties"]["type"]["const"] for v in variants}
    assert names == set(events.EVENT_NAMES)


def test_generator_check_mode_passes(generator) -> None:
    """``--check`` is what CI runs; it must exit 0 on a clean tree."""
    assert generator.main(["--check"]) == 0


# ── there is only one vocabulary ──────────────────────────────────


def test_there_is_no_second_event_vocabulary() -> None:
    """The event vocabulary has exactly one home.

    The chat agent used to carry a second copy of the wire names in
    ``apps/chat/agent/unified/events.py``. That package is gone; the
    vocabulary lives in ``events.py`` alone.
    """
    import importlib

    with pytest.raises(ImportError):
        importlib.import_module("llmwikify.apps.chat.agent.unified")


def test_research_events_come_from_the_research_runner() -> None:
    """The research vocabulary has its own home, not a second copy."""
    assert research_runner.EVENT_REASONING == "reasoning"
    assert research_runner.EVENT_ACTION_ERROR == "action_error"
    assert research_runner.EVENT_OBSERVATION_ERROR == "observation_error"
    assert research_runner.EVENT_ROUND_COMPLETE == "round_complete"
    assert research_runner.EVENT_TIMEOUT == "timeout"
    assert research_runner.EVENT_PHASE == events.PHASE


def test_no_second_definition_of_the_wire_names() -> None:
    """The wire names are defined once, in ``events.py``.

    The drift this mechanism exists to prevent started with a second
    *vocabulary* — a module that assigned the wire names to its own
    constants. An ordinary string that happens to equal a wire name
    (``status == "done"``) is not a vocabulary; only a module-level
    constant assignment is.
    """
    package = Path(events.__file__).parent
    wire_names = set(events.EVENT_NAMES)
    offenders: list[str] = []

    for path in package.rglob("*.py"):
        if path.name == "events.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if not isinstance(node.value, ast.Constant):
                    continue
                value = node.value.value
                if isinstance(value, str) and value in wire_names:
                    offenders.append(
                        f"{path.relative_to(package)}: {target.id} = {value!r}"
                    )

    assert not offenders, (
        "wire names assigned outside events.py:\n  " + "\n  ".join(sorted(offenders))
    )
