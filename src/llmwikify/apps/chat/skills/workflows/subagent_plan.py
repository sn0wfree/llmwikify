"""SubagentPlan — the subagent tool loop as a plan on the shared runtime.

The subagent worker used to carry its own ReAct-style tool loop: a
``for`` loop with its own iteration cap, its own error fallback and its
own message bookkeeping. It now runs on the shared
:class:`llmwikify.kernel.agent.runtime.AgentRuntime` with this plan.

Like the chat plan, this is an **adapter**: the stages call the same
client and the same dispatcher the old loop did, so the messages, the
tool results and the token accounting are unchanged.

The loop is the same shape as the chat one — ask the model, run the
tools it asked for, feed the results back — which is why it belongs on
the shared runtime rather than in a fourth copy of it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from llmwikify.foundation.llm.streamable import LLMRequestError
from llmwikify.kernel.agent.runtime import AgentPlan

logger = logging.getLogger(__name__)

#: The cap of the tool loop — the same value the old loop used.
MAX_TOOL_ITER = 5

#: The HTTP statuses that must not be swallowed by the plain-chat
#: fallback (auth, rate limit, server errors).
_FATAL_STATUS = (401, 403, 429, 500, 502, 503)


class SubagentPlan(AgentPlan):
    """The subagent tool loop as a plan on the shared runtime.

    The result is not a stream of events but a ``(content, tokens)``
    pair, so the plan holds it — the caller reads it after the run.
    """

    def __init__(
        self,
        client: Any,
        messages: list[dict[str, Any]],
        tools_def: list[dict[str, Any]],
        handlers: dict[str, Any],
        *,
        max_iterations: int = MAX_TOOL_ITER,
        extract_content_and_tokens: Any,
        extract_tool_calls: Any,
        normalize_chat_result: Any,
        dispatch_tool_call: Any,
    ) -> None:
        self._client = client
        self._messages = messages
        self._tools_def = tools_def
        self._handlers = handlers
        self._extract_content_and_tokens = extract_content_and_tokens
        self._extract_tool_calls = extract_tool_calls
        self._normalize_chat_result = normalize_chat_result
        self._dispatch_tool_call = dispatch_tool_call

        self.max_iterations = max_iterations

        #: The result of the run.
        self.content = ""
        self.total_tokens = 0
        #: The loop fell back to a plain chat call.
        self._fallback = False
        #: How many rounds ran.
        self._rounds = 0

    # ── ROUND SETUP ───────────────────────────────────────────────

    async def before_iteration(self, rctx: Any) -> None:
        self._rounds += 1

    # ── REASON ────────────────────────────────────────────────────

    async def reason(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """Ask the model for the next step."""
        try:
            result = self._client.chat_with_tools(
                self._messages, tools=self._tools_def
            )
        except LLMRequestError as e:
            logger.error("subagent tool loop: chat_with_tools failed: %s", e)
            # Only fall back to plain chat for non-fatal errors
            # (e.g., tool-not-supported). For API/auth/rate-limit
            # errors, propagate immediately.
            if getattr(e, "status_code", 0) in _FATAL_STATUS:
                raise
            self._fallback_to_plain_chat()
            rctx.decision = None
            return
        except Exception as e:
            logger.error("subagent tool loop: chat_with_tools failed: %s", e)
            # Fall back to plain chat to recover.
            self._fallback_to_plain_chat()
            rctx.decision = None
            return

        content, tokens_inc = self._extract_content_and_tokens(result)
        self.total_tokens += tokens_inc
        self.content = content
        rctx.decision = self._extract_tool_calls(result) or None
        return
        yield {}  # pragma: no cover — makes this an async generator

    def _fallback_to_plain_chat(self) -> None:
        """Recover with a plain chat call (no tools)."""
        result = self._client.chat(messages=self._messages)
        self.content, self.total_tokens = self._normalize_chat_result(result)
        self._fallback = True

    # ── ACT ───────────────────────────────────────────────────────

    async def act(self, rctx: Any, decision: Any) -> AsyncIterator[dict[str, Any]]:
        """Run the tools the model asked for."""
        tool_calls = decision or []
        # Append the assistant message with tool_calls (OpenAI schema).
        self._messages.append(
            {
                "role": "assistant",
                "content": self.content,
                "tool_calls": [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": tc.get("args", ""),
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )

        # Execute each tool and append a tool-role message.
        for tc in tool_calls:
            output = self._dispatch_tool_call(tc, self._handlers)
            self._messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )

        rctx.result = self
        return
        yield {}  # pragma: no cover — makes this an async generator

    # ── FINALIZE ──────────────────────────────────────────────────

    async def finalize(self, rctx: Any) -> AsyncIterator[dict[str, Any]]:
        """The loop ended — nothing is streamed, the result is on the plan."""
        if not self._fallback and self._rounds >= self.max_iterations:
            logger.warning(
                "subagent tool loop hit MAX_TOOL_ITER=%d; returning last content",
                self.max_iterations,
            )
        return
        yield {}  # pragma: no cover — makes this an async generator


__all__ = ["SubagentPlan", "MAX_TOOL_ITER"]
