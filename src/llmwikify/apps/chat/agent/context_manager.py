"""ContextManager — runtime conversation state for active sessions.

Extracted from ChatService (v0.41) to separate request-scoped state
management from the agent loop and prompt construction.

Manages:
  - AgentContext (in-memory per-session working state)
  - Token-aware message truncation
  - LLM-based message compaction (summarization)
  - ContextStore (LRU + TTL eviction)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from llmwikify.apps.chat.agent.context_store import ContextStore
from llmwikify.foundation.llm.token_estimator import count_messages

logger = logging.getLogger(__name__)


# ─── AgentContext dataclass ────────────────────────────────────


@dataclass
class AgentContext:
    """In-memory conversation state for one session."""

    wiki_id: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    recent_wiki_id: str | None = None
    _tool_calls: dict[str, Any] = field(default_factory=dict)

    # ReAct state tracking
    react_observations: list[str] = field(default_factory=list)
    react_thoughts: list[str] = field(default_factory=list)
    react_round: int = 0
    _thinking: str = ""

    # Config-driven limits
    _observation_limit: int = 10
    _observation_summary_limit: int = 5

    def add_user_message(self, content: str) -> None:
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict[str, str]]:
        return list(self.messages)

    def set_recent_wiki(self, wiki_id: str) -> None:
        self.recent_wiki_id = wiki_id

    def add_observation(self, observation: str) -> None:
        """Track a ReAct observation from a tool call result."""
        self.react_observations.append(observation)
        if len(self.react_observations) > self._observation_limit:
            self.react_observations = self.react_observations[-self._observation_limit:]

    def add_thought(self, thought: str) -> None:
        """Track a ReAct thought from the LLM reasoning step."""
        if thought:
            self.react_thoughts.append(thought)
            if len(self.react_thoughts) > self._observation_limit:
                self.react_thoughts = self.react_thoughts[-self._observation_limit:]

    def get_observations_summary(self) -> str:
        """Generate a summary of recent observations for prompt injection."""
        if not self.react_observations:
            return ""
        lines = ["## Recent tool observations"]
        for i, obs in enumerate(self.react_observations[-self._observation_summary_limit:], 1):
            lines.append(f"{i}. {obs}")
        return "\n".join(lines)


# ─── ContextManager ────────────────────────────────────────────


class ContextManager:
    """Manages in-memory conversation state for active sessions.

    Owns the ContextStore (LRU + TTL eviction) and provides
    token-aware message preparation (compaction + truncation).
    """

    def __init__(self, config: dict | None = None, llm_client: Any = None):
        from llmwikify.apps.chat.config import merge_six_step_config
        self.config = config or merge_six_step_config()
        self._llm_client = llm_client
        self._contexts = ContextStore(
            max_size=self.config.get("context_store_max_size", 200),
            ttl_seconds=self.config.get("context_store_ttl_seconds", 1800),
        )

    def set_llm_client(self, llm_client: Any) -> None:
        """Set the LLM client (called after construction)."""
        self._llm_client = llm_client

    async def get_or_create(
        self,
        session_id: str,
        wiki_id: str | None,
        history_loader: Callable,
        db: Any = None,
    ) -> AgentContext:
        """Get existing context or create a new one.

        Args:
            session_id: The session ID.
            wiki_id: Optional wiki ID.
            history_loader: Async callable that returns message history.
            db: ChatDatabase for session lookup.
        """
        ctx = self._contexts.get(session_id)
        if ctx is None:
            ctx = AgentContext(
                wiki_id=wiki_id,
                _observation_limit=self.config.get("observation_limit", 10),
                _observation_summary_limit=self.config.get("observation_summary_limit", 5),
            )
            # Restore conversation history
            db_messages = await history_loader(session_id)
            for msg in db_messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if role == "user":
                    ctx.messages.append({"role": "user", "content": content})
                elif role == "assistant":
                    ctx.messages.append({"role": "assistant", "content": content})
            # Restore wiki_id from session
            if not wiki_id and db is not None:
                session = db.get_chat_session(session_id)
                if session and session.get("wiki_id"):
                    ctx.set_recent_wiki(session["wiki_id"])
            self._contexts.set(session_id, ctx)
        return self._contexts.get(session_id)

    async def prepare_messages(
        self,
        messages: list[dict[str, str]],
        wiki_service: Any = None,
    ) -> list[dict[str, str]]:
        """Truncate and compact messages for LLM consumption."""
        messages = await self.compact(messages, wiki_service)
        messages = self.truncate(messages)
        return messages

    def remove(self, session_id: str) -> None:
        """Remove a session's context."""
        self._contexts.remove(session_id)

    @property
    def stats(self) -> dict:
        return self._contexts.stats

    # ─── Compaction ────────────────────────────────────────────

    async def compact(
        self,
        messages: list[dict[str, str]],
        wiki_service: Any = None,
    ) -> list[dict[str, str]]:
        """Summarize older messages when context is near capacity."""
        if not self.config.get("compaction_enabled", True):
            return messages

        if len(messages) <= self.config.get("compaction_min_messages", 6):
            return messages

        model_name = self._get_model_name()
        budget = self._compute_budget()
        current_tokens = count_messages(messages, model_name)
        threshold = budget * self.config.get("compaction_threshold_ratio", 0.8)

        if current_tokens < threshold:
            return messages

        system = messages[0]
        keep_recent = 4
        if len(messages) <= keep_recent + 1:
            return messages

        old_messages = messages[1:-(keep_recent)]
        recent_messages = messages[-(keep_recent):]

        max_compact_tokens = self.config.get("compaction_max_tokens", 4000)
        compact_text_parts: list[str] = []
        compact_tokens = 0
        for msg in old_messages:
            msg_text = f"{msg['role']}: {msg['content']}"
            msg_tokens = count_messages([msg], model_name)
            if compact_tokens + msg_tokens > max_compact_tokens:
                break
            compact_text_parts.append(msg_text)
            compact_tokens += msg_tokens

        if not compact_text_parts:
            return messages

        compact_text = "\n".join(compact_text_parts)

        try:
            summary_prompt = [
                {"role": "system", "content": (
                    "Summarize the following conversation into a concise brief. "
                    "Preserve key facts, decisions, and context. "
                    "Output ONLY the summary, no preamble."
                )},
                {"role": "user", "content": compact_text},
            ]
            llm = wiki_service.get_llm() if wiki_service else self._llm_client
            response = await llm.achat(
                messages=summary_prompt,
                temperature=0.1,
                max_tokens=1024,
            )
            summary_content = response.get("content", "")
            if not summary_content:
                return messages

            summary_msg = {
                "role": "system",
                "content": f"[Conversation summary]\n{summary_content}",
            }
            logger.info(
                "Compacted %d messages (%d tokens) into summary (%d tokens)",
                len(compact_text_parts),
                compact_tokens,
                count_messages([summary_msg], model_name),
            )
            return [system, summary_msg] + recent_messages

        except Exception:
            logger.warning("Compaction failed, falling back to truncation", exc_info=True)
            return messages

    # ─── Truncation ────────────────────────────────────────────

    def truncate(
        self,
        messages: list[dict[str, str]],
        max_messages: int | None = None,
    ) -> list[dict[str, str]]:
        """Truncate messages to fit within the model's context window."""
        if not messages:
            return messages

        model_name = self._get_model_name()
        budget = self._compute_budget()

        system = messages[0]
        system_tokens = count_messages([system], model_name)

        if system_tokens >= budget:
            return [system]

        remaining = budget - system_tokens
        kept: list[dict[str, str]] = []
        kept_tokens = 0
        for msg in reversed(messages[1:]):
            msg_tokens = count_messages([msg], model_name)
            if kept_tokens + msg_tokens > remaining:
                break
            kept.append(msg)
            kept_tokens += msg_tokens

        kept.reverse()
        dropped = len(messages) - 1 - len(kept)

        if not kept and len(messages) > 1 and dropped > 0:
            max_msgs = max_messages or self.config.get("max_messages", 50)
            kept = messages[-(max_msgs):]
            dropped = len(messages) - 1 - len(kept)

        if dropped > 0:
            summary_note = {
                "role": "system",
                "content": f"[Note: {dropped} earlier messages omitted for context window management]",
            }
            return [system, summary_note] + kept
        return [system] + kept

    # ─── Internal helpers ──────────────────────────────────────

    def _get_model_name(self) -> str:
        if self._llm_client is not None:
            return getattr(self._llm_client, "model", "gpt-4o")
        return "gpt-4o"

    def _compute_budget(self) -> int:
        """Compute available token budget (shared by compact/truncate)."""
        reserve = self.config.get("context_reserve_tokens", 4096)
        override = self.config.get("context_window_override", 0)
        if override > 0:
            return override - reserve
        if self._llm_client is not None:
            budget_checker = getattr(self._llm_client, "_budget_checker", None)
            if budget_checker is not None:
                return budget_checker.context_window - reserve
        return 128_000 - reserve
