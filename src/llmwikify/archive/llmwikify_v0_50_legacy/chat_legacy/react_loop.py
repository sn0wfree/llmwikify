"""Generic ReAct loop framework — thin backward-compat wrapper.

The canonical implementation is in :mod:`react_engine`.
This module re-exports all public symbols for backward compatibility.

New code should import directly from ``react_engine``.
"""

from llmwikify.archive.llmwikify_v0_50_legacy.chat_legacy.react_engine import (  # noqa: F401
    ReactConfig,
    ReactLoop,
    ReActConfig,
    ReActEngine,
    EVENT_REASONING,
    EVENT_ACTION_ERROR,
    EVENT_ROUND_COMPLETE,
    EVENT_PHASE,
    EVENT_OBSERVATION_ERROR,
    EVENT_TIMEOUT,
    ReasonCallable,
    ObserveCallable,
    OnBeforeActHook,
    OnAfterActHook,
    OnBeforeObserveHook,
    OnAfterObserveHook,
    PersistStateHook,
    RestoreStateHook,
    DoneConditionHook,
)

__all__ = [
    "ReactConfig",
    "ReactLoop",
    "ReActConfig",
    "ReActEngine",
    "ReasonCallable",
    "ObserveCallable",
    "OnBeforeActHook",
    "OnAfterActHook",
    "OnBeforeObserveHook",
    "OnAfterObserveHook",
    "PersistStateHook",
    "RestoreStateHook",
    "DoneConditionHook",
    "EVENT_REASONING",
    "EVENT_ACTION_ERROR",
    "EVENT_ROUND_COMPLETE",
    "EVENT_PHASE",
    "EVENT_OBSERVATION_ERROR",
    "EVENT_TIMEOUT",
]
