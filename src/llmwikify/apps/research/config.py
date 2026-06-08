"""Quick Research configuration.

Per Sprint C4 of the 4-layer refactor, the 31 shared default
keys and the ``merge_research_config`` helper now live in
:mod:`llmwikify.apps.research.base`. This module is a thin
wrapper that re-exports the canonical names so that the 14
``agent/backend/research.*.py`` shim files and any external
callers continue to work without an import-path change.
"""

from __future__ import annotations

from typing import Any

from .base import BaseResearchConfig


DEFAULT_RESEARCH_CONFIG: dict[str, Any] = dict(BaseResearchConfig.DEFAULT)


def merge_research_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    return BaseResearchConfig.merge(overrides)
