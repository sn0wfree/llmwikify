"""Agent 路由共享基础设施。

提供 router、AgentService 单例、JsonBodyHelper 等共享组件。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from llmwikify.apps.chat.agent.agent_service import AgentService
from llmwikify.interfaces.server.http._handlers import (
    ParseJsonHandler,
    ReadBodyHandler,
    ValidateModelHandler,
)
from llmwikify.interfaces.server.http._helpers import Helper

logger = logging.getLogger(__name__)

# ─── Router ────────────────────────────────────────────────────

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ─── AgentService 单例 ─────────────────────────────────────────

AGENT_SERVICE: AgentService | None = None


def set_agent_service(service: AgentService) -> None:
    """设置全局 AgentService 实例。"""
    global AGENT_SERVICE
    AGENT_SERVICE = service


def get_agent_service() -> AgentService:
    """获取全局 AgentService 实例。未初始化时抛出 RuntimeError。"""
    if AGENT_SERVICE is None:
        raise RuntimeError("Agent service not initialized")
    return AGENT_SERVICE


# ─── JsonBodyHelper: JSON body 解析链 ──────────────────────────

JsonBodyHelper = (
    Helper()
    .add_handler(ReadBodyHandler())
    .add_handler(ParseJsonHandler())
    .add_handler(ValidateModelHandler())
)
