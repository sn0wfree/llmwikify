"""``doctor`` command — check llmwikify installation health."""

from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_success, print_warning


CONFIG_PATH = Path.home() / ".llmwikify" / "llmwikify.json"


def _check(label: str, ok: bool, detail: str = "") -> bool:
    """Print a check result line."""
    icon = ICON_SUCCESS if ok else "❌"
    msg = f"  {icon} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return ok


def run_doctor(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Run health checks on llmwikify installation.

    Returns:
        0 if all checks pass, 1 if any fail.
    """
    errors = 0

    print("🔍 llmwikify doctor")
    print()

    # --- 1. Config file ---
    print("Config file:")
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            llm = data.get("llm", {})
            if llm.get("enabled") and llm.get("api_key"):
                provider = llm.get("provider", "unknown")
                model = llm.get("model", "unknown")
                _check(
                    f"~/.llmwikify/llmwikify.json",
                    True,
                    f"provider={provider}, model={model}",
                )
            elif not llm.get("enabled"):
                _check("~/.llmwikify/llmwikify.json", True, "LLM disabled (offline mode)")
            else:
                _check("~/.llmwikify/llmwikify.json", False, "missing api_key")
                errors += 1
        except (json.JSONDecodeError, OSError) as e:
            _check("~/.llmwikify/llmwikify.json", False, f"parse error: {e}")
            errors += 1
    else:
        _check("~/.llmwikify/llmwikify.json", False, "not found — run: llmwikify init-llm")
        errors += 1

    # --- 2. Python version ---
    print()
    print("Python:")
    v = sys.version_info
    _check(f"Python {v.major}.{v.minor}.{v.micro}", v >= (3, 10), "requires >= 3.10")
    if v < (3, 10):
        errors += 1

    # --- 3. Core dependencies ---
    print()
    print("Core dependencies:")
    for mod_name in ["llmwikify", "yaml", "duckdb", "jinja2"]:
        try:
            importlib.import_module(mod_name)
            _check(mod_name, True)
        except ImportError:
            _check(mod_name, False, "not installed")
            errors += 1

    # --- 4. Optional extras ---
    print()
    print("Optional extras:")
    extras = {
        "fastapi": "web (serve --web)",
        "fastmcp": "mcp (MCP server)",
        "watchdog": "watch (file watching)",
        "networkx": "graph (knowledge graph)",
        "markitdown": "extractors (PDF/Office)",
        "tiktoken": "llm (token counting)",
        "httpx": "http client",
    }
    for mod_name, desc in extras.items():
        try:
            importlib.import_module(mod_name)
            _check(f"{mod_name}", True, desc)
        except ImportError:
            _check(f"{mod_name}", False, f"{desc} — pip install llmwikify[{desc.split('(')[0].strip()}]")

    # --- 5. WebUI bundle ---
    print()
    print("WebUI bundle:")
    # Find the ui/webui/dist path relative to the package
    try:
        import llmwikify
        pkg_dir = Path(llmwikify.__file__).parent.parent.parent
        dist_path = pkg_dir / "ui" / "webui" / "dist"
        if dist_path.exists() and (dist_path / "index.html").exists():
            _check(f"ui/webui/dist/", True, "found")
        else:
            _check(f"ui/webui/dist/", False, "not built — cd ui/webui && pnpm build")
    except Exception:
        _check("ui/webui/dist/", False, "cannot locate")

    # --- 6. Server health (optional) ---
    server_url = os.environ.get("SERVER_URL", "http://localhost:8765")
    print()
    print(f"Server ({server_url}):")
    try:
        import httpx
        resp = httpx.get(f"{server_url}/api/health", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            _check("Server reachable", True, f"status={data.get('status', '?')}")
        else:
            _check("Server reachable", False, f"HTTP {resp.status_code}")
    except Exception:
        _check("Server reachable", False, "not running (start with: llmwikify serve --web)")

    # --- Summary ---
    print()
    if errors == 0:
        print(f"{ICON_SUCCESS} All checks passed.")
    else:
        print(f"⚠️  {errors} issue(s) found. See above for details.")

    return 0 if errors == 0 else 1


class DoctorCommand(Command):
    """Check llmwikify installation health."""

    name = "doctor"
    help = "Check config, dependencies, WebUI bundle, and server health"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction
        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        subparsers.add_parser(self.name, help=self.help)

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_doctor(wiki, wiki.root if hasattr(wiki, 'root') else None, args)
