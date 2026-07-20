"""Tests for MemoryManager (apps/chat/memory)."""

from __future__ import annotations

import asyncio
import tempfile

import pytest

from llmwikify.apps.chat.memory import (
    ContextStore,
    ConversationStore,
    MemoryIndex,
    MemoryManager,
    ReActStateStore,
    UserPreferenceStore,
)
from llmwikify.apps.db import AppDatabase


@pytest.fixture
def memory_env():
    with tempfile.TemporaryDirectory() as tmp:
        app_db = AppDatabase(tmp)
        yield app_db, tmp


@pytest.fixture
def memory_manager(memory_env) -> MemoryManager:
    app_db, tmp = memory_env
    chat_sid = app_db.chat.create_chat_session(wiki_id="wiki-1")
    research_sid = app_db.research.create_research_session("wiki-1", "test query")
    mm = MemoryManager(app_db, wiki=None, data_dir=tmp)
    # MemoryManager fixtures typically use the chat session id (most stores
    # are chat-facing). ReActStateStore tests should override.
    return mm, {"chat": chat_sid, "research": research_sid}


class TestConversationStore:
    def test_add_and_list(self, memory_manager):
        mm, sid = memory_manager
        mm.conversation.add(sid["chat"], "user", "hello")
        mm.conversation.add(sid["chat"], "assistant", "hi there")
        msgs = mm.conversation.list(sid["chat"])
        assert len(msgs) == 2
        # Default order is DESC (newest first)
        assert msgs[0]["role"] == "assistant"
        assert msgs[1]["role"] == "user"

    def test_search(self, memory_manager):
        mm, sid = memory_manager
        mm.conversation.add(sid["chat"], "user", "tell me about python")
        mm.conversation.add(sid["chat"], "assistant", "python is a snake")
        results = mm.conversation.search(sid["chat"], "python")
        assert len(results) == 2

    def test_search_no_match(self, memory_manager):
        mm, sid = memory_manager
        mm.conversation.add(sid["chat"], "user", "hello")
        results = mm.conversation.search(sid["chat"], "nonexistent")
        assert len(results) == 0


class TestContextStore:
    def test_add_and_list(self, memory_manager):
        mm, sid = memory_manager
        mm.context.add(sid["chat"], "rag", "context chunk 1")
        mm.context.add(sid["chat"], "tool_result", "tool output 1")
        entries = mm.context.list(sid["chat"])
        assert len(entries) == 2

    def test_list_by_type(self, memory_manager):
        mm, sid = memory_manager
        mm.context.add(sid["chat"], "rag", "context chunk 1")
        mm.context.add(sid["chat"], "tool_result", "tool output 1")
        rag_entries = mm.context.list(sid["chat"], entry_type="rag")
        assert len(rag_entries) == 1
        assert rag_entries[0]["entry_type"] == "rag"

    def test_clear(self, memory_manager):
        mm, sid = memory_manager
        mm.context.add(sid["chat"], "rag", "x")
        mm.context.add(sid["chat"], "rag", "y")
        deleted = mm.context.clear(sid["chat"])
        assert deleted == 2
        assert len(mm.context.list(sid["chat"])) == 0


class TestReActStateStore:
    def test_save_and_load(self, memory_manager):
        mm, sid = memory_manager
        state = {"phase": "gather", "sub_queries": ["q1", "q2"]}
        mm.react_state.save(sid["research"], 1, state)
        loaded = mm.react_state.load(sid["research"], 1)
        assert loaded is not None
        assert loaded["phase"] == "gather"

    def test_latest(self, memory_manager):
        mm, sid = memory_manager
        mm.react_state.save(sid["research"], 1, {"phase": "plan"})
        mm.react_state.save(sid["research"], 2, {"phase": "gather"})
        latest = mm.react_state.latest(sid["research"])
        assert latest is not None
        assert latest["phase"] == "gather"


class TestUserPreferenceStore:
    def test_set_and_get(self, memory_env):
        app_db, tmp = memory_env
        prefs = UserPreferenceStore(tmp)
        prefs.set("user1", "theme", "dark")
        assert prefs.get("user1", "theme") == "dark"

    def test_get_default(self, memory_env):
        app_db, tmp = memory_env
        prefs = UserPreferenceStore(tmp)
        assert prefs.get("user1", "missing", default="x") == "x"

    def test_all(self, memory_env):
        app_db, tmp = memory_env
        prefs = UserPreferenceStore(tmp)
        prefs.set("user1", "k1", "v1")
        prefs.set("user1", "k2", "v2")
        all_prefs = prefs.all("user1")
        assert all_prefs == {"k1": "v1", "k2": "v2"}


class TestMemoryIndex:
    def test_search_conversation(self, memory_manager):
        mm, sid = memory_manager
        mm.conversation.add(sid["chat"], "user", "python tutorial")
        results = mm.index.search("python", session_id=sid["chat"])
        assert any(r["source"] == "conversation" for r in results)

    def test_search_context(self, memory_manager):
        mm, sid = memory_manager
        mm.context.add(sid["chat"], "rag", "python is a programming language")
        results = mm.index.search("python", session_id=sid["chat"])
        assert any(r["source"] == "context" for r in results)


class TestMemoryManagerInit:
    def test_stores_initialized(self, memory_env):
        app_db, tmp = memory_env
        mm = MemoryManager(app_db, wiki=None, data_dir=tmp)
        assert isinstance(mm.conversation, ConversationStore)
        assert isinstance(mm.context, ContextStore)
        assert isinstance(mm.react_state, ReActStateStore)
        assert isinstance(mm.preferences, UserPreferenceStore)
        assert mm.knowledge is None
        assert isinstance(mm.index, MemoryIndex)


class TestMemorySkillIntegration:
    """End-to-end: memory_skill via SkillService wired to MemoryManager."""

    def test_add_list_search_via_skill(self, memory_env):
        import asyncio

        from llmwikify.apps.chat.skills.base import SkillContext
        from llmwikify.apps.chat.skills.service import SkillService

        app_db, tmp = memory_env
        mm = MemoryManager(app_db, wiki=None, data_dir=tmp)
        svc = SkillService(memory_manager=mm)
        svc.register_all()
        sid = app_db.chat.create_chat_session("wiki-1")
        ctx = SkillContext(db=app_db.chat, config={}, session_id=sid)

        # add
        r = asyncio.run(svc.execute("memory", "add", {
            "role": "user", "content": "hello world",
        }, ctx))
        assert r.status == "ok"
        assert r.data["added"] is True

        # list
        r = asyncio.run(svc.execute("memory", "list", {}, ctx))
        assert r.status == "ok"
        assert r.data["count"] == 1
        assert r.data["entries"][0]["content"] == "hello world"

        # search
        r = asyncio.run(svc.execute("memory", "search", {
            "query": "hello",
        }, ctx))
        assert r.status == "ok"
        assert r.data["count"] == 1

        # clear
        r = asyncio.run(svc.execute("memory", "clear", {}, ctx))
        assert r.status == "ok"


class TestAsyncMemory:
    """Phase 3.5 (v0.36): verify async wrappers work."""

    def test_async_conversation_store(self, memory_manager):
        mm, sid = memory_manager
        async def run():
            await mm.conversation.aadd(sid["chat"], "user", "async hello")
            msgs = await mm.conversation.alist(sid["chat"])
            assert len(msgs) >= 1
            assert msgs[0]["content"] == "async hello"
        asyncio.run(run())

    def test_async_context_store(self, memory_manager):
        mm, sid = memory_manager
        async def run():
            await mm.context.aadd(sid["chat"], "tool_result", "tool output async")
            entries = await mm.context.alist(sid["chat"])
            assert len(entries) >= 1
        asyncio.run(run())

    def test_async_user_preference_store(self, memory_manager):
        mm, _ = memory_manager
        async def run():
            await mm.preferences.aset("default", "style", "verbose")
            val = await mm.preferences.aget("default", "style")
            assert val == "verbose"
            all_prefs = await mm.preferences.aall("default")
            assert all_prefs.get("style") == "verbose"
        asyncio.run(run())

    def test_async_memory_index(self, memory_manager):
        mm, sid = memory_manager
        async def run():
            await mm.conversation.aadd(sid["chat"], "user", "test query")
            results = await mm.index.asearch("test", session_id=sid["chat"], limit=5)
            assert len(results) >= 1
        asyncio.run(run())
