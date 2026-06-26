"""Tests for unified/registry.py — register_mode + create_agent_loop。"""
from __future__ import annotations

import pytest

from llmwikify.apps.chat.agent.unified.core import StepHandler, StepResult
from llmwikify.apps.chat.agent.unified.registry import (
    AgentModeConfig,
    create_agent_loop,
    list_modes,
    register_mode,
)
from llmwikify.apps.chat.agent.unified.spec import ActResult, BaseSpec, ReasonResponse


# ── Mock handlers ─────────────────────────────────────────


class _SimpleStep(StepHandler):
    async def handle(self, input, spec, ctx):
        return StepResult.ok(None)


# ── Tests ─────────────────────────────────────────────────


def test_register_and_list():
    """注册后 list_modes 可见。"""
    modes_before = set(list_modes())

    register_mode(AgentModeConfig(
        name="__test_mode__",
        reasoner=_SimpleStep(),
        actor=_SimpleStep(),
    ))

    modes_after = list_modes()
    assert "__test_mode__" in modes_after
    assert len(modes_after) == len(modes_before) + 1


def test_create_agent_loop_codegen():
    """create_agent_loop('codegen') 正确构造。"""
    loop = create_agent_loop("codegen")
    assert loop is not None
    assert loop._reasoner is not None
    assert loop._actor is not None
    assert "after_act" in loop._deciders


def test_create_agent_loop_chat():
    """create_agent_loop('chat') 正确构造。"""
    loop = create_agent_loop("chat", chat_service=object(), tool_executor=object())
    assert loop is not None
    assert loop._reasoner is not None
    assert loop._actor is not None
    assert "after_reason" in loop._deciders


def test_create_agent_loop_unknown():
    """未知 mode → ValueError。"""
    with pytest.raises(ValueError, match="Unknown mode"):
        create_agent_loop("__nonexistent_mode__")


def test_create_agent_loop_with_factory():
    """工厂函数接收 kwargs。"""
    received_kwargs = {}

    def _capture_reasoner(**kwargs):
        received_kwargs.update(kwargs)
        return _SimpleStep()

    register_mode(AgentModeConfig(
        name="__test_factory__",
        reasoner=_capture_reasoner,
        actor=_SimpleStep(),
    ))

    create_agent_loop("__test_factory__", custom_arg="hello")
    assert received_kwargs.get("custom_arg") == "hello"
