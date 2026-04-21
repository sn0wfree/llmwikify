"""llmwikify Agent - Autonomous wiki maintenance layer.

Optional enhancement that calls existing Core functions.
Install via: pip install llmwikify[agent]
"""

from __future__ import annotations

from .wiki_agent import WikiAgent

__all__ = ["WikiAgent"]
