"""Back-compat shim — same module object as ``llmwikify.apps.knowledge.base``.

The shared research base classes (config, quality gate, task manager)
moved to ``llmwikify.apps.knowledge.base`` so that ``apps.chat`` and
``apps.research`` no longer import each other (see
``llmwikify.apps.knowledge``).

This shim preserves the old import path
``from llmwikify.apps.research.base import BaseResearchConfig`` and
exposes the SAME module object (via the ``sys.modules`` trick), so
``mock.patch`` on either path affects both.

New code should import from ``llmwikify.apps.knowledge.base``.
"""

import sys as _sys

from llmwikify.apps.knowledge import base as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
