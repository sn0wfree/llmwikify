"""Back-compat shim — same module object as ``llmwikify.apps.research.actions``.

v0.40 moved the canonical implementation to
``llmwikify.apps.research.actions``. This shim preserves the old
import path ``from llmwikify.apps.chat.research_engine.actions``
and ``from llmwikify.apps.chat import actions`` so existing tests
and external callers keep working.

The shim exposes the SAME module object as the canonical home (via
``sys.modules`` trick) so that ``mock.patch.object`` on either path
affects both — test compatibility.
"""
import sys as _sys

from llmwikify.apps.research import actions as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
