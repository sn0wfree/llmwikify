"""FastAPI route definitions - unified single and multi-wiki mode."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException

from llmwikify.apps.chat.channels.websocket import _register_websocket_routes
from llmwikify.kernel.multi_wiki.registry import WikiRegistry

logger = logging.getLogger(__name__)


def register_routes(
    app: FastAPI,
    registry: WikiRegistry,
    provider: Any = None,
    *,
    api_key: str | None = None,
) -> None:
    """Register all API routes (unified architecture).

    Args:
        app: FastAPI application
        registry: WikiRegistry (always created, even for single wiki)
        provider: optional LLM client (Phase 7). Forwarded to
            ``_register_agent_routes`` so AgentService can wire it
            into MemoryManager for Consolidator + Dream.
        api_key
            Optional API key (Phase 14, WS auth). Forwarded to
            ``_register_websocket_routes`` so the WebSocket
            handshake can validate ``?token=`` against the same
            key as the REST ``AuthMiddleware``. Pass ``None`` to
            disable WS auth (dev mode).
    """
    # Wiki 路由
    from llmwikify.interfaces.server.http.wiki.wiki_routes import register_wiki_routes
    register_wiki_routes(app, registry)

    # Wikis 注册路由
    from llmwikify.interfaces.server.http.wiki.registry_routes import (
        register_registry_routes,
    )
    register_registry_routes(app, registry)

    # 搜索路由
    from llmwikify.interfaces.server.http.wiki.search_routes import (
        register_search_routes,
    )
    register_search_routes(app, registry)

    # 日志路由
    from llmwikify.interfaces.server.http.wiki.log_routes import register_log_routes
    register_log_routes(app)

    # 自维护路由（manager 由 lifespan 挂载到 app.state）
    from llmwikify.interfaces.server.http.maintenance_routes import (
        register_maintenance_routes,
    )
    register_maintenance_routes(app)

    # Agent 路由
    _register_agent_routes(app, registry, provider=provider)

    # Skills 路由
    _register_skills_routes(app)

    # WebSocket 路由
    from llmwikify.interfaces.server.http.agent._common import get_agent_service
    agent_svc = None
    try:
        agent_svc = get_agent_service()
    except RuntimeError:
        # Agent service not initialized — WS falls back to echo
        pass
    _register_websocket_routes(
        app, api_key=api_key or "", chat_service=agent_svc,
    )


# ─── Config loading helpers ────────────────────────────────────


def _load_research_config() -> dict[str, Any] | None:
    """Load research config from global config file (~/.llmwikify/llmwikify.json).

    Reads the "research" section if present. Returns None if file doesn't exist.
    """
    import json as _json

    config_file = Path.home() / ".llmwikify" / "llmwikify.json"
    if not config_file.exists():
        return None
    try:
        data = _json.loads(config_file.read_text())
        return data.get("research")
    except Exception:
        return None


def _load_llm_config() -> dict[str, Any] | None:
    """Load llm config from global config file (~/.llmwikify/llmwikify.json).

    Thin wrapper over ``foundation.llm.client.load_llm_config`` that
    preserves the legacy ``None``-on-missing contract (the foundation
    helper returns ``{}`` instead) AND the legacy call-time
    ``Path.home()`` resolution (the foundation helper uses a module-
    level ``CONFIG_PATH`` constant evaluated at import time, which
    breaks tests that monkeypatch ``Path.home``). One source of truth
    lives in ``foundation/llm/client.py``; this shim exists for
    backward compat with the two test files and one in-tree caller in
    this module.

    Reads the "llm" section if present. Returns None if file doesn't exist.
    """
    from llmwikify.foundation.llm.client import load_llm_config
    return load_llm_config(
        config_path=Path.home() / ".llmwikify" / "llmwikify.json",
    ) or None


def _build_research_config_overrides() -> dict[str, Any]:
    """Build research config overrides from global llmwikify.json.

    Reads the ``research`` section and applies automatic fallbacks so that
    existing deployments get a working web-search provider without any
    config change:

    - If ``research.minimax_api_host`` is unset, derive it from
      ``llm.base_url`` (stripping the ``/v1`` suffix) so the search
      endpoint resolves to the same host as chat.
    - If ``research.minimax_api_key`` is unset AND the user has not
      pinned a different ``research.search_provider``, reuse
      ``llm.api_key`` so a single credential covers both chat and
      search. Skipped for non-minimax LLM providers to avoid injecting
      a stranger's minimax key into another vendor's search config.

    The injected ``minimax_api_key`` is only used to construct the
    search provider client inside the request handler — the override
    dict itself is logged at DEBUG, not INFO/WARNING.

    Returns an empty dict when no overrides apply or the config file is
    missing. Never raises.
    """
    try:
        user_cfg = _load_research_config() or {}
        out: dict[str, Any] = {k: v for k, v in user_cfg.items() if v is not None}

        # Derive minimax_api_host from llm.base_url when not explicitly set.
        if "minimax_api_host" not in out:
            llm_cfg = _load_llm_config() or {}
            base_url = llm_cfg.get("base_url")
            if base_url:
                host = base_url.rstrip("/")
                if host.endswith("/v1"):
                    host = host[: -len("/v1")]
                out["minimax_api_host"] = host

        # Derive minimax_api_key from llm.api_key when not explicitly set,
        # and the user has not pinned a non-minimax search provider.
        # "auto" is treated as minimax-compatible (it picks a provider at
        # runtime, defaulting to minimax), so the fallback still applies.
        if "minimax_api_key" not in out:
            llm_cfg = _load_llm_config() or {}
            search_provider = out.get("search_provider")
            if (
                llm_cfg.get("provider") == "minimax"
                and llm_cfg.get("api_key")
                and (
                    not search_provider
                    or search_provider in {"minimax", "auto"}
                )
            ):
                out["minimax_api_key"] = llm_cfg["api_key"]
        return out
    except Exception as e:
        logger.warning("Failed to build research config overrides: %s", e)
        return {}


# ─── Agent routes ──────────────────────────────────────────────


def _register_agent_routes(
    app: FastAPI,
    registry: WikiRegistry,
    provider: Any = None,
) -> None:
    """Register Agent backend routes (Phase 1).

    Phase 7 (2026-06-19): Accepts an optional ``provider`` (LLM client)
    so the AgentService wires it into MemoryManager, enabling the
    Phase 6 Consolidator + Dream pipeline. If ``provider`` is None,
    the existing fallback path (provider-less MemoryManager) is used.

    Phase 19-D (2026-06-22): ``data_dir`` honors ``LLMWIKIFY_DATA_DIR``
    when set, falling back to ``~/.llmwikify/agent``. This lets tests
    monkeypatch the data dir via ``monkeypatch.setenv`` without writing
    to the production database (which ``Path.home()`` ignores on Linux).
    """
    from llmwikify.apps.chat.agent.agent_service import AgentService
    from llmwikify.interfaces.server.http.agent._common import set_agent_service

    # Phase 19-D: prefer explicit LLMWIKIFY_DATA_DIR; fall back to
    # the previous ``~/.llmwikify/agent`` default. Without this,
    # pytest's ``monkeypatch.setenv("HOME", ...)`` had no effect
    # (``Path.home()`` consults /etc/passwd, not $HOME), so test
    # runs polluted the real production DB with mock-LLM fixtures.
    _env_data_dir = os.environ.get("LLMWIKIFY_DATA_DIR")
    if _env_data_dir:
        data_dir = Path(_env_data_dir)
    else:
        data_dir = Path.home() / ".llmwikify" / "agent"
    data_dir.mkdir(parents=True, exist_ok=True)

    agent_service = AgentService(registry, data_dir, provider=provider)
    set_agent_service(agent_service)

    # Register /api/autoresearch/* routes (router exists, never mounted)
    from llmwikify.apps.chat.config import merge_six_step_config
    from llmwikify.apps.chat.research_engine.routes import (
        router as autoresearch_router,
    )
    from llmwikify.apps.chat.research_engine.routes import (
        set_autoresearch_deps,
    )

    db = agent_service.app_db.chat
    autoresearch_llm = provider
    if autoresearch_llm is None:
        try:
            autoresearch_llm = agent_service._get_llm()
        except Exception:
            logger.debug("agent_service._get_llm() unavailable, proceeding without LLM client for autoresearch")
    research_overrides = _build_research_config_overrides()
    set_autoresearch_deps(
        db=db,
        wiki_registry=registry,
        llm_client=autoresearch_llm,
        config=merge_six_step_config(research_overrides),
        tool_registry=agent_service._get_tool_registry(),
    )
    app.include_router(autoresearch_router)

    from llmwikify.interfaces.server.http.agent._common import router as agent_router

    app.include_router(agent_router)

    # P1-1 (vendored from nanobot api/server.py):
    # OpenAI-compatible /v1/chat/completions + /v1/models + /v1/health.
    # L3-local: openai_server.py maintains its own agent_service registry
    # (no L3→L4 import); routes.py sets it explicitly here.
    from llmwikify.apps.api.openai_server import (
        create_openai_router,
    )
    from llmwikify.apps.api.openai_server import (
        set_agent_service as set_openai_agent_service,
    )

    set_openai_agent_service(agent_service)

    model_name = "llmwikify-chat"
    try:
        from llmwikify.apps.chat.providers.registry import get_default_provider
        provider = get_default_provider()
        if provider and getattr(provider, "model", None):
            model_name = provider.model
    except Exception:
        logger.debug("Could not resolve default provider model, using fallback %r", model_name)
    app.include_router(create_openai_router(model=model_name))


# ─── Skills routes ─────────────────────────────────────────────


def _register_skills_routes(app: FastAPI) -> None:
    """Phase 11-F2: expose registered skills + plugin metadata.

    Two endpoints, both mounted under ``/api/skills``:

      - ``GET /api/skills``         — list all registered skills with
        their manifests (name / description / actions) and any plugin
        frontmatter (version / author / tags / license / source).
      - ``GET /api/skills/{name}``  — single skill detail.

    Skills that were registered through ``PromptBasedSkill`` plugin
    files (``~/.llmwikify/skills/<name>/SKILL.md``) carry an extra
    ``_plugin_metadata`` dict populated by ``plugin_loader``; those
    fields are surfaced as ``plugin.*`` in the response. Built-in
    skills don't have plugin metadata, so those keys are simply absent
    — callers should use ``.get('plugin')`` defensively.
    """
    from llmwikify.apps.chat.skills.registry import default_registry

    skills_router = APIRouter(prefix="/api/skills", tags=["skills"])

    @skills_router.get("")
    async def list_skills() -> dict[str, Any]:
        """List all registered skills with action summaries + plugin metadata."""
        registry = default_registry()
        out: list[dict[str, Any]] = []
        for skill in registry:
            entry: dict[str, Any] = {
                "name": skill.name,
                "description": skill.description,
                "action_count": len(skill.actions),
                "actions": sorted(skill.actions.keys()),
            }
            plugin_meta = getattr(skill, "_plugin_metadata", None)
            if plugin_meta:
                entry["plugin"] = plugin_meta
            out.append(entry)
        return {"count": len(out), "skills": out}

    @skills_router.get("/{name}")
    async def get_skill(name: str) -> dict[str, Any]:
        """Detail for a single skill; 404 if not registered."""
        registry = default_registry()
        skill = registry.get(name)
        if skill is None:
            raise HTTPException(
                status_code=404, detail=f"Skill {name!r} not registered"
            )
        manifest = skill.manifest().to_dict()
        entry: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "manifest": manifest,
        }
        plugin_meta = getattr(skill, "_plugin_metadata", None)
        if plugin_meta:
            entry["plugin"] = plugin_meta
        return entry

    app.include_router(skills_router)
