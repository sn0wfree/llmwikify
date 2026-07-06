"""Back-compat shim — same module object as ``llmwikify.apps.research.actions``.

The v0.40 refactor (Phase 4) moved research logic from
``llmwikify.apps.chat.research_engine.actions`` to the canonical home
``llmwikify.apps.research.actions``. This shim preserves the old
import path ``from llmwikify.apps.chat import actions`` so existing
tests and external callers keep working.

The shim exposes the SAME module object as the canonical home (via
``sys.modules`` trick) so that:

  * ``from llmwikify.apps.chat import actions; actions.foo`` and
    ``from llmwikify.apps.research.actions import actions; actions.foo``
    refer to the same identity (important for ``mock.patch.object``).
  * Type checks like ``isinstance(x, Y)`` work across both import paths.

New code should import from ``llmwikify.apps.research.actions`` directly.
"""
import sys as _sys

from llmwikify.apps.research import actions as _canonical  # noqa: F401

# Make ``llmwikify.apps.chat.actions`` and
# ``llmwikify.apps.research.actions`` the same module object so that
# patching one affects the other (test compatibility).
_sys.modules[__name__] = _canonical
