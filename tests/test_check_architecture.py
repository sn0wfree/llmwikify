"""Tests for scripts/check_architecture.py.

Covers two things the guard has never had a net for:

1. **N1 regression** — the report uses emoji. On a Windows console with a
   legacy code page (GBK) — or any time stdout is a pipe rather than a real
   console handle — the default stream encoding cannot represent them, so
   the script used to die with ``UnicodeEncodeError`` *after* the check had
   already passed. The guard then exited 1 on a clean tree, i.e. it
   reported a **false architecture violation** in CI.

2. **The detection logic itself** — the forbidden-edge table and the
   layer classification have to actually flag a violation when one exists;
   otherwise "0 violations" is vacuous.
"""

from __future__ import annotations

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "check_architecture.py"


def _load():
    """Import the script as a module (it is not an installed package)."""
    spec = importlib.util.spec_from_file_location("check_architecture", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeSys:
    """Deprecated placeholder — main() prints through the real ``sys``."""


def _write(root: Path, rel: str, body: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def _run_on_fake_tree(mod, root: Path, monkeypatch) -> tuple[int, str]:
    """Run main() against a synthetic src/llmwikify tree.

    ``print()`` resolves ``sys.stdout`` from the *real* ``sys`` module, so the
    capture has to patch that, not the script's ``mod.sys`` binding.
    """
    src = root / "src" / "llmwikify"
    monkeypatch.setattr(mod, "SRC", src)
    monkeypatch.setattr(mod, "REPO_ROOT", root)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    monkeypatch.setattr(sys, "stderr", buf)
    rc = mod.main()
    return rc, buf.getvalue()


# ─── N1: must survive a non-UTF8 console ───────────────────────────────


@pytest.mark.parametrize("encoding", ["ascii", "gbk"])
def test_script_survives_non_utf8_console(encoding: str) -> None:
    """Regression net for N1: emoji output must not kill a legacy console.

    Before the fix the script raised UnicodeEncodeError while printing the
    summary and exited 1 — a clean tree reported as a violation.
    """
    try:
        "".encode(encoding)
    except LookupError:  # pragma: no cover - codec not available on this box
        pytest.skip(f"{encoding} codec unavailable")

    env = {**os.environ, "PYTHONIOENCODING": encoding}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=120,
    )
    assert "UnicodeEncodeError" not in proc.stderr
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_script_passes_on_current_repo() -> None:
    """The committed tree must satisfy its own architecture rules."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "0 architecture violations" in proc.stdout


# ─── detection logic ──────────────────────────────────────────────────


def test_detects_kernel_to_apps_violation(tmp_path, monkeypatch) -> None:
    mod = _load()
    _write(
        tmp_path,
        "src/llmwikify/kernel/bad.py",
        "from llmwikify.apps.chat.db import ChatDatabase\n",
    )
    rc, out = _run_on_fake_tree(mod, tmp_path, monkeypatch)
    assert rc == 1
    assert "architecture violation" in out


def test_detects_foundation_to_kernel_violation(tmp_path, monkeypatch) -> None:
    mod = _load()
    _write(
        tmp_path,
        "src/llmwikify/foundation/bad.py",
        "from llmwikify.kernel.agent import Agent\n",
    )
    rc, out = _run_on_fake_tree(mod, tmp_path, monkeypatch)
    assert rc == 1
    assert "foundation → kernel" in out


def test_allows_legal_dependency_direction(tmp_path, monkeypatch) -> None:
    """kernel → foundation and interfaces → apps are both legal."""
    mod = _load()
    _write(
        tmp_path,
        "src/llmwikify/kernel/ok.py",
        "from llmwikify.foundation.db import get_connection\n",
    )
    _write(
        tmp_path,
        "src/llmwikify/interfaces/ok.py",
        "from llmwikify.apps.chat.db import ChatDatabase\n",
    )
    rc, out = _run_on_fake_tree(mod, tmp_path, monkeypatch)
    assert rc == 0, out
    assert "0 architecture violations" in out


def test_ignores_same_layer_and_external_imports(tmp_path, monkeypatch) -> None:
    """Same-layer imports and third-party imports are not violations."""
    mod = _load()
    _write(
        tmp_path,
        "src/llmwikify/kernel/ok.py",
        "from llmwikify.kernel.agent import Agent\nimport httpx\n",
    )
    rc, out = _run_on_fake_tree(mod, tmp_path, monkeypatch)
    assert rc == 0, out


# ─── unit-level helpers ───────────────────────────────────────────────


def test_layer_of(tmp_path, monkeypatch) -> None:
    mod = _load()
    src = tmp_path / "src" / "llmwikify"
    monkeypatch.setattr(mod, "SRC", src)
    assert mod._layer_of(src / "kernel" / "x.py") == "kernel"
    assert mod._layer_of(src / "apps" / "chat" / "x.py") == "apps"
    assert mod._layer_of(src / "notalayer" / "x.py") is None


def test_forbidden_table_matches_architecture_doc() -> None:
    """The table encodes AGENTS.md §'架构分层' — keep it in sync."""
    mod = _load()
    assert mod.FORBIDDEN["foundation"] == ("kernel", "apps", "interfaces")
    assert mod.FORBIDDEN["kernel"] == ("apps", "interfaces")
    assert mod.FORBIDDEN["apps"] == ("interfaces",)
    assert mod.FORBIDDEN["interfaces"] == ()
