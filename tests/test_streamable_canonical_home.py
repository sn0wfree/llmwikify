"""Verify StreamableLLMClient is importable from new canonical home.

Phase 1 #1 / C1 — refactor to move the streaming LLM client out of
the deprecated ``llmwikify.agent.backend.adapters`` module and into
the neutral ``llmwikify.foundation.llm.streamable`` location.

This test asserts the new import path works and that the class
behaves identically to the legacy one (same constructor signature,
same default base URL mapping).
"""

from __future__ import annotations

import inspect


def test_streamable_imports_from_llm_package():
    """StreamableLLMClient is importable from llmwikify.foundation.llm.streamable."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    assert StreamableLLMClient is not None


def test_streamable_constructor_signature_matches_legacy():
    """The new home's __init__ signature is byte-equivalent to the legacy one."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    sig = inspect.signature(StreamableLLMClient.__init__)
    params = list(sig.parameters.keys())

    # 11 named params total (incl. self)
    assert params[0] == "self"
    for expected in (
        "provider",
        "base_url",
        "api_key",
        "model",
        "reasoning_split",
        "auth_header",
        "context_window",
        "budget_on_exceed",
        "request_timeout_seconds",
    ):
        assert expected in params, f"missing param: {expected}"


def test_streamable_default_base_url_table_includes_known_providers():
    """_default_base_url knows openai/ollama/lmstudio/xiaomi/minimax."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    assert StreamableLLMClient._default_base_url("openai") == "https://api.openai.com"
    assert StreamableLLMClient._default_base_url("ollama") == "http://localhost:11434/v1"
    assert StreamableLLMClient._default_base_url("lmstudio") == "http://localhost:1234/v1"
    assert StreamableLLMClient._default_base_url("xiaomi") == "https://token-plan-cn.xiaomimimo.com"
    assert StreamableLLMClient._default_base_url("minimax") == "https://api.minimaxi.com/v1"
    # Unknown provider falls back to openai default
    assert StreamableLLMClient._default_base_url("unknown") == "https://api.openai.com"


def test_streamable_instance_creation_strips_v1_from_base_url():
    """When user passes base_url ending in /v1, the trailing /v1 is stripped."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    c = StreamableLLMClient(
        provider="custom",
        base_url="https://example.com/v1/",
        api_key="k",
        model="m",
    )
    assert c.base_url == "https://example.com"


def test_streamable_instance_preserves_user_base_url():
    """When user passes base_url without /v1, it is left alone."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    c = StreamableLLMClient(
        provider="custom",
        base_url="https://example.com/api",
        api_key="k",
        model="m",
    )
    assert c.base_url == "https://example.com/api"


def test_streamable_build_headers_bearer():
    """Default auth_header=bearer emits Authorization: Bearer ..."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    c = StreamableLLMClient(provider="openai", api_key="sk-test", model="m")
    headers = c._build_headers()
    assert headers["Authorization"] == "Bearer sk-test"
    assert "api-key" not in headers


def test_streamable_build_headers_api_key():
    """auth_header=api-key emits api-key: ..."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    c = StreamableLLMClient(
        provider="custom",
        api_key="ak",
        model="m",
        auth_header="api-key",
    )
    headers = c._build_headers()
    assert headers["api-key"] == "ak"
    assert "Authorization" not in headers


def test_streamable_has_all_required_methods():
    """The class exposes the full streaming/async/tool surface."""
    from llmwikify.foundation.llm.streamable import StreamableLLMClient

    c = StreamableLLMClient(provider="openai", api_key="k", model="m")
    for name in ("chat", "chat_with_tools", "stream_chat", "astream_chat", "achat"):
        assert callable(getattr(c, name)), f"missing method: {name}"


def test_streamable_inherits_from_llm_client():
    """StreamableLLMClient is a subclass of LLMClient.

    Phase 1 #1 / C2 — the streaming client now extends the basic
    LLMClient. This lets ``isinstance(client, LLMClient)`` checks
    succeed and means code that takes a ``LLMClient`` parameter
    will accept a ``StreamableLLMClient`` instance.

    The reverse is **not** true: an LLMClient instance has no
    ``stream_chat``/``achat``/``astream_chat``/``chat_with_tools``
    methods.
    """
    from llmwikify.foundation.llm.streamable import StreamableLLMClient
    from llmwikify.foundation.llm_client import LLMClient

    assert issubclass(StreamableLLMClient, LLMClient)
    assert not issubclass(LLMClient, StreamableLLMClient)


def test_streamable_instance_is_instance_of_llm_client():
    """isinstance check succeeds — type hierarchy lets LLMClient consumers
    accept a StreamableLLMClient instance.
    """
    from llmwikify.foundation.llm.streamable import StreamableLLMClient
    from llmwikify.foundation.llm_client import LLMClient

    c = StreamableLLMClient(provider="openai", api_key="k", model="m")
    assert isinstance(c, LLMClient)


def test_streamable_uses_relative_imports_for_budget_modules():
    """The new module imports from .budget_decorator / .token_budget, not absolute.

    This is the structural signal that the file now lives inside
    the llm/ package, not as a sibling of the agent module.

    The one allowed absolute import is the lazy provider-registry
    bridge inside ``from_config`` — that one is intentional and
    will be revisited in C5 (Phase 1 #1).
    """
    import llmwikify.foundation.llm.streamable as streamable_mod

    src = inspect.getsource(streamable_mod)
    # Module-level imports must be relative (we live in llm/ now)
    assert "from .budget_decorator import" in src
    assert "from .token_budget import" in src
    # The provider-registry bridge is allowed (lazy, only in from_config)
    # Per the 4-layer refactor (Batch B4), the L1->L3 cross-dep
    # in ``from_config`` was removed. The function is now a
    # pure config-to-constructor translation; callers that need
    # the provider registry use ``apps.chat.providers.registry``
    # directly (per v0.32 Phase 4, providers migrated from
    # apps/agent/ to apps/chat/).
    assert "from llmwikify.apps.agent.providers.registry" not in src
    assert "from llmwikify.apps.chat.providers.registry" not in src
    assert "from llmwikify._legacy.adapters" not in src
    # No other absolute agent imports at module level
    top_level_agent_imports = [
        line for line in src.splitlines()
        if line.startswith("from llmwikify.agent") and "providers.registry" not in line
    ]
    assert top_level_agent_imports == [], (
        f"unexpected agent import at module level: {top_level_agent_imports}"
    )
