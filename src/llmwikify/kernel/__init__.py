"""L2 kernel layer — the business kernel of llmwikify.

Per the 4-layer refactor (see
``docs/designs/refactor-4layer-architecture.md``), this
package contains the business logic that sits between the L1
foundation (LLM clients, extractors, ...) and the L3 apps/L4
interfaces (CLI, MCP, server, web).

Subpackages:
    - wiki: the central ``Wiki`` class, mixins, engines, lint
    - storage: WikiBackend, WikiIndex, QuerySink, watcher
    - graph: knowledge graph analysis, export, visualization
    - search: QMD hybrid full-text + vector search
    - multi_wiki: registry/instance/discovery/remote
    - quant: quant-domain shared code (codegen, data_source) — C1 added

Top-level modules:
    - principle_checker: validates wiki content against the
      LLM Wiki Principles (see docs/LLM_WIKI_PRINCIPLES.md).
"""
from .graph import GraphAnalyzer
from .multi_wiki import (
    RemoteWiki,
    WikiDiscovery,
    WikiInstance,
    WikiRegistry,
    WikiStatus,
    WikiType,
)
from .search import QmdClient, QmdIndex
from .storage import (
    FileSystemWatcher,
    LocalFileBackend,
    QuerySink,
    WikiBackend,
    WikiIndex,
)
from .wiki import VALID_AGENTS, Wiki
from .wiki.engines import RelationEngine, SynthesisEngine, WikiAnalyzer
from .wiki.mixins import (
    WikiIngestMixin,
    WikiInitMixin,
    WikiLinkMixin,
    WikiLintMixin,
    WikiLLMMixin,
    WikiPageIOMixin,
    WikiQueryMixin,
    WikiRelationMixin,
    WikiSchemaMixin,
    WikiSourceAnalysisMixin,
    WikiStatusMixin,
    WikiSynthesisMixin,
    WikiUtilityMixin,
)
from .wiki.protocols import WikiProtocol

__all__ = [
    "Wiki",
    "VALID_AGENTS",
    "WikiAnalyzer",
    "RelationEngine",
    "SynthesisEngine",
    "GraphAnalyzer",
    "RemoteWiki",
    "WikiDiscovery",
    "WikiInstance",
    "WikiRegistry",
    "WikiStatus",
    "WikiType",
    "QmdClient",
    "QmdIndex",
    "WikiBackend",
    "LocalFileBackend",
    "WikiIndex",
    "QuerySink",
    "FileSystemWatcher",
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
    "WikiProtocol",
]
