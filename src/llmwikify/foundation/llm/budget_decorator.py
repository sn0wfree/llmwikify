"""Decorator for automatic token budget checking on LLM client methods.

Usage::

    from llmwikify.foundation.llm.budget_decorator import check_token_budget

    class MyLLMClient:
        def __init__(self):
            self._budget_checker = TokenBudgetChecker(...)

        @check_token_budget(lambda self: self._budget_checker)
        def chat(self, messages, **kwargs):
            ...

    # Callers pass _prompt_name to label the call in logs:
    client.chat(messages, _prompt_name="analyze_source", temperature=0.1)

The decorator:
1. Extracts _prompt_name from kwargs (defaults to function name)
2. Calls checker.check() with messages and prompt_name
3. Passes through to the original function
4. Handles generators and async generators transparently
"""

from __future__ import annotations

import functools
import inspect
from typing import Any, Callable, TypeVar

from .token_budget import TokenBudgetChecker

F = TypeVar("F", bound=Callable[..., Any])


def check_token_budget(checker_getter: Callable[..., TokenBudgetChecker]) -> Callable[[F], F]:
    """Decorator that checks token budget before LLM calls.

    Args:
        checker_getter: A callable that receives the instance (self) and returns
            the TokenBudgetChecker. Typically ``lambda self: self._budget_checker``.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Extract _prompt_name (consumed by decorator, not passed to API)
            prompt_name = kwargs.pop("_prompt_name", func.__name__)

            # Get messages: first positional arg after self, or from kwargs
            messages = kwargs.get("messages", [])
            if not messages and len(args) > 1:
                messages = args[1]  # args[0] is self, args[1] is messages

            # Run budget check
            if messages:
                checker = checker_getter(args[0]) if args else checker_getter()
                checker.check(messages, prompt_name=prompt_name)

            # Call original function
            result = func(*args, **kwargs)

            # Handle generators (sync)
            if inspect.isgeneratorfunction(func):
                return result  # generator is already lazy, check ran above

            # Handle async generators
            if inspect.isasyncgenfunction(func):
                return result  # async gen is already lazy, check ran above

            return result

        return wrapper  # type: ignore[return-value]

    return decorator
