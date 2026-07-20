"""Config 路由 — LLM 配置管理。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from fastapi import Request

from llmwikify.interfaces.server.http._models import SaveConfigRequest
from llmwikify.interfaces.server.http.agent._common import (
    JsonBodyHelper,
    get_agent_service,
    router,
)

logger = logging.getLogger(__name__)


# ─── Config helper ─────────────────────────────────────────────

async def _get_config_data() -> dict:
    """组装配置数据（mutable + research_mutable + system_prompt）。"""
    from llmwikify.apps.chat.config import get_mutable_defaults
    from llmwikify.apps.chat.config_manager import get_global_config_manager

    manager = get_global_config_manager()
    llm_cfg = manager.load_effective_llm_config()
    result = manager.mask_api_key(llm_cfg)

    # v0.41: 附加 chat_mutable 和 research_mutable
    mutable_defaults = get_mutable_defaults()
    result["chat_mutable"] = mutable_defaults
    # research_mutable 直接读取 YAML
    try:
        _research_yaml = Path(__file__).parent.parent.parent.parent.parent / "apps" / "research" / "config_defaults.yaml"
        if _research_yaml.exists():
            raw = yaml.safe_load(_research_yaml.read_text(encoding="utf-8"))
            result["research_mutable"] = raw.get("mutable", {})
        else:
            result["research_mutable"] = {}
    except Exception:
        result["research_mutable"] = {}

    # v0.40: include custom system prompt from user preferences
    try:
        service = get_agent_service()
        if service.memory_manager:
            prefs = await service.memory_manager.preferences.aall("default")
            result["system_prompt"] = prefs.get("system_prompt", "")
    except Exception:
        result["system_prompt"] = ""
    return result


# ─── Config 端点 ───────────────────────────────────────────────

@router.get("/config")
async def get_llm_config() -> Any:
    """GET /config — return mutable LLM config + chat_mutable + research_mutable.

    v0.41: API 只暴露 mutable 配置。immutable 配置不出现在返回中。
    如需调试 immutable，可使用 GET /config/debug (内部端点)。
    """
    return await _get_config_data()


@router.put("/config")
async def save_llm_config(request: Request) -> dict[str, Any]:
    """PUT /config — save mutable LLM config fields.

    v0.41: 只接受 mutable 字段。immutable 字段（如果客户端发送）会被忽略。
    """
    from llmwikify.apps.chat.config_manager import get_global_config_manager
    req = await JsonBodyHelper.execute(request, SaveConfigRequest)
    manager = get_global_config_manager()
    # Preserve real api_key: if the incoming key is masked (contains ***),
    # keep the original value from the existing config.
    config_dict = req.model_dump(exclude_none=True)
    incoming_key = config_dict.get("api_key", "")
    if incoming_key and "***" in incoming_key:
        current = manager.load_effective_llm_config()
        config_dict["api_key"] = current.get("api_key", incoming_key)
    # v0.40: system_prompt is stored in user preferences, not LLM config
    system_prompt = config_dict.pop("system_prompt", None)
    # v0.41: chat_mutable 和 research_mutable 暂不通过此端点保存
    config_dict.pop("chat_mutable", None)
    config_dict.pop("research_mutable", None)
    manager.save_global_config(config_dict)
    manager.reload()
    if system_prompt is not None:
        try:
            service = get_agent_service()
            if service.memory_manager:
                await service.memory_manager.preferences.aset(
                    "default", "system_prompt", system_prompt,
                )
        except Exception as e:
            logger.warning("Failed to save system prompt: %s", e)
    return {"saved": True}


@router.get("/config/debug")
async def get_llm_config_debug() -> Any:
    """GET /config/debug — return ALL config (mutable + immutable) for debugging.

    v0.41: 新增调试端点，返回完整配置（含 immutable）。
    """
    from llmwikify.apps.chat.config import get_all_defaults
    from llmwikify.apps.chat.config_manager import get_global_config_manager

    manager = get_global_config_manager()
    llm_cfg = manager.load_effective_llm_config()
    result = manager.mask_api_key(llm_cfg)
    # 附加完整业务默认值（mutable + immutable）
    result["chat_defaults"] = get_all_defaults()
    return result


@router.post("/config/reload")
async def reload_llm_config() -> dict[str, Any]:
    from llmwikify.apps.chat.config_manager import get_global_config_manager
    manager = get_global_config_manager()
    manager.reload()
    return {"reloaded": True}
