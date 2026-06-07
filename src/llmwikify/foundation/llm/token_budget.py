"""Token budget checker — check and log only, no truncation.

The checker estimates token usage for LLM requests and compares against
the model's context window. It logs structured data via standard logging
(with extra= parameters) and returns a TokenUsage record. It never
modifies the messages.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

from .context_windows import resolve_context_window
from .token_estimator import count_messages, count_tokens

logger = logging.getLogger("llmwikify.token_budget")


@dataclass(frozen=True)
class TokenUsage:
    """Token usage record for a single LLM call."""

    timestamp: float
    model: str
    prompt_name: str
    estimated_tokens: int
    context_window: int
    exceeds_window: bool
    message_count: int
    largest_message_tokens: int


@dataclass(frozen=True)
class TokenBudgetConfig:
    """Configuration for TokenBudgetChecker."""

    model: str = "gpt-4o"
    context_window: int | None = None  # None = auto-resolve
    reserve_output_tokens: int = 4096
    on_exceed: Literal["warn", "raise"] = "warn"
    base_url: str | None = None
    api_key: str | None = None


class TokenBudgetExceeded(Exception):
    """Raised when token budget is exceeded and on_exceed="raise"."""

    pass


class TokenBudgetChecker:
    """Token budget checker — check and log, never truncate.

    Usage::

        checker = TokenBudgetChecker(TokenBudgetConfig(model="gpt-4o"))
        usage = checker.check(messages, prompt_name="analyze_source")
        if usage.exceeds_window:
            # caller decides what to do
            pass
    """

    def __init__(self, config: TokenBudgetConfig | None = None) -> None:
        cfg = config or TokenBudgetConfig()
        self.model = cfg.model
        self.context_window = resolve_context_window(
            model=cfg.model,
            config_override=cfg.context_window,
            base_url=cfg.base_url,
            api_key=cfg.api_key,
        )
        self.reserve_output = cfg.reserve_output_tokens
        self.budget = self.context_window - self.reserve_output
        self.on_exceed = cfg.on_exceed
        self._usage_log: list[TokenUsage] = []

    def check(
        self,
        messages: list[dict[str, str]],
        prompt_name: str = "unknown",
    ) -> TokenUsage:
        """Check token budget and return usage record.

        When on_exceed="warn", always returns TokenUsage with
        exceeds_window=True/False. When on_exceed="raise", raises
        TokenBudgetExceeded on exceed.
        """
        total_tokens = count_messages(messages, self.model)

        # Find largest single message
        max_msg_tokens = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                msg_tokens = count_tokens(content, self.model)
                max_msg_tokens = max(max_msg_tokens, msg_tokens)

        exceeds = total_tokens > self.budget

        usage = TokenUsage(
            timestamp=time.time(),
            model=self.model,
            prompt_name=prompt_name,
            estimated_tokens=total_tokens,
            context_window=self.context_window,
            exceeds_window=exceeds,
            message_count=len(messages),
            largest_message_tokens=max_msg_tokens,
        )

        self._usage_log.append(usage)

        # Structured log via standard logging extra=
        log_extra = {
            "model": self.model,
            "prompt_name": prompt_name,
            "estimated_tokens": total_tokens,
            "context_window": self.context_window,
            "budget": self.budget,
            "exceeds_window": exceeds,
            "message_count": len(messages),
            "largest_message_tokens": max_msg_tokens,
        }

        pct = round(total_tokens / self.budget * 100, 1) if self.budget > 0 else 0

        if exceeds:
            logger.warning(
                "token_budget.exceeded: %d/%d tokens (%.1f%%) for '%s'",
                total_tokens,
                self.budget,
                pct,
                prompt_name,
                extra={**log_extra, "pct": pct},
            )
            if self.on_exceed == "raise":
                raise TokenBudgetExceeded(
                    f"Token budget exceeded: {total_tokens}/{self.budget} tokens "
                    f"({pct}%) for prompt '{prompt_name}'"
                )
        else:
            logger.info(
                "token_budget.ok: %d/%d tokens (%.1f%%) for '%s'",
                total_tokens,
                self.budget,
                pct,
                prompt_name,
                extra={**log_extra, "pct": pct},
            )

        return usage

    def get_stats(self) -> dict[str, Any]:
        """Get cumulative usage statistics."""
        if not self._usage_log:
            return {"total_calls": 0}
        total = len(self._usage_log)
        exceeded = sum(1 for u in self._usage_log if u.exceeds_window)
        return {
            "total_calls": total,
            "exceeded_count": exceeded,
            "exceeded_rate": round(exceeded / total, 3),
            "avg_tokens": sum(u.estimated_tokens for u in self._usage_log) // total,
            "max_tokens": max(u.estimated_tokens for u in self._usage_log),
            "context_window": self.context_window,
            "budget": self.budget,
        }
