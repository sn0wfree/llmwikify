"""``doctor`` command — check llmwikify installation health.

Enhanced (P3+):
- LLM connectivity test (actual API call, 5s timeout)
- Wiki directory check (configurable via --wiki-root)
- Permission checks
- JSON output mode (--json)
- Skip LLM test (--skip-llm)
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .._base import Command
from .._output import ICON_SUCCESS, ICON_WARNING, print_success, print_warning


CONFIG_DIR = Path.home() / ".llmwikify"
CONFIG_PATH = CONFIG_DIR / "llmwikify.json"
LLM_TEST_TIMEOUT = 5.0


def _check(label: str, ok: bool, detail: str = "", silent: bool = False) -> bool:
    """Print a check result line (suppressed when silent=True for --json mode)."""
    if not silent:
        icon = ICON_SUCCESS if ok else "❌"
        msg = f"  {icon} {label}"
        if detail:
            msg += f" — {detail}"
        print(msg)
    return ok


def _check_config(silent: bool = False) -> tuple[bool, dict]:
    """Check ~/.llmwikify/llmwikify.json. Returns (ok, data_for_json)."""
    if not CONFIG_PATH.exists():
        _check("~/.llmwikify/llmwikify.json", False,
               "not found — run: llmwikify init-llm", silent=silent)
        return False, {"category": "config", "name": str(CONFIG_PATH),
                       "status": "missing"}

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _check("~/.llmwikify/llmwikify.json", False, f"parse error: {e}", silent=silent)
        return False, {"category": "config", "name": str(CONFIG_PATH),
                       "status": "error", "detail": str(e)}

    llm = data.get("llm", {})
    if not llm.get("enabled"):
        _check("~/.llmwikify/llmwikify.json", True, "LLM disabled (offline mode)", silent=silent)
        return True, {"category": "config", "name": str(CONFIG_PATH),
                      "status": "ok", "enabled": False}

    provider = llm.get("provider", "unknown")
    model = llm.get("model", "unknown")
    _check("~/.llmwikify/llmwikify.json", True,
           f"provider={provider}, model={model}", silent=silent)
    return True, {"category": "config", "name": str(CONFIG_PATH),
                  "status": "ok", "enabled": True,
                  "provider": provider, "model": model}


def _check_python(silent: bool = False) -> bool:
    """Check Python version >= 3.10."""
    v = sys.version_info
    ok = v >= (3, 10)
    _check(f"Python {v.major}.{v.minor}.{v.micro}", ok, "requires >= 3.10", silent=silent)
    return ok


def _check_core_deps(silent: bool = False) -> int:
    """Check core dependencies. Returns number of failures."""
    failures = 0
    for mod_name in ["llmwikify", "yaml", "duckdb", "jinja2"]:
        try:
            importlib.import_module(mod_name)
            _check(mod_name, True, silent=silent)
        except ImportError:
            _check(mod_name, False, "not installed", silent=silent)
            failures += 1
    return failures


def _check_optional_deps(silent: bool = False) -> None:
    """Check optional extras — failures are warnings, not errors."""
    extras = {
        "fastapi": "web",
        "fastmcp": "mcp",
        "watchdog": "watch",
        "networkx": "graph",
        "markitdown": "extractors",
        "tiktoken": "llm",
        "httpx": "http",
    }
    for mod_name, extra in extras.items():
        try:
            importlib.import_module(mod_name)
            _check(f"{mod_name}", True, extra, silent=silent)
        except ImportError:
            _check(f"{mod_name}", False,
                   f"{extra} — pip install 'llmwikify[{extra}]'", silent=silent)


def _check_llm_connectivity() -> tuple[bool, float, str]:
    """Test LLM API connectivity with a minimal request.

    Returns:
        (ok, latency_seconds, detail_string)
    """
    if not CONFIG_PATH.exists():
        return False, 0.0, "config not found"

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False, 0.0, "config parse error"

    llm = data.get("llm", {})
    if not llm.get("enabled"):
        return True, 0.0, "LLM disabled (skipped)"
    if not llm.get("api_key"):
        return False, 0.0, "api_key missing"

    provider = llm.get("provider", "openai")
    model = llm.get("model", "gpt-4o")
    api_key = llm["api_key"]

    # Provider endpoints
    provider_urls = {
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "minimax": "https://api.minimaxi.com/v1/chat/completions",
        "xiaomi": "https://api.xiaomi.com/v1/chat/completions",
    }
    default_base = {
        "openai": "https://api.openai.com/v1",
        "anthropic": "https://api.anthropic.com/v1",
        "minimax": "https://api.minimaxi.com/v1",
        "xiaomi": "https://api.xiaomi.com/v1",
    }

    base_url = llm.get("base_url") or default_base.get(provider, default_base["openai"])
    url = provider_urls.get(provider, f"{base_url.rstrip('/')}/chat/completions")

    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Say hi"}],
        "max_tokens": 5,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        import httpx
        start = time.monotonic()
        resp = httpx.post(url, json=body, headers=headers, timeout=LLM_TEST_TIMEOUT)
        latency = time.monotonic() - start

        if resp.status_code in (200, 201):
            return True, latency, f"responded in {latency:.1f}s"
        elif resp.status_code in (401, 403):
            return False, latency, f"auth error (HTTP {resp.status_code})"
        else:
            return False, latency, f"HTTP {resp.status_code}: {resp.text[:100]}"
    except Exception as e:
        return False, 0.0, f"network error: {type(e).__name__}"


def _check_webui_bundle(silent: bool = False) -> bool:
    """Check if WebUI bundle is built."""
    try:
        import llmwikify
        pkg_dir = Path(llmwikify.__file__).parent.parent.parent
        dist_path = pkg_dir / "ui" / "webui" / "dist"
        if dist_path.exists() and (dist_path / "index.html").exists():
            _check("ui/webui/dist/", True, "found", silent=silent)
            return True
        else:
            _check("ui/webui/dist/", False,
                   "not built — cd ui/webui && pnpm build", silent=silent)
            return False
    except Exception:
        _check("ui/webui/dist/", False, "cannot locate", silent=silent)
        return False


def _check_wiki_dir(wiki_root: Path, silent: bool = False) -> tuple[bool, list[str]]:
    """Check wiki directory structure. Returns (ok, missing_files)."""
    expected = ["wiki.md", ".llmwikify.db", "index.md", "raw"]
    missing = []

    for name in expected:
        path = wiki_root / name
        if not path.exists():
            missing.append(name)

    if not (wiki_root / "wiki.md").exists():
        _check(f"{wiki_root}", False,
               "not a wiki directory — no wiki.md found", silent=silent)
        return False, expected
    else:
        if missing:
            detail = f"missing: {', '.join(missing)}"
        else:
            detail = f"{len(expected)} files present"
        _check(f"{wiki_root}", not missing, detail, silent=silent)
        return not missing, missing


def _check_permissions(wiki_root: Path, silent: bool = False) -> bool:
    """Check write permissions for config dir and wiki root."""
    ok = True
    if CONFIG_DIR.exists():
        test_file = CONFIG_DIR / ".doctor_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            _check("~/.llmwikify/", True, "writable", silent=silent)
        except OSError:
            _check("~/.llmwikify/", False, "not writable", silent=silent)
            ok = False
    else:
        _check("~/.llmwikify/", False, "does not exist", silent=silent)
        ok = False

    if wiki_root.exists():
        test_file = wiki_root / ".doctor_test"
        try:
            test_file.write_text("test")
            test_file.unlink()
            _check(f"{wiki_root}", True, "writable", silent=silent)
        except OSError:
            _check(f"{wiki_root}", False, "not writable", silent=silent)
            ok = False

    return ok


def _check_server(server_url: str, silent: bool = False) -> bool:
    """Check if server is reachable."""
    try:
        import httpx
        resp = httpx.get(f"{server_url}/api/health", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            _check("Server reachable", True,
                   f"status={data.get('status', '?')}", silent=silent)
            return True
        else:
            _check("Server reachable", False, f"HTTP {resp.status_code}", silent=silent)
            return False
    except Exception:
        _check("Server reachable", False,
               f"not running (start with: llmwikify serve --web)", silent=silent)
        return False


def run_doctor(wiki: Any, wiki_root: Any, args: Any) -> int:
    """Run health checks on llmwikify installation.

    Returns:
        0 if all checks pass, 1 if any fail, 2 if config missing.
    """
    skip_llm = getattr(args, "skip_llm", False)
    json_mode = getattr(args, "json", False)
    custom_root = getattr(args, "wiki_root", None)
    check_wiki_root = Path(custom_root) if custom_root else Path.cwd()

    server_url = os.environ.get("SERVER_URL", "http://localhost:8765")

    # In JSON mode, suppress noisy library logs (httpx, numexpr, etc.)
    if json_mode:
        import logging
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("numexpr").setLevel(logging.WARNING)

    errors = 0
    warnings = 0
    results: list[dict] = []

    def _section(title: str) -> None:
        """Print a section header (suppressed in JSON mode)."""
        if not json_mode:
            print()
            print(title)

    def _summary() -> None:
        if not json_mode:
            print()
            if errors == 0 and warnings == 0:
                print(f"{ICON_SUCCESS} All checks passed.")
            elif errors == 0:
                print(f"⚠️  All critical checks passed. {warnings} warning(s).")
            else:
                print(f"❌ {errors} error(s), {warnings} warning(s). See above for details.")

    if not json_mode:
        print("🔍 llmwikify doctor")
        print()

    # --- 1. Config file ---
    if not json_mode:
        print("Config file:")
    ok, data = _check_config(silent=json_mode)
    results.append(data)
    if not ok:
        errors += 1
        if data.get("status") == "missing":
            return 2

    # --- 2. Python version ---
    _section("Python:")
    ok = _check_python(silent=json_mode)
    results.append({"category": "python", "status": "ok" if ok else "fail"})
    if not ok:
        errors += 1

    # --- 3. Core dependencies ---
    _section("Core dependencies:")
    failures = _check_core_deps(silent=json_mode)
    results.append({"category": "core_deps", "status": "ok" if failures == 0 else "fail",
                    "failures": failures})
    errors += failures

    # --- 4. Optional extras ---
    _section("Optional extras:")
    _check_optional_deps(silent=json_mode)

    # --- 5. LLM connectivity ---
    _section("LLM connectivity:")
    if skip_llm:
        _check("LLM test", True, "skipped (--skip-llm)", silent=json_mode)
        results.append({"category": "llm", "status": "skipped"})
    else:
        ok, latency, detail = _check_llm_connectivity()
        _check("LLM test", ok, detail, silent=json_mode)
        results.append({"category": "llm", "status": "ok" if ok else "fail",
                        "latency_s": round(latency, 2), "detail": detail})
        if not ok:
            warnings += 1

    # --- 6. Wiki directory ---
    _section(f"Wiki directory ({check_wiki_root}):")
    ok, missing = _check_wiki_dir(check_wiki_root, silent=json_mode)
    results.append({"category": "wiki", "status": "ok" if ok else "fail",
                    "path": str(check_wiki_root), "missing": missing})
    if not ok and (check_wiki_root / "wiki.md").exists():
        errors += 1

    # --- 7. Permissions ---
    _section("Permissions:")
    ok = _check_permissions(check_wiki_root, silent=json_mode)
    results.append({"category": "permissions", "status": "ok" if ok else "fail"})
    if not ok:
        errors += 1

    # --- 8. WebUI bundle ---
    _section("WebUI bundle:")
    ok = _check_webui_bundle(silent=json_mode)
    results.append({"category": "webui", "status": "ok" if ok else "fail"})
    if not ok:
        warnings += 1

    # --- 9. Server health ---
    _section(f"Server ({server_url}):")
    ok = _check_server(server_url, silent=json_mode)
    results.append({"category": "server", "status": "ok" if ok else "fail",
                    "url": server_url})
    if not ok:
        warnings += 1

    # --- Summary ---
    if json_mode:
        summary = {
            "total": len(results),
            "passed": sum(1 for r in results if r.get("status") == "ok"),
            "failed": errors,
            "warnings": warnings,
        }
        output = {"checks": results, "summary": summary}
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        _summary()

    return 0 if errors == 0 else 1


class DoctorCommand(Command):
    """Check llmwikify installation health."""

    name = "doctor"
    help = "Check config, dependencies, LLM connectivity, wiki structure, and server health"

    def setup_parser(self, subparsers: Any) -> None:
        from argparse import _SubParsersAction
        if not isinstance(subparsers, _SubParsersAction):
            raise TypeError("setup_parser requires an argparse subparsers action")
        p = subparsers.add_parser(self.name, help=self.help)
        p.add_argument(
            "--wiki-root", dest="wiki_root", default=None,
            help="Path to wiki directory to check (default: current dir)",
        )
        p.add_argument(
            "--skip-llm", dest="skip_llm", action="store_true",
            help="Skip LLM connectivity test (faster, no API call)",
        )
        p.add_argument(
            "--json", dest="json", action="store_true",
            help="Output results as JSON (for scripts/CI)",
        )

    def run(self, args: Any, wiki: Any, config: dict) -> int:
        return run_doctor(wiki, wiki.root if hasattr(wiki, 'root') else None, args)
