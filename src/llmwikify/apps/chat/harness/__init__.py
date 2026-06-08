"""apps/chat/harness/ — Phase 7: 5 evaluation classes for research.

Per v0.32-execution-plan.md Phase 7 (1.5 weeks, scaled to
single session): the 5 evaluation classes are consolidated
into a single ``apps/chat/harness/`` subpackage. Phase 2
already renamed ``apps/chat/harness.py`` to
``apps/chat/eval_harness.py`` to free the ``harness/`` name.

The 5 classes are NOT skills — they are evaluation
primitives used by:

  - ``apps/chat/eval_harness.py`` (the eval framework's
    golden-case + LLM-as-judge runner, used in pytest)
  - ``apps/chat/skills/research_skill.py`` (Phase 6, gate
    intervention hook in on_after_act)
  - the future ``harness/score_skill`` (Phase 12, eval
    helper that consumes these classes)

Public API
----------

  - ``QualityGate``           (apps/chat/harness/quality_gate.py)
  - ``GateResult``            (apps/chat/harness/quality_gate.py)
  - ``SourceFilter``          (apps/chat/harness/source_filter.py)
  - ``ResearchReviewer``      (apps/chat/harness/review.py)
  - ``ResearchRevisor``       (apps/chat/harness/review.py)
  - ``StructureValidator``    (apps/chat/harness/structure_validator.py)
  - ``SourceAnalyzer``        (apps/chat/harness/source_analyzer.py)

Design refs
-----------

  - ``v0.32-skill-restructure.md`` §4.2 (file mapping)
  - ``v0.32-execution-plan.md`` Phase 7
"""

from __future__ import annotations

from llmwikify.apps.chat.harness.quality_gate import GateResult, QualityGate
from llmwikify.apps.chat.harness.review import (
    ResearchReviewer,
    ResearchRevisor,
)
from llmwikify.apps.chat.harness.source_analyzer import SourceAnalyzer
from llmwikify.apps.chat.harness.source_filter import SourceFilter
from llmwikify.apps.chat.harness.structure_validator import StructureValidator


__all__ = [
    "QualityGate",
    "GateResult",
    "SourceFilter",
    "ResearchReviewer",
    "ResearchRevisor",
    "StructureValidator",
    "SourceAnalyzer",
]
