"""SSE 契约 + 静默失败回归测试。

覆盖 docs/designs/sse-contract-and-silent-failures.md：
- #1 duration_ms：runner_v2 / tool_chat / ChatEvent 工厂三类发射点
- #4 协程分支：_call_service_method 不再静默
- #8 web 抓取失败：产生日志而非零观测
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from llmwikify.apps.chat.agent.orchestrator import ChatEvent
from llmwikify.apps.chat.agent.runner_v2 import ChatRunnerV2
from llmwikify.apps.chat.skills.actions._helpers import _as_skill_result
from llmwikify.foundation.extractors.web import _fetch_with_timeout

# ─── Helpers（镜像 test_apps_chat_agent_runner_v2 的桩） ──────────


class _StubExecutor:
    def execute(self, *a: Any, **k: Any) -> dict:
        return {"status": "ok", "data": {}}

    def save_message(self, *a: Any, **k: Any) -> None:  # pragma: no cover
        pass


class _StubPromptBuilder:
    def parse_wiki_prefix(self, text: str) -> tuple[None, str]:
        return None, text


def _make_spec(**over: Any) -> Any:
    from llmwikify.apps.chat.agent.runner_v2 import ChatRunSpec

    base: dict[str, Any] = {
        "messages": [{"role": "user", "content": "hi"}],
        "session_id": "s1",
        "tool_registry": object(),
    }
    base.update(over)
    return ChatRunSpec(**base)


class _OkService:
    """chat_service 桩：提供同步 adapter 方法。"""

    def _truncate_messages(self, messages: list) -> list:
        return list(messages)

    def _get_toolspec(self, _registry: Any) -> list:
        return [{"type": "function", "function": {"name": "t"}}]

    config: dict = {}

    async def _llm_stream_with_retry(self, _m: list, _t: list):  # pragma: no cover
        yield {"type": "done", "content": "ok"}


class _AsyncService(_OkService):
    """chat_service 桩：adapter 方法误为 async — 触发协程分支。"""

    async def _truncate_messages(self, messages: list) -> list:  # type: ignore[override]
        return list(messages)

    async def _get_toolspec(self, _registry: Any) -> list:  # type: ignore[override]
        return []


# ─── #1 duration_ms — runner_v2 ────────────────────────────────────


class TestRunnerV2DurationMs:
    def _run(self, llm_events: list[dict], executor: Any = None) -> list[dict]:
        runner = ChatRunnerV2(
            chat_service=_OkService(),
            tool_executor=executor or _StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        )

        class _LLM:
            config: dict = {}

            def _get_toolspec(self, _r: Any) -> list:
                return []

            def _truncate_messages(self, m: list) -> list:
                return list(m)

            async def _llm_stream_with_retry(self, _m: list, _t: list):
                for ev in llm_events:
                    yield ev

        runner._chat_service = _LLM()
        spec = _make_spec()

        async def go() -> list[dict]:
            return [ev async for ev in runner.run_stream(spec)]

        return asyncio.run(go())

    def test_tool_call_end_has_duration_ms(self) -> None:
        events = self._run(
            [
                {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
                {"type": "done", "content": "ok"},
            ]
        )
        ends = [e for e in events if e["type"] == "tool_call_end"]
        assert ends, "expected tool_call_end"
        assert isinstance(ends[0].get("duration_ms"), (int, float))

    def test_tool_call_error_exception_has_duration_ms(self) -> None:
        class _Raise:
            def execute(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("boom")

        events = self._run(
            [
                {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
                {"type": "done", "content": "ok"},
            ],
            executor=_Raise(),
        )
        errs = [e for e in events if e["type"] == "tool_call_error"]
        assert errs
        assert isinstance(errs[0].get("duration_ms"), (int, float))

    def test_tool_call_error_status_has_duration_ms(self) -> None:
        class _StatusErr:
            def execute(self, *a: Any, **k: Any) -> dict:
                return {"status": "error", "error": "nope"}

        events = self._run(
            [
                {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
                {"type": "done", "content": "ok"},
            ],
            executor=_StatusErr(),
        )
        errs = [e for e in events if e["type"] == "tool_call_error"]
        assert errs
        assert isinstance(errs[0].get("duration_ms"), (int, float))

    def test_tool_call_error_empty_name_has_duration_ms(self) -> None:
        events = self._run(
            [
                {"type": "tool_call", "id": "c1", "name": "", "args": {}},
                {"type": "done", "content": "ok"},
            ]
        )
        errs = [e for e in events if e["type"] == "tool_call_error"]
        assert errs
        assert errs[0].get("duration_ms") == 0

    def test_confirmation_required_has_duration_ms(self) -> None:
        class _Conf:
            def execute(self, *a: Any, **k: Any) -> dict:
                return {
                    "status": "confirmation_required",
                    "confirmation_id": "cf1",
                    "impact": {},
                }

        events = self._run(
            [
                {"type": "tool_call", "id": "c1", "name": "x", "args": {}},
                {"type": "done", "content": "ok"},
            ],
            executor=_Conf(),
        )
        confs = [e for e in events if e["type"] == "confirmation_required"]
        assert confs
        assert isinstance(confs[0].get("duration_ms"), (int, float))


# ─── #1 duration_ms — tool_actor ───────────────────────────────────


class TestToolActorDurationMs:
    def _collect(self, executor: Any) -> list[Any]:
        from llmwikify.apps.chat.agent.unified.handlers.tool_actor import ToolActor

        actor = ToolActor(executor)

        class _Resp:
            tool_calls = [
                {"id": "c1", "name": "x", "args": {}},
            ]

        class _Spec:
            tool_registry = None
            session_id = "s1"
            microcompact = False
            microcompact_compactable_tools: set = set()

        async def go() -> list[Any]:
            out = []
            async for ev in actor.stream(_Resp(), _Spec(), None):
                out.append(ev)
            return out

        return asyncio.run(go())

    def test_tool_call_end_has_duration_ms(self) -> None:
        events = self._collect(_StubExecutor())
        ends = [e for e in events if isinstance(e, dict) and e.get("type") == "tool_call_end"]
        assert ends
        assert isinstance(ends[0].get("duration_ms"), (int, float))

    def test_tool_call_error_has_duration_ms(self) -> None:
        class _Raise:
            def execute(self, *a: Any, **k: Any) -> Any:
                raise RuntimeError("boom")

        events = self._collect(_Raise())
        errs = [e for e in events if isinstance(e, dict) and e.get("type") == "tool_call_error"]
        assert errs
        assert isinstance(errs[0].get("duration_ms"), (int, float))

    def test_confirmation_required_has_duration_ms(self) -> None:
        class _Conf:
            def execute(self, *a: Any, **k: Any) -> dict:
                return {
                    "status": "confirmation_required",
                    "confirmation_id": "cf1",
                    "impact": {},
                }

        events = self._collect(_Conf())
        confs = [
            e for e in events if isinstance(e, dict) and e.get("type") == "confirmation_required"
        ]
        assert confs
        assert isinstance(confs[0].get("duration_ms"), (int, float))


# ─── #1 duration_ms — ChatEvent 工厂 ───────────────────────────────


class TestChatEventFactory:
    def test_confirmation_required_factory_has_duration_ms(self) -> None:
        ev = ChatEvent.confirmation_required("cf1", "write", {}, {}, call_id="c1")
        assert ev["duration_ms"] == 0
        ev2 = ChatEvent.confirmation_required(
            "cf1", "write", {}, {}, call_id="c1", duration_ms=42
        )
        assert ev2["duration_ms"] == 42

    def test_tool_call_end_factory_has_duration_ms(self) -> None:
        ev = ChatEvent.tool_call_end("x", {}, call_id="c1", duration_ms=7)
        assert ev["duration_ms"] == 7


# ─── #4 _call_service_method 协程分支 ─────────────────────────────


class TestCoroutineBranch:
    def test_async_adapter_method_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        runner = ChatRunnerV2(
            chat_service=_AsyncService(),
            tool_executor=_StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        )
        with caplog.at_level(logging.WARNING):
            result = runner._call_service_method(
                "_truncate_messages", [], default=[], log_label="truncate"
            )
        assert result == []
        assert any("coroutine" in r.message for r in caplog.records)

    def test_coroutine_is_closed(self) -> None:
        import warnings

        runner = ChatRunnerV2(
            chat_service=_AsyncService(),
            tool_executor=_StubExecutor(),
            prompt_builder=_StubPromptBuilder(),
        )
        # 关闭协程后不应产生 RuntimeWarning: coroutine was never awaited
        with warnings.catch_warnings():
            warnings.simplefilter("error", RuntimeWarning)
            runner._call_service_method("_truncate_messages", [], default=[])


# ─── #8 web 抓取失败日志 ───────────────────────────────────────────


class TestWebFetchLogging:
    def test_request_failure_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            result = _fetch_with_timeout("http://127.0.0.1:1/never", timeout=(1, 1))
        assert result is None
        assert any("Fetch failed" in r.message for r in caplog.records)


# ─── #8 _as_skill_result None 分支可观测 ──────────────────────────


class TestAsSkillResultNone:
    def test_none_is_void_success(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG):
            result = _as_skill_result(None)
        assert result.ok
        assert result.data == {}
        assert any("void success" in r.message for r in caplog.records)

    def test_dict_passthrough(self) -> None:
        r = _as_skill_result({"a": 1})
        assert r.ok and r.data == {"a": 1}
