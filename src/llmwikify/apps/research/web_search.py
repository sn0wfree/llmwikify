"""Back-compat shim — same module object as ``llmwikify.apps.knowledge.web_search``.

The web-search facade moved to the shared substrate
``llmwikify.apps.knowledge.web_search`` so that ``apps.chat`` and
``apps.research`` no longer import each other (see
``llmwikify.apps.knowledge``).

This shim preserves the old import path
``from llmwikify.apps.research.web_search import WebSearch`` and
exposes the SAME module object (via the ``sys.modules`` trick), so
``mock.patch`` on either path affects both.

New code should import from ``llmwikify.apps.knowledge.web_search``.
"""

import sys as _sys

from llmwikify.apps.knowledge import web_search as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
