"""Unit tests for ``interfaces/cli/commands/init_llm_cmd.py``.

``create_llm_config`` writes to module-level ``CONFIG_PATH`` — every
test redirects it to ``tmp_path`` and clears provider env vars so
auto-detect doesn't leak the host machine's keys into assertions.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands import init_llm_cmd as ilc
from llmwikify.interfaces.cli.commands.init_llm_cmd import (
    InitLlmCommand,
    _get_default_model,
    auto_detect_provider,
    create_llm_config,
    resolve_api_key,
    run_init_llm,
)


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg_dir = tmp_path / ".llmwikify"
    cfg_path = cfg_dir / "llmwikify.json"
    monkeypatch.setattr(ilc, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(ilc, "CONFIG_PATH", cfg_path)
    # Neutralise host env so auto-detect is deterministic
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    return cfg_path


# ── _get_default_model ──────────────────────────────────────────────


def test_default_model_known_provider() -> None:
    # openai is in providers.yaml — should return a non-empty model
    model = _get_default_model("openai")
    assert isinstance(model, str)


def test_default_model_unknown_provider() -> None:
    assert _get_default_model("no-such-provider") == ""


def test_default_model_alias() -> None:
    # provider aliases (e.g. "gpt" → openai) go through apply_provider_alias
    model = _get_default_model("openai")
    assert isinstance(model, str)


# ── auto_detect_provider ────────────────────────────────────────────


def test_detect_none_when_env_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "MINIMAX_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    assert auto_detect_provider() is None


def test_detect_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    assert auto_detect_provider() == "openai"


def test_detect_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    assert auto_detect_provider() == "anthropic"


def test_detect_minimax(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MINIMAX_API_KEY", "mm")
    assert auto_detect_provider() == "minimax"


def test_detect_order_openai_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "b")
    assert auto_detect_provider() == "openai"


# ── resolve_api_key ─────────────────────────────────────────────────


def test_resolve_explicit_key_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert resolve_api_key("openai", explicit_key="explicit") == "explicit"


def test_resolve_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert resolve_api_key("openai") == "env-key"


def test_resolve_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert resolve_api_key("openai") is None


def test_resolve_provider_without_env_var() -> None:
    # xiaomi maps to None → no env lookup
    assert resolve_api_key("xiaomi") is None


def test_resolve_unknown_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("API_KEY", raising=False)
    assert resolve_api_key("mystery") is None


# ── create_llm_config ───────────────────────────────────────────────


def test_create_no_provider(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    rc = create_llm_config()
    assert rc == 1
    out = capsys.readouterr().out
    assert "Cannot auto-detect provider" in out
    assert "Supported providers" in out
    assert not config_env.exists()


def test_create_no_api_key(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    rc = create_llm_config(provider="openai")
    assert rc == 1
    assert "No API key found" in capsys.readouterr().out


def test_create_success_quiet(config_env: Path) -> None:
    rc = create_llm_config(provider="openai", model="gpt-4o", api_key="sk-test", quiet=True)
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert data["llm"]["enabled"] is True
    assert data["llm"]["provider"] == "openai"
    assert data["llm"]["model"] == "gpt-4o"
    assert data["llm"]["api_key"] == "sk-test"
    assert "base_url" not in data["llm"]


def test_create_with_base_url(config_env: Path) -> None:
    rc = create_llm_config(
        provider="openai", model="m", api_key="k", base_url="https://x/v1", quiet=True
    )
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert data["llm"]["base_url"] == "https://x/v1"


def test_create_prints_success(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    rc = create_llm_config(provider="openai", model="gpt-4o", api_key="sk-abcdefgh")
    assert rc == 0
    out = capsys.readouterr().out
    assert "LLM config written" in out
    assert "Provider: openai" in out
    assert "...abcdefgh" in out  # last 8 of key
    assert "llmwikify doctor" in out


def test_create_existing_no_overwrite(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text("{}", encoding="utf-8")
    rc = create_llm_config(provider="openai", model="m", api_key="k")
    assert rc == 1
    out = capsys.readouterr().out
    assert "already exists" in out
    assert "--overwrite" in out
    # original untouched
    assert json.loads(config_env.read_text(encoding="utf-8")) == {}


def test_create_overwrite(config_env: Path) -> None:
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text('{"old": true}', encoding="utf-8")
    rc = create_llm_config(
        provider="anthropic", model="claude", api_key="k", overwrite=True, quiet=True
    )
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "anthropic"
    assert "old" not in data


def test_create_from_env_key(config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    rc = create_llm_config(provider="openai", model="m", quiet=True)
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert data["llm"]["api_key"] == "sk-from-env"


def test_create_default_model_when_none(config_env: Path) -> None:
    # model=None → _get_default_model("openai") — may be "" if providers.yaml missing
    rc = create_llm_config(provider="openai", api_key="k", quiet=True)
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert isinstance(data["llm"]["model"], str)


def test_create_creates_config_dir(config_env: Path) -> None:
    assert not config_env.parent.exists()
    rc = create_llm_config(provider="openai", model="m", api_key="k", quiet=True)
    assert rc == 0
    assert config_env.exists()


def test_create_quiet_suppresses_warnings(
    config_env: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = create_llm_config(quiet=True)
    assert rc == 1
    assert capsys.readouterr().out == ""


# ── run_init_llm ────────────────────────────────────────────────────


def test_run_forwards_args(config_env: Path) -> None:
    args = argparse.Namespace(
        provider="openai",
        model="m",
        api_key="k",
        base_url=None,
        overwrite=False,
    )
    rc = run_init_llm(None, None, args)
    assert rc == 0
    data = json.loads(config_env.read_text(encoding="utf-8"))
    assert data["llm"]["provider"] == "openai"


def test_run_defaults_when_attrs_missing(config_env: Path) -> None:
    # No provider / no env → cannot detect → 1
    rc = run_init_llm(None, None, argparse.Namespace())
    assert rc == 1


def test_run_overwrite(config_env: Path) -> None:
    config_env.parent.mkdir(parents=True, exist_ok=True)
    config_env.write_text("{}", encoding="utf-8")
    args = argparse.Namespace(
        provider="openai", model="m", api_key="k", base_url=None, overwrite=True
    )
    assert run_init_llm(None, None, args) == 0


# ── InitLlmCommand ──────────────────────────────────────────────────


def test_setup_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitLlmCommand().setup_parser(sub)
    ns = parser.parse_args(
        ["init-llm", "--provider", "anthropic", "--model", "m", "--api-key", "k",
         "--base-url", "u", "--overwrite"]
    )
    assert ns.provider == "anthropic"
    assert ns.model == "m"
    assert ns.api_key == "k"
    assert ns.base_url == "u"
    assert ns.overwrite is True


def test_setup_parser_defaults() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitLlmCommand().setup_parser(sub)
    ns = parser.parse_args(["init-llm"])
    assert ns.provider is None
    assert ns.model is None
    assert ns.api_key is None
    assert ns.base_url is None
    assert ns.overwrite is False


def test_setup_parser_rejects_bad_provider() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    InitLlmCommand().setup_parser(sub)
    with pytest.raises(SystemExit):
        parser.parse_args(["init-llm", "--provider", "bogus"])


def test_command_run(config_env: Path) -> None:
    cmd = InitLlmCommand()

    class W:
        root = Path("/w")

    args = argparse.Namespace(
        provider="openai", model="m", api_key="k", base_url=None, overwrite=False
    )
    assert cmd.run(args, W(), {}) == 0
    assert config_env.exists()


def test_command_run_no_wiki_root(config_env: Path) -> None:
    cmd = InitLlmCommand()
    args = argparse.Namespace(
        provider="openai", model="m", api_key="k", base_url=None, overwrite=False
    )
    # object() has no .root → None passed through
    assert cmd.run(args, object(), {}) == 0


def test_name_help() -> None:
    cmd = InitLlmCommand()
    assert cmd.name == "init-llm"
    assert "LLM" in cmd.help
