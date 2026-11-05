"""get_skill_commands tool — discover available skill triggers.

Moved from ``apps/agent/tools/`` — it is a chat-skill discovery
tool; keeping it under ``agent/`` made ``agent`` depend on
``chat``'s skill registry.
"""

from __future__ import annotations

from typing import Any


async def handle_get_skill_commands(args: dict[str, Any], ctx: Any) -> Any:
    """Return all available skill triggers/commands.

    The LLM calls this tool to discover which ``/commands`` are
    available.  The response contains trigger strings, the
    underlying tool name, and the parameter to fill.
    """
    from llmwikify.apps.chat.skills.registry import default_registry

    registry = default_registry()
    commands = registry.all_triggers()
    return {
        "commands": commands,
        "count": len(commands),
        "usage": (
            "When a user types a trigger (e.g. /study), call "
            "skill_action with the skill, action, and the user's "
            "input as the trigger parameter."
        ),
    }


SKILL_COMMANDS_TOOL = {
    "name": "get_skill_commands",
    "handler": handle_get_skill_commands,
    "description": "List all available skill commands and triggers",
    "action_type": "read",
    "requires_confirmation": False,
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
