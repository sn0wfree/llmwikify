"""Consistency checks for the parameter registry (foundation/params.py).

The registry is meant to become the single source of truth for tunable
defaults. Until every group has landed, this module checks two things:

1. **No drift** — where a key exists both in the registry and in one of the
   legacy default files, the values must be identical. This is the
   direction that causes bugs (two sources disagreeing).
2. **Coverage ratchet** — the number of legacy keys already mirrored in
   the registry must not go down. That keeps the migration monotonic.

Run ``python -m pytest tests/test_foundation_params.py -q`` to see the
current coverage numbers.
"""

from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from llmwikify.foundation import config as config_mod
from llmwikify.foundation.params import PARAMS, param_default

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_JSON = REPO_ROOT / "src/llmwikify/foundation/templates/llmwikify.default.json"
RESEARCH_YAML = REPO_ROOT / "src/llmwikify/apps/research/config_defaults.yaml"
SIX_STEP_YAML = REPO_ROOT / "src/llmwikify/apps/research/six_step_config_defaults.yaml"

# Coverage ratchet: legacy keys mirrored in the registry, per source.
# Raise these as groups land; never lower them.
COVERAGE_BASELINE = {
    "template_json": 38,
    "research_yaml": 7,
    "six_step_yaml": 9,
}


def _flatten(data: Any, prefix: str = "") -> dict[str, Any]:
    """Flatten a nested dict into dotted keys."""
    out: dict[str, Any] = {}
    if not isinstance(data, dict):
        return out
    for key, value in data.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, f"{dotted}."))
        else:
            out[dotted] = value
    return out


def _legacy_default_config() -> dict[str, Any]:
    """The DEFAULT_CONFIG literal as it was before the registry existed."""
    src = subprocess.run(
        ["git", "show", "HEAD:src/llmwikify/foundation/config.py"],
        capture_output=True,
        check=True,
    ).stdout.decode("utf-8")
    for node in ast.parse(src).body:
        if (
            isinstance(node, ast.AnnAssign)
            and getattr(node.target, "id", None) == "DEFAULT_CONFIG"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError("DEFAULT_CONFIG not found in HEAD")


# ── No drift ───────────────────────────────────────────────────────


def test_registry_matches_template_json() -> None:
    """Keys present in both the registry and the template JSON agree."""
    template = json.loads(TEMPLATE_JSON.read_text(encoding="utf-8"))
    flat = _flatten(template)
    mismatches = [
        (key, flat[key], param_default(key))
        for key in flat
        if key in PARAMS and flat[key] != param_default(key)
    ]
    assert not mismatches, f"registry disagrees with template JSON: {mismatches}"


def test_registry_matches_research_yaml() -> None:
    """Keys present in both the registry and research YAML agree.

    Only the ``mutable`` section is compared: it maps 1:1 onto the
    global ``research_mutable`` section. The ``immutable`` section shares
    names with the global ``research`` section but carries different
    values — see the clash test below.
    """
    data = yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8")) or {}
    mismatches: list[tuple[str, Any, Any]] = []
    for key, value in (data.get("mutable") or {}).items():
        full = "research_mutable." + key
        if full in PARAMS and value != param_default(full):
            mismatches.append((full, value, param_default(full)))
    assert not mismatches, f"registry disagrees with research YAML: {mismatches}"


@pytest.mark.xfail(
    strict=False,
    reason="known clash — global research section vs research-YAML immutable "
    "section share names with different defaults; prefixes not separated yet",
)
def test_known_clash_research_section_defaults() -> None:
    """Documented clash: global ``research`` vs research-YAML ``immutable``.

    Both define ``search_provider`` / ``minimax_api_key`` /
    ``minimax_api_host`` with different defaults (``""`` vs ``null``,
    ``""`` vs a provider URL). The YAML comment says ``null`` means
    "fall back to llm.api_key" — so they are different concepts that
    happen to share names, and the registry needs distinct prefixes.

    Expected to flip to XPASS once the prefixes are separated.
    """
    data = yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8")) or {}
    immutable = data.get("immutable") or {}
    clashes = [
        key
        for key in ("search_provider", "minimax_api_key", "minimax_api_host")
        if key in immutable and immutable[key] != param_default("research." + key)
    ]
    assert not clashes, f"research section clash resolved for: {clashes}"


def test_registry_matches_six_step_yaml() -> None:
    """Keys present in both the registry and the six-step YAML agree."""
    data = yaml.safe_load(SIX_STEP_YAML.read_text(encoding="utf-8")) or {}
    mismatches: list[tuple[str, Any, Any]] = []
    for key, value in (data.get("mutable") or {}).items():
        full = "chat_mutable." + key
        if full in PARAMS and value != param_default(full):
            mismatches.append((full, value, param_default(full)))
    assert not mismatches, f"registry disagrees with six-step YAML: {mismatches}"


def test_embedded_default_config_unchanged() -> None:
    """DEFAULT_CONFIG is still exactly what it was before the registry.

    It is now *derived* from the registry, so this pins the derivation
    to the hand-written literal it replaced.
    """
    assert config_mod.DEFAULT_CONFIG == _legacy_default_config()


# ── Coverage ratchet ───────────────────────────────────────────────


def _covered_keys(flat: dict[str, Any], prefix_map: dict[str, str]) -> set[str]:
    """Registry keys that also exist in a legacy source."""
    covered = set()
    for legacy_key in flat:
        for legacy_prefix, registry_prefix in prefix_map.items():
            if legacy_key.startswith(legacy_prefix):
                candidate = registry_prefix + legacy_key[len(legacy_prefix) :]
                if candidate in PARAMS:
                    covered.add(candidate)
                break
    return covered


def test_coverage_does_not_regress() -> None:
    """The registry keeps mirroring at least as many legacy keys as before."""
    template = json.loads(TEMPLATE_JSON.read_text(encoding="utf-8"))
    template_flat = _flatten(template)
    template_covered = {
        key for key in template_flat if key in PARAMS
    }
    assert len(template_covered) >= COVERAGE_BASELINE["template_json"], (
        f"template JSON coverage dropped: "
        f"{len(template_covered)} < {COVERAGE_BASELINE['template_json']}"
    )

    research = yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8")) or {}
    research_covered = {
        "research_mutable." + key
        for key in (research.get("mutable") or {})
        if "research_mutable." + key in PARAMS
    }
    assert len(research_covered) >= COVERAGE_BASELINE["research_yaml"], (
        f"research YAML coverage dropped: "
        f"{len(research_covered)} < {COVERAGE_BASELINE['research_yaml']}"
    )

    six_step = yaml.safe_load(SIX_STEP_YAML.read_text(encoding="utf-8")) or {}
    six_covered = {
        "chat_mutable." + key
        for key in (six_step.get("mutable") or {})
        if "chat_mutable." + key in PARAMS
    }
    assert len(six_covered) >= COVERAGE_BASELINE["six_step_yaml"], (
        f"six-step YAML coverage dropped: "
        f"{len(six_covered)} < {COVERAGE_BASELINE['six_step_yaml']}"
    )


# ── Registry sanity ────────────────────────────────────────────────


def test_registry_keys_are_well_formed() -> None:
    """No empty segments, no trailing dots, lowercase dotted paths."""
    for key in PARAMS:
        assert key, "empty parameter key"
        assert not key.startswith(".") and not key.endswith("."), key
        assert ".." not in key, key
        for part in key.split("."):
            assert part, f"empty segment in {key!r}"
            assert part == part.lower(), f"non-lowercase segment in {key!r}"


def test_get_param_resolution_order(tmp_path: Path) -> None:
    """wiki scope > global scope > registry default."""
    from llmwikify.foundation.config import Config

    cfg = Config()
    cfg._cache = None
    cfg._wiki_cache.clear()

    # registry default
    assert cfg.get_param("llm.timeout") == param_default("llm.timeout")

    # global scope wins over the registry
    cfg._cache = {"llm": {"timeout": 42}}
    assert cfg.get_param("llm.timeout") == 42

    # wiki scope wins over global
    (tmp_path / ".wiki-config.yaml").write_text(
        "llm:\n  timeout: 7\n", encoding="utf-8"
    )
    cfg._wiki_cache.clear()
    assert cfg.get_param("llm.timeout", wiki_root=tmp_path) == 7
    assert cfg.get_param("llm.timeout") == 42

    # unknown key resolves to None rather than raising
    assert cfg.get_param("llm.does_not_exist") is None

    cfg._cache = None
    cfg._wiki_cache.clear()


@pytest.mark.parametrize(
    "key",
    ["llm.timeout", "search.qmd.port", "wikis.discovery.scan_depth"],
)
def test_get_param_reads_nested_paths(key: str) -> None:
    """Dotted keys resolve through nested config sections."""
    from llmwikify.foundation.config import Config

    cfg = Config()
    cfg._cache = None
    assert cfg.get_param(key) == param_default(key)
    cfg._cache = None
