"""Back-compat shim for ``llmwikify.apps.chat.research_engine.engine``.

v0.40 moved the canonical implementation to
``llmwikify.apps.research.engine``. This shim re-exports from the
canonical module so legacy imports
``from llmwikify.apps.chat.research_engine.engine import ResearchEngine``
return the SAME class object as the canonical path.

Uses lazy attribute access (PEP 562) to avoid circular imports:
``research_agent.py`` imports this shim while ``apps.research.engine``
is mid-loading, and we must not re-trigger that load.
"""

_LAZY_ATTRS = {
    "ResearchEngine": ("llmwikify.apps.research.engine", "ResearchEngine"),
}


def __getattr__(name: str):
    if name in _LAZY_ATTRS:
        from importlib import import_module

        mod_path, attr = _LAZY_ATTRS[name]
        mod = import_module(mod_path)
        value = getattr(mod, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = list(_LAZY_ATTRS.keys())