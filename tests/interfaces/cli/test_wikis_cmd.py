"""Unit tests for ``interfaces/cli/commands/wikis.py``.

The subcommands construct a real ``WikiRegistry`` against the merged
config, so the tests provide a temp data-dir config and register real
entries — no mocking of the registry itself.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands.wikis import (
    WikisCommand,
    _wikis_add,
    _wikis_list,
    _wikis_remove,
    _wikis_scan,
    run_wikis,
)


def _config(tmp_path: Path, local: list[dict] | None = None) -> dict:
    """Minimal config pointing every data path at tmp_path.

    ``WikiRegistry`` is in-memory: entries are loaded from
    ``config['wikis']['local']`` on ``initialize()``, not persisted.
    """
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    return {
        "data_dir": str(data),
        "wikis": {"default": None, "local": local or [], "remote": []},
    }


def _args(**kw: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {"wikis_subcommand": "list"}
    defaults.update(kw)
    return argparse.Namespace(**defaults)


# ── _wikis_list ─────────────────────────────────────────────────────


def test_list_empty(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    rc = _wikis_list(_config(tmp_path), None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "No wikis registered" in out
    assert "wikis add" in out


def test_list_with_entries(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "w1"
    root.mkdir()
    config = _config(
        tmp_path,
        local=[{"id": "main", "name": "Main Wiki", "path": str(root)}],
    )
    rc = _wikis_list(config, None)
    assert rc == 0
    out = capsys.readouterr().out
    assert "main" in out
    assert "Main Wiki" in out
    assert "Default" in out


# ── _wikis_add ──────────────────────────────────────────────────────


def test_add_local(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "newwiki"
    root.mkdir()
    args = _args(wiki_id="newwiki", path=str(root), name="New", url=None, api_key=None)
    rc = _wikis_add(_config(tmp_path), args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Registered local wiki: newwiki" in out
    assert str(root) in out


def test_add_local_default_name(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "my-wiki"
    root.mkdir()
    args = _args(wiki_id="my-wiki", path=str(root), name=None, url=None, api_key=None)
    rc = _wikis_add(_config(tmp_path), args)
    assert rc == 0
    assert "My Wiki" in capsys.readouterr().out


def test_add_local_missing_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(
        wiki_id="ghost",
        path=str(tmp_path / "nope"),
        name="Ghost",
        url=None,
        api_key=None,
    )
    rc = _wikis_add(_config(tmp_path), args)
    assert rc == 1
    out = capsys.readouterr().out
    assert "does not exist" in out


def test_add_remote(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(
        wiki_id="remote1",
        path=None,
        name="Remote",
        url="https://example.com",
        api_key="k",
    )
    rc = _wikis_add(_config(tmp_path), args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Registered remote wiki: remote1" in out
    assert "https://example.com" in out


def test_add_neither_path_nor_url(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(wiki_id="x", path=None, name=None, url=None, api_key=None)
    rc = _wikis_add(_config(tmp_path), args)
    assert rc == 1
    assert "--path or --url" in capsys.readouterr().out


# ── _wikis_remove ───────────────────────────────────────────────────


def test_remove_existing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    root = tmp_path / "gone"
    root.mkdir()
    config = _config(
        tmp_path,
        local=[{"id": "gone", "name": "Gone", "path": str(root)}],
    )
    args = _args(wiki_id="gone")
    rc = _wikis_remove(config, args)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Unregistered wiki: gone" in out
    assert "Gone" in out


def test_remove_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(wiki_id="nope")
    rc = _wikis_remove(_config(tmp_path), args)
    assert rc == 1
    assert "Wiki not found: nope" in capsys.readouterr().out


# ── _wikis_scan ─────────────────────────────────────────────────────


def test_scan_no_new(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    args = _args(paths=[str(empty)], depth=1)
    rc = _wikis_scan(_config(tmp_path), args)
    assert rc == 0
    assert "No new wikis found" in capsys.readouterr().out


def test_scan_defaults_to_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    # paths attr missing → defaults to ["."]
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    args = argparse.Namespace()  # no paths / depth attrs
    rc = _wikis_scan(_config(tmp_path), args)
    assert rc == 0
    assert "No new wikis found" in capsys.readouterr().out


# ── run_wikis dispatcher ────────────────────────────────────────────


def test_run_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert run_wikis(None, _config(tmp_path), _args(wikis_subcommand="list")) == 0
    assert "No wikis" in capsys.readouterr().out


def test_run_add(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    args = _args(wiki_id="r", path=str(root), name="R", url=None, api_key=None)
    assert run_wikis(None, _config(tmp_path), args) == 0


def test_run_remove(tmp_path: Path) -> None:
    args = _args(wikis_subcommand="remove", wiki_id="missing")
    assert run_wikis(None, _config(tmp_path), args) == 1


def test_run_scan(tmp_path: Path) -> None:
    empty = tmp_path / "e"
    empty.mkdir()
    args = _args(wikis_subcommand="scan", paths=[str(empty)], depth=1)
    assert run_wikis(None, _config(tmp_path), args) == 0


def test_run_unknown(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(wikis_subcommand="bogus")
    assert run_wikis(None, _config(tmp_path), args) == 1
    assert "Unknown wikis subcommand" in capsys.readouterr().out


def test_run_default_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # no wikis_subcommand → defaults to list
    assert run_wikis(None, _config(tmp_path), argparse.Namespace()) == 0
    assert "No wikis" in capsys.readouterr().out


# ── WikisCommand ────────────────────────────────────────────────────


def test_wikis_command_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    WikisCommand().setup_parser(sub)

    ns = parser.parse_args(["wikis", "list"])
    assert ns.wikis_subcommand == "list"

    ns = parser.parse_args(["wikis", "add", "id1", "--path", "/p", "--name", "N"])
    assert ns.wikis_subcommand == "add"
    assert ns.wiki_id == "id1"
    assert ns.path == "/p"
    assert ns.name == "N"

    ns = parser.parse_args(["wikis", "remove", "id1"])
    assert ns.wikis_subcommand == "remove"
    assert ns.wiki_id == "id1"

    ns = parser.parse_args(["wikis", "scan", "a", "b", "--depth", "3"])
    assert ns.wikis_subcommand == "scan"
    assert ns.paths == ["a", "b"]
    assert ns.depth == 3


def test_wikis_command_subcommand_required() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    WikisCommand().setup_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["wikis"])


def test_wikis_command_run(tmp_path: Path) -> None:
    cmd = WikisCommand()
    assert cmd.run(_args(wikis_subcommand="list"), None, _config(tmp_path)) == 0


def test_wikis_command_name_help() -> None:
    cmd = WikisCommand()
    assert cmd.name == "wikis"
    assert "wiki" in cmd.help.lower()
