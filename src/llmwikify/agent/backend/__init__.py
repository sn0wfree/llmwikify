"""Backward-compat shim: ``llmwikify.agent.backend`` → ``llmwikify.apps.agent``.

Per Batch B4 of the 4-layer refactor, the agent/backend/
package moved to apps/agent/ (L3 layer). This shim preserves
the old import path until v0.33.0.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "llmwikify.agent.backend is moved to llmwikify.apps.agent in the "
    "4-layer refactor. Update your imports. This shim will be removed "
    "in v0.33.0.",
    DeprecationWarning,
    stacklevel=2,
)
