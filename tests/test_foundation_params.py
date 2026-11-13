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

import importlib.util
import json
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
    "research_immutable": 26,
    "six_step_immutable": 52,
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


def _expected_default_config() -> dict[str, Any]:
    """The hand-written DEFAULT_CONFIG literal, frozen as a snapshot.

    ``DEFAULT_CONFIG`` is now *derived* from the registry. This snapshot
    pins the derivation to the values the hand-written literal had before
    the registry existed — so a registry edit that would silently change
    a default fails here instead of shipping.
    """
    return {
        "directories": {"raw": "raw", "wiki": "wiki"},
        "database": {"name": ".llmwikify.db"},
        "reference_index": {"name": "reference_index.json", "auto_export": True},
        "orphan_detection": {
            "default_exclude_patterns": [],
            "exclude_frontmatter": [],
            "archive_directories": [],
        },
        "performance": {"batch_size": 100},
        "llm": {
            "enabled": False,
            "provider": None,
            "model": None,
            "base_url": None,
            "api_key": "",
            "timeout": 120,
            "context_window": None,
            "budget_on_exceed": "warn",
        },
        "mcp": {
            "name": None,
            "host": "127.0.0.1",
            "port": 8765,
            "transport": "stdio",
        },
        "web": {"port": 8766, "host": "127.0.0.1"},
        "prompts": {"custom_dir": None},
        "search": {
            "backend": "fts5",
            "qmd": {"host": "127.0.0.1", "port": 8181, "auto_start": False},
        },
        "wikis": {
            "default": None,
            "local": [],
            "remote": [],
            "discovery": {
                "enabled": False,
                "scan_paths": ["."],
                "scan_depth": 2,
                "exclude_patterns": [
                    "node_modules",
                    ".git",
                    "__pycache__",
                    ".venv",
                    "venv",
                ],
                "auto_register": False,
                "scan_interval": 3600,
            },
        },
    }


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


def _flatten_immutable(section: Any, prefix: str) -> dict[str, Any]:
    """Flatten an immutable section to ``{registry_key: value}``."""
    out: dict[str, Any] = {}
    if not isinstance(section, dict):
        return out

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict) and node:
            for k, v in node.items():
                walk(v, f"{path}.{k}" if path else str(k))
        else:
            out[path] = node

    walk(section, prefix)
    return out


def test_registry_matches_research_immutable_yaml() -> None:
    """research YAML ``immutable`` agrees with ``research_immutable.*``."""
    data = yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8")) or {}
    expected = _flatten_immutable(data.get("immutable"), "research_immutable")
    mismatches = [
        (key, value, param_default(key))
        for key, value in expected.items()
        if key in PARAMS and value != param_default(key)
    ]
    missing = [key for key in expected if key not in PARAMS]
    assert not missing, f"research immutable keys missing from registry: {missing}"
    assert not mismatches, f"registry disagrees with research immutable: {mismatches}"


def test_registry_matches_six_step_immutable_yaml() -> None:
    """six-step YAML ``immutable`` agrees with ``chat_immutable.*``."""
    data = yaml.safe_load(SIX_STEP_YAML.read_text(encoding="utf-8")) or {}
    expected = _flatten_immutable(data.get("immutable"), "chat_immutable")
    mismatches = [
        (key, value, param_default(key))
        for key, value in expected.items()
        if key in PARAMS and value != param_default(key)
    ]
    missing = [key for key in expected if key not in PARAMS]
    assert not missing, f"six-step immutable keys missing from registry: {missing}"
    assert not mismatches, f"registry disagrees with six-step immutable: {mismatches}"


def test_embedded_default_config_unchanged() -> None:
    """DEFAULT_CONFIG is still exactly what it was before the registry.

    It is now *derived* from the registry, so this pins the derivation
    to a frozen snapshot of the hand-written literal it replaced.
    """
    assert config_mod.DEFAULT_CONFIG == _expected_default_config()


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

    # Immutable sections (flattened nested keys, e.g. llm_params.*)
    res_imm = _flatten_immutable(
        (yaml.safe_load(RESEARCH_YAML.read_text(encoding="utf-8")) or {}).get(
            "immutable"
        ),
        "research_immutable",
    )
    res_imm_covered = {k for k in res_imm if k in PARAMS}
    assert len(res_imm_covered) >= COVERAGE_BASELINE["research_immutable"], (
        f"research immutable coverage dropped: "
        f"{len(res_imm_covered)} < {COVERAGE_BASELINE['research_immutable']}"
    )

    six_imm = _flatten_immutable(
        (yaml.safe_load(SIX_STEP_YAML.read_text(encoding="utf-8")) or {}).get(
            "immutable"
        ),
        "chat_immutable",
    )
    six_imm_covered = {k for k in six_imm if k in PARAMS}
    assert len(six_imm_covered) >= COVERAGE_BASELINE["six_step_immutable"], (
        f"six-step immutable coverage dropped: "
        f"{len(six_imm_covered)} < {COVERAGE_BASELINE['six_step_immutable']}"
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


# ── Generated type stub (option C) ─────────────────────────────────


def _load_stub_builder() -> Any:
    """Import scripts/gen_params_stub.py by path (scripts/ is not on sys.path)."""
    script = REPO_ROOT / "scripts" / "gen_params_stub.py"
    spec = importlib.util.spec_from_file_location("gen_params_stub", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generated_stub_is_current() -> None:
    """params.pyi on disk matches what the generator would emit now.

    This is the drift gate for option C: the registry is the source of
    truth, the stub is derived, and this test fails when they diverge.
    Regenerate with ``python scripts/gen_params_stub.py``.
    """
    module = _load_stub_builder()
    expected = module.build()
    stub_path = REPO_ROOT / "src" / "llmwikify" / "foundation" / "params.pyi"
    actual = stub_path.read_text(encoding="utf-8")
    assert actual == expected, (
        "params.pyi is stale — run: python scripts/gen_params_stub.py"
    )


def test_stub_declares_every_runtime_export() -> None:
    """A sibling ``.pyi`` *shadows* the runtime ``.py`` for mypy.

    If the stub omits a name the runtime exports, every caller of that
    name fails type checking even though the code is correct. This test
    pins the stub's declared names against ``params.__all__`` + ``PARAMS``.
    """
    import llmwikify.foundation.params as params_mod

    stub_path = REPO_ROOT / "src" / "llmwikify" / "foundation" / "params.pyi"
    text = stub_path.read_text(encoding="utf-8")

    required = set(params_mod.__all__) | {"PARAMS"}
    missing = sorted(
        name
        for name in required
        # `class X:` or `def x(` or `X: ` at line start
        if not any(
            line.startswith(f"class {name}:")
            or line.startswith(f"def {name}(")
            or line.startswith(f"{name}:")
            for line in text.splitlines()
        )
    )
    assert not missing, f"params.pyi is missing declarations: {missing}"


def test_nested_view_attribute_access() -> None:
    """Runtime views expose nested attribute access derived from the keys."""
    from llmwikify.foundation.params import (
        AppsParams,
        FoundationParams,
        InterfacesParams,
        KernelParams,
        param_default,
    )

    kernel = KernelParams()
    assert kernel.wiki.similarity_threshold == param_default(
        "wiki.similarity_threshold"
    )
    assert kernel.search.qmd.port == param_default("search.qmd.port")
    assert kernel.directories.raw == param_default("directories.raw")

    foundation = FoundationParams()
    assert foundation.llm.timeout == param_default("llm.timeout")

    apps = AppsParams()
    assert apps.chat_mutable.max_chat_rounds == param_default(
        "chat_mutable.max_chat_rounds"
    )

    interfaces = InterfacesParams()
    assert interfaces.mcp.port == param_default("mcp.port")


def test_layer_views_expose_only_their_layer() -> None:
    """Each view resolves only the keys owned by its layer."""
    from llmwikify.foundation.params import (
        AppsParams,
        FoundationParams,
        InterfacesParams,
        KernelParams,
    )

    for cls in (FoundationParams, KernelParams, AppsParams, InterfacesParams):
        view = cls()
        for key in cls.layer_keys():
            spec = PARAMS[key]
            assert spec.layer == cls.LAYER, key
        # Cross-layer keys must not be reachable on this view.
        foreign = [k for k, p in PARAMS.items() if p.layer != cls.LAYER]
        assert foreign, "registry should have keys in more than one layer"
        # Sanity: a known foreign key's first segment is absent unless
        # another key in this layer shares that section name.
        for key in foreign:
            top = key.split(".")[0]
            own_tops = {k.split(".")[0] for k in cls.layer_keys()}
            if top not in own_tops:
                assert not hasattr(view, top), f"{cls.__name__}.{top}"


def test_nest_rejects_leaf_section_collision() -> None:
    """A key that is both a leaf and a section prefix is a registry bug."""
    from llmwikify.foundation.params import nest

    with pytest.raises(ValueError, match="collides"):
        nest({"llm": 1, "llm.timeout": 2})


# ── ParamRegistry (step 4) ────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_config_singleton() -> Any:
    """Reset the ``Config`` singleton's caches around every test.

    ``Config`` is a process-wide singleton (``__new__`` returns the same
    instance), so a test that writes ``cfg._cache`` would otherwise leak
    into the next one — the "hidden global singleton makes tests
    order-dependent" failure mode the design research called out.
    """
    from llmwikify.foundation.config import Config

    cfg = Config()
    cfg._cache = None
    cfg._wiki_cache.clear()
    yield cfg
    cfg._cache = None
    cfg._wiki_cache.clear()


class TestParamRegistry:
    """Resolution chain, provenance, layer views, reload + on_change."""

    def _fresh(self, tmp_path: Path) -> Any:
        from llmwikify.foundation.config import ParamRegistry

        return ParamRegistry(wiki_root=tmp_path)

    def test_resolution_chain_wiki_over_global_over_registry(self, tmp_path: Path) -> None:

        reg = self._fresh(tmp_path)
        cfg = reg._config

        # registry default
        assert reg.get("llm.timeout") == param_default("llm.timeout")
        assert reg.source("llm.timeout") == "registry"

        # global scope wins — the registry caches its resolution, so a
        # changed source file only takes effect after reload()
        cfg._cache = {"llm": {"timeout": 42}}
        assert reg.reload() == {"llm.timeout"}
        assert reg.get("llm.timeout") == 42
        assert reg.source("llm.timeout") == "global"

        # wiki scope wins over global
        (tmp_path / ".wiki-config.yaml").write_text(
            "llm:\n  timeout: 7\n", encoding="utf-8"
        )
        cfg._wiki_cache.clear()
        assert reg.reload() == {"llm.timeout"}
        assert reg.get("llm.timeout") == 7
        assert reg.source("llm.timeout") == "wiki"

        cfg._cache = None
        cfg._wiki_cache.clear()

    def test_env_scope_wins_over_everything(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Declare a param with an env var, inject it into the registry.
        from llmwikify.foundation import params as params_mod
        from llmwikify.foundation.params import Param

        original = dict(params_mod.PARAMS)
        try:
            params_mod.PARAMS["llm.timeout"] = Param(
                120, int, "timeout", "foundation", env="LLM_TEST_TIMEOUT"
            )
            monkeypatch.setenv("LLM_TEST_TIMEOUT", "9")
            reg = self._fresh(tmp_path)
            assert reg.get("llm.timeout") == 9
            assert reg.source("llm.timeout") == "env"
        finally:
            params_mod.PARAMS.clear()
            params_mod.PARAMS.update(original)

    def test_env_coercion(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from llmwikify.foundation import params as params_mod
        from llmwikify.foundation.params import Param

        original = dict(params_mod.PARAMS)
        try:
            params_mod.PARAMS["llm.timeout"] = Param(
                120, int, "timeout", "foundation", env="LLM_TEST_TIMEOUT"
            )
            monkeypatch.setenv("LLM_TEST_TIMEOUT", "8765")
            reg = self._fresh(tmp_path)
            assert reg.get("llm.timeout") == 8765  # str → int
        finally:
            params_mod.PARAMS.clear()
            params_mod.PARAMS.update(original)

    def test_for_layer_filters_by_layer(self, tmp_path: Path) -> None:
        reg = self._fresh(tmp_path)
        kernel = reg.for_layer("kernel")
        assert "wiki.similarity_threshold" in kernel
        assert "llm.timeout" not in kernel
        assert "mcp.port" not in kernel

    def test_layer_views(self, tmp_path: Path) -> None:
        reg = self._fresh(tmp_path)
        assert reg.foundation().llm.timeout == param_default("llm.timeout")
        assert reg.kernel().wiki.similarity_threshold == param_default(
            "wiki.similarity_threshold"
        )
        assert reg.apps().chat_mutable.max_chat_rounds == param_default(
            "chat_mutable.max_chat_rounds"
        )
        assert reg.interfaces().mcp.port == param_default("mcp.port")

    def test_reload_notifies_listeners_with_changed_keys(self, tmp_path: Path) -> None:

        reg = self._fresh(tmp_path)
        cfg = reg._config
        cfg._cache = {"llm": {"timeout": 42}}
        reg.resolve()

        seen: list[set[str]] = []
        unsub = reg.on_change(seen.append)

        # Change the global config, then reload.
        cfg._cache = {"llm": {"timeout": 99}}
        changed = reg.reload()
        assert changed == {"llm.timeout"}
        assert seen == [{"llm.timeout"}]

        # Unsubscribed listener is not called again.
        cfg._cache = {"llm": {"timeout": 100}}
        unsub()
        reg.reload()
        assert seen == [{"llm.timeout"}]

        cfg._cache = None

    def test_reload_returns_empty_on_first_call(self, tmp_path: Path) -> None:
        reg = self._fresh(tmp_path)
        assert reg.reload() == set()  # no previous snapshot to diff

    def test_registry_for_caches_per_wiki_root(self, tmp_path: Path) -> None:
        from llmwikify.foundation.config import registry_for

        a = registry_for(tmp_path)
        b = registry_for(tmp_path)
        assert a is b
        other = registry_for(tmp_path / "other")
        assert other is not a


# ── alias_of (iii): canonical key + deprecated aliases ────────────


class TestAliasOf:
    """D5 (iii): one concept, one value; aliases resolve at load time."""

    def test_canonical_key_follows_alias_chain(self) -> None:
        from llmwikify.foundation.params import canonical_key

        assert canonical_key("chat_mutable.max_chat_rounds") == "agent.max_iterations"
        assert canonical_key("agent.max_iterations") == "agent.max_iterations"
        assert canonical_key("llm.timeout") == "llm.timeout"  # no alias
        assert canonical_key("does.not.exist") == "does.not.exist"

    def test_aliases_of_lists_the_family(self) -> None:
        from llmwikify.foundation.params import aliases_of

        assert aliases_of("agent.max_iterations") == [
            "chat_mutable.max_chat_rounds"
        ]
        assert aliases_of("llm.timeout") == []

    def test_param_default_resolves_through_alias(self) -> None:
        """An alias's default lives on the canonical (D5 iii)."""
        assert param_default("chat_mutable.max_chat_rounds") == param_default(
            "agent.max_iterations"
        )
        assert param_default("agent.max_iterations") == 4

    def test_section_defaults_still_yield_alias_value(self) -> None:
        """config-file shape keeps the alias's effective default (snapshot)."""
        from llmwikify.foundation.params import section_defaults

        chat = section_defaults("chat_mutable")
        assert chat["max_chat_rounds"] == 4

    def test_registry_alias_setting_flows_to_canonical(self, tmp_path: Path) -> None:
        """A deprecated name the user still sets reaches the canonical."""
        from llmwikify.foundation.config import ParamRegistry

        reg = ParamRegistry(wiki_root=tmp_path)
        cfg = reg._config
        reg.resolve()  # establish the snapshot reload() diffs against
        cfg._cache = {"chat_mutable": {"max_chat_rounds": 10}}
        assert reg.reload() >= {"agent.max_iterations", "chat_mutable.max_chat_rounds"}
        assert reg.get("agent.max_iterations") == 10
        assert reg.get("chat_mutable.max_chat_rounds") == 10
        assert reg.source("agent.max_iterations") == "global"
        cfg._cache = None

    def test_canonical_setting_wins_over_alias(self, tmp_path: Path) -> None:
        """When both are set, the canonical wins — not last-writer-wins."""
        from llmwikify.foundation.config import ParamRegistry

        reg = ParamRegistry(wiki_root=tmp_path)
        cfg = reg._config
        cfg._cache = {
            "agent": {"max_iterations": 20},
            "chat_mutable": {"max_chat_rounds": 10},
        }
        reg.resolve()
        assert reg.get("agent.max_iterations") == 20
        assert reg.get("chat_mutable.max_chat_rounds") == 20
        cfg._cache = None

    def test_registry_default_when_neither_set(self, tmp_path: Path) -> None:
        from llmwikify.foundation.config import ParamRegistry

        reg = ParamRegistry(wiki_root=tmp_path)
        reg.resolve()
        assert reg.get("agent.max_iterations") == 4
        assert reg.source("agent.max_iterations") == "registry"

    def test_alias_cycle_is_rejected(self) -> None:
        from llmwikify.foundation import params as params_mod
        from llmwikify.foundation.params import Param, canonical_key

        original = dict(params_mod.PARAMS)
        try:
            params_mod.PARAMS["a.b"] = Param(1, int, "", "apps", alias_of="c.d")
            params_mod.PARAMS["c.d"] = Param(2, int, "", "apps", alias_of="a.b")
            with pytest.raises(ValueError, match="cycle"):
                canonical_key("a.b")
        finally:
            params_mod.PARAMS.clear()
            params_mod.PARAMS.update(original)
