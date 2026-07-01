"""Lint rule implementations — one file per rule.

Each module exposes a single ``Rule`` subclass with a unique
``name``. The ``RULES`` list at the bottom of this file is the
canonical registry consumed by ``LintEngine``.

The 8 rules are direct extractions of the corresponding
``WikiAnalyzer._detect_X`` methods. Behavior is preserved
byte-for-byte (modulo the ``type`` field, which is now the
rule's ``name``).
"""

from __future__ import annotations

from .data_gaps import DataGapsRule

# Each rule is imported here and added to the RULES list.
# Adding a new rule = add a file + 1 import + 1 list entry.
from .dated_claims import DatedClaimsRule
from .knowledge_gaps import KnowledgeGapsRule
from .missing_cross_refs import MissingCrossRefsRule
from .outdated_pages import OutdatedPagesRule
from .potential_contradictions import PotentialContradictionsRule
from .query_page_overlap import QueryPageOverlapRule
from .redundancy import RedundancyRule

RULES = [
    DatedClaimsRule(),
    QueryPageOverlapRule(),
    MissingCrossRefsRule(),
    PotentialContradictionsRule(),
    DataGapsRule(),
    OutdatedPagesRule(),
    KnowledgeGapsRule(),
    RedundancyRule(),
]


__all__ = [
    "RULES",
    "DatedClaimsRule",
    "QueryPageOverlapRule",
    "MissingCrossRefsRule",
    "PotentialContradictionsRule",
    "DataGapsRule",
    "OutdatedPagesRule",
    "KnowledgeGapsRule",
    "RedundancyRule",
]
