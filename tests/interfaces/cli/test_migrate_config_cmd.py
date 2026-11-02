"""Unit tests for ``interfaces/cli/commands/migrate_config_cmd.py``.

``run_migrate_config`` calls into ``foundation.migration`` — the tests
monkeypatch that boundary and drive every ``result.reason`` branch.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.migrate_config_cmd import (
    MigrateConfigCommand,
    _format_plan,
    run_migrate_config,
)


def _result(**kw: Any) -> SimpleNamespace:
    defaults: dict[str, Any] = {
        "wiki_root": Path("/w"),
        "migrated": False,
        "reason": None,
        "backup_path": None,
        "changes": [],
        "conflicts": [],
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _change(**kw: Any) -> SimpleNamespace:
    defaults = {
        "section": "llm",
        "key": "provider",
        "old_value": "openai",
        "new_value": "anthropic",
        "conflict": False,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "wiki_root": None,
        "dry_run": False,
        "strict": False,
        "auto_global": False,
        "auto_wiki": False,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


@pytest.fixture
def fake_migrate(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Replace foundation.migration.auto_migrate_wiki_config with a recorder."""
    import llmwikify.foundation.migration as mig

    state: dict[str, Any] = {"result": None, "exc": None, "call": None}

    def fake(target_root: Any, auto_resolve: str = "") -> Any:
        state["call"] = (target_root, auto_resolve)
        if state["exc"] is not None:
            raise state["exc"]
        return state["result"]

    monkeypatch.setattr(mig, "auto_migrate_wiki_config", fake)
    return state


# ── _format_plan ────────────────────────────────────────────────────


def test_format_plan_minimal(capsys: pytest.CaptureFixture) -> None:
    out = _format_plan(_result())
    assert f"Wiki root: {Path('/w')}" in out
    assert "Status:    skipped" in out


def test_format_plan_migrated_status() -> None:
    out = _format_plan(_result(migrated=True, reason=None))
    assert "Status:    migrated" in out


def test_format_plan_with_backup() -> None:
    out = _format_plan(_result(backup_path="/w/.wiki-config.yaml.bak.1"))
    assert "Backup:    /w/.wiki-config.yaml.bak.1" in out


def test_format_plan_changes_and_conflicts() -> None:
    # NOTE: source uses `ch.old_value is object()` which is always False
    # (fresh object each call) — the "<new>" branch is dead code. Assert
    # the repr path that actually runs.
    result = _result(
        changes=[
            _change(),
            _change(key="model", old_value=None, new_value="gpt", conflict=True),
        ],
        conflicts=[
            SimpleNamespace(section="llm", key="api_key", global_value="g1", wiki_value="w1"),
        ],
    )
    out = _format_plan(result)
    assert "Changes (2):" in out
    assert "llm.provider: 'openai' → 'anthropic'" in out
    assert "[conflict]" in out
    assert "llm.model: None → 'gpt'" in out
    assert "Conflicts (1):" in out
    assert "global='g1'" in out and "wiki='w1'" in out


def test_format_plan_no_changes_no_conflicts() -> None:
    out = _format_plan(_result())
    assert "Changes" not in out
    assert "Conflicts" not in out


# ── run_migrate_config: auto_resolve mapping ────────────────────────


def test_dry_run_maps_to_dry_run(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="dry_run")
    rc = run_migrate_config(None, tmp_path, _args(dry_run=True))
    assert fake_migrate["call"][1] == "dry_run"
    assert rc == 0


def test_strict_maps_to_strict(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    run_migrate_config(None, tmp_path, _args(strict=True))
    assert fake_migrate["call"][1] == "strict"


def test_auto_wiki_maps_to_wiki(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    run_migrate_config(None, tmp_path, _args(auto_wiki=True))
    assert fake_migrate["call"][1] == "wiki"


def test_auto_global_maps_to_global(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    run_migrate_config(None, tmp_path, _args(auto_global=True))
    assert fake_migrate["call"][1] == "global"


def test_default_maps_to_interactive(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    run_migrate_config(None, tmp_path, _args())
    assert fake_migrate["call"][1] == "interactive"


def test_wiki_root_override(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    custom = tmp_path / "custom"
    custom.mkdir()
    run_migrate_config(None, tmp_path, _args(wiki_root=str(custom)))
    assert fake_migrate["call"][0] == custom.resolve()


# ── run_migrate_config: reason branches ─────────────────────────────


def test_reason_no_migratable(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(reason="no_migratable_sections")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 0
    assert "Nothing to migrate" in capsys.readouterr().out


def test_reason_already_migrated(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(reason="already_migrated")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 0
    assert "Already on latest schema" in capsys.readouterr().out


def test_reason_no_config(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 0
    assert "No .wiki-config.yaml found" in capsys.readouterr().out


def test_reason_parse_error(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(reason="parse_error")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 1
    assert "Failed to parse" in capsys.readouterr().out


def test_reason_dry_run(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(reason="dry_run", changes=[_change()])
    rc = run_migrate_config(None, tmp_path, _args(dry_run=True))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Dry run complete" in out
    assert "Changes (1):" in out


def test_migrated_success(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["result"] = _result(
        migrated=True,
        changes=[_change(), _change(key="model")],
        backup_path="/w/bak",
    )
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Migrated 2 fields" in out
    assert "Backup saved at: /w/bak" in out


def test_migrated_false_falls_through(tmp_path: Path, fake_migrate: dict) -> None:
    # migrated=False and no recognized reason → return 1
    fake_migrate["result"] = _result(migrated=False, reason=None)
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 1


# ── run_migrate_config: exceptions ──────────────────────────────────


def test_runtime_error(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["exc"] = RuntimeError("boom")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 1
    assert "Migration failed: boom" in capsys.readouterr().out


def test_unexpected_error(tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture) -> None:
    fake_migrate["exc"] = ValueError("weird")
    rc = run_migrate_config(None, tmp_path, _args())
    assert rc == 1
    assert "Unexpected error" in capsys.readouterr().out


# ── MigrateConfigCommand ────────────────────────────────────────────


def test_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    MigrateConfigCommand().setup_parser(sub)
    ns = parser.parse_args(
        ["migrate-config", "--dry-run", "--strict", "--auto-global", "--auto-wiki", "--wiki-root", "/x"]
    )
    assert ns.dry_run is True
    assert ns.strict is True
    assert ns.auto_global is True
    assert ns.auto_wiki is True
    assert ns.wiki_root == "/x"


def test_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    MigrateConfigCommand().setup_parser(sub)
    ns = parser.parse_args(["migrate-config"])
    assert ns.dry_run is False
    assert ns.strict is False
    assert ns.auto_global is False
    assert ns.auto_wiki is False
    assert ns.wiki_root is None


def test_command_run_uses_wiki_root(
    tmp_path: Path, fake_migrate: dict, capsys: pytest.CaptureFixture
) -> None:
    fake_migrate["result"] = _result(reason="no_config")

    class W:
        root = tmp_path

    cmd = MigrateConfigCommand()
    rc = cmd.run(_args(), W(), {})
    assert rc == 0
    assert fake_migrate["call"][0] == tmp_path


def test_command_run_custom_root_builds_wiki(
    tmp_path: Path, fake_migrate: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    import llmwikify.kernel as kernel

    built: list[Path] = []

    class StubWiki:
        def __init__(self, root: Path, config: dict | None = None):
            built.append(root)
            self.root = root

    monkeypatch.setattr(kernel, "Wiki", StubWiki)
    custom = tmp_path / "c"
    custom.mkdir()
    cmd = MigrateConfigCommand()
    rc = cmd.run(_args(wiki_root=str(custom)), object(), {})
    assert rc == 0
    assert built and built[0] == custom.resolve()
    assert fake_migrate["call"][0] == custom.resolve()


def test_command_run_no_wiki_root_attr(tmp_path: Path, fake_migrate: dict) -> None:
    fake_migrate["result"] = _result(reason="no_config")
    cmd = MigrateConfigCommand()
    # object() has no .root → falls back to Path.cwd()
    rc = cmd.run(_args(), object(), {})
    assert rc == 0
    assert fake_migrate["call"][0] == Path.cwd()


def test_name_help() -> None:
    cmd = MigrateConfigCommand()
    assert cmd.name == "migrate-config"
    assert "0.41" in cmd.help
