"""Wiki mixins — composed into the ``Wiki`` class via metaclass.

The mixins are split into three subpackages by responsibility
(per the MX1 grouping in the 4-layer refactor design doc):

- ``core``: lifecycle, path/slug/templates, schema
  (``init``, ``utility``, ``schema``)
- ``io``: page I/O, ingest, source analysis, link
  (``ingest``, ``link``, ``page_io``, ``source_analysis``)
- ``analysis``: lint delegation, LLM calls, query, relation,
  synthesis, status (``lint``, ``llm``, ``query``,
  ``relation``, ``status``, ``synthesis``)

External code should import specific mixins from the
appropriate subpackage; this ``__init__`` re-exports the most
common names for convenience.
"""
from .analysis import (
    WikiLintMixin,
    WikiLLMMixin,
    WikiQueryMixin,
    WikiRelationMixin,
    WikiStatusMixin,
    WikiSynthesisMixin,
)
from .core import WikiInitMixin, WikiSchemaMixin, WikiUtilityMixin
from .io import WikiIngestMixin, WikiLinkMixin, WikiPageIOMixin, WikiSourceAnalysisMixin

__all__ = [
    "WikiInitMixin",
    "WikiSchemaMixin",
    "WikiUtilityMixin",
    "WikiIngestMixin",
    "WikiLinkMixin",
    "WikiPageIOMixin",
    "WikiSourceAnalysisMixin",
    "WikiLintMixin",
    "WikiLLMMixin",
    "WikiQueryMixin",
    "WikiRelationMixin",
    "WikiStatusMixin",
    "WikiSynthesisMixin",
]
