"""Unit tests for the v0.32 skill framework (Phase 1).

Covers:

  - ``SkillResult``     - envelope (ok / fail / needs_confirmation)
  - ``SkillAction``     - dataclass + validation
  - ``SkillContext``    - per-call context + with_overrides
  - ``Skill``           - ABC (name/description/actions enforcement,
                          setup/teardown, manifest)
  - ``SkillManifest``   - aggregation
  - error hierarchy     - all 6 types carry the expected fields
  - ``SkillRegistry``   - register/unregister/clear/lookup/parse/
                          manifests/actions/tags/iteration
  - ``SkillRuntime``    - dispatch (sync + async handlers),
                          validation (required, type, additional),
                          error translation, qualified names

Target: 60+ tests, no I/O, no network, no real LLM calls.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from llmwikify.apps.chat.skills import (
    ActionNotFoundError,
    ConfirmationRequiredError,
    Skill,
    SkillAction,
    SkillContext,
    SkillError,
    SkillExecutionError,
    SkillManifest,
    SkillNotFoundError,
    SkillRegistry,
    SkillResult,
    SkillRuntime,
    SkillValidationError,
    default_registry,
    reset_default_registry,
)

# ─── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def fresh_registry() -> SkillRegistry:
    """A clean registry per-test (does NOT touch the default singleton)."""
    return SkillRegistry()


@pytest.fixture
def ctx() -> SkillContext:
    return SkillContext(
        wiki=object(),
        db=object(),
        llm_client=object(),
        config={"k": "v"},
        metrics=object(),
        session_id="sess-1",
    )


def _search_skill() -> Skill:
    """A tiny in-memory skill used by registry/runtime tests."""

    async def search(args: dict, ctx: SkillContext) -> SkillResult:
        return SkillResult.ok({"hits": [args["q"]] * args.get("n", 1)})

    class SearchSkill(Skill):
        name = "search"
        description = "Tiny search skill for tests"
        actions = {
            "search": SkillAction(
                description="Search for a query",
                handler=search,
                input_schema={
                    "type": "object",
                    "properties": {
                        "q": {"type": "string"},
                        "n": {"type": "integer"},
                    },
                    "required": ["q"],
                },
            ),
        }

    return SearchSkill()


def _write_skill() -> Skill:
    """A skill that requires pre-execution confirmation."""

    async def write(args: dict, ctx: SkillContext) -> SkillResult:
        return SkillResult.ok({"written": args["page"]})

    class WriteSkill(Skill):
        name = "write"
        description = "Tiny write skill (requires pre-confirm)"
        actions = {
            "write_page": SkillAction(
                description="Write a page",
                handler=write,
                requires_confirmation="pre",
                action_type="write",
                input_schema={
                    "type": "object",
                    "properties": {"page": {"type": "string"}},
                    "required": ["page"],
                    "additionalProperties": False,
                },
            ),
        }

    return WriteSkill()


# ─── SkillResult ───────────────────────────────────────────────────


class TestSkillResult:
    def test_ok_factory(self) -> None:
        r = SkillResult.ok({"x": 1})
        assert r.status == "ok"
        assert r.data == {"x": 1}
        assert r.error is None
        assert r.confirmation_id is None

    def test_ok_default_empty(self) -> None:
        r = SkillResult.ok()
        assert r.status == "ok"
        assert r.data == {}

    def test_fail_factory(self) -> None:
        r = SkillResult.fail("oops", extra="info")
        assert r.status == "error"
        assert r.error == "oops"
        assert r.data == {"extra": "info"}

    def test_needs_confirmation(self) -> None:
        r = SkillResult.needs_confirmation("conf-123", "please confirm")
        assert r.status == "needs_confirmation"
        assert r.confirmation_id == "conf-123"
        assert r.error == "please confirm"

    def test_to_dict_minimal(self) -> None:
        d = SkillResult.ok({"a": 1}).to_dict()
        assert d == {"status": "ok", "data": {"a": 1}}
        assert "error" not in d
        assert "confirmation_id" not in d

    def test_to_dict_with_error(self) -> None:
        d = SkillResult.fail("bad").to_dict()
        assert d["error"] == "bad"

    def test_to_dict_with_confirmation_id(self) -> None:
        d = SkillResult.needs_confirmation("c-1").to_dict()
        assert d["confirmation_id"] == "c-1"

    def test_default_construction(self) -> None:
        r = SkillResult()
        assert r.status == "ok"
        assert r.data == {}


# ─── SkillAction ───────────────────────────────────────────────────


class TestSkillAction:
    def test_requires_handler(self) -> None:
        with pytest.raises(ValueError, match="requires a handler"):
            SkillAction(name="x", description="x")

    def test_invalid_action_type(self) -> None:
        with pytest.raises(ValueError, match="action_type"):
            SkillAction(
                name="x", description="x",
                handler=lambda a, c: SkillResult.ok(),
                action_type="delete",
            )

    def test_default_name_empty(self) -> None:
        a = SkillAction(description="x", handler=lambda a, c: SkillResult.ok())
        assert a.name == ""

    def test_action_type_default_read(self) -> None:
        a = SkillAction(description="x", handler=lambda a, c: SkillResult.ok())
        assert a.action_type == "read"

    def test_input_schema_default(self) -> None:
        a = SkillAction(description="x", handler=lambda a, c: SkillResult.ok())
        assert a.input_schema["type"] == "object"
        assert a.input_schema["properties"] == {}

    def test_requires_confirmation_default_false(self) -> None:
        a = SkillAction(description="x", handler=lambda a, c: SkillResult.ok())
        assert a.requires_confirmation is False


# ─── SkillContext ─────────────────────────────────────────────────


class TestSkillContext:
    def test_defaults(self) -> None:
        c = SkillContext()
        assert c.wiki is None
        assert c.db is None
        assert c.llm_client is None
        assert c.config == {}
        assert c.metrics is None
        assert c.session_id == ""

    def test_with_overrides_returns_new(self, ctx: SkillContext) -> None:
        c2 = ctx.with_overrides(session_id="other")
        assert c2 is not ctx
        assert c2.session_id == "other"
        assert ctx.session_id == "sess-1"

    def test_with_overrides_preserves_other_fields(self, ctx: SkillContext) -> None:
        c2 = ctx.with_overrides(session_id="x")
        assert c2.wiki is ctx.wiki
        assert c2.db is ctx.db
        assert c2.config == {"k": "v"}


# ─── Skill ABC ─────────────────────────────────────────────────────


class TestSkillABC:
    def test_name_required(self) -> None:
        with pytest.raises(ValueError, match="must set class attribute 'name'"):
            class Bad(Skill):
                description = "x"
                actions = {"a": SkillAction(description="a", handler=lambda a, c: SkillResult.ok())}
            Bad()

    def test_actions_required(self) -> None:
        with pytest.raises(ValueError, match="at least one action"):
            class Bad(Skill):
                name = "n"
                description = "x"
                actions = {}
            Bad()

    def test_action_name_auto_filled_from_dict_key(self) -> None:
        s = _search_skill()
        assert s.actions["search"].name == "search"

    def test_get_action_found(self) -> None:
        s = _search_skill()
        assert s.get_action("search") is not None

    def test_get_action_missing_returns_none(self) -> None:
        s = _search_skill()
        assert s.get_action("nope") is None

    def test_list_actions_sorted(self) -> None:
        s = _search_skill()
        assert s.list_actions() == ["search"]

    def test_setup_and_teardown_called(self) -> None:
        calls: list[str] = []

        class Tracked(Skill):
            name = "t"
            description = "t"
            actions = {
                "a": SkillAction(description="a", handler=lambda a, c: SkillResult.ok()),
            }
            def setup(self) -> None:
                calls.append("setup")
            def teardown(self) -> None:
                calls.append("teardown")

        reg = SkillRegistry()
        reg.register(Tracked())
        reg.clear()
        assert calls == ["setup", "teardown"]

    def test_manifest_includes_action_descriptions(self) -> None:
        s = _search_skill()
        m = s.manifest()
        assert m.name == "search"
        assert m.description == "Tiny search skill for tests"
        assert m.action_count == 1
        assert m.actions[0]["name"] == "search"
        assert m.actions[0]["description"] == "Search for a query"


# ─── SkillManifest ─────────────────────────────────────────────────


class TestSkillManifest:
    def test_action_count(self) -> None:
        m = SkillManifest(name="x", description="y", actions=[{}, {}, {}])
        assert m.action_count == 3

    def test_to_dict(self) -> None:
        m = SkillManifest(
            name="search",
            description="desc",
            actions=[{"name": "go", "description": "do it"}],
        )
        d = m.to_dict()
        assert d == {
            "name": "search",
            "description": "desc",
            "actions": [{"name": "go", "description": "do it"}],
        }


# ─── Errors ────────────────────────────────────────────────────────


class TestErrors:
    def test_skill_not_found(self) -> None:
        e = SkillNotFoundError("foo")
        assert e.skill_name == "foo"
        assert "foo" in str(e)

    def test_action_not_found(self) -> None:
        e = ActionNotFoundError("foo", "bar")
        assert e.skill_name == "foo"
        assert e.action_name == "bar"

    def test_skill_validation_error(self) -> None:
        e = SkillValidationError("bad", skill_name="s", action_name="a", errors=["x"])
        assert e.skill_name == "s"
        assert e.action_name == "a"
        assert e.errors == ["x"]

    def test_skill_execution_error_with_cause(self) -> None:
        cause = ValueError("root")
        e = SkillExecutionError("wrapper", cause=cause)
        assert e.__cause__ is cause

    def test_confirmation_required(self) -> None:
        e = ConfirmationRequiredError("s", "a", {"x": 1})
        assert e.skill_name == "s"
        assert e.action_name == "a"
        assert e.action_args == {"x": 1}

    def test_all_inherit_skill_error(self) -> None:
        for cls in (
            SkillNotFoundError,
            ActionNotFoundError,
            SkillValidationError,
            SkillExecutionError,
            ConfirmationRequiredError,
        ):
            assert issubclass(cls, SkillError)


# ─── SkillRegistry ─────────────────────────────────────────────────


class TestSkillRegistry:
    def test_empty_on_init(self, fresh_registry: SkillRegistry) -> None:
        assert len(fresh_registry) == 0
        assert fresh_registry.list_names() == []

    def test_register_returns_skill(self, fresh_registry: SkillRegistry) -> None:
        s = _search_skill()
        assert fresh_registry.register(s) is s

    def test_register_replaces_with_warning(
        self, fresh_registry: SkillRegistry, caplog: pytest.LogCaptureFixture
    ) -> None:
        fresh_registry.register(_search_skill())
        fresh_registry.register(_search_skill())
        assert any("Replacing" in r.message for r in caplog.records)

    def test_register_reject_on_duplicate(
        self, fresh_registry: SkillRegistry
    ) -> None:
        fresh_registry.register(_search_skill())
        with pytest.raises(ValueError, match="already registered"):
            fresh_registry.register(_search_skill(), replace=False)

    def test_register_requires_skill_instance(
        self, fresh_registry: SkillRegistry
    ) -> None:
        with pytest.raises(TypeError, match="requires a Skill"):
            fresh_registry.register("not a skill")  # type: ignore[arg-type]

    def test_unregister_returns_removed(
        self, fresh_registry: SkillRegistry
    ) -> None:
        fresh_registry.register(_search_skill())
        assert fresh_registry.unregister("search") is not None
        assert fresh_registry.get("search") is None

    def test_unregister_unknown_returns_none(
        self, fresh_registry: SkillRegistry
    ) -> None:
        assert fresh_registry.unregister("nope") is None

    def test_clear(self, fresh_registry: SkillRegistry) -> None:
        fresh_registry.register(_search_skill())
        fresh_registry.register(_write_skill())
        fresh_registry.clear()
        assert len(fresh_registry) == 0

    def test_get_and_has(self, fresh_registry: SkillRegistry) -> None:
        s = _search_skill()
        fresh_registry.register(s)
        assert fresh_registry.get("search") is s
        assert fresh_registry.has("search")
        assert fresh_registry.get("missing") is None
        assert not fresh_registry.has("missing")

    def test_find_action(self, fresh_registry: SkillRegistry) -> None:
        fresh_registry.register(_search_skill())
        skill, action = fresh_registry.find_action("search", "search")
        assert skill.name == "search"
        assert action.name == "search"

    def test_find_action_missing_skill_raises(
        self, fresh_registry: SkillRegistry
    ) -> None:
        with pytest.raises(SkillNotFoundError):
            fresh_registry.find_action("nope", "x")

    def test_find_action_missing_action_raises(
        self, fresh_registry: SkillRegistry
    ) -> None:
        fresh_registry.register(_search_skill())
        with pytest.raises(ActionNotFoundError):
            fresh_registry.find_action("search", "nope")

    def test_parse_qualified(self, fresh_registry: SkillRegistry) -> None:
        assert fresh_registry.parse_qualified("a.b") == ("a", "b")

    def test_parse_qualified_no_dot_raises(
        self, fresh_registry: SkillRegistry
    ) -> None:
        with pytest.raises(ValueError, match="skill.action"):
            fresh_registry.parse_qualified("nodot")

    def test_parse_qualified_empty_part_raises(
        self, fresh_registry: SkillRegistry
    ) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            fresh_registry.parse_qualified(".b")
        with pytest.raises(ValueError, match="non-empty"):
            fresh_registry.parse_qualified("a.")

    def test_all_manifests_sorted(
        self, fresh_registry: SkillRegistry
    ) -> None:
        fresh_registry.register(_write_skill())
        fresh_registry.register(_search_skill())
        names = [m.name for m in fresh_registry.all_manifests()]
        assert names == ["search", "write"]

    def test_all_actions_no_filter(
        self, fresh_registry: SkillRegistry
    ) -> None:
        fresh_registry.register(_search_skill())
        fresh_registry.register(_write_skill())
        out = fresh_registry.all_actions()
        assert len(out) == 2
        assert all(isinstance(a, SkillAction) for _, a in out)

    def test_all_actions_tag_filter(
        self, fresh_registry: SkillRegistry
    ) -> None:
        class Tagged(Skill):
            name = "tagged"
            description = "tag demo"
            actions = {
                "a": SkillAction(
                    description="a",
                    handler=lambda a, c: SkillResult.ok(),
                    tags=["low-level"],
                ),
                "b": SkillAction(
                    description="b",
                    handler=lambda a, c: SkillResult.ok(),
                    tags=["crud"],
                ),
            }

        fresh_registry.register(Tagged())
        low = fresh_registry.all_actions(tag="low-level")
        assert [(n, a.name) for n, a in low] == [("tagged", "a")]

    def test_iteration(self, fresh_registry: SkillRegistry) -> None:
        fresh_registry.register(_search_skill())
        names = sorted(s.name for s in fresh_registry)
        assert names == ["search"]

    def test_contains(self, fresh_registry: SkillRegistry) -> None:
        fresh_registry.register(_search_skill())
        assert "search" in fresh_registry
        assert "nope" not in fresh_registry
        assert object() not in fresh_registry

    def test_thread_safety(self, fresh_registry: SkillRegistry) -> None:
        """N threads concurrently register unique skills, all land in registry."""
        N = 50
        errors: list[Exception] = []

        def worker(i: int) -> None:
            try:
                class ThreadSkill(Skill):
                    name = f"thread-{i}"
                    description = f"thread {i}"
                    actions = {
                        "go": SkillAction(
                            description="go",
                            handler=lambda a, c: SkillResult.ok(),
                        ),
                    }
                fresh_registry.register(ThreadSkill())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(fresh_registry) == N


# ─── Default singleton ────────────────────────────────────────────


class TestDefaultRegistry:
    def test_returns_same_instance(self) -> None:
        a = default_registry()
        b = default_registry()
        assert a is b

    def test_reset_replaces(self) -> None:
        a = default_registry()
        b = reset_default_registry()
        assert a is not b
        assert b is default_registry()


# ─── SkillRuntime ──────────────────────────────────────────────────


class TestSkillRuntime:
    def test_default_uses_singleton(self) -> None:
        r = SkillRuntime.default()
        assert r.registry is default_registry()

    @pytest.mark.asyncio
    async def test_execute_async_handler(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "search", {"q": "x", "n": 3}, ctx)
        assert result.status == "ok"
        assert result.data == {"hits": ["x", "x", "x"]}

    @pytest.mark.asyncio
    async def test_execute_sync_handler(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        def sync_handler(args: dict, ctx: SkillContext) -> SkillResult:
            return SkillResult.ok({"sync": True, "q": args["q"]})

        class Sync(Skill):
            name = "sync"
            description = "sync skill"
            actions = {
                "go": SkillAction(
                    description="go",
                    handler=sync_handler,
                    input_schema={
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                ),
            }

        fresh_registry.register(Sync())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("sync", "go", {"q": "hi"}, ctx)
        assert result.status == "ok"
        assert result.data == {"sync": True, "q": "hi"}

    @pytest.mark.asyncio
    async def test_execute_returns_skillresult_when_handler_returns_dict(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        def dict_handler(args: dict, ctx: SkillContext) -> dict:
            return {"raw": "dict"}

        class Dicty(Skill):
            name = "dicty"
            description = "dict handler"
            actions = {
                "go": SkillAction(description="go", handler=dict_handler),
            }

        fresh_registry.register(Dicty())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("dicty", "go", {}, ctx)
        assert result.status == "ok"
        assert result.data == {"raw": "dict"}

    @pytest.mark.asyncio
    async def test_execute_unknown_skill(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("nope", "x", {}, ctx)
        assert result.status == "error"
        assert "Skill not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_unknown_action(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "nope", {}, ctx)
        assert result.status == "error"
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_missing_required(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "search", {}, ctx)
        assert result.status == "error"
        assert "missing required" in result.error
        assert "q" in result.error

    @pytest.mark.asyncio
    async def test_execute_wrong_type(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "search", {"q": 123}, ctx)
        assert result.status == "error"
        assert "wrong type" in result.error

    @pytest.mark.asyncio
    async def test_execute_unexpected_arg_with_additional_false(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_write_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("write", "write_page", {"page": "x", "extra": 1}, ctx)
        assert result.status == "error"
        assert "unexpected argument" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_exception_becomes_fail(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        async def boom(args: dict, ctx: SkillContext) -> SkillResult:
            raise ValueError("nope")

        class Boom(Skill):
            name = "boom"
            description = "boom"
            actions = {"go": SkillAction(description="go", handler=boom)}

        fresh_registry.register(Boom())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("boom", "go", {}, ctx)
        assert result.status == "error"
        assert "nope" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_returns_wrong_type_raises(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        def bad_return(args: dict, ctx: SkillContext) -> str:
            return "not a SkillResult or dict"

        class Bad(Skill):
            name = "bad"
            description = "bad"
            actions = {"go": SkillAction(description="go", handler=bad_return)}

        fresh_registry.register(Bad())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("bad", "go", {}, ctx)
        assert result.status == "error"
        assert "str" in result.error

    @pytest.mark.asyncio
    async def test_execute_qualified(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute_qualified("search.search", {"q": "y"}, ctx)
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_execute_qualified_malformed(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute_qualified("nodot", {}, ctx)
        assert result.status == "error"
        assert "skill.action" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_args(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "search", None, ctx)
        assert result.status == "error"
        assert "missing required" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_ctx(self, fresh_registry: SkillRegistry) -> None:
        fresh_registry.register(_search_skill())
        rt = SkillRuntime(fresh_registry)
        result = await rt.execute("search", "search", {"q": "z"})
        assert result.status == "ok"

    @pytest.mark.asyncio
    async def test_execute_threads_ctx_to_handler(
        self, fresh_registry: SkillRegistry, ctx: SkillContext
    ) -> None:
        seen: dict[str, Any] = {}

        def grab(args: dict, c: SkillContext) -> SkillResult:
            seen["session_id"] = c.session_id
            seen["config"] = c.config
            return SkillResult.ok({})

        class Grab(Skill):
            name = "grab"
            description = "grab"
            actions = {"go": SkillAction(description="go", handler=grab)}

        fresh_registry.register(Grab())
        rt = SkillRuntime(fresh_registry)
        await rt.execute("grab", "go", {}, ctx)
        assert seen["session_id"] == "sess-1"
        assert seen["config"] == {"k": "v"}


# ─── Validator edge cases ────────────────────────────────────────


class TestValidator:
    """Direct tests for the schema-validation helpers (white-box)."""

    def test_check_type_string(self) -> None:
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type("x", "string")
        assert not _check_type(1, "string")

    def test_check_type_integer_vs_boolean(self) -> None:
        """bool is a subclass of int; we must reject booleans for integer."""
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type(1, "integer")
        assert not _check_type(True, "integer")

    def test_check_type_number(self) -> None:
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type(1, "number")
        assert _check_type(1.5, "number")
        assert not _check_type("x", "number")

    def test_check_type_array_and_object(self) -> None:
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type([], "array")
        assert not _check_type({}, "array")
        assert _check_type({}, "object")
        assert not _check_type([], "object")

    def test_check_type_unknown_returns_true(self) -> None:
        """The runtime is a subset validator: unknown types pass."""
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type("x", "anyOf")
        assert _check_type("x", ["string", "anyOf"])

    def test_check_type_list_of_types(self) -> None:
        from llmwikify.apps.chat.skills.runtime import _check_type
        assert _check_type(1, ["string", "integer"])

    def test_validate_args_rejects_non_object_schema(self) -> None:
        from llmwikify.apps.chat.skills.runtime import _validate_args
        a = SkillAction(
            description="x",
            handler=lambda a, c: SkillResult.ok(),
            input_schema={"type": "array"},
        )
        errs = _validate_args(a, [])
        assert errs and "only 'object'" in errs[0]
