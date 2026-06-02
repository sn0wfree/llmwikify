"""Agent Backend Routes Package."""

from .agent import router as agent_router
from .ppt import router as ppt_router
from .research import router as research_router

__all__ = ["agent_router", "ppt_router", "research_router"]