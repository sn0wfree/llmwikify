"""Status 路由 — 系统状态/指标/工具。"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from llmwikify.interfaces.server.http._helpers import get_wiki_id
from llmwikify.interfaces.server.http.agent._common import (
    get_agent_service,
    router,
)


@router.get("/status")
async def agent_status(request: Request) -> Any:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    try:
        return service.get_agent_status(wiki_id)
    except (KeyError, ValueError):
        return {
            "state": "idle",
            "scheduler_tasks": [],
            "pending_work": {},
            "action_log": [],
            "pending_confirmations": 0,
            "wiki_dream_proposals": {},
            "unread_notifications": 0,
        }

# --- LLM metrics endpoint (Pass7, Phase 8, 2026-06-22) ---

@router.get("/llm-metrics")
async def llm_metrics() -> Any:
    """Return aggregate LLM-call metrics from the process-wide collector.

    Backed by ``LLMMetricsCollector`` (apps/chat/agent/llm_metrics.py)
    which is populated by ``ChatRunnerV2._stream_llm`` via
    ``measure_latency()`` CM (decorator-pattern CM, see Pass5).

    Returns:
        JSON summary with ``total_records``, ``success_count``,
        ``error_count``, ``total_latency_ms``, ``avg_latency_ms``,
        ``total_chars_in``, ``uptime_seconds``, ``by_prompt`` (per-prompt
        aggregates), and ``recent`` (last 20 records).
    """
    from llmwikify.apps.chat.agent.llm_metrics import (
        get_llm_metrics_collector,
    )
    return get_llm_metrics_collector().summary()


# --- Research run endpoints ---

@router.get("/research-runs/{run_id}")
async def get_research_run(run_id: str) -> Any:
    service = get_agent_service()
    return service.get_research_run_status(run_id)


# --- Tools endpoint ---

@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    wiki_id = get_wiki_id(request)
    service = get_agent_service()
    if wiki_id:
        registry = service._get_tool_registry(wiki_id)
    else:
        registry = service._get_tool_registry(None)
    return {"tools": registry.list_tools()}
