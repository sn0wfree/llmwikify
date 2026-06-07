"""Wiki class — the public L2 entry point for the wiki.

Per the 4-layer refactor (Batch B3), ``core/`` moved to
``kernel/``. The ``Wiki`` class is the central abstraction; the
mixins that compose it live in ``kernel/wiki/mixins/``.
"""
from .wiki import VALID_AGENTS, Wiki

__all__ = ["Wiki", "VALID_AGENTS"]
