"""Back-compat shim — same module object as ``llmwikify.apps.knowledge.db``.

The research artifact store moved to the shared substrate
``llmwikify.apps.knowledge.db`` so that ``apps.chat`` and
``apps.research`` no longer import each other (see
``llmwikify.apps.knowledge``).

This shim preserves the old import path
``from llmwikify.apps.research.db import ResearchDatabase`` and exposes
the SAME module object (via the ``sys.modules`` trick), so
``mock.patch`` on either path affects both.

New code should import from ``llmwikify.apps.knowledge.db``.
"""

import sys as _sys

from llmwikify.apps.knowledge import db as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
