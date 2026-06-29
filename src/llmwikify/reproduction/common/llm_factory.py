"""LLM client factory: load config from ~/.llmwikify/llmwikify.json.

⚠️ C2 (PR-C2) refactor: this module is now a **thin re-export wrapper**
for backward compatibility. The actual implementations live in
`llmwikify.kernel.quant.llm_client` (which both apps/ and reproduction/
can import without creating a layer cycle).

New code should import from `llmwikify.kernel.quant.llm_client` directly.
This wrapper exists for backward compat with pre-C2 callers.

Functions re-exported:
  - load_llm_config: from llmwikify.kernel.quant.llm_client
  - build_default_client: re-export of build_llm_client (legacy name)
    Note: the kernel version is called `build_llm_client`; the legacy
    name `build_default_client` is kept here for callers that still
    import it (e.g., scripts/run_101_alphas.py, factor_compiler.py).
"""
from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

from llmwikify.kernel.quant.llm_client import (  # noqa: F401
    CONFIG_PATH,
    build_llm_client,
    load_llm_config,
)


def build_default_client(model: str | None = None) -> Any:
    """⚠️ DEPRECATED: use ``llmwikify.kernel.quant.llm_client.build_llm_client`` instead.

    Thin re-export of ``build_llm_client`` for backward compat.
    C2 changed the canonical name from ``build_default_client`` to
    ``build_llm_client`` for clarity (it's the one and only client
    builder — "default" is misleading).

    This wrapper emits a DeprecationWarning on first call to nudge callers
    to migrate. Will be removed in a future release.
    """
    warnings.warn(
        "reproduction.common.llm_factory.build_default_client is deprecated; "
        "use llmwikify.kernel.quant.llm_client.build_llm_client instead. "
        "This wrapper will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
    return build_llm_client(model=model)


__all__ = ["CONFIG_PATH", "load_llm_config", "build_llm_client", "build_default_client"]
