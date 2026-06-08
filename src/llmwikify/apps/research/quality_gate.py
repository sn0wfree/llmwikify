"""Quality gates between research stages.

Gate results are injected as observations into the ReAct loop.
The Reasoner decides what to do based on gate observations.

Sprint C4: the 4 base gate methods were extracted to
:mod:`llmwikify.apps.research.base.BaseQualityGate`. This
module now just re-exports the base class and ``GateResult``
under their public names so that
``from llmwikify.apps.research.quality_gate import QualityGate``
keeps working for the 14 ``agent/backend/research.*.py`` shim
files and external callers.
"""

from __future__ import annotations

from .base import BaseGateResult, BaseQualityGate

# Public aliases — preserve the original module-level names.
GateResult = BaseGateResult


class QualityGate(BaseQualityGate):
    """Quick-Research variant of the 4 base quality gates.

    Inherits all behavior from :class:`BaseQualityGate`. The
    6-step framework gates (``check_evidence_quality`` etc.)
    live only in the ``apps/chat/`` subclass.
    """

    pass
