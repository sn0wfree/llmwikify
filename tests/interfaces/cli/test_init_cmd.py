"""Unit tests for ``interfaces/cli/commands/init_cmd.py``.

``run_init`` delegates to ``wiki.init(...)`` — the tests use a fake
wiki returning canned status dicts. The interactive LLM prompt is
bypassed via ``no_llm_prompt`` or by making stdin non-tty.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.init_cmd import (
    InitCommand,
    _maybe_prompt_llm_setup,
    run_init,
)


class FakeWiki:
    def __init__(self, result: dict, root: str | Path = "/w"):
        self._result = result
        self.root = Path(root)
        self.init_kwargs: dict[str, Any] | None = None

    def init(self, **kwargs: Any) -> dict:
        self.init_kwargs = kwargs
        return self._result


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "overwrite": False,
        "agent": None,
        "force": False,
        "merge": False,
        "llm": False,
        "llm_provider": None,
        "llm_model": None,
        "llm_api_key": None,
        "llm_base_url": None,
        "llm_overwrite": False,
        "no_llm_prompt": True,  # default: skip interactive prompt
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ── run_init: invalid agent ─────────────────────────────────────────


def test_invalid_agent(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "ok"})
    rc = run_init(wiki, "/w", _args(agent="bogus"))
    assert rc == 1
    out = capsys.readouterr().out
    assert "Invalid agent type 'bogus'" in out
    assert "opencode" in out  # lists VALID_AGENTS
    assert wiki.init_kwargs is None  # never called


def test_valid_agent_forwarded() -> None:
    wiki = FakeWiki({"status": "created", "message": "ok", "created_files": [], "skipped_files": []})
    rc = run_init(wiki, "/w", _args(agent="opencode"))
    assert rc == 0
    assert wiki.init_kwargs == {
        "overwrite": False,
        "agent": "opencode",
        "force": False,
        "merge": False,
    }


# ── run_init: already_exists ────────────────────────────────────────


def test_already_exists_no_agent(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "already_exists", "existing_files": ["index.md", "wiki.md"]}
    )
    rc = run_init(wiki, "/w", _args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "already initialized" in out
    assert "index.md, wiki.md" in out
    assert "--overwrite to reinitialize" in out


def test_already_exists_with_agent(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "already_exists", "existing_files": ["index.md"]})
    rc = run_init(wiki, "/w", _args(agent="claude"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "--force to overwrite or --merge" in out


# ── run_init: mcp_config_added ──────────────────────────────────────


def test_mcp_config_added(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {
            "status": "mcp_config_added",
            "created_files": [".mcp.json"],
            "warnings": ["port already in use"],
        }
    )
    rc = run_init(wiki, "/w", _args(agent="opencode"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "MCP config added" in out
    assert ".mcp.json" in out
    assert "port already in use" in out


def test_mcp_config_added_no_files(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki({"status": "mcp_config_added", "created_files": []})
    rc = run_init(wiki, "/w", _args(agent="claude"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "MCP config added" in out
    assert "Added:" not in out


# ── run_init: created ───────────────────────────────────────────────


def test_created_basic(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {
            "status": "created",
            "message": "Wiki created",
            "created_files": ["index.md", "wiki.md"],
            "skipped_files": ["log.md"],
        }
    )
    rc = run_init(wiki, "/w", _args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "Wiki created" in out
    assert "Created: index.md, wiki.md" in out
    assert "Skipped: log.md" in out
    assert "Next steps:" in out
    assert "Drop sources into raw/" in out


def test_created_with_agent_opencode(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    rc = run_init(wiki, "/w", _args(agent="opencode"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "Run: opencode" in out
    assert "Start ingesting news" in out


def test_created_with_agent_claude(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    run_init(wiki, "/w", _args(agent="claude"))
    assert "Run: claude" in capsys.readouterr().out


def test_created_with_agent_codex(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    run_init(wiki, "/w", _args(agent="codex"))
    assert "codex mode" in capsys.readouterr().out


def test_created_with_warnings_and_raw_stats(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {
            "status": "created",
            "message": "ok",
            "created_files": [],
            "skipped_files": [],
            "warnings": ["some warning"],
            "raw_stats": {
                "total": 12,
                "categories": {"news": 8, "docs": 3, "misc": 1},
            },
        }
    )
    rc = run_init(wiki, "/w", _args())
    assert rc == 0
    out = capsys.readouterr().out
    assert "some warning" in out
    assert "Source analysis:" in out
    assert "12 files in 3 categories" in out
    assert "news (8)" in out


def test_created_raw_stats_zero_total(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {
            "status": "created",
            "message": "ok",
            "created_files": [],
            "skipped_files": [],
            "raw_stats": {"total": 0, "categories": {}},
        }
    )
    run_init(wiki, "/w", _args())
    assert "Source analysis" not in capsys.readouterr().out


def test_created_no_raw_stats_key(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    run_init(wiki, "/w", _args())
    assert "Source analysis" not in capsys.readouterr().out


# ── run_init: --llm flag ────────────────────────────────────────────


def test_llm_flag_calls_create(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    captured: dict[str, Any] = {}

    def fake_create(**kwargs: Any) -> int:
        captured.update(kwargs)
        return 0

    import llmwikify.interfaces.cli.commands.init_llm_cmd as ilc

    monkeypatch.setattr(ilc, "create_llm_config", fake_create)
    # Also patch the re-import inside run_init via the module attribute
    rc = run_init(
        wiki,
        "/w",
        _args(
            llm=True,
            llm_provider="openai",
            llm_model="gpt-4o",
            llm_api_key="k",
            llm_base_url="https://x",
            llm_overwrite=True,
        ),
    )
    assert rc == 0
    assert captured == {
        "provider": "openai",
        "model": "gpt-4o",
        "api_key": "k",
        "base_url": "https://x",
        "overwrite": True,
    }
    # no_llm_prompt default True so prompt path not taken; but llm=True path is
    assert "Next steps" in capsys.readouterr().out


def test_llm_flag_failure_rc(monkeypatch: pytest.MonkeyPatch) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )

    import llmwikify.interfaces.cli.commands.init_llm_cmd as ilc

    monkeypatch.setattr(ilc, "create_llm_config", lambda **kw: 2)
    rc = run_init(wiki, "/w", _args(llm=True))
    assert rc == 2


# ── run_init: prompt path ───────────────────────────────────────────


def test_prompt_skipped_when_no_llm_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []}
    )
    called = {"n": 0}

    def fake_prompt() -> int:
        called["n"] += 1
        return 0

    monkeypatch.setattr(
        "llmwikify.interfaces.cli.commands.init_cmd._maybe_prompt_llm_setup",
        fake_prompt,
    )
    run_init(wiki, "/w", _args(no_llm_prompt=True))
    assert called["n"] == 0

    run_init(wiki, "/w", _args(no_llm_prompt=False))
    assert called["n"] == 1


# ── _maybe_prompt_llm_setup ─────────────────────────────────────────


def test_prompt_returns_0_when_config_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmwikify.interfaces.cli.commands import init_llm_cmd as ilc

    cfg = tmp_path / "llmwikify.json"
    cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(ilc, "CONFIG_PATH", cfg)
    # patch the name imported inside _maybe_prompt_llm_setup
    import llmwikify.interfaces.cli.commands.init_cmd as init_mod

    # The function does `from .init_llm_cmd import CONFIG_PATH` at call time,
    # so patching ilc.CONFIG_PATH is enough.
    assert _maybe_prompt_llm_setup() == 0


def test_prompt_returns_0_when_not_tty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from llmwikify.interfaces.cli.commands import init_llm_cmd as ilc

    cfg = tmp_path / "nope.json"  # does not exist
    monkeypatch.setattr(ilc, "CONFIG_PATH", cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert _maybe_prompt_llm_setup() == 0


def test_prompt_decline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from llmwikify.interfaces.cli.commands import init_llm_cmd as ilc

    cfg = tmp_path / "nope.json"
    monkeypatch.setattr(ilc, "CONFIG_PATH", cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")
    assert _maybe_prompt_llm_setup() == 0
    out = capsys.readouterr().out
    assert "Set one up now?" in out
    assert "Skipped" in out


def test_prompt_accept_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from llmwikify.interfaces.cli.commands import init_llm_cmd as ilc

    cfg = tmp_path / "nope.json"
    monkeypatch.setattr(ilc, "CONFIG_PATH", cfg)
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def boom() -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    assert _maybe_prompt_llm_setup() == 0
    assert capsys.readouterr().out  # printed a newline


# ── InitCommand ─────────────────────────────────────────────────────


def test_init_command_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitCommand().setup_parser(sub)
    ns = parser.parse_args(
        [
            "init",
            "--overwrite",
            "--agent",
            "opencode",
            "--force",
            "--merge",
            "--llm",
            "--llm-provider",
            "openai",
            "--llm-model",
            "m",
            "--llm-api-key",
            "k",
            "--llm-base-url",
            "u",
            "--llm-overwrite",
            "--no-llm-prompt",
        ]
    )
    assert ns.overwrite is True
    assert ns.agent == "opencode"
    assert ns.force is True
    assert ns.merge is True
    assert ns.llm is True
    assert ns.llm_provider == "openai"
    assert ns.llm_model == "m"
    assert ns.llm_api_key == "k"
    assert ns.llm_base_url == "u"
    assert ns.llm_overwrite is True
    assert ns.no_llm_prompt is True


def test_init_command_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitCommand().setup_parser(sub)
    ns = parser.parse_args(["init"])
    assert ns.overwrite is False
    assert ns.agent is None
    assert ns.llm is False
    assert ns.no_llm_prompt is False


def test_init_command_rejects_bad_agent() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitCommand().setup_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["init", "--agent", "nope"])


def test_init_command_run_uses_wiki_root(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        {"status": "created", "message": "ok", "created_files": [], "skipped_files": []},
        root=Path("/some/root"),
    )
    cmd = InitCommand()
    rc = cmd.run(_args(), wiki, {})
    assert rc == 0
    out = capsys.readouterr().out
    assert "Next steps" in out


def test_init_command_name_help() -> None:
    cmd = InitCommand()
    assert cmd.name == "init"
    assert "wiki" in cmd.help.lower()
