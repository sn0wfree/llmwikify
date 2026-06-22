"""Unit tests for Phase 12: CRUD skills (memory/notify/scheduler/dream).

These are thin wrappers around the existing apps/agent/
implementations. Tests verify the Skill contract (name,
actions, input_schema) and delegation to the manager.

Covers:

  - MemorySkill: metadata, append/query/summarize/clear
  - NotifySkill: metadata, list/mark_read/subscribe
  - SchedulerSkill: metadata, add_job/list_jobs/remove_job/trigger
  - WikiDreamSkill: metadata, run/get_proposals/approve/reject

Target: 30+ tests, no I/O, mocks for managers.
"""

from __future__ import annotations

import pytest

from llmwikify.apps.chat.skills import SkillContext, SkillResult
from llmwikify.apps.chat.skills.crud.wiki_dream_skill import WikiDreamSkill, _approve, _get_proposals, _reject, _run, wiki_dream_skill
from llmwikify.apps.chat.skills.crud.memory_skill import MemorySkill, _add, _clear, _list, _search, memory_skill
from llmwikify.apps.chat.skills.crud.notify_skill import NotifySkill, _list_notifications, _mark_read, _subscribe, notify_skill
from llmwikify.apps.chat.skills.crud.scheduler_skill import SchedulerSkill, _add_job, _list_jobs, _remove_job, _trigger, scheduler_skill


# ─── Mock managers ────────────────────────────────────────────────


class MockMemoryManager:
    def __init__(self) -> None:
        self._entries: list[dict] = []
        self.conversation = MockConversationStore(self._entries)
        self.context = MockContextStore()

    def add(self, session_id: str, role: str, content: str) -> str:
        import uuid
        entry_id = str(uuid.uuid4())[:8]
        self._entries.append({"id": entry_id, "session_id": session_id, "role": role, "content": content})
        return entry_id

    def list(self, session_id: str, limit: int = 50) -> list[dict]:
        return [e for e in self._entries if e["session_id"] == session_id][-limit:]

    def search(self, session_id: str, query: str, limit: int = 10) -> list[dict]:
        return [e for e in self._entries
                if e["session_id"] == session_id and query.lower() in e["content"].lower()][:limit]


class MockConversationStore:
    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries

    def add(self, session_id: str, role: str, content: str) -> str:
        import uuid
        entry_id = str(uuid.uuid4())[:8]
        self._entries.append({"id": entry_id, "session_id": session_id, "role": role, "content": content})
        return entry_id

    def list(self, session_id: str, limit: int = 50) -> list[dict]:
        return [e for e in self._entries if e["session_id"] == session_id][-limit:]

    def search(self, session_id: str, query: str, limit: int = 10) -> list[dict]:
        return [e for e in self._entries
                if e["session_id"] == session_id and query.lower() in e["content"].lower()][:limit]

    def clear(self, session_id: str) -> int:
        before = len(self._entries)
        self._entries[:] = [e for e in self._entries if e["session_id"] != session_id]
        return before - len(self._entries)


class MockContextStore:
    def clear(self, session_id: str) -> int:
        return 0


class MockNotificationManager:
    def __init__(self) -> None:
        self._notifications: list[dict] = [
            {"id": "n1", "type": "info", "message": "test", "read": False},
            {"id": "n2", "type": "warn", "message": "old", "read": True},
        ]

    def list_all(self) -> list[dict]:
        return list(self._notifications)

    def list_unread(self) -> list[dict]:
        return [n for n in self._notifications if not n["read"]]

    def mark_read(self, nid: str) -> bool:
        for n in self._notifications:
            if n["id"] == nid:
                n["read"] = True
                return True
        return False


class MockScheduler:
    def __init__(self) -> None:
        self._tasks: dict[str, dict] = {}

    def add_task(self, name: str, cron_expr: str, handler: object, description: str = "", enabled: bool = True, is_write: bool = False) -> None:
        self._tasks[name] = {"name": name, "cron_expr": cron_expr, "enabled": enabled}

    def list_tasks(self) -> list[dict]:
        return list(self._tasks.values())

    def remove_task(self, name: str) -> None:
        self._tasks.pop(name, None)

    def get_task(self, name: str) -> object | None:
        if name not in self._tasks:
            return None

        class Task:
            def run(self_inner) -> dict:
                return {"status": "ok", "task": name}

        return Task()


class MockWikiDreamEditor:
    def __init__(self) -> None:
        self._proposals: list[dict] = [
            {"id": "p1", "status": "pending", "page_name": "test"},
        ]

    def run_wiki_dream(self) -> dict:
        return {"status": "ok", "pending_review": 0}

    @property
    def proposals(self) -> "_ProposalManager":
        return _ProposalManager(self._proposals)


class _ProposalManager:
    def __init__(self, proposals: list[dict]) -> None:
        self._proposals = proposals

    def get_proposals(self, status: str = "pending") -> list[dict]:
        if status == "all":
            return list(self._proposals)
        return [p for p in self._proposals if p["status"] == status]

    def approve(self, pid: str) -> bool:
        for p in self._proposals:
            if p["id"] == pid and p["status"] == "pending":
                p["status"] = "approved"
                return True
        return False

    def reject(self, pid: str, reason: str = "") -> bool:
        for p in self._proposals:
            if p["id"] == pid and p["status"] == "pending":
                p["status"] = "rejected"
                return True
        return False


@pytest.fixture
def ctx_with_memory() -> SkillContext:
    return SkillContext(config={"memory_manager": MockMemoryManager()}, session_id="s1")


@pytest.fixture
def ctx_with_notify() -> SkillContext:
    return SkillContext(config={"notification_manager": MockNotificationManager()})


@pytest.fixture
def ctx_with_scheduler() -> SkillContext:
    return SkillContext(config={"scheduler": MockScheduler()})


@pytest.fixture
def ctx_with_dream() -> SkillContext:
    return SkillContext(config={"wiki_dream_editor": MockWikiDreamEditor()})


@pytest.fixture
def ctx_empty() -> SkillContext:
    return SkillContext()


# ─── MemorySkill ─────────────────────────────────────────────────


class TestMemorySkillMetadata:
    def test_name(self) -> None:
        assert memory_skill.name == "memory"

    def test_has_4_actions(self) -> None:
        assert set(memory_skill.actions.keys()) == {"add", "list", "search", "clear"}

    def test_manifest(self) -> None:
        m = memory_skill.manifest()
        assert m.name == "memory"
        assert m.action_count == 4


class TestMemorySkillActions:
    @pytest.mark.asyncio
    async def test_add(self, ctx_with_memory: SkillContext) -> None:
        r = await _add({"role": "user", "content": "hello"}, ctx_with_memory)
        assert r.status == "ok"
        assert r.data["added"] is True

    @pytest.mark.asyncio
    async def test_add_empty_content(self, ctx_with_memory: SkillContext) -> None:
        r = await _add({"content": ""}, ctx_with_memory)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_list(self, ctx_with_memory: SkillContext) -> None:
        r = await _list({"limit": 10}, ctx_with_memory)
        assert r.status == "ok"
        assert "entries" in r.data

    @pytest.mark.asyncio
    async def test_search(self, ctx_with_memory: SkillContext) -> None:
        r = await _search({"query": "test"}, ctx_with_memory)
        assert r.status == "ok"
        assert "entries" in r.data

    @pytest.mark.asyncio
    async def test_clear(self, ctx_with_memory: SkillContext) -> None:
        r = await _clear({}, ctx_with_memory)
        assert r.status == "ok"
        assert r.data["cleared"] is True

    @pytest.mark.asyncio
    async def test_no_manager(self, ctx_empty: SkillContext) -> None:
        r = await _add({"content": "x"}, ctx_empty)
        assert r.status == "error"


# ─── NotifySkill ─────────────────────────────────────────────────


class TestNotifySkillMetadata:
    def test_name(self) -> None:
        assert notify_skill.name == "notify"

    def test_has_3_actions(self) -> None:
        assert set(notify_skill.actions.keys()) == {"list", "mark_read", "subscribe"}

    def test_manifest(self) -> None:
        m = notify_skill.manifest()
        assert m.name == "notify"
        assert m.action_count == 3


class TestNotifySkillActions:
    @pytest.mark.asyncio
    async def test_list_all(self, ctx_with_notify: SkillContext) -> None:
        r = await _list_notifications({"read_filter": "all"}, ctx_with_notify)
        assert r.status == "ok"
        assert r.data["count"] == 2

    @pytest.mark.asyncio
    async def test_list_unread(self, ctx_with_notify: SkillContext) -> None:
        r = await _list_notifications({"read_filter": "unread"}, ctx_with_notify)
        assert r.status == "ok"
        assert r.data["count"] == 1

    @pytest.mark.asyncio
    async def test_mark_read(self, ctx_with_notify: SkillContext) -> None:
        r = await _mark_read({"notification_id": "n1"}, ctx_with_notify)
        assert r.status == "ok"
        assert r.data["marked_read"] is True

    @pytest.mark.asyncio
    async def test_mark_read_not_found(self, ctx_with_notify: SkillContext) -> None:
        r = await _mark_read({"notification_id": "nonexistent"}, ctx_with_notify)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_subscribe(self, ctx_with_notify: SkillContext) -> None:
        r = await _subscribe({"event_type": "info"}, ctx_with_notify)
        assert r.status == "ok"
        assert r.data["subscribed"] is True

    @pytest.mark.asyncio
    async def test_no_manager(self, ctx_empty: SkillContext) -> None:
        r = await _list_notifications({}, ctx_empty)
        assert r.status == "error"


# ─── SchedulerSkill ──────────────────────────────────────────────


class TestSchedulerSkillMetadata:
    def test_name(self) -> None:
        assert scheduler_skill.name == "scheduler"

    def test_has_4_actions(self) -> None:
        assert set(scheduler_skill.actions.keys()) == {"add_job", "list_jobs", "remove_job", "trigger"}

    def test_manifest(self) -> None:
        m = scheduler_skill.manifest()
        assert m.name == "scheduler"
        assert m.action_count == 4


class TestSchedulerSkillActions:
    @pytest.mark.asyncio
    async def test_add_job(self, ctx_with_scheduler: SkillContext) -> None:
        r = await _add_job({"name": "test", "cron_expr": "0 * * * *"}, ctx_with_scheduler)
        assert r.status == "ok"
        assert r.data["added"] is True

    @pytest.mark.asyncio
    async def test_add_job_missing_fields(self, ctx_with_scheduler: SkillContext) -> None:
        r = await _add_job({"name": "test"}, ctx_with_scheduler)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_list_jobs(self, ctx_with_scheduler: SkillContext) -> None:
        r = await _list_jobs({}, ctx_with_scheduler)
        assert r.status == "ok"
        assert "jobs" in r.data

    @pytest.mark.asyncio
    async def test_remove_job(self, ctx_with_scheduler: SkillContext) -> None:
        r = await _remove_job({"name": "test"}, ctx_with_scheduler)
        assert r.status == "ok"
        assert r.data["removed"] is True

    @pytest.mark.asyncio
    async def test_trigger(self, ctx_with_scheduler: SkillContext) -> None:
        await _add_job({"name": "test", "cron_expr": "0 * * * *"}, ctx_with_scheduler)
        r = await _trigger({"name": "test"}, ctx_with_scheduler)
        assert r.status == "ok"
        assert r.data["triggered"] is True

    @pytest.mark.asyncio
    async def test_trigger_not_found(self, ctx_with_scheduler: SkillContext) -> None:
        r = await _trigger({"name": "nonexistent"}, ctx_with_scheduler)
        assert r.status == "error"

    @pytest.mark.asyncio
    async def test_no_scheduler(self, ctx_empty: SkillContext) -> None:
        r = await _add_job({"name": "x", "cron_expr": "* * * * *"}, ctx_empty)
        assert r.status == "error"


# ─── WikiDreamSkill ──────────────────────────────────────────────────


class TestWikiDreamSkillMetadata:
    def test_name(self) -> None:
        assert wiki_dream_skill.name == "wiki_dream"

    def test_has_4_actions(self) -> None:
        assert set(wiki_dream_skill.actions.keys()) == {"run", "get_proposals", "approve", "reject"}

    def test_manifest(self) -> None:
        m = wiki_dream_skill.manifest()
        assert m.name == "wiki_dream"
        assert m.action_count == 4


class TestWikiDreamSkillActions:
    @pytest.mark.asyncio
    async def test_run(self, ctx_with_dream: SkillContext) -> None:
        r = await _run({}, ctx_with_dream)
        assert r.status == "ok"
        assert r.data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_get_proposals(self, ctx_with_dream: SkillContext) -> None:
        r = await _get_proposals({"status": "pending"}, ctx_with_dream)
        assert r.status == "ok"
        assert r.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_approve(self, ctx_with_dream: SkillContext) -> None:
        r = await _approve({"proposal_id": "p1"}, ctx_with_dream)
        assert r.status == "ok"
        assert r.data["approved"] is True

    @pytest.mark.asyncio
    async def test_reject(self, ctx_with_dream: SkillContext) -> None:
        r = await _reject({"proposal_id": "p1", "reason": "bad"}, ctx_with_dream)
        assert r.status == "ok"
        assert r.data["rejected"] is True

    @pytest.mark.asyncio
    async def test_no_editor(self, ctx_empty: SkillContext) -> None:
        r = await _run({}, ctx_empty)
        assert r.status == "error"
