"""Backward-compat shim: WikiToolRegistry 已移 apps/wiki/tool_registry.py,
handle_get_skill_commands/SKILL_COMMANDS_TOOL 已移
apps/chat/skills/commands_tool.py.

新代码应直接:
    from llmwikify.apps.wiki.tool_registry import WikiToolRegistry
    from llmwikify.apps.chat.skills.commands_tool import handle_get_skill_commands

The re-exports are lazy (PEP 562) so this shim does not create an
import-time ``agent → chat`` edge — that is exactly the dependency the
move was meant to remove.
"""

from __future__ import annotations

from typing import Any

__all__ = ["WikiToolRegistry", "handle_get_skill_commands", "SKILL_COMMANDS_TOOL"]

_EXPORTS = {
    "WikiToolRegistry": "llmwikify.apps.wiki.tool_registry",
    "handle_get_skill_commands": "llmwikify.apps.chat.skills.commands_tool",
    "SKILL_COMMANDS_TOOL": "llmwikify.apps.chat.skills.commands_tool",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        from importlib import import_module

        mod = import_module(_EXPORTS[name])
        value = getattr(mod, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
