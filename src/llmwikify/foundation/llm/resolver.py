"""LLM config resolver — the single source for LLM configuration.

Part of the LLM Access Layer (LAL). See
``docs/designs/llm-access-layer.md`` for the full design.

This module is the ONLY place in the codebase allowed to read LLM
configuration from any source (env vars, config dict, old id alias).
All other code paths must call ``resolve_chat_llm(config)`` and
consume the returned ``LLMSpec``.

Configuration priority (highest wins):

    P0  environment variables  (``LLM_API_KEY``, ``LLM_BASE_URL``,
        ``LLM_MODEL``, ``LLM_PROVIDER``)
    P1  wiki config  (``config["llm"]`` dict)
    P2  provider-internal defaults  (e.g. ``minimax`` base URL)
    P3  legacy id alias  (e.g. ``minimax`` → ``minimax``)

Behavioural rules:

- This resolver does NOT validate ``enabled`` or ``api_key``. It only
  resolves values. Callers (``LLMClient.from_config``, the registry)
  decide what counts as "not configured" and raise accordingly. (PR 4
  will centralize that validation behind ``LLMNotConfiguredError``.)
- This resolver does NOT silently fall back to ``openai/gpt-4o``.
  Defaults are only used when the field is genuinely missing from BOTH
  env and config; the resulting spec still requires the caller to
  provide an ``api_key`` to actually use it.
- The ``LLM_USE_RESOLVER`` env var is a kill switch for the resolver
  integration. When set to ``"false"`` (case-insensitive), the public
  ``from_config`` entry points fall back to their original inline
  implementation. Default is ``"true"`` (use the resolver).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .spec import LLMSpec

logger = logging.getLogger(__name__)


# ─── Alias table ──────────────────────────────────────────────────────
# Old provider id → canonical provider id. Applied in the resolver
# before any field-level resolution so downstream code (and
# ``provider.supported_models`` checks in PR 3) sees canonical ids
# only.

PROVIDER_ALIASES: dict[str, str] = {
    "minimax": "minimax",
}


def apply_provider_alias(provider: str) -> str:
    """Return the canonical provider id, applying any legacy alias.

    Unknown ids are returned unchanged. Logs at INFO when an alias is
    applied so operators can find old configs that need migration.
    """
    aliased = PROVIDER_ALIASES.get(provider, provider)
    if aliased != provider:
        logger.info(
            "provider alias applied: %r -> %r (consider updating config)",
            provider, aliased,
        )
    return aliased


# ─── Provider-internal defaults (P2) ──────────────────────────────────
# Used only when both env and config are silent for a given field.
# The keys here intentionally do NOT include ``model`` — model is left
# as an empty string in that case so the resolver's source-tracking is
# accurate ("config did not specify a model"), and downstream callers
# can decide what to do (raise, ask user, etc.). For PR 1 we keep the
# old behaviour of defaulting ``model`` to ``"gpt-4o"`` so that
# ``LLMClient.from_config`` does not change behaviour.

_PROVIDER_BASE_URL_DEFAULTS: dict[str, str] = {
    "openai": "https://api.openai.com",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "minimax": "https://api.minimaxi.com/v1",
    "xiaomi": "https://token-plan-cn.xiaomimimo.com",
}

_PROVIDER_DEFAULT_MODEL: dict[str, str] = {
    "openai": "gpt-4o",
    "minimax": "minimax-M3",
    "xiaomi": "mimo-v2.5-pro",
    # ollama / lmstudio intentionally absent — no meaningful default
}

_PROVIDER_AUTH_SCHEME: dict[str, str] = {
    "openai": "bearer",
    "ollama": "bearer",
    "lmstudio": "bearer",
    "minimax": "bearer",
    "xiaomi": "api-key",
}

_PROVIDER_REASONING_SPLIT: dict[str, bool] = {
    "minimax": True,
    "xiaomi": True,
}


def _provider_default_base_url(provider: str) -> str:
    return _PROVIDER_BASE_URL_DEFAULTS.get(
        provider, "https://api.openai.com"
    )


def _provider_default_model(provider: str) -> str:
    return _PROVIDER_DEFAULT_MODEL.get(provider, "gpt-4o")


def _provider_auth_scheme(provider: str) -> str:
    return _PROVIDER_AUTH_SCHEME.get(provider, "bearer")


def _provider_reasoning_split(provider: str) -> bool:
    return _PROVIDER_REASONING_SPLIT.get(provider, False)


# ─── Env-var resolution helpers ───────────────────────────────────────

def _env_or(value: str | None, env_key: str) -> str | None:
    """Return the env override if set, else the value unchanged."""
    env_val = os.environ.get(env_key)
    if env_val is not None and env_val != "":
        return env_val
    return value


def _expand_env_var(value: str) -> str:
    """Expand ``env:VAR_NAME`` syntax in api_key field."""
    if isinstance(value, str) and value.startswith("env:"):
        var_name = value[4:]
        return os.environ.get(var_name, "")
    return value


# ─── Public resolver ──────────────────────────────────────────────────

def resolve_chat_llm(config: dict[str, Any] | None = None) -> LLMSpec:
    """Resolve a wiki / dict config into a fully-resolved ``LLMSpec``.

    The single source of truth for "what LLM should I use?". All
    ``from_config`` entry points in the codebase should call this
    function rather than reading ``config["llm"]`` directly.

    Args:
        config: The full config dict (may have a top-level ``llm``
            key, or be the ``llm`` section itself). When ``None`` or
            empty, all defaults are used.

    Returns:
        A frozen ``LLMSpec`` with every field populated. The
        ``source`` field records the dominant config source.

    Notes:
        Does not raise on missing ``api_key`` or unset ``enabled`` —
        callers decide whether those are errors. The empty-string
        sentinel for missing ``api_key`` is preserved so old
        validation logic keeps working.
    """
    config = config or {}
    llm_cfg = config.get("llm", config) if isinstance(config, dict) else {}

    # Determine source: env-only, config-only, or merged.
    env_hit = any(
        os.environ.get(k) is not None and os.environ.get(k) != ""
        for k in ("LLM_PROVIDER", "LLM_MODEL", "LLM_BASE_URL", "LLM_API_KEY")
    )
    config_hit = bool(llm_cfg.get("provider") or llm_cfg.get("model"))
    if env_hit and config_hit:
        source = "merged"
    elif env_hit:
        source = "env"
    elif config_hit:
        source = "ui" if llm_cfg.get("provider") else "config"
    else:
        source = "config"

    # Resolve provider with alias.
    raw_provider = (
        os.environ.get("LLM_PROVIDER")
        or llm_cfg.get("provider")
        or "openai"
    )
    provider = apply_provider_alias(raw_provider)

    # Resolve base URL. Env > config > provider default.
    base_url = (
        os.environ.get("LLM_BASE_URL")
        or llm_cfg.get("base_url", "")
        or _provider_default_base_url(provider)
    )

    # Resolve API key. Env > config (with env:VAR expansion).
    config_api_key = llm_cfg.get("api_key", "")
    config_api_key = _expand_env_var(config_api_key) if config_api_key else ""
    api_key = os.environ.get("LLM_API_KEY", config_api_key)

    # Resolve model. Env > config > provider default. For PR 1 we
    # keep the historical default of "gpt-4o" so that callers that
    # don't set a model still get a usable spec. PR 4 will require
    # the model to come from config or env, not from defaults.
    model = (
        os.environ.get("LLM_MODEL")
        or llm_cfg.get("model")
        or _provider_default_model(provider)
    )

    # Resolve timeout (seconds).
    timeout_raw = llm_cfg.get("timeout", llm_cfg.get("request_timeout_seconds", 120))
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        timeout = 120.0

    # Resolve context window. None means "let the client probe".
    context_window = llm_cfg.get("context_window")
    if context_window is not None:
        try:
            context_window = int(context_window)
        except (TypeError, ValueError):
            context_window = None

    # Resolve reasoning_split: config overrides provider default.
    if "reasoning_split" in llm_cfg:
        reasoning_split = bool(llm_cfg["reasoning_split"])
    else:
        reasoning_split = _provider_reasoning_split(provider)

    # Resolve budget_on_exceed: config value or default "warn".
    budget_on_exceed = str(llm_cfg.get("budget_on_exceed", "warn"))

    # Resolve auth_scheme: config overrides provider default.
    if "auth_scheme" in llm_cfg or "auth_header" in llm_cfg:
        auth_scheme = llm_cfg.get("auth_scheme") or llm_cfg.get("auth_header")
    else:
        auth_scheme = _provider_auth_scheme(provider)

    # Resolve extra_headers (rarely used; pass through if present).
    extra_headers = dict(llm_cfg.get("extra_headers", {}) or {})

    return LLMSpec(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        context_window=context_window,
        timeout=timeout,
        reasoning_split=reasoning_split,
        auth_scheme=auth_scheme,
        budget_on_exceed=budget_on_exceed,
        extra_headers=extra_headers,
        source=source,
    )


# ─── Gradient switch ──────────────────────────────────────────────────


def resolver_enabled() -> bool:
    """Return True if the resolver should be used (default).

    Set the env var ``LLM_USE_RESOLVER=false`` to disable the resolver
    and fall back to legacy inline config reading in the public
    ``from_config`` entry points. Used as a kill switch when a
    resolver regression needs to be bypassed without redeploying.
    """
    val = os.environ.get("LLM_USE_RESOLVER", "true").strip().lower()
    return val not in ("false", "0", "no", "off", "")


__all__ = [
    "PROVIDER_ALIASES",
    "apply_provider_alias",
    "resolve_chat_llm",
    "resolver_enabled",
]
