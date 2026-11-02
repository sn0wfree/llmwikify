"""Unit tests for ``interfaces/cli/commands/doctor_cmd.py``.

``CONFIG_PATH`` / ``CONFIG_DIR`` are module-level constants, so every
check that touches the user's real home directory is redirected to
``tmp_path`` via monkeypatch. Network-facing checks (LLM, server) are
driven through a fake ``httpx`` module — no real sockets.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from llmwikify.interfaces.cli.commands import doctor_cmd as dc

# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point CONFIG_DIR / CONFIG_PATH at a fresh temp directory."""
    cfg_dir = tmp_path / ".llmwikify"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "llmwikify.json"
    monkeypatch.setattr(dc, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(dc, "CONFIG_PATH", cfg_path)
    return cfg_path


def _write_config(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class _FakeResp:
    def __init__(self, status_code: int = 200, text: str = "", json_data: Any = None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no json")
        return self._json


class _FakeHttpx:
    """Stand-in for the ``httpx`` module with programmable responses."""

    def __init__(self, get_resp: Any = None, post_resp: Any = None, get_exc: Exception | None = None, post_exc: Exception | None = None):
        self._get_resp = get_resp
        self._post_resp = post_resp
        self._get_exc = get_exc
        self._post_exc = post_exc
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, timeout: float = 0) -> Any:
        self.calls.append(("get", url))
        if self._get_exc is not None:
            raise self._get_exc
        return self._get_resp

    def post(self, url: str, json: Any = None, headers: Any = None, timeout: float = 0) -> Any:
        self.calls.append(("post", url))
        if self._post_exc is not None:
            raise self._post_exc
        return self._post_resp


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> _FakeHttpx:
    """Install a fake ``httpx`` into sys.modules for doctor's local import."""
    import sys

    fx = _FakeHttpx()
    monkeypatch.setitem(sys.modules, "httpx", fx)
    return fx


# ── _check ──────────────────────────────────────────────────────────


def test_check_prints_and_returns_true(capsys: pytest.CaptureFixture) -> None:
    assert dc._check("label", True, "detail") is True
    out = capsys.readouterr().out
    assert "label" in out and "detail" in out


def test_check_silent_prints_nothing(capsys: pytest.CaptureFixture) -> None:
    assert dc._check("label", False, silent=True) is False
    assert capsys.readouterr().out == ""


def test_check_fail_icon(capsys: pytest.CaptureFixture) -> None:
    dc._check("label", False, "oops")
    out = capsys.readouterr().out
    assert "oops" in out


# ── _check_config ───────────────────────────────────────────────────


def test_config_missing(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    ok, data = dc._check_config()
    assert ok is False
    assert data["status"] == "missing"
    assert data["fix"]["commands"] == ["llmwikify init-llm"]
    assert "not found" in capsys.readouterr().out


def test_config_parse_error(config_env: Path) -> None:
    config_env.write_text("{ not json", encoding="utf-8")
    ok, data = dc._check_config(silent=True)
    assert ok is False
    assert data["status"] == "error"
    assert "detail" in data


def test_config_llm_disabled(config_env: Path) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    ok, data = dc._check_config(silent=True)
    assert ok is True
    assert data["enabled"] is False


def test_config_llm_enabled(config_env: Path) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "provider": "openai", "model": "gpt-4o"}})
    ok, data = dc._check_config(silent=True)
    assert ok is True
    assert data["enabled"] is True
    assert data["provider"] == "openai"
    assert data["model"] == "gpt-4o"


def test_config_missing_key_llm_absent(config_env: Path) -> None:
    _write_config(config_env, {})
    ok, data = dc._check_config(silent=True)
    # data.get("llm", {}) -> {} -> not enabled -> offline mode ok
    assert ok is True
    assert data["enabled"] is False


# ── _check_python ───────────────────────────────────────────────────


def test_python_ok() -> None:
    assert dc._check_python(silent=True) is True


def test_python_text_mode_prints(capsys: pytest.CaptureFixture) -> None:
    assert dc._check_python() is True
    assert "Python" in capsys.readouterr().out


# ── _check_core_deps ────────────────────────────────────────────────


def test_core_deps_all_present() -> None:
    # llmwikify / yaml / duckdb / jinja2 are hard deps — all installed.
    assert dc._check_core_deps(silent=True) == 0


def test_core_deps_text_mode(capsys: pytest.CaptureFixture) -> None:
    failures = dc._check_core_deps()
    assert failures == 0
    assert "llmwikify" in capsys.readouterr().out


def test_core_deps_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = dc.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "duckdb":
            raise ImportError("no duckdb")
        return real_import(name)

    monkeypatch.setattr(dc.importlib, "import_module", fake_import)
    assert dc._check_core_deps(silent=True) == 1


def test_core_deps_missing_prints_fix(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    real_import = dc.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "jinja2":
            raise ImportError("no jinja2")
        return real_import(name)

    monkeypatch.setattr(dc.importlib, "import_module", fake_import)
    failures = dc._check_core_deps()
    assert failures == 1
    out = capsys.readouterr().out
    assert "pip install" in out


# ── _check_optional_deps ────────────────────────────────────────────


def test_optional_deps_runs(capsys: pytest.CaptureFixture) -> None:
    dc._check_optional_deps()
    out = capsys.readouterr().out
    # at least one of the extras should be reported (installed or not)
    assert "fastapi" in out or "networkx" in out


def test_optional_deps_silent() -> None:
    dc._check_optional_deps(silent=True)  # no assertion — just must not raise


def test_optional_deps_missing_warns(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    real_import = dc.importlib.import_module

    def fake_import(name: str) -> Any:
        if name == "watchdog":
            raise ImportError("no watchdog")
        return real_import(name)

    monkeypatch.setattr(dc.importlib, "import_module", fake_import)
    dc._check_optional_deps()
    out = capsys.readouterr().out
    assert "watchdog" in out and "pip install" in out


# ── _check_llm_connectivity ─────────────────────────────────────────


def test_llm_no_config(config_env: Path) -> None:
    ok, latency, detail = dc._check_llm_connectivity()
    assert ok is False and latency == 0.0 and detail == "config not found"


def test_llm_parse_error(config_env: Path) -> None:
    config_env.write_text("{bad", encoding="utf-8")
    ok, _, detail = dc._check_llm_connectivity()
    assert ok is False and detail == "config parse error"


def test_llm_disabled(config_env: Path) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    ok, latency, detail = dc._check_llm_connectivity()
    assert ok is True and latency == 0.0 and "disabled" in detail


def test_llm_missing_api_key(config_env: Path) -> None:
    _write_config(config_env, {"llm": {"enabled": True}})
    ok, _, detail = dc._check_llm_connectivity()
    assert ok is False and detail == "api_key missing"


def test_llm_http_success(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "openai", "model": "m"}})
    fake_httpx._post_resp = _FakeResp(200)
    ok, latency, detail = dc._check_llm_connectivity()
    assert ok is True and "responded in" in detail
    assert fake_httpx.calls[0][0] == "post"


def test_llm_http_auth_error(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "bad", "provider": "openai"}})
    fake_httpx._post_resp = _FakeResp(401, text="unauthorized")
    ok, _, detail = dc._check_llm_connectivity()
    assert ok is False and "auth error" in detail


def test_llm_http_server_error(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "openai"}})
    fake_httpx._post_resp = _FakeResp(500, text="boom")
    ok, _, detail = dc._check_llm_connectivity()
    assert ok is False and "HTTP 500" in detail


def test_llm_network_error(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "openai"}})
    fake_httpx._post_exc = ConnectionError("refused")
    ok, latency, detail = dc._check_llm_connectivity()
    assert ok is False and latency == 0.0 and "network error" in detail


def test_llm_anthropic_path(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "anthropic", "base_url": "https://api.anthropic.com"}})
    fake_httpx._post_resp = _FakeResp(200)
    ok, _, _ = dc._check_llm_connectivity()
    assert ok is True
    url = fake_httpx.calls[0][1]
    assert url.endswith("/v1/messages")


def test_llm_base_url_with_v1_suffix(config_env: Path, fake_httpx: _FakeHttpx) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "openai", "base_url": "https://x.example/v1"}})
    fake_httpx._post_resp = _FakeResp(200)
    ok, _, _ = dc._check_llm_connectivity()
    assert ok is True
    url = fake_httpx.calls[0][1]
    assert url.endswith("/v1/chat/completions")


# ── _check_webui_bundle ─────────────────────────────────────────────


def test_webui_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    # Path(__file__).parent.parent.parent → 3 levels up from the package file
    import llmwikify

    # tmp_path/a/b/llmwikify/__init__.py → pkg_dir = tmp_path
    pkg_file = tmp_path / "a" / "b" / "llmwikify" / "__init__.py"
    pkg_file.parent.mkdir(parents=True)
    pkg_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(llmwikify, "__file__", str(pkg_file))
    assert dc._check_webui_bundle() is False
    assert "not built" in capsys.readouterr().out


def test_webui_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import llmwikify

    # __file__ = tmp_path/a/b/llmwikify/__init__.py → pkg_dir = tmp_path/a
    pkg_file = tmp_path / "a" / "b" / "llmwikify" / "__init__.py"
    pkg_file.parent.mkdir(parents=True)
    pkg_file.write_text("", encoding="utf-8")
    dist = tmp_path / "a" / "ui" / "webui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html/>", encoding="utf-8")
    monkeypatch.setattr(llmwikify, "__file__", str(pkg_file))
    assert dc._check_webui_bundle(silent=True) is True


def test_webui_exception_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import llmwikify

    # Make Path(llmwikify.__file__).parent raise via a non-path-like value
    monkeypatch.setattr(llmwikify, "__file__", 12345)  # type: ignore[assignment]
    assert dc._check_webui_bundle(silent=True) is False


# ── _check_wiki_dir ─────────────────────────────────────────────────


def test_wiki_dir_none(capsys: pytest.CaptureFixture) -> None:
    result = dc._check_wiki_dir(None)
    assert result["ok"] is False
    assert "raw/" in result["missing_required"]
    assert "not provided" in capsys.readouterr().out


def test_wiki_dir_no_layout_diff() -> None:
    result = dc._check_wiki_dir(SimpleNamespace(root="/tmp/x"))
    assert result["ok"] is False


def test_wiki_dir_all_present() -> None:
    wiki = SimpleNamespace(
        root="/w",
        layout_diff=lambda: {
            "in_both": ["raw/", "wiki/", ".llmwikify.db", "wiki.md"],
            "declared_only": [],
            "actual_only": [],
        },
    )
    result = dc._check_wiki_dir(wiki, silent=True)
    assert result["ok"] is True
    assert result["missing_required"] == []


def test_wiki_dir_missing_required() -> None:
    wiki = SimpleNamespace(
        root="/w",
        layout_diff=lambda: {
            "in_both": ["raw/"],
            "declared_only": ["wiki/", "wiki.md"],  # required missing
            "actual_only": [],
        },
    )
    result = dc._check_wiki_dir(wiki, silent=True)
    assert result["ok"] is False
    assert set(result["missing_required"]) == {"wiki/", "wiki.md"}


def test_wiki_dir_actual_only_info() -> None:
    wiki = SimpleNamespace(
        root="/w",
        layout_diff=lambda: {
            "in_both": ["raw/", "wiki/", ".llmwikify.db", "wiki.md"],
            "declared_only": [],
            "actual_only": ["custom/"],
        },
    )
    result = dc._check_wiki_dir(wiki, silent=True)
    assert result["ok"] is True  # actual_only is info-only
    assert result["actual_only"] == ["custom/"]


def test_wiki_dir_text_output(capsys: pytest.CaptureFixture) -> None:
    wiki = SimpleNamespace(
        root="/w",
        layout_diff=lambda: {
            "in_both": ["raw/"],
            "declared_only": ["wiki.md"],
            "actual_only": [],
        },
    )
    dc._check_wiki_dir(wiki)
    out = capsys.readouterr().out
    assert "missing" in out


# ── _check_permissions ──────────────────────────────────────────────


def test_permissions_ok(tmp_path: Path, config_env: Path, capsys: pytest.CaptureFixture) -> None:
    # CONFIG_DIR exists (fixture created it), wiki_root exists (tmp_path)
    assert dc._check_permissions(tmp_path) is True
    out = capsys.readouterr().out
    assert "writable" in out


def test_permissions_config_dir_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "no-such-dir"
    monkeypatch.setattr(dc, "CONFIG_DIR", missing)
    assert dc._check_permissions(tmp_path, silent=True) is False


def test_permissions_wiki_root_missing(tmp_path: Path, config_env: Path) -> None:
    # wiki_root doesn't exist → the wiki_root branch is skipped,
    # but config dir is fine → overall True (existing behaviour).
    missing = tmp_path / "no-wiki"
    assert dc._check_permissions(missing, silent=True) is True


def test_permissions_not_writable(tmp_path: Path, config_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Make write_text raise OSError by patching Path.write_text on the test file
    real_write = Path.write_text

    def boom(self: Path, *a: Any, **k: Any) -> int:
        if self.name == ".doctor_test":
            raise OSError("denied")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)
    assert dc._check_permissions(tmp_path, silent=True) is False


def test_permissions_fix_printed(tmp_path: Path, config_env: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    real_write = Path.write_text

    def boom(self: Path, *a: Any, **k: Any) -> int:
        if self.name == ".doctor_test":
            raise OSError("denied")
        return real_write(self, *a, **k)

    monkeypatch.setattr(Path, "write_text", boom)
    dc._check_permissions(tmp_path)
    out = capsys.readouterr().out
    assert "chmod" in out or "Fix:" in out


# ── _check_server ───────────────────────────────────────────────────


def test_server_ok(fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    fake_httpx._get_resp = _FakeResp(200, json_data={"status": "ok"})
    assert dc._check_server("http://localhost:1") is True
    assert "Server reachable" in capsys.readouterr().out


def test_server_http_error(fake_httpx: _FakeHttpx) -> None:
    fake_httpx._get_resp = _FakeResp(503)
    assert dc._check_server("http://localhost:1", silent=True) is False


def test_server_down_prints_fix(fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    fake_httpx._get_exc = ConnectionError("refused")
    assert dc._check_server("http://localhost:1") is False
    out = capsys.readouterr().out
    assert "serve --web" in out


def test_server_down_silent(fake_httpx: _FakeHttpx) -> None:
    fake_httpx._get_exc = ConnectionError("refused")
    assert dc._check_server("http://localhost:1", silent=True) is False


# ── _print_recommended_actions ──────────────────────────────────────


def test_recommended_actions_empty(capsys: pytest.CaptureFixture) -> None:
    dc._print_recommended_actions([{"status": "ok"}])
    assert capsys.readouterr().out == ""


def test_recommended_actions_prints(capsys: pytest.CaptureFixture) -> None:
    results = [
        {"status": "fail", "category": "config", "detail": "missing", "fix": {"commands": ["llmwikify init-llm"], "docs": "d.md", "cost": "30s", "risk": "low", "auto": False}},
        {"status": "ok", "category": "python"},
        {"status": "warn", "category": "server", "fix": {"commands": ["serve"], "hint": "h"}},
    ]
    dc._print_recommended_actions(results)
    out = capsys.readouterr().out
    assert "Recommended actions" in out
    assert "FAIL 1/2" in out
    assert "WARN 2/2" in out
    assert "llmwikify init-llm" in out
    assert "Hint:  h" in out


def test_recommended_actions_skips_info(capsys: pytest.CaptureFixture) -> None:
    dc._print_recommended_actions([{"status": "info", "category": "x", "fix": {"commands": ["y"]}}])
    assert capsys.readouterr().out == ""


# ── run_doctor ──────────────────────────────────────────────────────


def _args(**kw: Any) -> SimpleNamespace:
    defaults = {"skip_llm": True, "json": False, "wiki_root": None}
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def test_run_doctor_missing_config_json(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    # config missing → early return 2, but JSON mode must still emit JSON
    code = dc.run_doctor(None, None, _args(json=True, skip_llm=True))
    assert code == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["summary"]["failed"] >= 1
    assert payload["checks"][0]["status"] == "missing"


def test_run_doctor_missing_config_text(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    code = dc.run_doctor(None, None, _args(json=False, skip_llm=True))
    assert code == 2
    out = capsys.readouterr().out
    assert "not found" in out


def test_run_doctor_full_json(config_env: Path, fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    code = dc.run_doctor(None, None, _args(json=True, skip_llm=True))
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code in (0, 1)
    cats = [c["category"] for c in payload["checks"]]
    assert "config" in cats and "python" in cats and "core_deps" in cats
    assert "llm" in cats and "wiki" in cats and "permissions" in cats
    assert "webui" in cats and "server" in cats
    # skip_llm → status skipped
    llm_entry = next(c for c in payload["checks"] if c["category"] == "llm")
    assert llm_entry["status"] == "skipped"
    assert "summary" in payload


def test_run_doctor_llm_checked(config_env: Path, fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "k", "provider": "openai"}})
    fake_httpx._post_resp = _FakeResp(200)
    code = dc.run_doctor(None, None, _args(json=True, skip_llm=False))
    payload = json.loads(capsys.readouterr().out)
    llm_entry = next(c for c in payload["checks"] if c["category"] == "llm")
    assert llm_entry["status"] == "ok"
    assert code in (0, 1)


def test_run_doctor_llm_fail_gets_fix(config_env: Path, fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": True, "api_key": "bad", "provider": "openai"}})
    fake_httpx._post_resp = _FakeResp(401, text="no")
    dc.run_doctor(None, None, _args(json=True, skip_llm=False))
    payload = json.loads(capsys.readouterr().out)
    llm_entry = next(c for c in payload["checks"] if c["category"] == "llm")
    assert llm_entry["status"] == "fail"
    assert llm_entry["fix"]["commands"] == ["llmwikify init-llm"]


def test_run_doctor_text_mode_summary(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    code = dc.run_doctor(None, None, _args(json=False, skip_llm=True))
    out = capsys.readouterr().out
    assert "llmwikify doctor" in out
    assert "All checks passed" in out or "warning" in out or "error" in out
    assert code in (0, 1)


def test_run_doctor_wiki_root_override(config_env: Path, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    code = dc.run_doctor(None, None, _args(json=True, skip_llm=True, wiki_root=str(tmp_path)))
    payload = json.loads(capsys.readouterr().out)
    wiki_entry = next(c for c in payload["checks"] if c["category"] == "wiki")
    assert wiki_entry["path"] == str(tmp_path)
    assert code in (0, 1)


def test_run_doctor_wiki_fail_has_fix(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    # wiki=None → _check_wiki_dir fails → fix attached
    dc.run_doctor(None, None, _args(json=True, skip_llm=True))
    payload = json.loads(capsys.readouterr().out)
    wiki_entry = next(c for c in payload["checks"] if c["category"] == "wiki")
    assert wiki_entry["status"] == "fail"
    assert wiki_entry["fix"]["commands"] == ["llmwikify init"]


def test_run_doctor_server_fail_has_fix(config_env: Path, fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    fake_httpx._get_exc = ConnectionError("refused")
    dc.run_doctor(None, None, _args(json=True, skip_llm=True))
    payload = json.loads(capsys.readouterr().out)
    server_entry = next(c for c in payload["checks"] if c["category"] == "server")
    assert server_entry["status"] == "fail"
    assert "serve" in server_entry["fix"]["commands"][0]


def test_run_doctor_server_url_env(config_env: Path, fake_httpx: _FakeHttpx, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    monkeypatch.setenv("SERVER_URL", "http://custom:9999")
    fake_httpx._get_resp = _FakeResp(200, json_data={"status": "ok"})
    dc.run_doctor(None, None, _args(json=True, skip_llm=True))
    payload = json.loads(capsys.readouterr().out)
    server_entry = next(c for c in payload["checks"] if c["category"] == "server")
    assert server_entry["url"] == "http://custom:9999"
    assert fake_httpx.calls[0][1].startswith("http://custom:9999")


def test_run_doctor_text_recommended_actions(config_env: Path, fake_httpx: _FakeHttpx, capsys: pytest.CaptureFixture) -> None:
    _write_config(config_env, {"llm": {"enabled": False}})
    fake_httpx._get_exc = ConnectionError("refused")
    dc.run_doctor(None, None, _args(json=False, skip_llm=True))
    out = capsys.readouterr().out
    assert "Recommended actions" in out


# ── DoctorCommand ───────────────────────────────────────────────────


def test_doctor_command_setup_parser() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    cmd = dc.DoctorCommand()
    cmd.setup_parser(sub)
    ns = parser.parse_args(["doctor", "--skip-llm", "--json", "--wiki-root", "/tmp"])
    assert ns.skip_llm is True
    assert ns.json is True
    assert ns.wiki_root == "/tmp"


def test_doctor_command_setup_parser_defaults() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd")
    dc.DoctorCommand().setup_parser(sub)
    ns = parser.parse_args(["doctor"])
    assert ns.skip_llm is False
    assert ns.json is False
    assert ns.wiki_root is None


def test_doctor_command_run_custom_root(
    config_env: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """--wiki-root different from wiki.root rebuilds a Wiki at that path."""
    _write_config(config_env, {"llm": {"enabled": False}})

    class FakeWiki:
        root = Path("/original/root")

        def layout_diff(self) -> dict:
            return {"in_both": [], "declared_only": [], "actual_only": []}

    cmd = dc.DoctorCommand()
    args = _args(json=True, skip_llm=True, wiki_root=str(tmp_path))
    import llmwikify.kernel as kernel

    constructed: list[Path] = []

    class StubWiki:
        def __init__(self, root: Path, config: dict | None = None):
            constructed.append(root)
            self.root = root

        def layout_diff(self) -> dict:
            return {
                "in_both": ["raw/", "wiki/", ".llmwikify.db", "wiki.md"],
                "declared_only": [],
                "actual_only": [],
            }

    monkeypatch.setattr(kernel, "Wiki", StubWiki)
    code = cmd.run(args, FakeWiki(), {})
    payload = json.loads(capsys.readouterr().out)
    wiki_entry = next(c for c in payload["checks"] if c["category"] == "wiki")
    assert wiki_entry["path"] == str(tmp_path)
    assert constructed and constructed[0] == tmp_path
    assert code in (0, 1)


def test_doctor_command_run_same_root(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    """Same root → no Wiki rebuild, uses the passed instance as-is."""
    _write_config(config_env, {"llm": {"enabled": False}})

    class FakeWiki:
        root = Path.cwd()

        def layout_diff(self) -> dict:
            return {
                "in_both": ["raw/", "wiki/", ".llmwikify.db", "wiki.md"],
                "declared_only": [],
                "actual_only": [],
            }

    cmd = dc.DoctorCommand()
    args = _args(json=True, skip_llm=True, wiki_root=str(Path.cwd()))
    code = cmd.run(args, FakeWiki(), {})
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"]
    assert code in (0, 1)


def test_doctor_command_run_no_wiki_root_attr(config_env: Path, capsys: pytest.CaptureFixture) -> None:
    """wiki without .root → run_doctor receives None root."""
    _write_config(config_env, {"llm": {"enabled": False}})
    cmd = dc.DoctorCommand()
    args = _args(json=True, skip_llm=True, wiki_root=None)
    code = cmd.run(args, object(), {})
    payload = json.loads(capsys.readouterr().out)
    assert payload["checks"]
    assert code in (0, 1)


def test_doctor_command_name_and_help() -> None:
    cmd = dc.DoctorCommand()
    assert cmd.name == "doctor"
    assert "health" in cmd.help.lower() or "config" in cmd.help.lower()
