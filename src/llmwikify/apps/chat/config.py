"""AutoResearch independent configuration.

v0.41: 默认值从 ``config_defaults.yaml`` 读取，代码中不再硬编码。
mutable/immutable 分类用于控制 API/UI 暴露范围。

Defines the 6-step framework configuration, self-loop settings,
and retry parameters.

Per Sprint C4 of the 4-layer refactor, the 31 keys shared with
``apps/research/config.py`` now live in
:mod:`llmwikify.apps.research.base.BaseResearchConfig`. The
30+ keys specific to the 6-step framework (clarify / evidence /
structure / strict-exit / retry managers / per-prompt
``llm_params``) are kept in this module as ``_SIX_STEP_EXTRAS``
and merged with the base defaults at module load.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from llmwikify.apps.research.base import BaseResearchConfig

_DEFAULTS_FILE = Path(__file__).parent / "config_defaults.yaml"


@lru_cache(maxsize=1)
def _load_defaults() -> dict[str, Any]:
    """Load chat config defaults from YAML.

    Returns:
        dict with two keys: 'mutable' and 'immutable', each containing
        the default config values.
    """
    if not _DEFAULTS_FILE.exists():
        return {"mutable": {}, "immutable": {}}
    import yaml

    try:
        data = yaml.safe_load(_DEFAULTS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"mutable": {}, "immutable": {}}
        return {
            "mutable": data.get("mutable", {}),
            "immutable": data.get("immutable", {}),
        }
    except Exception:
        return {"mutable": {}, "immutable": {}}


def get_mutable_defaults() -> dict[str, Any]:
    """Get mutable defaults (exposed via API/UI)."""
    return dict(_load_defaults().get("mutable", {}))


def get_immutable_defaults() -> dict[str, Any]:
    """Get immutable defaults (debug only, not exposed via API/UI)."""
    return dict(_load_defaults().get("immutable", {}))


def get_all_defaults() -> dict[str, Any]:
    """Get all defaults (mutable + immutable merged)."""
    defaults = _load_defaults()
    merged: dict[str, Any] = {}
    merged.update(defaults.get("immutable", {}))
    merged.update(defaults.get("mutable", {}))
    return merged


# Backward-compat: keep _SIX_STEP_EXTRAS but load from YAML
_SIX_STEP_EXTRAS: dict[str, Any] = get_all_defaults()


DEFAULT_SIX_STEP_CONFIG: dict[str, Any] = {
    **BaseResearchConfig.DEFAULT,
    **_SIX_STEP_EXTRAS,
}


def merge_six_step_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge user overrides on top of the 6-step defaults.

    Unlike ``merge_research_config``, the self-loop and
    framework check switches are kept on (no off path) per the
    v3 design decision.
    """
    config = dict(DEFAULT_SIX_STEP_CONFIG)
    if overrides:
        for k, v in overrides.items():
            if k in config and v is not None:
                config[k] = v
    return config


# Backward-compat alias; the engine and tests still reference the old name.
merge_research_config = merge_six_step_config


__all__ = [
    "DEFAULT_SIX_STEP_CONFIG",
    "merge_six_step_config",
    "merge_research_config",
    "get_mutable_defaults",
    "get_immutable_defaults",
    "get_all_defaults",
]
