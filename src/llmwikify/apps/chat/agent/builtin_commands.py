"""Built-in slash command handlers (Pass6, 2026-06-22).

Module-level handlers extracted from
``ChatOrchestrator._build_default_command_router`` so each command
is independently testable and the orchestrator stays declarative.

All handlers receive the standard :class:`CommandContext` (vendored
from nanobot command/router.py) and produce one or more event dicts
in the chat SSE vocabulary. Handlers MUST return either a dict
(single event) or an AsyncIterator[dict] (multiple events).

The 8 built-ins:

  - ``/stop`` (priority) — abort the active session.
  - ``/help`` (exact) — list available commands.
  - ``/clear`` (exact) — clear the in-memory context.
  - ``/status`` (exact) — report session status.
  - ``/title <text>`` (prefix) — set session title.
  - ``/memory_dream [session <id>]`` (prefix) — trigger fact extractor.
  - ``/goal [<objective> | done [recap]]`` (prefix) — long-goal CRUD.

Phase 6 (2026-06-19) added ``/memory_dream`` (borrowed from nanobot
agent/memory.py:859, distinct from the existing ``/wiki_dream``
slash command which wraps ``apps/agent/wiki_dream_editor/``).
Phase 8 (2026-06-20) added ``/goal`` (long-goal skill wrapper).

Pass4-C (2026-06-22) fixed a latent bug: ``/memory_dream`` previously
injected ``memory_manager=None`` (CommandContext doesn't carry that
field), so the handler was always disabled. The handler now accepts
``memory_manager`` as an explicit kwarg from the registration site
(``ChatOrchestrator`` passes ``self.memory_manager``).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from llmwikify.apps.chat.command_router import CommandContext, CommandRouter

logger = logging.getLogger(__name__)


# ─── Event factory (decoupled from ChatEvent class) ────────────


def command_done_event(
    command: str, ok: bool, message: str, data: Any = None,
) -> dict:
    """Build a ``command_done`` SSE event dict.

    Decoupled from :class:`ChatEvent.command_done` so builtin
    commands can live in a separate module without importing the
    full ``ChatEvent`` factory cluster (which carries 12 methods).

    Mirrors the wire shape produced by ``ChatEvent.command_done``
    (orchestrator.py:87-98). If ``data`` is None, the ``data`` key
    is omitted (matching the original factory's behaviour).
    """
    ev: dict[str, Any] = {
        "type": "command_done",
        "command": command,
        "ok": ok,
        "message": message,
    }
    if data is not None:
        ev["data"] = data
    return ev


# ─── Skill stub helper (mirrors orchestrator._make_skill_ctx) ───


def make_skill_ctx(
    cmd_ctx: Any,
    *,
    include_db: bool = False,
    memory_manager: Any = None,
) -> Any:
    """Build a SkillContext-shaped object from a CommandContext.

    Mirrors :func:`llmwikify.apps.chat.agent.orchestrator._make_skill_ctx`
    (Pass4-C). Duplicated here to avoid an import cycle (orchestrator
    imports builtin_commands; if builtin_commands imported orchestrator
    we'd get a circular import at module-load time).

    Skill handlers (memory_dream / goal) need ``session_id`` + ``db`` +
    ``config["memory_manager"]``. CommandContext doesn't expose those,
    so we wrap.
    """
    class _StubSkillContext:
        pass

    stub = _StubSkillContext()
    stub.session_id = cmd_ctx.session_id or ""
    if include_db:
        stub.db = cmd_ctx.db
    stub.config = {}
    if memory_manager is not None:
        stub.config["memory_manager"] = memory_manager
    return stub


# ─── Handlers ────────────────────────────────────────────────────


async def stop_handler(ctx: Any) -> dict:
    """``/stop`` (priority) — abort the active session."""
    if ctx.abort_event is not None:
        ctx.abort_event.set()
    return command_done_event("/stop", True, "Session aborted")


async def help_handler(ctx: Any) -> dict:
    """``/help`` (exact) — list available commands."""
    return command_done_event(
        "/help",
        True,
        (
            "Available commands: /stop, /help, /clear, /status, "
            "/title <text>, /memory_dream [session <id>], "
            "/goal [<objective> | done [recap]]"
        ),
    )


async def clear_handler(ctx: Any) -> dict:
    """``/clear`` (exact) — clear the in-memory context."""
    if ctx.ctx is not None and hasattr(ctx.ctx, "clear"):
        ctx.ctx.clear()
    return command_done_event("/clear", True, "Context cleared")


async def status_handler(ctx: Any) -> dict:
    """``/status`` (exact) — report session status."""
    return command_done_event(
        "/status",
        True,
        f"session_id={ctx.session_id} wiki_id={ctx.wiki_id}",
    )


async def title_handler(ctx: Any) -> dict:
    """``/title <text>`` (prefix) — set session title."""
    new_title = (ctx.args or "").strip()
    if not new_title:
        return command_done_event("/title", False, "Usage: /title <text>")
    if ctx.db is not None and ctx.session_id:
        try:
            ctx.db.update_chat_session_title(ctx.session_id, new_title)
        except Exception:
            pass
    return command_done_event(
        "/title", True, f"Title set: {new_title[:50]}",
    )


async def memory_dream_handler(ctx: Any, *, memory_manager: Any = None) -> AsyncIterator[dict]:
    """``/memory_dream [session <id>]`` (prefix) — fact extractor.

    Triggers the long-term fact extractor (borrowed from nanobot
    agent/memory.py:859). Distinct from the existing ``/wiki_dream``
    slash command which wraps ``apps/agent/wiki_dream_editor/``.

    Args:
        ctx: CommandContext from CommandRouter.
        memory_manager: Optional MemoryManager. Pass ``None`` (default)
            to short-circuit to "dream not configured".
    """
    from llmwikify.apps.chat.skills.crud.memory_dream_skill import (
        _get_dream,
        _run,
        _run_for_session,
    )

    stub = make_skill_ctx(ctx, memory_manager=memory_manager)
    dream = _get_dream(stub)
    if isinstance(dream, dict) and dream.get("ok") is False:
        yield command_done_event(
            "/memory_dream",
            False,
            dream.get("message", "dream not configured"),
        )
        return

    args_text = (ctx.args or "").strip()
    if args_text.startswith("session "):
        sid = args_text[len("session "):].strip()
        result = await _run_for_session({"session_id": sid}, stub)
    else:
        result = await _run({}, stub)

    yield command_done_event(
        "/memory_dream",
        result.ok if hasattr(result, "ok") else True,
        (
            result.message
            if hasattr(result, "message") and not result.ok
            else "dream complete"
        ),
        data=getattr(result, "data", None),
    )


def _summarize_goal(args_text: str, res: Any) -> str:
    """Format a GoalSkill result into a user-facing summary line.

    Mirrors the inner helper from orchestrator's old inline goal handler.
    """
    data = getattr(res, "data", None) or {}
    if not args_text:
        if not data.get("active"):
            return "No active goal"
        g = data.get("goal", {})
        return f"Active: {g.get('objective', '')[:100]}"
    if args_text.lower() == "done" or args_text.lower().startswith("done "):
        if data.get("completed"):
            return f"Completed: {data.get('objective', '')[:80]}"
        return data.get("reason", "no active goal")
    return f"Goal registered: {data.get('objective', '')[:100]}"


async def goal_handler(ctx: Any) -> dict:
    """``/goal [<objective> | done [recap]]`` (prefix) — long-goal CRUD.

    Thin wrapper around GoalSkill so users get the same ChatRunner
    ergonomics from the chat input box.

      - ``/goal``                    → show current goal
      - ``/goal <objective text>``   → start_long_task (objective=text)
      - ``/goal done [recap text]``  → complete_goal (recap=text)
    """
    from llmwikify.apps.chat.skills.crud.goal_skill import (
        _complete_goal,
        _get_goal,
        _start_long_task,
    )

    stub = make_skill_ctx(ctx, include_db=True)
    args_text = (ctx.args or "").strip()

    if not args_text:
        result = await _get_goal({}, stub)
    elif args_text.lower() == "done" or args_text.lower().startswith("done "):
        recap = args_text[4:].strip() if len(args_text) > 4 else ""
        result = await _complete_goal({"recap": recap}, stub)
    else:
        result = await _start_long_task(
            {"goal": args_text, "ui_summary": args_text[:120]},
            stub,
        )

    ok = getattr(result, "status", "ok") == "ok"
    return command_done_event(
        "/goal",
        ok,
        (
            getattr(result, "error", "") or "goal command failed"
            if not ok
            else _summarize_goal(args_text, result)
        ),
        data=getattr(result, "data", None),
    )


# ─── Memory dream wrapper (binds memory_manager at registration) ──


def make_memory_dream_handler(memory_manager: Any):
    """Bind ``memory_manager`` once and return a ``CommandContext``-only handler.

    Pass4-C fix: prior code did ``getattr(ctx, "memory_manager", None)`` which
    always returned None (CommandContext doesn't carry the field). Now the
    orchestrator passes its ``self.memory_manager`` once at registration time.
    """
    async def handler(ctx: Any) -> AsyncIterator[dict]:
        async for ev in memory_dream_handler(ctx, memory_manager=memory_manager):
            yield ev
    return handler


# ─── Registration ────────────────────────────────────────────────


def register_builtin_commands(
    router: Any,
    *,
    memory_manager: Any = None,
) -> Any:
    """Register all 8 built-in slash commands on *router*.

    Returns the router for chaining.

    Args:
        router: A :class:`CommandRouter` instance.
        memory_manager: Optional MemoryManager for ``/memory_dream``.
            Pass ``None`` to short-circuit that command.
    """
    router.priority("/stop", stop_handler)
    router.exact("/help", help_handler)
    router.exact("/clear", clear_handler)
    router.exact("/status", status_handler)
    router.prefix("/title", title_handler)
    router.prefix("/memory_dream", make_memory_dream_handler(memory_manager))
    router.prefix("/goal", goal_handler)
    return router


__all__ = [
    "command_done_event",
    "make_skill_ctx",
    "stop_handler",
    "help_handler",
    "clear_handler",
    "status_handler",
    "title_handler",
    "memory_dream_handler",
    "goal_handler",
    "make_memory_dream_handler",
    "register_builtin_commands",
]
