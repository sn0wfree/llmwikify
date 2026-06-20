"""Tests for skills/loader.py — Phase 11 frontmatter parsing.

Borrowed from nanobot v0.2.1 ``skills/loader.py`` design: tolerant
parse with warnings, no raises, back-compat with body-only SKILL.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from llmwikify.apps.chat.skills.loader import (
    SkillFrontmatter,
    SkillMarkdown,
    parse_skill_frontmatter,
)

# ── no-frontmatter back-compat ───────────────────────────────────


class TestNoFrontmatter:
    def test_empty_string(self) -> None:
        r = parse_skill_frontmatter("", fallback_name="empty_skill")
        assert r.frontmatter.name == "empty_skill"
        assert r.frontmatter.version == "0.1.0"
        assert r.frontmatter.author == "unknown"
        assert r.frontmatter.triggers == []
        assert r.frontmatter.allowed_tools == []
        assert r.frontmatter.tags == []
        assert r.frontmatter.license == ""
        assert r.frontmatter.requires_config is False
        assert r.frontmatter.warnings == []
        assert r.body == ""

    def test_body_only_markdown(self) -> None:
        raw = "# My Skill\n\nThis skill does X and Y."
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.name == "x"
        assert r.frontmatter.description == "Plugin skill: x"
        assert r.body == raw
        assert r.frontmatter.warnings == []

    def test_uses_fallback_name_when_missing(self) -> None:
        raw = "---\ndescription: only-desc\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="from_dir")
        assert r.frontmatter.name == "from_dir"
        assert r.frontmatter.description == "only-desc"
        assert r.frontmatter.warnings == []


# ── happy path ────────────────────────────────────────────────────


class TestHappyPath:
    def test_full_frontmatter(self) -> None:
        raw = (
            "---\n"
            "name: study\n"
            "description: study helper\n"
            "version: 1.2.0\n"
            "author: bob\n"
            "triggers:\n  - /a\n  - /b\n"
            "allowed-tools:\n  - read_file\n"
            "tags:\n  - edu\n  - research\n"
            "license: MIT\n"
            "requires-config: true\n"
            "---\n"
            "# body\n"
            "actual instructions\n"
        )
        r = parse_skill_frontmatter(raw, fallback_name="study")
        assert isinstance(r, SkillMarkdown)
        assert r.frontmatter.name == "study"
        assert r.frontmatter.description == "study helper"
        assert r.frontmatter.version == "1.2.0"
        assert r.frontmatter.author == "bob"
        assert r.frontmatter.triggers == ["/a", "/b"]
        assert r.frontmatter.allowed_tools == ["read_file"]
        assert r.frontmatter.tags == ["edu", "research"]
        assert r.frontmatter.license == "MIT"
        assert r.frontmatter.requires_config is True
        assert r.frontmatter.warnings == []
        assert r.body == "# body\nactual instructions"

    def test_minimal_frontmatter(self) -> None:
        raw = "---\nname: minimal\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="anyway")
        assert r.frontmatter.name == "minimal"
        # everything else defaults
        assert r.frontmatter.version == "0.1.0"
        assert r.frontmatter.author == "unknown"
        assert r.frontmatter.triggers == []
        assert r.frontmatter.warnings == []


# ── type coercion + warnings ──────────────────────────────────────


class TestCoercion:
    def test_comma_separated_triggers(self) -> None:
        raw = '---\nname: x\ntriggers: "/a, /b, /c"\n---\nbody'
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.triggers == ["/a", "/b", "/c"]
        assert any("triggers" in w for w in r.frontmatter.warnings)

    def test_non_string_in_list(self) -> None:
        raw = "---\nname: x\ntriggers: [1, 2, bad]\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.triggers == ["bad"]
        assert any("non-string" in w for w in r.frontmatter.warnings)

    def test_wrong_type_for_string_field(self) -> None:
        raw = "---\nname: 123\nversion: [1, 2]\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        # ``name`` cast through str() → "123"
        assert r.frontmatter.name == "123"
        # ``version`` default applied + warning
        assert r.frontmatter.version == "0.1.0"
        assert any("version" in w for w in r.frontmatter.warnings)

    def test_wrong_type_for_bool(self) -> None:
        raw = '---\nname: x\nrequires-config: "yes"\n---\nbody'
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.requires_config is False
        assert any("requires_config" in w for w in r.frontmatter.warnings)

    def test_frontmatter_is_a_list_not_mapping(self) -> None:
        raw = "---\n- a\n- b\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        # Falls back to defaults; warning recorded
        assert r.frontmatter.name == "x"
        assert any("not a mapping" in w for w in r.frontmatter.warnings)


# ── error / edge cases ───────────────────────────────────────────


class TestErrors:
    def test_yaml_error_does_not_raise(self) -> None:
        # mapping values not allowed here
        raw = "---\nname: : bad\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        # Falls back to fallback_name
        assert r.frontmatter.name == "x"
        assert any("YAML parse error" in w for w in r.frontmatter.warnings)
        # Body still extracted
        assert r.body == "body"

    def test_unclosed_frontmatter_treated_as_body_only(self) -> None:
        raw = "---\nname: x\nno closing delimiter here"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.name == "x"
        assert any("no closing ---" in w for w in r.frontmatter.warnings)
        # Body preserves the original (frontmatter is left as-is in body)
        assert "no closing delimiter" in r.body

    def test_empty_yaml_frontmatter(self) -> None:
        # ``---`` followed by ``---`` with only whitespace
        raw = "---\n\n---\nactual body"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.name == "x"
        assert r.frontmatter.warnings == []
        assert r.body == "actual body"

    def test_frontmatter_with_extra_unknown_keys_ignored(self) -> None:
        # Frontmatter schema is permissive — unknown keys are ignored
        raw = "---\nname: x\nfoo: bar\nbaz: 42\n---\nbody"
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.name == "x"
        assert r.frontmatter.warnings == []


# ── SkillFrontmatter.to_dict ─────────────────────────────────────


class TestToDict:
    def test_default_serialization(self) -> None:
        fm = SkillFrontmatter(name="x")
        d = fm.to_dict()
        assert d == {
            "name": "x",
            "description": "",
            "version": "0.1.0",
            "author": "unknown",
            "triggers": [],
            "allowed_tools": [],
            "tags": [],
            "license": "",
            "requires_config": False,
        }
        # warnings are intentionally not serialized (internal field)

    def test_serialized_dict_is_json_safe(self) -> None:
        import json

        fm = SkillFrontmatter(
            name="x",
            triggers=["/a"],
            allowed_tools=["read"],
        )
        json.dumps(fm.to_dict())  # does not raise


# ── source_path ──────────────────────────────────────────────────


class TestSourcePath:
    def test_source_path_stored_when_provided(self, tmp_path: Path) -> None:
        r = parse_skill_frontmatter(
            "body", fallback_name="x", source_path=tmp_path / "SKILL.md"
        )
        assert r.source_path == tmp_path / "SKILL.md"

    def test_source_path_defaults_to_empty_path(self) -> None:
        r = parse_skill_frontmatter("body", fallback_name="x")
        assert r.source_path == Path("")


# ── edge case: body containing ``---`` separator ────────────────


class TestBodyContainingDashes:
    def test_dashes_inside_body_preserved(self) -> None:
        # Only the FIRST ``\n---\n`` is the closing delimiter;
        # subsequent ``---`` in body stays put.
        raw = (
            "---\n"
            "name: x\n"
            "---\n"
            "section A\n\n---\n\nsection B"
        )
        r = parse_skill_frontmatter(raw, fallback_name="x")
        assert r.frontmatter.name == "x"
        assert r.body == "section A\n\n---\n\nsection B"


# ── Smoke: warnings are stable for known issues ────────────────


def test_warnings_does_not_double_count() -> None:
    """Calling the same parse twice should produce the same warnings
    (no global state, no accumulation)."""
    raw = "---\nname: x\ntriggers: 123\n---\nbody"
    r1 = parse_skill_frontmatter(raw, fallback_name="x")
    r2 = parse_skill_frontmatter(raw, fallback_name="x")
    assert r1.frontmatter.warnings == r2.frontmatter.warnings


@pytest.mark.parametrize(
    "raw,expected_warnings_empty",
    [
        ("---\nname: x\n---\nbody", True),
        ("---\ntriggers: 123\n---\nbody", False),
        ("---\nname: : bad\n---\nbody", False),
    ],
)
def test_warnings_param(
    raw: str, expected_warnings_empty: bool
) -> None:
    r = parse_skill_frontmatter(raw, fallback_name="x")
    assert (len(r.frontmatter.warnings) == 0) is expected_warnings_empty
