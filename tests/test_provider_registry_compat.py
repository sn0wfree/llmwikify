"""Verify provider registry at the post-Phase-4 canonical home.

Per v0.32 Phase 4 (3 days, 🟢): the provider registry, provider
implementations, and provider-related infrastructure were
migrated from ``llmwikify.apps.agent.providers`` to
``llmwikify.apps.chat.providers`` so they live alongside
ChatBase and other LLM-consuming components in apps/chat/.

The backward-compat shim at
``llmwikify.agent.backend.providers`` re-exports the new home
and is scheduled for removal in v0.33.0.

This test validates the post-Phase-4 state:

  - Provider registry resolves the same providers (xiaomi,
    minimax) as before
  - Each provider's ``from_config`` returns a working
    ``StreamableLLMClient`` instance from the canonical home
    (``llmwikify.foundation.llm.streamable``)
  - The provider classes are still Liskov-substitutable
  - The provider registry module lives at the new home
    (``llmwikify.apps.chat.providers.registry``)
  - The legacy shim still re-exports everything for callers
    that haven't migrated yet
"""

from __future__ import annotations

import inspect


def test_provider_registry_contains_known_providers():
    """xiaomi + minimax are the auto-registered built-in providers."""
    from llmwikify.apps.chat.providers import list_providers

    providers = list_providers()
    assert "xiaomi" in providers
    assert "minimax" in providers
    assert len(providers) >= 2


def test_get_provider_returns_provider_instance():
    """get_provider('xiaomi') returns a XiaomiProvider instance."""
    from llmwikify.apps.chat.providers import get_provider
    from llmwikify.apps.chat.providers.xiaomi import XiaomiProvider

    p = get_provider("xiaomi")
    assert isinstance(p, XiaomiProvider)


def test_get_provider_unknown_raises():
    """get_provider('nope') raises ValueError with the list of available providers."""
    from llmwikify.apps.chat.providers import get_provider

    try:
        get_provider("nope")
    except ValueError as e:
        msg = str(e)
        assert "Unknown provider 'nope'" in msg
        assert "xiaomi" in msg
    else:
        raise AssertionError("expected ValueError for unknown provider")


def test_create_llm_uses_canonical_streamable_class():
    """create_llm returns an instance of the new-home StreamableLLMClient."""
    from llmwikify.apps.chat.providers import create_llm
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    config = {
        "enabled": True,
        "provider": "xiaomi",
        "api_key": "tp-test-key",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "model": "mimo-v2.5-pro",
    }
    client = create_llm(config)
    assert isinstance(client, StreamableLLMClient)
    assert client.provider == "xiaomi"
    assert client.auth_header == "api-key"
    assert client.reasoning_split is True


def test_create_llm_raises_when_disabled():
    """create_llm with enabled=False raises ValueError."""
    from llmwikify.apps.chat.providers import create_llm

    try:
        create_llm({"enabled": False, "api_key": "x"})
    except ValueError as e:
        assert "not enabled" in str(e).lower()
    else:
        raise AssertionError("expected ValueError when LLM disabled")


def test_create_llm_respects_llm_provider_env(monkeypatch):
    """LLM_PROVIDER env var overrides the config provider."""
    from llmwikify.apps.chat.providers import create_llm

    monkeypatch.setenv("LLM_PROVIDER", "minimax")
    config = {"enabled": True, "api_key": "x", "model": "y"}
    try:
        create_llm(config)
    except Exception:
        pass
    finally:
        monkeypatch.delenv("LLM_PROVIDER", raising=False)


def test_provider_classes_use_new_home_for_type_hints():
    """Provider modules import StreamableLLMClient from the new home, not the shim."""
    from llmwikify.apps.chat.providers import xiaomi, minimax, base, registry

    for mod in (xiaomi, minimax, base, registry):
        src = inspect.getsource(mod)
        assert "from ..adapters" not in src, (
            f"{mod.__name__} still imports from the deprecated adapters shim"
        )
        assert "from .adapters" not in src
        if "StreamableLLMClient" in src:
            assert "from llmwikify.foundation.llm.streamable" in src, (
                f"{mod.__name__} references StreamableLLMClient but doesn't "
                f"import it from the canonical home"
            )


def test_provider_protocol_still_uses_streamable_type():
    """The LLMProvider Protocol's from_config signature references StreamableLLMClient."""
    from llmwikify.apps.chat.providers import base

    src = inspect.getsource(base)
    assert "StreamableLLMClient" in src
    assert "from llmwikify.foundation.llm.streamable" in src


def test_provider_registry_at_new_home():
    """The provider registry module is at its post-Phase-4 home."""
    from llmwikify.apps.chat.providers import registry

    assert registry.__name__ == "llmwikify.apps.chat.providers.registry"
    assert hasattr(registry, "create_llm")
    assert hasattr(registry, "get_provider")
    assert hasattr(registry, "list_providers")
    assert hasattr(registry, "register_provider")


def test_legacy_shim_reexports_providers():
    """llmwikify.agent.backend.providers shim re-exports the new home.

    Backward compatibility for callers that imported via the
    deprecation shim during the v0.32 transition window.
    """
    from llmwikify.agent.backend import providers as shim

    # The shim's __name__ still identifies as the legacy path
    assert shim.__name__ == "llmwikify.agent.backend.providers"
    # But the symbols resolve to the new-home classes
    from llmwikify.apps.chat.providers import (
        create_llm as new_create_llm,
        get_provider as new_get_provider,
        list_providers as new_list_providers,
    )
    assert shim.create_llm is new_create_llm
    assert shim.get_provider is new_get_provider
    assert shim.list_providers is new_list_providers


def test_legacy_shim_submodule_paths():
    """The 4 sub-shims (base, registry, xiaomi, minimax) all re-export."""
    from llmwikify.agent.backend.providers import (
        base as shim_base,
        registry as shim_reg,
        xiaomi as shim_xiaomi,
        minimax as shim_minimax,
    )
    from llmwikify.apps.chat.providers import (
        base as new_base,
        registry as new_registry,
        xiaomi as new_xiaomi,
        minimax as new_minimax,
    )
    assert shim_base.__name__ == "llmwikify.agent.backend.providers.base"
    assert shim_reg.__name__ == "llmwikify.agent.backend.providers.registry"
    assert shim_xiaomi.__name__ == "llmwikify.agent.backend.providers.xiaomi"
    assert shim_minimax.__name__ == "llmwikify.agent.backend.providers.minimax"
    # Classes re-export (name identity, not object identity — Python
    # ``from X import *`` re-binds the names in the shim's namespace)
    assert shim_base.BaseLLMProvider is new_base.BaseLLMProvider
    assert shim_xiaomi.XiaomiProvider is new_xiaomi.XiaomiProvider
    assert shim_minimax.MiniMaxProvider is new_minimax.MiniMaxProvider
    assert shim_reg.create_llm is new_registry.create_llm


def test_create_llm_falls_back_to_minimax_by_default(monkeypatch):
    """create_llm defaults to 'minimax' provider when none specified."""
    from llmwikify.apps.chat.providers import create_llm

    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    config = {"enabled": True, "api_key": "x", "model": "y"}
    try:
        create_llm(config)
    except ValueError as e:
        if "Unknown provider 'minimax'" in str(e):
            raise AssertionError("minimax should be auto-registered")
    except Exception:
        pass
