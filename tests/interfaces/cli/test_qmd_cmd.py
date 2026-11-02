"""Unit tests for ``interfaces/cli/commands/qmd.py``.

Dispatcher over five subcommands — driven with a fake wiki and a
monkeypatched ``subprocess.run`` so no external ``qmd`` binary is
ever invoked.
"""

from __future__ import annotations

import argparse
from types import SimpleNamespace
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands import qmd as qmd_mod
from llmwikify.interfaces.cli.commands.qmd import (
    QmdCommand,
    _qmd_embed,
    _qmd_install,
    _qmd_mcp,
    _qmd_search,
    _qmd_status,
    run_qmd,
)


class FakeQmd:
    def __init__(self, available: bool = True, install_guide: str = "npm i -g qmd"):
        self._available = available
        self._guide = install_guide
        self.embed_calls = 0

    def is_available(self) -> bool:
        return self._available

    def get_install_guide(self) -> str:
        return self._guide

    def embed(self) -> dict:
        self.embed_calls += 1
        return {"status": "ok"}


class FakeWiki:
    def __init__(
        self,
        status: dict | None = None,
        results: list | None = None,
        qmd: FakeQmd | None = None,
        root: str = "/w",
    ):
        self._status = status or {
            "page_count": 100,
            "available": True,
            "recommended": False,
        }
        self._results = results if results is not None else []
        self.qmd = qmd
        self.root = root
        self.search_calls: list[tuple] = []

    def qmd_status(self) -> dict:
        return self._status

    def search(self, query: str, limit: int = 10, backend: str = "") -> list:
        self.search_calls.append((query, limit, backend))
        return self._results


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"qmd_subcommand": "status"}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ── _qmd_status ─────────────────────────────────────────────────────


def test_status_basic(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki()
    assert _qmd_status(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "QMD Hybrid Search Status" in out
    assert "Pages in wiki: 100" in out
    assert "QMD available: ✅ Yes" in out
    assert "QMD recommended: ℹ️ No" in out


def test_status_with_message(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        status={
            "page_count": 5,
            "available": False,
            "recommended": True,
            "threshold": 500,
            "backend": "hybrid",
            "message": "install qmd",
        }
    )
    assert _qmd_status(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "QMD threshold: 500" in out
    assert "Configured backend: hybrid" in out
    assert "QMD available: ❌ No" in out
    assert "QMD recommended: ✅ Yes" in out
    assert "💡 install qmd" in out


# ── _qmd_search ─────────────────────────────────────────────────────


def test_search_no_results(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(results=[])
    assert _qmd_search(wiki, _args(query="foo")) == 1
    out = capsys.readouterr().out
    assert "No results found" in out
    assert "qmd mcp" in out


def test_search_with_results(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(
        results=[
            {"page_name": "a", "score": 0.9123, "snippet": "hello"},
            {"page_name": "b", "score": 0.5, "snippet": "world"},
        ]
    )
    assert _qmd_search(wiki, _args(query="hello", limit=5)) == 0
    out = capsys.readouterr().out
    assert "results for: hello" in out
    assert "1. a" in out and "2. b" in out
    assert "Score: 0.9123" in out
    assert wiki.search_calls == [("hello", 5, "qmd")]


# ── _qmd_install ────────────────────────────────────────────────────


def test_install_with_wiki_qmd(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(qmd=FakeQmd(install_guide="GUIDE-FROM-WIKI"))
    assert _qmd_install(wiki, _args()) == 0
    assert "GUIDE-FROM-WIKI" in capsys.readouterr().out


def test_install_without_wiki_qmd(capsys: pytest.CaptureFixture) -> None:
    # Falls back to constructing a real QmdClient — its guide is a string.
    wiki = FakeWiki(qmd=None)
    assert _qmd_install(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert out.strip()  # something printed


# ── _qmd_embed ──────────────────────────────────────────────────────


def test_embed_unavailable(capsys: pytest.CaptureFixture) -> None:
    wiki = FakeWiki(qmd=FakeQmd(available=False))
    assert _qmd_embed(wiki, _args()) == 1
    out = capsys.readouterr().out
    assert "not available" in out
    assert "qmd mcp" in out


def test_embed_no_qmd_attr(capsys: pytest.CaptureFixture) -> None:
    wiki = SimpleNamespace(qmd=None)
    assert _qmd_embed(wiki, _args()) == 1


def test_embed_success(capsys: pytest.CaptureFixture) -> None:
    q = FakeQmd(available=True)
    wiki = FakeWiki(qmd=q)
    assert _qmd_embed(wiki, _args()) == 0
    out = capsys.readouterr().out
    assert "Starting embedding" in out
    assert "Result: ok" in out
    assert q.embed_calls == 1


# ── _qmd_mcp ────────────────────────────────────────────────────────


def test_mcp_builds_command(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list, cwd: str = "") -> None:
        captured["cmd"] = cmd
        captured["cwd"] = cwd

    monkeypatch.setattr(qmd_mod.subprocess, "run", fake_run)
    wiki = FakeWiki(root="/mywiki")
    assert _qmd_mcp(wiki, _args(port=9000, host="0.0.0.0")) == 0
    assert captured["cmd"] == ["qmd", "mcp", "--http", "--port", "9000", "--host", "0.0.0.0"]
    assert captured["cwd"] == "/mywiki"
    out = capsys.readouterr().out
    assert "Starting QMD MCP server" in out
    assert "Press Ctrl+C" in out


def test_mcp_with_collection(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list, cwd: str = "") -> None:
        captured["cmd"] = cmd

    monkeypatch.setattr(qmd_mod.subprocess, "run", fake_run)
    wiki = FakeWiki()
    assert _qmd_mcp(wiki, _args(collection="docs")) == 0
    assert "--collection" in captured["cmd"]
    assert "docs" in captured["cmd"]


def test_mcp_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run(cmd: list, cwd: str = "") -> None:
        captured["cmd"] = cmd

    monkeypatch.setattr(qmd_mod.subprocess, "run", fake_run)
    assert _qmd_mcp(FakeWiki(), SimpleNamespace()) == 0
    assert captured["cmd"] == ["qmd", "mcp", "--http", "--port", "8181", "--host", "127.0.0.1"]


def test_mcp_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def fake_run(cmd: list, cwd: str = "") -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(qmd_mod.subprocess, "run", fake_run)
    assert _qmd_mcp(FakeWiki(), SimpleNamespace()) == 0
    assert "Server stopped" in capsys.readouterr().out


def test_mcp_file_not_found(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def fake_run(cmd: list, cwd: str = "") -> None:
        raise FileNotFoundError("no qmd")

    monkeypatch.setattr(qmd_mod.subprocess, "run", fake_run)
    assert _qmd_mcp(FakeWiki(), SimpleNamespace()) == 1
    out = capsys.readouterr().out
    assert "not found" in out
    assert "npm install" in out


# ── run_qmd dispatcher ──────────────────────────────────────────────


def test_run_qmd_status(capsys: pytest.CaptureFixture) -> None:
    assert run_qmd(FakeWiki(), _args(qmd_subcommand="status")) == 0
    assert "Status" in capsys.readouterr().out


def test_run_qmd_search(capsys: pytest.CaptureFixture) -> None:
    assert run_qmd(FakeWiki(results=[]), _args(qmd_subcommand="search", query="q")) == 1


def test_run_qmd_install(capsys: pytest.CaptureFixture) -> None:
    assert run_qmd(FakeWiki(qmd=FakeQmd()), _args(qmd_subcommand="install")) == 0


def test_run_qmd_embed(capsys: pytest.CaptureFixture) -> None:
    assert run_qmd(FakeWiki(qmd=FakeQmd()), _args(qmd_subcommand="embed")) == 0


def test_run_qmd_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qmd_mod.subprocess, "run", lambda *a, **k: None)
    assert run_qmd(FakeWiki(), _args(qmd_subcommand="mcp", port=1, host="h")) == 0


def test_run_qmd_unknown(capsys: pytest.CaptureFixture) -> None:
    assert run_qmd(FakeWiki(), _args(qmd_subcommand="bogus")) == 1
    assert "Unknown qmd subcommand" in capsys.readouterr().out


def test_run_qmd_default_status() -> None:
    # no qmd_subcommand attr → defaults to status
    assert run_qmd(FakeWiki(), SimpleNamespace()) == 0


# ── QmdCommand ──────────────────────────────────────────────────────


def test_qmd_command_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    QmdCommand().setup_parser(sub)

    ns = parser.parse_args(["qmd", "search", "hello", "-l", "3"])
    assert ns.qmd_subcommand == "search"
    assert ns.query == "hello"
    assert ns.limit == 3

    ns = parser.parse_args(["qmd", "mcp", "-p", "9999", "--host", "0.0.0.0", "--collection", "c"])
    assert ns.qmd_subcommand == "mcp"
    assert ns.port == 9999
    assert ns.host == "0.0.0.0"
    assert ns.collection == "c"

    ns = parser.parse_args(["qmd", "status"])
    assert ns.qmd_subcommand == "status"


def test_qmd_command_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qmd_mod.subprocess, "run", lambda *a, **k: None)
    cmd = QmdCommand()
    assert cmd.run(_args(qmd_subcommand="status"), FakeWiki(), {}) == 0


def test_qmd_command_name_help() -> None:
    cmd = QmdCommand()
    assert cmd.name == "qmd"
    assert "QMD" in cmd.help
