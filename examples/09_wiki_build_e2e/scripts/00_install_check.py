#!/usr/bin/env python3
"""00_install_check.py — verify that llmwikify is correctly installed.

This is the first script in the 00->01->02->03 chain. It catches the
common installation pitfalls before the rest of the suite wastes time
on them:

* Python 3.10+ required
* llmwikify importable, version printable
* the ``llmwikify`` console entry point exists (or, on a dev tree,
  ``python -m llmwikify`` works)
* all optional extras used by the e2e flow (``[extractors,web]``) can
  be imported
* ``doctor --skip-llm --json`` reports zero failures

The script never modifies the host (no files written outside the temp
dir). It exits 0 when everything checks out, 1 otherwise.

Run::

    python examples/09_wiki_build_e2e/scripts/00_install_check.py
"""

from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

from _lib import (  # noqa: E402
    IN_DOCKER,
    WIKI_ROOT,
    env_banner,
    record,
    section,
    skip,
    summary,
    warn,
)

REQUIRED_EXTRAS = {
    "fastapi": "web",
    "httpx": "web",
    "fastmcp": "mcp",
    "watchdog": "watch (optional)",
}

OPTIONAL_EXTRAS = {
    "markitdown": "extractors (large: markitdown[all] + pymupdf)",
}


def check_python_version() -> None:
    section("Python version")
    v = sys.version_info
    print(f"  python {v.major}.{v.minor}.{v.micro}")
    ok = (v.major, v.minor) >= (3, 10)
    record("python>=3.10", ok, f"found {v.major}.{v.minor}.{v.micro}")


def check_llmwikify_import() -> None:
    section("llmwikify package")
    try:
        mod = import_module("llmwikify")
    except ImportError as e:
        record("import llmwikify", False, str(e))
        return
    version = getattr(mod, "__version__", "?")
    print(f"  version: {version}")
    record("import llmwikify", True, version)


def check_cli_entry() -> None:
    section("CLI entry point")
    import shutil
    if shutil.which("llmwikify"):
        record("llmwikify on PATH", True, shutil.which("llmwikify"))
    elif IN_DOCKER:
        record("llmwikify on PATH", False,
               "not on PATH - entrypoint pip install may have failed")
    else:
        warn("llmwikify on PATH", "not on PATH, but -m llmwikify will be used")


def check_optional_extras() -> None:
    section("Required extras (e2e flow)")
    for mod_name, extra in REQUIRED_EXTRAS.items():
        try:
            import_module(mod_name)
            record(f"import {mod_name}", True, f"[{extra}]")
        except ImportError as e:
            record(f"import {mod_name}", False, f"pip install 'llmwikify[{extra}]' - {e}")

    section("Optional extras (large deps)")
    for mod_name, extra in OPTIONAL_EXTRAS.items():
        try:
            import_module(mod_name)
            record(f"import {mod_name}", True, f"[{extra}]")
        except ImportError:
            skip(f"import {mod_name}",
                 f"not installed; e2e flow does not need [{extra}]")


def check_doctor() -> None:
    section("doctor --skip-llm --json")
    from _lib import cli

    try:
        proc = cli("doctor", "--skip-llm", "--json", check=False)
    except FileNotFoundError as e:
        record("run doctor", False, str(e))
        return

    if proc.returncode not in (0, 1, 2):
        record("run doctor", False, f"exit {proc.returncode}: {proc.stderr[:200]}")
        return

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        record("parse doctor json", False, str(e))
        return

    summary_block = data.get("summary", {})
    passed = summary_block.get("passed", 0)
    failed = summary_block.get("failed", 0)
    print(f"  doctor: {passed} passed, {failed} failed")
    if failed == 0:
        record("doctor --skip-llm", True, f"{passed} checks pass")
    else:
        record("doctor --skip-llm", False, f"{failed} checks failed")


def main() -> int:
    print("=" * 60)
    print("  llmwikify install check (00_install_check.py)")
    print("=" * 60)
    env_banner()

    check_python_version()
    check_llmwikify_import()
    check_cli_entry()
    check_optional_extras()
    check_doctor()

    print()
    print(f"  Wiki root (will be created by later scripts): {WIKI_ROOT}")
    return summary("00 install check")


if __name__ == "__main__":
    sys.exit(main())
