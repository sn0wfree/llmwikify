"""Back-compat shim — same module object as ``llmwikify.apps.research.agent``.

The research agent is research-specific, so it belongs with the
research engine (``llmwikify.apps.research.agent``) rather than in the
chat package. Moving it out is what lets ``apps.chat`` stop importing
``apps.research``.

This shim preserves the old import path
``from llmwikify.apps.chat.research_agent import ResearchAgent`` and
exposes the SAME module object (via the ``sys.modules`` trick), so
``mock.patch`` on either path affects both.

New code should import from ``llmwikify.apps.research.agent``.
"""

import sys as _sys

from llmwikify.apps.research import agent as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
