"""Verify the legacy adapters path is a 5-line deprecation shim.

Phase 1 #1 / C4 — collapse ``llmwikify.agent.backend.adapters``
to a thin re-export shim that emits a DeprecationWarning.

The shim:
- Re-exports ``StreamableLLMClient`` (literally the same class
  object, not a copy)
- Emits a DeprecationWarning on import with the new home + version
- Does NOT re-implement any logic (no chat/stream_chat/etc.)
- Is silenced for internal ``agent.backend`` package use (those
  files import from the new home directly)

The class identity check (``Legacy is New``) is the strongest
guarantee: if someone adds a parallel implementation back to
adapters.py, this test fails immediately.
"""

from __future__ import annotations

import warnings


def test_shim_reexports_streamable_llm_client():
    """adapters.StreamableLLMClient is the same class as llm.streamable.StreamableLLMClient."""
    from llmwikify.agent.backend.adapters import StreamableLLMClient as LegacyClient
    from llmwikify.llm.streamable import StreamableLLMClient as NewClient

    assert LegacyClient is NewClient


def test_shim_emits_deprecation_warning():
    """Importing the shim emits a DeprecationWarning pointing to the new home."""
    import importlib
    import sys

    # Force a fresh import — otherwise a previous import in the
    # same process will be cached and no warning will fire.
    if "llmwikify.agent.backend.adapters" in sys.modules:
        del sys.modules["llmwikify.agent.backend.adapters"]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from llmwikify.agent.backend.adapters import StreamableLLMClient  # noqa: F401

    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning)
    ]
    assert len(deprecations) == 1, f"expected 1 deprecation, got {len(deprecations)}"
    msg = str(deprecations[0].message)
    assert "llmwikify.llm.streamable" in msg, (
        f"shim warning must point to new home, got: {msg}"
    )
    assert "v0.33.0" in msg, f"shim warning must mention removal version, got: {msg}"


def test_shim_does_not_define_class_methods():
    """The shim does not have any of the actual method implementations.

    If a contributor accidentally re-adds the old class body to
    adapters.py, we want to know — the shim should be a pure
    re-export, not a parallel definition.
    """
    import inspect
    from llmwikify.agent.backend import adapters as shim

    src = inspect.getsource(shim)
    # No method definitions beyond module docstring + import + warning + __all__
    assert "def chat(" not in src
    assert "def stream_chat(" not in src
    assert "def astream_chat(" not in src
    assert "def achat(" not in src
    assert "def chat_with_tools(" not in src
    assert "def _default_base_url(" not in src
    assert "def _build_headers(" not in src


def test_shim_emits_warning_for_provider_registry_path():
    """The provider registry (xiaomi/minimax) was migrated to the new home.

    This test guards against re-introducing ``from ..adapters import``
    in the provider registry files.
    """
    from llmwikify.agent.backend.providers import registry
    import inspect

    src = inspect.getsource(registry)
    assert "from ..adapters" not in src, (
        "registry.py must not import from the deprecated adapters path"
    )
    assert "from llmwikify.llm.streamable" in src


def test_internal_agent_backend_import_does_not_fire_shim_warning():
    """Importing the agent.backend package (or its re-exports) does NOT fire
    the shim warning. The warning is reserved for direct legacy use.
    """
    import sys
    import importlib

    # Drop the shim from sys.modules so we can re-import fresh
    for mod_name in list(sys.modules):
        if "llmwikify.agent" in mod_name:
            del sys.modules[mod_name]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        # This is the internal re-export path
        from llmwikify.agent.backend import StreamableLLMClient  # noqa: F401
        # And the agent.backend package itself
        import llmwikify.agent.backend  # noqa: F401

    shim_msgs = [
        w for w in caught
        if issubclass(w.category, DeprecationWarning)
        and "llmwikify.llm.streamable" in str(w.message)
    ]
    assert shim_msgs == [], (
        f"shim warning fired for internal use, expected 0: "
        f"{[str(w.message) for w in shim_msgs]}"
    )


def test_shim_does_not_break_existing_chat_functionality():
    """A legacy import path still produces a working chat() method.

    This is the behavioral compatibility guarantee: the shim
    must be a transparent re-export, not a stub.
    """
    from llmwikify.agent.backend.adapters import StreamableLLMClient

    c = StreamableLLMClient(provider="openai", api_key="k", model="m")
    # Methods inherited via the LLMClient chain still exist
    assert callable(c.chat)
    assert callable(c.stream_chat)
    assert callable(c.astream_chat)
    assert callable(c.achat)
    assert callable(c.chat_with_tools)
    # Class still inherits from LLMClient
    from llmwikify.llm_client import LLMClient
    assert isinstance(c, LLMClient)
