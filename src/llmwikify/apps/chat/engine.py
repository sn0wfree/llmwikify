"""Back-compat shim — same module object as ``llmwikify.apps.research.engine``.

The v0.40 refactor (Phase 4) moved research logic from
``llmwikify.apps.chat.research_engine.engine`` to the canonical home
``llmwikify.apps.research.engine``. This shim preserves the old
import path ``from llmwikify.apps.chat import engine`` so existing
tests and external callers keep working.

The shim exposes the SAME module object as the canonical home (via
``sys.modules`` trick) so that ``from llmwikify.apps.chat import engine``
and ``from llmwikify.apps.research.engine`` refer to the same module.

New code should import from ``llmwikify.apps.research.engine`` directly.
"""
import sys as _sys

from llmwikify.apps.research import engine as _canonical  # noqa: F401

_sys.modules[__name__] = _canonical
