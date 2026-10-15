"""Shim identity contract — v0.40 refactor Phase 4.

After the refocus, research logic moved from
``llmwikify.apps.chat.research_engine.*`` to the canonical home
``llmwikify.apps.research.*``. Three new top-level shims were added so
existing callers keep working:

  * ``llmwikify.apps.chat.actions``  → ``llmwikify.apps.research.actions``
  * ``llmwikify.apps.chat.engine``   → ``llmwikify.apps.research.engine``
  * ``llmwikify.apps.chat.report``   → ``llmwikify.apps.research.report``

The shims use the ``sys.modules[__name__] = _canonical`` trick so that:

  1. Both import paths refer to the **same module object** (identity).
  2. ``mock.patch.object(canonical, ...)`` patches the shim too, and
     vice versa. This is what makes the existing test suite keep working
     when it mixes ``from llmwikify.apps.chat import actions`` with
     ``unittest.mock.patch.object(llmwikify.apps.research.actions, ...)``.

If any of these tests fail, downstream tests using
``mock.patch`` on the shim path will silently patch the wrong module.
Refs: plan/v0.40-refocus.md Phase 4, plan/v0.40-release-notes-draft.md.
"""

from __future__ import annotations

import sys
from unittest import mock

import pytest


@pytest.mark.parametrize(
    "shim_path",
    [
        "llmwikify.apps.chat.actions",
        "llmwikify.apps.chat.engine",
        "llmwikify.apps.chat.report",
    ],
)
def test_top_level_shim_resolves(shim_path):
    """Importing each new shim module succeeds (no ImportError)."""
    mod = __import__(shim_path, fromlist=["__name__"])
    assert mod is not None


@pytest.mark.parametrize(
    ("shim_path", "canonical_path"),
    [
        ("llmwikify.apps.chat.actions", "llmwikify.apps.research.actions"),
        ("llmwikify.apps.chat.engine", "llmwikify.apps.research.engine"),
        ("llmwikify.apps.chat.report", "llmwikify.apps.research.report"),
    ],
)
def test_shim_is_same_module_object_as_canonical(shim_path, canonical_path):
    """Both import paths point to the SAME module object (identity).

    This is what ``sys.modules[__name__] = _canonical`` is for.
    """
    shim = __import__(shim_path, fromlist=["__name__"])
    canonical = __import__(canonical_path, fromlist=["__name__"])
    assert shim is canonical, (
        f"{shim_path} and {canonical_path} must be the same module object; "
        f"got shim={shim!r} canonical={canonical!r}"
    )


def test_shim_identity_in_sys_modules():
    """sys.modules records the shim path under the canonical object."""
    import llmwikify.apps.chat.actions as shim_actions
    import llmwikify.apps.research.actions as canonical_actions

    assert sys.modules["llmwikify.apps.chat.actions"] is canonical_actions
    assert sys.modules["llmwikify.apps.research.actions"] is canonical_actions
    assert shim_actions is canonical_actions


def test_mock_patch_on_canonical_propagates_to_shim():
    """``mock.patch.object`` on the canonical path affects the shim too.

    This is the regression-guard the v0.40 release notes claim:
    "patching one affects the other (test compatibility)".
    """
    import llmwikify.apps.chat.actions as shim_actions
    import llmwikify.apps.research.actions as canonical_actions

    sentinel = mock.MagicMock(name="patched_function")
    with mock.patch.object(canonical_actions, "some_attr", sentinel, create=True):
        # Same object → same __dict__ → patch visible from both paths
        assert shim_actions.some_attr is sentinel
        assert canonical_actions.some_attr is sentinel


def test_research_engine_shims_still_work():
    """The older ``apps.chat.research_engine.*`` paths also resolve.

    These were the *original* Phase 4 shims; verify they still exist and
    forward to the canonical research modules.
    """
    import llmwikify.apps.chat.research_engine.actions as re_actions
    import llmwikify.apps.research.actions as canonical_actions

    assert re_actions is canonical_actions
