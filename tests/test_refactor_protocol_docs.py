"""Tests for the refactor multi-agent protocol documents.

The protocol is only useful if the artifacts it documents actually satisfy
the validator. These tests pin that relationship:

1. Every stage the validator knows has a JSON example in the protocol doc,
   and that example passes the stage's own gate.
2. Every role the protocol references has an agent prompt file on disk, with
   the frontmatter the agent loader needs.

Without this, the doc and ``scripts/validate_handoff.py`` drift apart
silently — the doc keeps showing a passing example that the gate would
reject.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VALIDATOR = ROOT / "scripts" / "validate_handoff.py"
PROTOCOL = ROOT / "docs" / "designs" / "refactor-multi-agent-protocol.md"

AGENT_DIR = ROOT / ".claude" / "agents"

# Roles the protocol's role table promises.
ROLES = (
    "wikify-refactor-orchestrator",
    "wikify-refactor-recon",
    "wikify-refactor-architect",
    "wikify-refactor-implementer",
    "wikify-refactor-reviewer",
    "wikify-refactor-benchmarker",
    "wikify-refactor-reuse-auditor",
)


def _load_validator():
    """Import the validator as a module (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("validate_handoff", VALIDATOR)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _json_blocks(text: str) -> list[dict]:
    """Extract every ```json fenced block that parses as an object."""
    blocks = []
    for raw in re.findall(r"```json\n(.*?)```", text, re.DOTALL):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            blocks.append(parsed)
    return blocks


@pytest.fixture(scope="module")
def validator():
    return _load_validator()


@pytest.fixture(scope="module")
def protocol_blocks() -> list[dict]:
    return _json_blocks(PROTOCOL.read_text(encoding="utf-8"))


def test_protocol_doc_exists() -> None:
    assert PROTOCOL.is_file()


@pytest.mark.parametrize("stage", sorted(_load_validator().REQUIRED_FIELDS))
def test_protocol_doc_has_a_valid_example_for_every_stage(
    stage: str, validator, protocol_blocks: list[dict]
) -> None:
    """The documented example must satisfy the validator it documents."""
    required = set(validator.REQUIRED_FIELDS[stage])
    matching = [block for block in protocol_blocks if required <= set(block)]
    assert matching, f"protocol doc has no JSON example with fields {sorted(required)}"
    for block in matching:
        errors = validator.validate_document(stage, block)
        assert errors == [], f"{stage} example rejected by validator: {errors}"


def test_every_protocol_json_example_is_valid_for_some_stage(
    validator, protocol_blocks: list[dict]
) -> None:
    """No example in the doc may be a shape the validator would reject."""
    stages = list(validator.REQUIRED_FIELDS)
    for block in protocol_blocks:
        matched = [s for s in stages if set(validator.REQUIRED_FIELDS[s]) <= set(block)]
        assert matched, f"protocol doc example matches no stage: {sorted(block)}"
        for stage in matched:
            errors = validator.validate_document(stage, block)
            assert errors == [], f"{stage} example rejected: {errors}"


@pytest.mark.parametrize("role", ROLES)
def test_role_agent_file_exists_with_frontmatter(role: str) -> None:
    path = AGENT_DIR / f"{role}.md"
    assert path.is_file(), f"missing agent prompt: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{role}.md has no YAML frontmatter"
    header = text.split("---", 2)[1]
    for field in ("name:", "description:"):
        assert field in header, f"{role}.md frontmatter lacks {field}"
    assert f"name: {role}" in header, f"{role}.md frontmatter name mismatch"


@pytest.mark.parametrize("role", ROLES)
def test_role_agent_file_mentions_the_handoff_contract(role: str) -> None:
    """Each prompt must state where its artifact goes and how it is gated."""
    text = (AGENT_DIR / f"{role}.md").read_text(encoding="utf-8")
    assert "refactor-handoff" in text, f"{role}.md does not name the handoff directory"
    assert "validate_handoff" in text, f"{role}.md does not name the gate script"
