"""Backward-compat shim for the old ``llmwikify.core`` package.

Per Batch B3 of the 4-layer refactor, ``core/`` moved to
``kernel/``. This package preserves the old public surface so
external user code that did ``from llmwikify.core import Wiki``
or ``from llmwikify.core.wiki_analyzer import WikiAnalyzer``
keeps working.

Strategy:
- The top-level names (``Wiki``, ``WikiIndex``, mixins, …)
  are re-exported explicitly from the matching ``kernel.*``
  sub-modules.
- Sub-module access (``llmwikify.core.wiki_analyzer``, …) is
  served by a ``__getattr__`` PEP 562 hook that imports the
  corresponding ``llmwikify.kernel.*`` module on demand.

All entry points emit a one-time ``DeprecationWarning`` on
first import. The shim is removed in v0.33.0.
"""
from __future__ import annotations

import importlib
import warnings

# Map from the old ``llmwikify.core.<sub>`` path to the new
# ``llmwikify.kernel.<sub>`` (or ``llmwikify.kernel.<sub>.<file>``)
# path. We translate the dotted prefix only — the rest of the
# path is preserved.
_SUBMODULE_REMAP: dict[str, str] = {
    "wiki": "kernel.wiki.wiki",
    "wiki_analyzer": "kernel.wiki.engines.analyzer",
    "relation_engine": "kernel.wiki.engines.relation",
    "synthesis_engine": "kernel.wiki.engines.synthesis",
    "wiki_backend": "kernel.storage.backend",
    "index": "kernel.storage.index",
    "query_sink": "kernel.storage.query_sink",
    "watcher": "kernel.storage.watcher",
    "graph_analyzer": "kernel.graph.analyzer",
    "graph_export": "kernel.graph.export",
    "graph_visualizer": "kernel.graph.visualizer",
    "qmd_index": "kernel.search.qmd_index",
    "qmd_client": "kernel.search.qmd_client",
    "wiki_registry": "kernel.multi_wiki.registry",
    "wiki_instance": "kernel.multi_wiki.instance",
    "wiki_discovery": "kernel.multi_wiki.discovery",
    "remote_wiki": "kernel.multi_wiki.remote",
    "principle_checker": "kernel.principle_checker",
    "prompt_registry": "kernel.wiki.prompt_registry",
    "protocols": "kernel.wiki.protocols",
    "constants": "kernel.wiki.constants",
    # Mixin split (MX1) — old single files now live in
    # ``kernel.wiki.mixins.<group>/<name>``.
    "wiki_mixin_init": "kernel.wiki.mixins.core.init",
    "wiki_mixin_utility": "kernel.wiki.mixins.core.utility",
    "wiki_mixin_schema": "kernel.wiki.mixins.core.schema",
    "wiki_mixin_page_io": "kernel.wiki.mixins.io.page_io",
    "wiki_mixin_ingest": "kernel.wiki.mixins.io.ingest",
    "wiki_mixin_source_analysis": "kernel.wiki.mixins.io.source_analysis",
    "wiki_mixin_link": "kernel.wiki.mixins.io.link",
    "wiki_mixin_lint": "kernel.wiki.mixins.analysis.lint",
    "wiki_mixin_llm": "kernel.wiki.mixins.analysis.llm",
    "wiki_mixin_query": "kernel.wiki.mixins.analysis.query",
    "wiki_mixin_relation": "kernel.wiki.mixins.analysis.relation",
    "wiki_mixin_synthesis": "kernel.wiki.mixins.analysis.synthesis",
    "wiki_mixin_status": "kernel.wiki.mixins.analysis.status",
    # lint package
    "lint": "kernel.wiki.lint",
    "lint.rules": "kernel.wiki.lint.rules",
}

_WARNED = False


def _warn_once() -> None:
    global _WARNED
    if _WARNED:
        return
    _WARNED = True
    warnings.warn(
        "llmwikify.core is moved to llmwikify.kernel in the 4-layer "
        "refactor. Update your imports. This shim will be removed "
        "in v0.33.0.",
        DeprecationWarning,
        stacklevel=3,
    )


# Eager re-exports of the most common top-level names.
from llmwikify.kernel import (
    VALID_AGENTS,
    Wiki,
    WikiAnalyzer,
    WikiBackend,
    WikiDiscovery,
    WikiIndex,
    WikiInitMixin,
    WikiIngestMixin,
    WikiInstance,
    WikiLLMMixin,
    WikiLintMixin,
    WikiLinkMixin,
    WikiPageIOMixin,
    WikiQueryMixin,
    WikiRegistry,
    WikiRelationMixin,
    WikiSchemaMixin,
    WikiSourceAnalysisMixin,
    WikiStatus,
    WikiStatusMixin,
    WikiSynthesisMixin,
    WikiType,
    WikiUtilityMixin,
    LocalFileBackend,
    QuerySink,
    RemoteWiki,
    WikiProtocol,
    FileSystemWatcher,
    RelationEngine,
    SynthesisEngine,
    GraphAnalyzer,
    QmdClient,
    QmdIndex,
)

# Common constants re-exports.
from llmwikify.kernel.wiki.constants import (
    CLAIM_OVERLAP_THRESHOLD,
    CONTRADICTION_OVERLAP_THRESHOLD,
    GROWING_WIKI_THRESHOLD,
    HASH_TRUNCATE_LENGTH,
    JACCARD_OVERLAP_THRESHOLD,
    MAX_CONTENT_CHARS,
    MAX_CONTRADICTIONS,
    MAX_CROSS_REF_HINTS,
    MAX_DATED_CLAIM_HINTS,
    MAX_KEY_TOPICS,
    MAX_MISSING_DISPLAY,
    MAX_QUERY_OVERLAP_HINTS,
    MAX_QUERY_TOPIC_LENGTH,
    MAX_SUGGESTED_UPDATES,
    MAX_SUMMARY_ITEMS,
    MIN_ASSERTION_LENGTH,
    MIN_ASSERTIONS_FOR_GAP,
    MIN_KEYWORD_LENGTH,
    MIN_MISSING_REF_COUNT,
    MIN_YEAR_THRESHOLD,
    OUTDATED_YEAR_GAP,
    SIMILARITY_THRESHOLD,
    SMALL_WIKI_THRESHOLD,
    STOP_WORDS,
    YEAR_GAP_THRESHOLD,
)

_warn_once()


__all__ = [
    # Wiki
    "Wiki",
    "VALID_AGENTS",
    "WikiIndex",
    "WikiAnalyzer",
    "RelationEngine",
    "SynthesisEngine",
    "WikiBackend",
    "LocalFileBackend",
    "QuerySink",
    "WikiWatcher",
    "GraphAnalyzer",
    "QmdIndex",
    "QmdClient",
    "WikiRegistry",
    "WikiInstance",
    "WikiType",
    "WikiStatus",
    "WikiDiscovery",
    "RemoteWiki",
    "WikiProtocol",
    "FileSystemWatcher",
    # Mixins
    "WikiInitMixin",
    "WikiIngestMixin",
    "WikiLinkMixin",
    "WikiLLMMixin",
    "WikiLintMixin",
    "WikiPageIOMixin",
    "WikiQueryMixin",
    "WikiRelationMixin",
    "WikiSchemaMixin",
    "WikiSourceAnalysisMixin",
    "WikiStatusMixin",
    "WikiSynthesisMixin",
    "WikiUtilityMixin",
    # Constants (re-exported for backward compat)
    "CLAIM_OVERLAP_THRESHOLD",
    "CONTRADICTION_OVERLAP_THRESHOLD",
    "GROWING_WIKI_THRESHOLD",
    "HASH_TRUNCATE_LENGTH",
    "JACCARD_OVERLAP_THRESHOLD",
    "MAX_CONTENT_CHARS",
    "MAX_CONTRADICTIONS",
    "MAX_CROSS_REF_HINTS",
    "MAX_DATED_CLAIM_HINTS",
    "MAX_KEY_TOPICS",
    "MAX_MISSING_DISPLAY",
    "MAX_QUERY_OVERLAP_HINTS",
    "MAX_QUERY_TOPIC_LENGTH",
    "MAX_SUGGESTED_UPDATES",
    "MAX_SUMMARY_ITEMS",
    "MIN_ASSERTION_LENGTH",
    "MIN_ASSERTIONS_FOR_GAP",
    "MIN_KEYWORD_LENGTH",
    "MIN_MISSING_REF_COUNT",
    "MIN_YEAR_THRESHOLD",
    "OUTDATED_YEAR_GAP",
    "SIMILARITY_THRESHOLD",
    "SMALL_WIKI_THRESHOLD",
    "STOP_WORDS",
    "YEAR_GAP_THRESHOLD",
]


def __getattr__(name: str):
    """Lazy re-export of sub-modules of the old ``core/`` package.

    For example, ``llmwikify.core.wiki_analyzer`` resolves to
    ``llmwikify.kernel.wiki.engines.analyzer``. This PEP 562 hook
    avoids having to create one shim file per sub-module.
    """
    if name in _SUBMODULE_REMAP:
        _warn_once()
        return importlib.import_module(f"llmwikify.{_SUBMODULE_REMAP[name]}")
    # Pass-through to ``llmwikify.kernel`` for any other name
    # (e.g. the public API listed in __all__).
    try:
        return getattr(importlib.import_module("llmwikify.kernel"), name)
    except AttributeError as e:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from e
