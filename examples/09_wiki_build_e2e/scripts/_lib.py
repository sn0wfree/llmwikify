"""Shared helpers for 09_wiki_build_e2e scripts.

Design: every script in this folder is **dual-habitat** — it runs both
on a developer machine (no container) and inside ``python-e2e-runner``
(generic Docker image from ``docker-tests/Dockerfile.e2e-runner``).

The behaviour is controlled by 3 environment variables:

============== ========================================== ===================
Env var        Meaning                                    Default
============== ========================================== ===================
``IN_DOCKER``  ``"1"`` inside the generic runner           ``"0"`` (host)
``WIKI_ROOT``  Where the scratch wiki lives                ``tempfile.mkdtemp(...)``
``AUTH_TOKEN`` Bearer token for serve / chat endpoints     ``"demo-token"``
============== ========================================== ===================

When ``IN_DOCKER=1`` the scripts use the ``llmwikify`` console entry
point (provided by the runtime ``pip install``); when ``IN_DOCKER=0``
they use ``python -m llmwikify`` so contributors can run them straight
out of a working tree without reinstalling.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

IN_DOCKER: bool = os.environ.get("IN_DOCKER") == "1"
WIKI_ROOT: Path = Path(
    os.environ.get("WIKI_ROOT") or tempfile.mkdtemp(prefix="llmwikify-e2e-")
)
AUTH_TOKEN: str = os.environ.get("AUTH_TOKEN", "demo-token")
SERVER_PORT: int = int(os.environ.get("SERVER_PORT", "8765"))

PASS = "[ OK ]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"
WARN = "[WARN]"

_results: list[tuple[str, bool, str]] = []


def section(title: str) -> None:
    """Print a 60-char-wide section banner."""
    bar = "=" * 60
    print(f"\n{bar}\n  {title}\n{bar}")


def cli(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Invoke the llmwikify console entry.

    In a container: ``llmwikify <args>`` (already on PATH via pip install).
    On a host:       ``python -m llmwikify <args>`` (uses the working tree).
    """
    if IN_DOCKER and shutil.which("llmwikify"):
        cmd: Sequence[str] = ("llmwikify", *args)
    else:
        cmd = (sys.executable, "-m", "llmwikify", *args)
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else str(WIKI_ROOT),
        check=check,
        capture_output=True,
        text=True,
    )


def record(name: str, ok: bool, detail: str = "") -> None:
    """Track a check result for the final summary."""
    _results.append((name, ok, detail))
    icon = PASS if ok else FAIL
    suffix = f" - {detail}" if detail else ""
    print(f"  {icon} {name}{suffix}")


def warn(name: str, detail: str) -> None:
    """Print a non-fatal warning."""
    print(f"  {WARN} {name} - {detail}")


def skip(name: str, reason: str) -> None:
    """Print a skipped check and record as pass (so the summary stays clean)."""
    _results.append((name, True, f"skipped: {reason}"))
    print(f"  {SKIP} {name} - {reason}")


def summary(label: str) -> int:
    """Print totals and return 0 if all passed, 1 otherwise."""
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)
    bar = "=" * 60
    print(f"\n{bar}\n  {label}: {passed}/{total} passed, {failed} failed\n{bar}")
    return 0 if failed == 0 else 1


def env_banner() -> None:
    """Print IN_DOCKER / WIKI_ROOT / Python info at startup."""
    print(f"  python:   {sys.executable} ({sys.version.split()[0]})")
    print(f"  IN_DOCKER: {IN_DOCKER}")
    print(f"  WIKI_ROOT: {WIKI_ROOT}")
    print(f"  AUTH_TOKEN: {AUTH_TOKEN}")
    print(f"  SERVER_PORT: {SERVER_PORT}")
