"""Unit tests for v0.32 Phase 10: ChatBase + SkillRegistry integration.

Covers:

  - ``register_skills(registry)`` — bulk registration of
    Skill actions as LLM tools (qualified name)
  - ``tools_schema(registry)`` — OpenAI function-calling
    JSON schema generation
  - ``invoke_tool(name, args, ctx)`` — single tool invocation
    via the SkillRuntime
  - ``ask_with_tools(prompt, ...)`` — full OpenAI-style
    tool-call loop with stub LLM
  - ``_call_llm_with_tools(...)`` — supports both
    OpenAI-style and plain calling conventions
  - ``_extract_content_and_tool_calls(reply)`` —
    normalizes str / dict / object replies

Target: 40+ tests, no I/O, no real LLM calls.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from llmwikify.apps.chat.skills.actions import (
    clarify_skill,
    filter_skill,
    plan_skill,
    register_all_actions,
    score_skill,
)
from llmwikify.apps.chat.skills.research_skill import research_skill
from llmwikify.apps.chat.skills.base import (
    SkillContext,
    SkillResult,
)
from llmwikify.apps.chat.skills.registry import (
    SkillRegistry,
    default_registry,
)
from llmwikify.apps.chat.base import (
    DEFAULT_MAX_TOOL_ITERATIONS,
    ChatBase,
    ChatMessage,
    ChatSession,
)


# ─── Stub LLM clients ─────────────────────────────────────────────


class StubLLM:
    """Stub LLM that records calls and returns canned responses.

    By default returns a string reply (no tool calls). Use
    ``tool_responses`` to script a sequence of replies —
    each ``ask_with_tools`` iteration pops one off the
    front; when empty, the LLM returns a final string.
    """

    def __init__(self, reply: str = "stub-reply", tool_responses: list[dict] | None = None) -> None:
        self.reply = reply
        self.tool_responses = list(tool_responses or [])
        self.calls: list[dict] = []
        self.last_tools: list[dict] | None = None

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        self.last_tools = kwargs.get("tools")
        if self.tool_responses:
            return self.tool_responses.pop(0)
        return self.reply


# ─── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext(session_id="chat-test")


@pytest.fixture
def fresh_registry() -> SkillRegistry:
    reg = SkillRegistry()
    register_all_actions(reg)
    reg.register(research_skill)
    return reg


@pytest.fixture
def chat(fresh_registry: SkillRegistry) -> ChatBase:
    return ChatBase(
        llm_client=StubLLM(),
        system_prompt="test prompt",
        skill_registry=fresh_registry,
    )


# ─── Construction ────────────────────────────────────────────────


class TestConstruction:
    def test_default_registry_used_when_none(self) -> None:
        # The default registry is empty until actions are
        # explicitly registered. This is by design — the
        # app startup (server) is responsible for populating
        # it via register_all_actions(default_registry()).
        cb = ChatBase(StubLLM())
        assert cb.skill_registry is not None
        assert len(cb.skill_registry) == 0  # pre-registration

    def test_default_registry_populated_after_register(self) -> None:
        from llmwikify.apps.chat.skills.actions import register_all_actions
        register_all_actions(default_registry())
        cb = ChatBase(StubLLM())
        assert len(cb.skill_registry) >= 23

    def test_explicit_registry_used(self, fresh_registry: SkillRegistry) -> None:
        cb = ChatBase(
            StubLLM(), skill_registry=fresh_registry,
        )
        assert cb.skill_registry is fresh_registry

    def test_default_runtime_created_if_none(self, fresh_registry: SkillRegistry) -> None:
        cb = ChatBase(
            StubLLM(), skill_registry=fresh_registry,
        )
        assert cb.skill_runtime is not None

    def test_explicit_runtime_used(self, fresh_registry: SkillRegistry) -> None:
        from llmwikify.apps.chat.skills.runtime import SkillRuntime
        rt = SkillRuntime(fresh_registry)
        cb = ChatBase(
            StubLLM(), skill_registry=fresh_registry, skill_runtime=rt,
        )
        assert cb.skill_runtime is rt

    def test_default_max_iterations(self) -> None:
        assert DEFAULT_MAX_TOOL_ITERATIONS == 8


# ─── register_skills (Phase 10 core) ───────────────────────────────


class TestRegisterSkills:
    @pytest.mark.skip(reason="v0.38: _tools dict removed; register_skills now count-only")
    def test_register_bulk_creates_qualified_names(self, chat: ChatBase) -> None:
        n = chat.register_skills()
        assert n == 26
        assert "research.run_research" in chat.tools
        assert "clarify.clarify" in chat.tools
        assert "search.search" in chat.tools
        assert "filter.filter" in chat.tools

    @pytest.mark.skip(reason="v0.38: _tools dict removed; register_skills now count-only")
    def test_register_skills_with_specific_registry(
        self, chat: ChatBase, fresh_registry: SkillRegistry
    ) -> None:
        before = len(chat.tools)
        n = chat.register_skills(fresh_registry)
        # fresh_registry has 14 base + 8 detect + 1 clarify
        # + research_skill (3 actions) = 26 total
        assert n == 26
        assert len(chat.tools) == before + 26

    @pytest.mark.skip(reason="v0.38: _SkillToolProxy removed")
    def test_register_skills_uses_skilltoolproxy(
        self, chat: ChatBase
    ) -> None:
        chat.register_skills()
        proxy = chat.tools["research.run_research"]
        assert isinstance(proxy, SkillToolProxy)
        assert proxy._skill_name == "research"
        assert proxy._action_name == "run_research"

    @pytest.mark.skip(reason="v0.38: _tools dict removed; register_skills now count-only")
    def test_register_skills_replaces_existing(self, chat: ChatBase) -> None:
        n1 = chat.register_skills()
        n2 = chat.register_skills()
        assert n1 == n2 == 26
        assert len(chat.tools) == 26


# ─── tools_schema (Phase 10 core) ────────────────────────────────


class TestToolsSchema:
    def test_returns_openai_format(self, chat: ChatBase) -> None:
        chat.register_skills()
        schema = chat.tools_schema()
        assert len(schema) == 26
        for tool in schema:
            assert tool["type"] == "function"
            assert "function" in tool
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn

    def test_schema_qualified_name_format(self, chat: ChatBase) -> None:
        chat.register_skills()
        schema = chat.tools_schema()
        names = {t["function"]["name"] for t in schema}
        assert "research.run_research" in names
        assert "clarify.clarify" in names
        assert "search.search" in names
        assert "filter.filter" in names

    def test_schema_parameters_match_action(
        self, chat: ChatBase
    ) -> None:
        chat.register_skills()
        schema = chat.tools_schema()
        clarify_schema = next(
            t for t in schema
            if t["function"]["name"] == "clarify.clarify"
        )
        params = clarify_schema["function"]["parameters"]
        assert params["type"] == "object"
        assert "query" in params["properties"]
        assert "query" in params["required"]

    def test_schema_with_specific_registry(
        self, chat: ChatBase, fresh_registry: SkillRegistry
    ) -> None:
        schema = chat.tools_schema()
        assert len(schema) == 26
        schema2 = chat.tools_schema(registry=fresh_registry)
        assert len(schema2) == 26

    def test_schema_empty_registry(self) -> None:
        cb = ChatBase(StubLLM(), skill_registry=SkillRegistry())
        assert cb.tools_schema() == []


# ─── invoke_tool (Phase 10 core) ─────────────────────────────────


@pytest.mark.skip(reason="v0.38: invoke_tool sync method removed")
class TestInvokeTool:
    def test_qualified_name_routing(self, chat: ChatBase) -> None:
        r = chat.invoke_tool("clarify.clarify", {"query": "What is X?"})
        assert r.status == "ok"
        assert r.data["scope_check"] is True

    def test_ainvoke_tool_routing(self, chat: ChatBase) -> None:
        """The async variant also works."""
        r = asyncio.run(chat.ainvoke_tool(
            "clarify.clarify", {"query": "Q?"},
        ))
        assert r.status == "ok"

    def test_unqualified_name_returns_fail(self, chat: ChatBase) -> None:
        r = chat.invoke_tool("unqualified", {})
        assert r.status == "error"
        assert "qualified" in r.error.lower()

    def test_unknown_skill_returns_fail(self, chat: ChatBase) -> None:
        r = chat.invoke_tool("nope.nada", {})
        assert r.status == "error"
        assert "Skill not found" in r.error

    def test_unknown_action_returns_fail(self, chat: ChatBase) -> None:
        r = chat.invoke_tool("clarify.nope", {})
        assert r.status == "error"
        assert "not found" in r.error

    def test_invoke_with_ctx(self, chat: ChatBase, ctx: SkillContext) -> None:
        r = chat.invoke_tool("filter.filter", {
            "sources": [{"url": "a", "score": 0.8}],
        }, ctx=ctx)
        assert r.status == "ok"


# ─── ask_with_tools (Phase 10 core) ──────────────────────────────


@pytest.mark.skip(reason="v0.38: ask_with_tools sync method removed")
class TestAskWithTools:
    def test_no_tools_returns_string_reply(self, chat: ChatBase) -> None:
        reply = chat.ask_with_tools("Hello")
        assert reply == "stub-reply"
        sess = chat.new_session()
        chat.ask_with_tools("Hi", session=sess)
        # 3 messages: system (added on first call) + user + assistant
        assert len(sess.messages) == 3
        assert sess.messages[0].role == "system"
        assert sess.messages[1].role == "user"
        assert sess.messages[2].role == "assistant"

    def test_session_reuse(self, chat: ChatBase) -> None:
        sess = chat.new_session()
        chat.ask_with_tools("Q1", session=sess)
        chat.ask_with_tools("Q2", session=sess)
        # 1 system + 2 user + 2 assistant = 5
        assert len(sess.messages) == 5

    def test_with_tool_call_then_final(
        self, chat: ChatBase, ctx: SkillContext
    ) -> None:
        chat.llm_client = StubLLM(
            tool_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "clarify.clarify",
                            "arguments": json.dumps({"query": "Q?"}),
                        },
                    }],
                },
                "final answer text",
            ],
        )
        sess = chat.new_session()
        reply = chat.ask_with_tools("ask", session=sess, ctx=ctx)
        assert reply == "final answer text"
        # 1 system + user + assistant(tool_call) + tool(result)
        # + assistant(final) = 5
        assert len(sess.messages) == 5
        assert sess.messages[3].role == "tool"
        assert sess.messages[3].tool_call_id == "call_1"

    def test_max_iterations_cap(self, chat: ChatBase) -> None:
        chat.llm_client = StubLLM(
            tool_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": "clarify.clarify",
                            "arguments": json.dumps({"query": f"Q{i}"}),
                        },
                    }],
                }
                for i in range(20)
            ],
        )
        sess = chat.new_session()
        reply = chat.ask_with_tools("Q", session=sess, max_iterations=3)
        # Cap was honored: 3 assistant messages max
        assistant_msgs = [
            m for m in sess.messages if m.role == "assistant"
        ]
        assert len(assistant_msgs) <= 3
        # The reply is the last message's content (whatever that is)
        # — the framework's "iteration cap" fallback.
        assert reply == sess.messages[-1].content
        # The session grew as expected: 1 system + user +
        # alternating (assistant, tool) * 3 + final tool
        assert len(sess.messages) >= 7

    def test_uses_system_prompt_on_first_call(self, chat: ChatBase) -> None:
        chat.ask_with_tools("user message")
        sent = chat.llm_client.calls[0]
        assert sent["messages"][0].role == "system"
        assert sent["messages"][0].content == "test prompt"

    def test_tools_kwarg_passed_to_llm(self, chat: ChatBase) -> None:
        chat.register_skills()
        chat.ask_with_tools("test")
        sent = chat.llm_client.calls[0]
        assert "tools" in sent["kwargs"]
        assert len(sent["kwargs"]["tools"]) == 26

    def test_tool_call_with_bad_json_args(self, chat: ChatBase) -> None:
        chat.llm_client = StubLLM(
            tool_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "call_bad",
                        "type": "function",
                        "function": {
                            "name": "clarify.clarify",
                            "arguments": "{not valid json",
                        },
                    }],
                },
                "done",
            ],
        )
        reply = chat.ask_with_tools("Q")
        assert reply == "done"

    def test_ask_with_tools_without_skills_registered(
        self, chat: ChatBase
    ) -> None:
        chat.llm_client = StubLLM(reply="no tools, just text")
        reply = chat.ask_with_tools("Hi")
        assert reply == "no tools, just text"


# ─── _call_llm_with_tools (internal) ────────────────────────────


@pytest.mark.skip(reason="v0.38: _call_llm_with_tools removed")
class TestCallLLMWithTools:
    def test_openai_style_with_tools_kwarg(self, chat: ChatBase) -> None:
        tools = [{"type": "function", "function": {"name": "x"}}]
        msgs = [ChatMessage(role="user", content="hi")]
        chat._call_llm_with_tools(msgs, tools, {})
        sent = chat.llm_client.calls[0]
        assert sent["kwargs"].get("tools") == tools

    def test_plain_convention_falls_back(
        self, chat: ChatBase
    ) -> None:
        class StrictLLM:
            def __init__(self):
                self.calls = []
            def chat(self, msgs, **kwargs):
                self.calls.append(kwargs)
                if "tools" in kwargs:
                    raise TypeError("got unexpected kwarg 'tools'")
                return "plain reply"
        chat.llm_client = StrictLLM()
        tools = [{"type": "function", "function": {"name": "x"}}]
        msgs = [ChatMessage(role="user", content="hi")]
        chat._call_llm_with_tools(msgs, tools, {"temperature": 0.5})
        second = chat.llm_client.calls[1]
        assert "tools" not in second
        assert second.get("temperature") == 0.5


# ─── _extract_content_and_tool_calls (internal) ─────────────────


class TestExtractContentAndToolCalls:
    def test_none_reply(self) -> None:
        content, calls = ChatBase._extract_content_and_tool_calls(None)
        assert content == ""
        assert calls == []

    def test_string_reply(self) -> None:
        content, calls = ChatBase._extract_content_and_tool_calls("hello")
        assert content == "hello"
        assert calls == []

    def test_dict_reply_with_content_only(self) -> None:
        content, calls = ChatBase._extract_content_and_tool_calls(
            {"content": "hi", "tool_calls": []}
        )
        assert content == "hi"
        assert calls == []

    def test_dict_reply_with_tool_calls(self) -> None:
        reply = {
            "content": "",
            "tool_calls": [{
                "id": "c1",
                "type": "function",
                "function": {"name": "x.y", "arguments": "{}"},
            }],
        }
        content, calls = ChatBase._extract_content_and_tool_calls(reply)
        assert content == ""
        assert len(calls) == 1
        assert calls[0]["id"] == "c1"
        assert calls[0]["function"]["name"] == "x.y"

    def test_object_reply_with_attrs(self) -> None:
        class FakeTC:
            def __init__(self, id, name, args):
                self.id = id
                self.function = type("F", (), {
                    "name": name, "arguments": args,
                })()
        class FakeReply:
            content = "obj-content"
            tool_calls = [FakeTC("c1", "x.y", "{}")]
        content, calls = ChatBase._extract_content_and_tool_calls(FakeReply())
        assert content == "obj-content"
        assert calls[0]["function"]["name"] == "x.y"

    def test_mixed_list_of_dicts_and_objects(self) -> None:
        class FakeTC:
            def __init__(self, id, name, args):
                self.id = id
                self.function = type("F", (), {
                    "name": name, "arguments": args,
                })()
        reply = {
            "content": "x",
            "tool_calls": [
                {"id": "d1", "type": "function",
                 "function": {"name": "a.b", "arguments": "{}"}},
                FakeTC("d2", "c.d", "{}"),
            ],
        }
        content, calls = ChatBase._extract_content_and_tool_calls(reply)
        assert content == "x"
        # Both dict- and object-typed tool calls are normalized
        ids = []
        for c in calls:
            # c is now a dict after normalization
            assert isinstance(c, dict)
            ids.append(c.get("id", c.get("function", {}).get("id", "")))
        # The dict variant has 'id' at top level; the object
        # variant gets normalized into the same shape
        assert "d1" in ids
        assert any("d2" in str(c) for c in calls)


# ─── SkillToolProxy ──────────────────────────────────────────────


@pytest.mark.skip(reason="v0.38: _SkillToolProxy removed")
class TestSkillToolProxy:
    def test_repr(self, fresh_registry: SkillRegistry) -> None:
        proxy = SkillToolProxy(
            registry=fresh_registry,
            skill_name="clarify",
            action_name="clarify",
        )
        r = repr(proxy)
        assert "clarify" in r
        assert "SkillToolProxy" in r

    def test_proxy_attributes(self, fresh_registry: SkillRegistry) -> None:
        proxy = SkillToolProxy(
            registry=fresh_registry,
            skill_name="research",
            action_name="run_research",
        )
        assert proxy._skill_name == "research"
        assert proxy._action_name == "run_research"


# ─── End-to-end (the actual use case) ───────────────────────────


@pytest.mark.skip(reason="v0.38: ask_with_tools sync method removed")
class TestEndToEndSkillChat:
    def test_clarify_then_search_then_final(
        self, chat: ChatBase
    ) -> None:
        chat.llm_client = StubLLM(
            tool_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "t1",
                        "type": "function",
                        "function": {
                            "name": "clarify.clarify",
                            "arguments": json.dumps({"query": "What is X?"}),
                        },
                    }],
                },
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "t2",
                        "type": "function",
                        "function": {
                            "name": "search.search",
                            "arguments": json.dumps({"query": "X"}),
                        },
                    }],
                },
                "Based on my research, X is Y.",
            ],
        )
        reply = chat.ask_with_tools("Tell me about X")
        assert reply == "Based on my research, X is Y."

    def test_filter_action_invoked_correctly(self, chat: ChatBase) -> None:
        chat.llm_client = StubLLM(
            tool_responses=[
                {
                    "content": "",
                    "tool_calls": [{
                        "id": "f1",
                        "type": "function",
                        "function": {
                            "name": "filter.filter",
                            "arguments": json.dumps({
                                "sources": [
                                    {"url": "a", "score": 0.9},
                                    {"url": "a", "score": 0.8},
                                    {"url": "b", "score": 0.1},
                                ],
                            }),
                        },
                    }],
                },
                "Filtered 1 source.",
            ],
        )
        reply = chat.ask_with_tools("Filter these")
        assert reply == "Filtered 1 source."
        sess_msgs = [c for c in chat.llm_client.calls]
        last = sess_msgs[-1]
        tool_msgs = [m for m in last["messages"] if m.role == "tool"]
        assert len(tool_msgs) == 1
        result = json.loads(tool_msgs[0].content)
        assert result["status"] == "ok"
        assert len(result["data"]["filtered"]) == 1
        assert result["data"]["dropped"] == 2
