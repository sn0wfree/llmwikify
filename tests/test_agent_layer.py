"""Tests for Agent layer components."""

import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from llmwikify.core import Wiki
from llmwikify.core.query_sink import QuerySink


@pytest.fixture
def wiki_root(tmp_path):
    root = tmp_path / "test_wiki"
    root.mkdir()
    (root / "raw").mkdir()
    (root / "wiki").mkdir()
    (root / "wiki" / ".sink").mkdir()
    db_path = root / ".llmwikify.db"
    wiki = Wiki(root)
    wiki.init()
    return wiki


# --- Runner Tests ---

class TestAgentRunner:
    def test_runner_init(self, wiki_root):
        from llmwikify.agent.runner import AgentRunner
        runner = AgentRunner(wiki_root)
        assert runner.wiki is wiki_root
        assert runner.state.value == "idle"
        assert runner.history == []
        assert runner.action_log == []

    def test_runner_reset(self, wiki_root):
        from llmwikify.agent.runner import AgentRunner
        runner = AgentRunner(wiki_root)
        runner.state = "running"
        runner.history = [{"role": "user", "content": "test"}]
        runner.reset()
        assert runner.state.value == "idle"
        assert runner.history == []

    def test_context_injector_builds_prompt(self, wiki_root):
        from llmwikify.agent.runner import WikiContextInjector
        injector = WikiContextInjector(wiki_root)
        prompt = injector.build_system_prompt()
        assert "wiki maintenance agent" in prompt.lower()
        assert "Current Wiki State" in prompt
        assert "Rules" in prompt

    def test_runner_hooks(self, wiki_root):
        from llmwikify.agent.runner import AgentRunner
        runner = AgentRunner(wiki_root)
        calls = []
        runner.register_hook("pre_run", lambda **kw: calls.append("pre_run"))
        runner.register_hook("post_run", lambda **kw: calls.append("post_run"))

        asyncio.get_event_loop().run_until_complete(runner.run([{"role": "user", "content": "test"}]))
        assert "pre_run" in calls
        assert "post_run" in calls

    def test_runner_stop(self, wiki_root):
        from llmwikify.agent.runner import AgentRunner, RunState
        runner = AgentRunner(wiki_root)
        runner.stop()
        assert runner.state == RunState.STOPPED


# --- Tool Registry Tests ---

class TestWikiToolRegistry:
    def test_registry_init(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)
        tools = registry.list_tools()
        assert len(tools) >= 15

    def test_list_tools_has_descriptions(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)
        tools = registry.list_tools()
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "action_type" in tool

    def test_execute_read_page(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)

        wiki_root.write_page("Test Page", "# Test")
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("wiki_read_page", {"page_name": "Test Page"})
        )
        assert "content" in result

    def test_execute_search(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("wiki_search", {"query": "test", "limit": 5})
        )
        assert isinstance(result, list)

    def test_execute_unknown_tool(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)
        with pytest.raises(ValueError, match="Unknown tool"):
            asyncio.get_event_loop().run_until_complete(
                registry.execute("nonexistent_tool", {})
            )

    def test_execute_status(self, wiki_root):
        from llmwikify.agent.tools import WikiToolRegistry
        registry = WikiToolRegistry(wiki_root)
        result = asyncio.get_event_loop().run_until_complete(
            registry.execute("wiki_status", {})
        )
        assert result is not None


# --- Hooks Tests ---

class TestHooks:
    def test_wiki_hook(self, wiki_root):
        from llmwikify.agent.hooks import WikiHook
        from llmwikify.agent.runner import ToolCall, ActionResult
        hook = WikiHook(wiki_root)
        mock_runner = MagicMock()
        tool_call = ToolCall(name="wiki_write_page", arguments={})
        result = ActionResult(tool_name="wiki_write_page", success=True)
        hook.on_post_tool(mock_runner, tool_call, result)

    def test_composite_hook(self):
        from llmwikify.agent.hooks import CompositeHook, Hook
        composite = CompositeHook()

        class TestHook(Hook):
            name = "test"
            def __init__(self):
                self.called = False
            def on_pre_run(self, runner, messages):
                self.called = True

        th = TestHook()
        composite.add(th)
        composite.fire_pre_run(None, [])
        assert th.called

    def test_composite_hook_remove(self):
        from llmwikify.agent.hooks import CompositeHook, Hook
        composite = CompositeHook()

        class TestHook(Hook):
            name = "test2"

        composite.add(TestHook())
        composite.remove("test2")
        assert len(composite._hooks) == 0

    def test_composite_hook_error_isolation(self):
        from llmwikify.agent.hooks import CompositeHook, Hook
        composite = CompositeHook()

        class FailingHook(Hook):
            name = "failing"
            def on_pre_run(self, runner, messages):
                raise RuntimeError("hook error")

        composite.add(FailingHook())
        composite.fire_pre_run(None, [])

    def test_auto_ingest_hook(self, wiki_root):
        from llmwikify.agent.hooks import AutoIngestHook
        hook = AutoIngestHook(wiki_root)
        new_files = hook.check_new_files()
        assert isinstance(new_files, list)

    def test_dream_sync_hook(self):
        from llmwikify.agent.hooks import DreamSyncHook
        from llmwikify.agent.runner import ToolCall, ActionResult
        hook = DreamSyncHook()
        mock_runner = MagicMock()
        tool_call = ToolCall(name="wiki_synthesize", arguments={})
        result = ActionResult(tool_name="wiki_synthesize", success=True)
        hook.on_post_tool(mock_runner, tool_call, result)
        assert hook.pending_dream is True


# --- Scheduler Tests ---

class TestScheduler:
    def test_scheduler_init(self):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        assert scheduler._tasks == {}

    def test_add_task(self):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        task = scheduler.add_task("test", "*/5 * * * *", lambda: "ok", "Test task")
        assert task.name == "test"
        assert task.enabled is True

    def test_remove_task(self):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        scheduler.add_task("test", "*/5 * * * *", lambda: "ok")
        scheduler.remove_task("test")
        assert scheduler.get_task("test") is None

    def test_enable_disable_task(self):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        scheduler.add_task("test", "*/5 * * * *", lambda: "ok")
        scheduler.disable_task("test")
        assert scheduler.get_task("test").enabled is False
        scheduler.enable_task("test")
        assert scheduler.get_task("test").enabled is True

    def test_list_tasks(self):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        scheduler.add_task("t1", "*/5 * * * *", lambda: "ok")
        scheduler.add_task("t2", "0 * * * *", lambda: "ok2")
        tasks = scheduler.list_tasks()
        assert len(tasks) == 2

    def test_task_to_dict(self):
        from llmwikify.agent.scheduler import ScheduledTask
        task = ScheduledTask("test", "*/5 * * * *", lambda: "ok", "desc")
        d = task.to_dict()
        assert d["name"] == "test"
        assert d["cron_expr"] == "*/5 * * * *"
        assert d["description"] == "desc"

    def test_register_system_tasks(self, wiki_root):
        from llmwikify.agent.scheduler import WikiScheduler
        scheduler = WikiScheduler()
        scheduler.register_system_tasks(wiki_root)
        tasks = scheduler.list_tasks()
        assert len(tasks) == 4
        task_names = [t["name"] for t in tasks]
        assert "dream_update" in task_names
        assert "check_raw" in task_names
        assert "daily_lint" in task_names
        assert "weekly_gaps" in task_names

    def test_save_load_state(self, tmp_path):
        from llmwikify.agent.scheduler import WikiScheduler
        data_dir = tmp_path / "agent_data"
        data_dir.mkdir()
        scheduler = WikiScheduler(data_dir)
        scheduler.add_task("test", "*/5 * * * *", lambda: "ok")
        scheduler.save_state()
        assert (data_dir / "scheduler.json").exists()

        scheduler2 = WikiScheduler(data_dir)
        scheduler2.add_task("test", "*/5 * * * *", lambda: "ok")
        scheduler2.load_state()


# --- Memory Tests ---

class TestConversationMemory:
    def test_append_and_get(self, tmp_path):
        from llmwikify.agent.memory import ConversationMemory
        mem = ConversationMemory(tmp_path)
        mem.append("user", "hello")
        mem.append("assistant", "hi there")
        entries = mem.get_recent()
        assert len(entries) == 2
        assert entries[0]["role"] == "user"

    def test_get_recent_limit(self, tmp_path):
        from llmwikify.agent.memory import ConversationMemory
        mem = ConversationMemory(tmp_path)
        for i in range(50):
            mem.append("user", f"msg {i}")
        entries = mem.get_recent(limit=5)
        assert len(entries) == 5

    def test_get_all(self, tmp_path):
        from llmwikify.agent.memory import ConversationMemory
        mem = ConversationMemory(tmp_path)
        mem.append("user", "hello")
        all_entries = mem.get_all()
        assert len(all_entries) == 1

    def test_clear(self, tmp_path):
        from llmwikify.agent.memory import ConversationMemory
        mem = ConversationMemory(tmp_path)
        mem.append("user", "hello")
        mem.clear()
        assert mem.get_all() == []

    def test_metadata(self, tmp_path):
        from llmwikify.agent.memory import ConversationMemory
        mem = ConversationMemory(tmp_path)
        mem.append("system", "info", {"key": "value"})
        entries = mem.get_all()
        assert entries[0]["metadata"]["key"] == "value"


class TestSinkMemory:
    def test_get_pending_pages_empty(self, wiki_root):
        from llmwikify.agent.memory import SinkMemory
        sm = SinkMemory(wiki_root)
        pages = sm.get_pending_pages()
        assert pages == []

    def test_get_sink_status(self, wiki_root):
        from llmwikify.agent.memory import SinkMemory
        sm = SinkMemory(wiki_root)
        status = sm.get_sink_status()
        assert "total_entries" in status


class TestMemoryManager:
    def test_store_and_get_context(self, wiki_root, tmp_path):
        from llmwikify.agent.memory import MemoryManager
        mm = MemoryManager(wiki_root, tmp_path / "mem")
        mm.store_conversation("user", "hello")
        mm.store_conversation("assistant", "hi")
        ctx = mm.get_context()
        assert len(ctx) == 2


# --- Dream Editor Tests ---

class TestDreamEditor:
    def test_init(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        data_dir = tmp_path / "agent"
        editor = DreamEditor(wiki_root, data_dir)
        assert editor.wiki is wiki_root
        assert editor.data_dir == data_dir

    def test_run_dream_empty_sinks(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        result = editor.run_dream()
        assert "sinks_processed" in result
        assert result["sinks_processed"] == 0

    def test_get_edit_log_empty(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        log = editor.get_edit_log()
        assert log == []

    def test_surgical_edit_append(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        wiki_root.write_page("TestEdit", "# Original")
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        result = editor._apply_surgical_edit("TestEdit", {
            "type": "append",
            "content": "## New Section\n\nAdded content",
        })
        assert result is True
        content = (wiki_root.wiki_dir / "TestEdit.md").read_text()
        assert "New Section" in content

    def test_surgical_edit_nonexistent_page(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        result = editor._apply_surgical_edit("NonExistent", {
            "type": "append",
            "content": "test",
        })
        assert result is False

    def test_edit_log_persistence(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        editor.run_dream()
        log = editor.get_edit_log()
        assert len(log) >= 1

    def test_create_page_from_sink(self, wiki_root, tmp_path):
        from llmwikify.agent.dream_editor import DreamEditor
        editor = DreamEditor(wiki_root, tmp_path / "agent")
        entries = [
            {"query": "Q1", "answer": "A1", "note": "unique"},
            {"query": "Q2", "answer": "A2", "note": "unique"},
        ]
        result = editor._create_page_from_sink("NewPage", entries)
        assert result["status"] == "created"
        assert result["edit_count"] == 2
        page_path = wiki_root.wiki_dir / "NewPage.md"
        assert page_path.exists()
        content = page_path.read_text()
        assert "Q1" in content
        assert "Q2" in content


# --- Notifications Tests ---

class TestNotificationManager:
    def test_add_and_list(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        n = nm.add("info", "test message")
        assert n["message"] == "test message"
        assert n["read"] is False

    def test_list_unread(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        nm.add("info", "msg1")
        nm.add("info", "msg2")
        unread = nm.list_unread()
        assert len(unread) == 2

    def test_mark_read(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        n = nm.add("info", "msg")
        nm.mark_read(n["id"])
        unread = nm.list_unread()
        assert len(unread) == 0

    def test_mark_all_read(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        nm.add("info", "msg1")
        nm.add("info", "msg2")
        count = nm.mark_all_read()
        assert count == 2
        assert nm.unread_count() == 0

    def test_max_size(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager(max_size=5)
        for i in range(10):
            nm.add("info", f"msg {i}")
        assert len(nm._notifications) == 5

    def test_mark_read_nonexistent(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        result = nm.mark_read("nonexistent")
        assert result is False

    def test_unread_count(self):
        from llmwikify.agent.notifications import NotificationManager
        nm = NotificationManager()
        nm.add("info", "msg1")
        nm.add("info", "msg2")
        assert nm.unread_count() == 2
        n = nm.list_all()[0]
        nm.mark_read(n["id"])
        assert nm.unread_count() == 1


# --- WikiAgent Integration Tests ---

class TestWikiAgent:
    def test_agent_init_with_root(self, wiki_root):
        from llmwikify.agent import WikiAgent
        agent = WikiAgent(root=str(wiki_root.root))
        assert agent.wiki is not None
        assert agent.tool_registry is not None
        assert agent.scheduler is not None

    def test_agent_init_with_wiki(self, wiki_root):
        from llmwikify.agent import WikiAgent
        agent = WikiAgent(wiki=wiki_root)
        assert agent.wiki is wiki_root

    def test_agent_requires_root_or_wiki(self):
        from llmwikify.agent import WikiAgent
        with pytest.raises(ValueError):
            WikiAgent()

    def test_agent_get_tools(self, wiki_root):
        from llmwikify.agent import WikiAgent
        agent = WikiAgent(wiki=wiki_root)
        tools = agent.get_tools()
        assert len(tools) > 0

    def test_agent_get_status(self, wiki_root):
        from llmwikify.agent import WikiAgent
        agent = WikiAgent(wiki=wiki_root)
        status = agent.get_status()
        assert "state" in status
        assert "scheduler_tasks" in status
        assert "pending_work" in status

    def test_agent_notification_callback(self, wiki_root):
        from llmwikify.agent import WikiAgent
        agent = WikiAgent(wiki=wiki_root)
        notifications = []
        agent.on_notification(lambda e, d: notifications.append((e, d)))
        agent._notify("test_event", {"data": "value"})
        assert len(notifications) == 1
        assert notifications[0] == ("test_event", {"data": "value"})
