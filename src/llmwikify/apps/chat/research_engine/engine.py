"""Back-compat shim — same module object as ``llmwikify.apps.research.engine``.

v0.40 moved the canonical implementation to
``llmwikify.apps.research.engine``. This shim preserves the old
import path ``from llmwikify.apps.chat.research_engine.engine``
so existing tests and external callers keep working.

The shim exposes the SAME module object as the canonical home (via
``sys.modules`` trick) so that ``mock.patch.object`` on either path
affects both — test compatibility.

Note: an earlier draft kept a PEP 562 ``__getattr__`` lazy fallback for
circular-import safety (``research_agent.py`` historically imported
this shim while ``apps.research.engine`` was mid-loading). That
concern is now moot: ``research_agent.py`` uses a ``TYPE_CHECKING``
guard plus a lazy local import in ``__init__``, so the eager
``from llmwikify.apps.research import engine`` below is safe.
"""
import sys as _sys

from llmwikify.apps.research import engine as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
