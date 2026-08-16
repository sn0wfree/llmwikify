"""Shared LLM-config fallback for maintenance services.

``wiki._llm_process_source`` / ``wiki.lint`` build their LLM clients
from the per-wiki ``wiki.config["llm"]`` section, but typical
deployments configure LLM once in ``~/.llmwikify/llmwikify.json`` (the
same file serve uses to wire the chat provider). Without this fallback,
maintenance work on such wikis silently degrades (auto-ingest →
proposal fallback, gap lint → offline fallback). Observed in
production 2026-08-16. The merge is in-memory only — never written back.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def ensure_global_llm_fallback(wiki: Any, wiki_id: str) -> bool:
    """Merge the global llm config into ``wiki.config`` when the local
    one is unusable. Returns True if a merge happened.

    A local config counts as usable when it is enabled AND carries an
    api_key or base_url (e.g. a local ollama deployment).
    """
    try:
        cfg = wiki.config
        if not isinstance(cfg, dict):
            return False
        llm = cfg.get("llm") or {}
        if llm.get("enabled") and (llm.get("api_key") or llm.get("base_url")):
            return False
        from llmwikify.foundation.llm.client import load_llm_config

        global_llm = load_llm_config()
        if not global_llm.get("enabled"):
            return False
        cfg["llm"] = {**llm, **global_llm, "enabled": True}
        logger.info(
            "[%s] maintenance: wiki-local llm off, using global "
            "config (provider=%s, model=%s)",
            wiki_id,
            global_llm.get("provider"),
            global_llm.get("model"),
        )
        return True
    except Exception:
        logger.debug(
            "[%s] maintenance: llm config fallback check failed",
            wiki_id,
            exc_info=True,
        )
        return False
