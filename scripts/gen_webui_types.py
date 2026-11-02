#!/usr/bin/env python3
"""Generate the WebUI SSE types from the backend event contract.

The chat SSE vocabulary has two ends: the backend constants in
``src/llmwikify/apps/chat/agent/events.py`` and the TypeScript union in
``ui/webui/src/api.ts``. They were written by hand on both sides and
drifted — the frontend knew 12 of the 17 events, and declared a
``duration_ms`` on ``confirmation_required`` that no backend emitter
sends.

This script makes the backend the single source:

* ``EVENT_SPECS`` (in ``events.py``) describes every event and its
  payload;
* this script renders it into ``ui/webui/src/generated/events.ts``;
* ``--check`` regenerates and diffs, so CI fails when the two sides
  disagree.

The backend module is loaded by file path (not imported as a package)
so the script does not pull in the whole ``llmwikify`` import graph.

Usage::

    python scripts/gen_webui_types.py           # write the files
    python scripts/gen_webui_types.py --check   # verify, exit 1 on drift
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parent.parent
EVENTS_PY = REPO_ROOT / "src" / "llmwikify" / "apps" / "chat" / "agent" / "events.py"
TS_OUT = REPO_ROOT / "ui" / "webui" / "src" / "generated" / "events.ts"
SCHEMA_OUT = REPO_ROOT / "docs" / "api" / "events.schema.json"

HEADER = """// AUTO-GENERATED FILE — do not edit by hand.
//
// Source of truth: src/llmwikify/apps/chat/agent/events.py (EVENT_SPECS)
// Regenerate:       python scripts/gen_webui_types.py
// Verify (CI):      python scripts/gen_webui_types.py --check
"""


def load_events() -> ModuleType:
    """Load ``events.py`` by path, without the package import graph."""
    name = "_llmwikify_chat_events"
    spec = importlib.util.spec_from_file_location(name, EVENTS_PY)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {EVENTS_PY}")
    module = importlib.util.module_from_spec(spec)
    # ``dataclasses`` looks the defining module up in ``sys.modules``,
    # so it must be registered before the body runs.
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _ts_member(wire_name: str, fields: tuple, extends: str | None) -> str:
    """One member of the TypeScript union."""
    if extends:
        return f"  | ({{ type: '{wire_name}' }} & {extends})"
    parts = [f"type: '{wire_name}'"]
    for f in fields:
        opt = "" if f.required else "?"
        parts.append(f"{f.name}{opt}: {f.ts_type}")
    return "  | { " + "; ".join(parts) + " }"


def render_ts(events: ModuleType) -> str:
    """The TypeScript module of the generated file."""
    lines = [HEADER, ""]
    extends = {s.extends for s in events.EVENT_SPECS if s.extends}
    if extends:
        names = ", ".join(sorted(extends))
        lines.append(f"import type {{ {names} }} from '../types/research';")
        lines.append("")

    lines.append("export type ChatStreamEvent =")
    for spec in events.EVENT_SPECS:
        wire = getattr(events, spec.const)
        lines.append(_ts_member(wire, spec.fields, spec.extends))
    lines[-1] += ";"
    lines.append("")

    lines.append("/** Every event type the backend can emit on the chat SSE stream. */")
    lines.append("export const CHAT_EVENT_NAMES = [")
    for spec in events.EVENT_SPECS:
        lines.append(f"  '{getattr(events, spec.const)}',")
    lines.append("] as const;")
    lines.append("")
    lines.append("export type ChatEventName = (typeof CHAT_EVENT_NAMES)[number];")
    lines.append("")
    return "\n".join(lines)


def render_schema(events: ModuleType) -> str:
    """The JSON Schema of the event stream, for non-TypeScript consumers."""
    variants = []
    for spec in events.EVENT_SPECS:
        wire = getattr(events, spec.const)
        props = {"type": {"const": wire}}
        required = ["type"]
        for f in spec.fields:
            props[f.name] = {"type": _json_type(f.ts_type)}
            if f.required:
                required.append(f.name)
        variant = {
            "title": spec.const,
            "properties": props,
            "required": required,
        }
        if spec.extends:
            variant["description"] = f"payload extends {spec.extends}"
        variants.append(variant)

    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://llmwikify.readthedocs.io/events.schema.json",
        "title": "llmwikify chat SSE events",
        "description": (
            "The chat SSE event stream. Generated from "
            "src/llmwikify/apps/chat/agent/events.py — do not edit by hand."
        ),
        "oneOf": variants,
    }
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def _json_type(ts_type: str) -> str:
    """The JSON Schema type of a TypeScript type name."""
    return {
        "string": "string",
        "number": "number",
        "boolean": "boolean",
        "unknown": "object",
        "Record<string, unknown>": "object",
    }.get(ts_type, "object")


def _write(path: Path, content: str, check: bool) -> bool:
    """Write or verify one file. Returns True when it is up to date."""
    if check:
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == content:
            print(f"ok   {path.relative_to(REPO_ROOT)}")
            return True
        print(f"DRIFT {path.relative_to(REPO_ROOT)}")
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT)}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the generated files are up to date (exit 1 on drift)",
    )
    args = parser.parse_args(argv)

    events = load_events()
    ok = _write(TS_OUT, render_ts(events), args.check)
    ok = _write(SCHEMA_OUT, render_schema(events), args.check) and ok

    if args.check and not ok:
        print(
            "\nThe generated files are out of date.\n"
            "Run: python scripts/gen_webui_types.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
