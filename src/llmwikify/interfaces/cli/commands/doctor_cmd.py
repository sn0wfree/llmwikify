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
from .._output import ICON_SUCCESS

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
        return False, {
            "category": "config",
            "name": str(CONFIG_PATH),
            "status": "missing",
            "fix": {
                "commands": ["llmwikify init-llm"],
                "docs":     "docs/ONBOARDING.md#configure-llm",
                "hint":     "Or set LLMWIKIFY_LLM_API_KEY env var",
                "cost":     "~30s",
                "risk":     "low",
                "auto":     False,
            },
        }

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _check("~/.llmwikify/llmwikify.json", False, f"parse error: {e}", silent=silent)
        return False, {
            "category": "config",
            "name": str(CONFIG_PATH),
            "status": "error",
            "detail": str(e),
            "fix": {
                "commands": ["llmwikify init-llm --force"],
                "docs":     "docs/ONBOARDING.md#configure-llm",
                "hint":     "Or edit ~/.llmwikify/llmwikify.json manually",
                "cost":     "~30s",
                "risk":     "medium",
                "auto":     False,
            },
        }

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


# Fix recipes (D5=A: hardcoded). Each fix dict follows the schema:
#   {commands, docs, hint?, cost, risk, auto}
# risk ∈ {"low", "medium", "high"}; auto = whether `llmwikify doctor --fix`
# (D6, deferred) could safely auto-run.
_PYTHON_FIX: dict[str, Any] = {
    "commands": ["pyenv install 3.11 && pyenv global 3.11"],
    "docs":     "README.md#requirements",
    "hint":     "Or use conda: conda create -n llmwikify python=3.11 "
               "Or use Docker image",
    "cost":     "~2 min (download + install)",
    "risk":     "medium",
    "auto":     False,
}


def _check_python(silent: bool = False) -> bool:
    """Check Python version >= 3.10."""
    v = sys.version_info
    ok = v >= (3, 10)
    _check(f"Python {v.major}.{v.minor}.{v.micro}", ok, "requires >= 3.10", silent=silent)
    if not ok:
        # Print fix hint inline (D6 deferred: only text mode hint, no auto)
        if not silent:
            print(f"      Fix:   {' | '.join(_PYTHON_FIX['commands'])}")
            print(f"      Docs:  {_PYTHON_FIX['docs']}")
            print(f"      Cost:  {_PYTHON_FIX['cost']}    "
                  f"Risk: {_PYTHON_FIX['risk']}    Auto: {_PYTHON_FIX['auto']}")
    return ok


_CORE_DEPS_FIX: dict[str, Any] = {
    "commands": ["pip install -e '.[dev]'"],
    "docs":     "pyproject.toml#project.dependencies",
    "hint":     "Or pip install <missing-pkg> for each individually",
    "cost":     "~30s",
    "risk":     "low",
    "auto":     False,
}


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
    if failures > 0 and not silent:
        print(f"      Fix:   {' | '.join(_CORE_DEPS_FIX['commands'])}")
        print(f"      Docs:  {_CORE_DEPS_FIX['docs']}")
        print(f"      Cost:  {_CORE_DEPS_FIX['cost']}    "
              f"Risk: {_CORE_DEPS_FIX['risk']}    Auto: {_CORE_DEPS_FIX['auto']}")
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


_LLM_FIX: dict[str, Any] = {
    "commands": ["llmwikify init-llm"],
    "docs":     "docs/ONBOARDING.md#configure-llm",
    "hint":     "Check API key validity / network / provider status",
    "cost":     "~30s",
    "risk":     "low",
    "auto":     False,
}


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
    # v0.41: base_url and model from providers.yaml + resolver
    from llmwikify.foundation.llm.resolver import resolve_chat_llm

    spec = resolve_chat_llm({"llm": llm})
    base_url = llm.get("base_url") or spec.base_url
    model = llm.get("model") or spec.model
    api_key = llm["api_key"]

    # Provider-specific completion endpoints (different APIs).
    # Anthropic uses /v1/messages; OpenAI-compat uses /v1/chat/completions.
    completion_paths = {
        "anthropic": "/v1/messages",
        "openai": "/v1/chat/completions",
        "minimax": "/v1/chat/completions",
        "xiaomi": "/v1/chat/completions",
    }
    base_url_normalized = base_url.rstrip("/")
    if base_url_normalized.endswith("/v1"):
        path = completion_paths.get(provider, "/v1/chat/completions")
    else:
        path = completion_paths.get(provider, "/v1/chat/completions")
    url = f"{base_url_normalized}{path}"

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


_WEBUI_FIX: dict[str, Any] = {
    "commands": ["cd ui/webui && pnpm install && pnpm build"],
    "docs":     "AGENTS.md#webui-构建",
    "hint":     "Or: cd ui/webui && npm install && npm run build",
    "cost":     "~2 min (npm install) + ~30s (build)",
    "risk":     "medium",
    "auto":     False,
}


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
            if not silent:
                print(f"      Fix:   {' | '.join(_WEBUI_FIX['commands'])}")
                print(f"      Docs:  {_WEBUI_FIX['docs']}")
                print(f"      Cost:  {_WEBUI_FIX['cost']}    "
                      f"Risk: {_WEBUI_FIX['risk']}    Auto: {_WEBUI_FIX['auto']}")
            return False
    except Exception:
        _check("ui/webui/dist/", False, "cannot locate", silent=silent)
        return False


def _check_wiki_dir(wiki: Any, silent: bool = False) -> dict[str, Any]:
    """Check wiki directory structure via Wiki object (single source of truth).

    Uses ``Wiki.expected_layout`` / ``Wiki.layout_diff`` instead of a
    hardcoded path list. The page-type subdirectory set is parsed
    dynamically from ``wiki.md`` (Directory Structure + Page Types),
    so this check tracks user-added custom subdirs without code change.

    Severity rules (D1-D4):
      - FAIL:   4 functional paths missing (raw/, wiki/, db, wiki.md)
      - WARN:   declared_only (wiki.md says X but disk has no X)
      - INFO:   actual_only (disk has Y but wiki.md doesn't mention Y)

    Returns a dict with ok flag and the diff details. Doctor's
    run_doctor() uses the diff to compute errors / warnings / info
    and to render the "Recommended actions" block (D9=C).
    """
    if wiki is None or not hasattr(wiki, "layout_diff"):
        _check("wiki object", False,
               "not provided — pass a Wiki instance", silent=silent)
        return {
            "ok": False,
            "missing_required": ["raw/", "wiki/", ".llmwikify.db", "wiki.md"],
            "in_both": [],
            "declared_only": [],
            "actual_only": [],
        }

    diff = wiki.layout_diff()
    required = {"raw/", "wiki/", ".llmwikify.db", "wiki.md"}
    required_missing = sorted(required & set(diff["declared_only"]))
    ok = not required_missing

    total_declared = len(diff["in_both"]) + len(diff["declared_only"])
    label = str(wiki.root) if hasattr(wiki, "root") else "wiki"

    if not diff["declared_only"] and not diff["actual_only"]:
        detail = f"{total_declared} declared paths all exist on disk"
    else:
        parts = [f"{len(diff['in_both'])}/{total_declared} declared paths exist"]
        if diff["declared_only"]:
            parts.append(f"missing: {diff['declared_only']}")
        if diff["actual_only"]:
            parts.append(f"undeclared: {diff['actual_only']}")
        detail = " — ".join(parts)

    _check(label, ok, detail, silent=silent)
    return {
        "ok": ok,
        "missing_required": required_missing,
        "in_both": diff["in_both"],
        "declared_only": diff["declared_only"],
        "actual_only": diff["actual_only"],
    }


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

    if not ok and not silent:
        print(f"      Fix:   {' | '.join(_PERMISSIONS_FIX['commands'])}")
        print(f"      Docs:  {_PERMISSIONS_FIX['docs']}")
        print(f"      Cost:  {_PERMISSIONS_FIX['cost']}    "
              f"Risk: {_PERMISSIONS_FIX['risk']}    Auto: {_PERMISSIONS_FIX['auto']}")
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
               "not running (start with: llmwikify serve --web)", silent=silent)
        if not silent:
            print("      Fix:   llmwikify serve --web --port 8765")
            print("      Docs:  AGENTS.md#服务器")
            print("      Cost:  startup    Risk: low    Auto: true")
        return False


_SERVER_FIX: dict[str, Any] = {
    "commands": ["llmwikify serve --web --port 8765"],
    "docs":     "AGENTS.md#服务器",
    "hint":     "AGENTS.md: 不加 --reload (会 reload 重启). "
               "Health check: curl http://localhost:8765/api/health",
    "cost":     "startup (~2s)",
    "risk":     "low",
    "auto":     True,
}


_PERMISSIONS_FIX: dict[str, Any] = {
    "commands": ["chmod u+w ~/.llmwikify <wiki_root>"],
    "docs":     "docs/ONBOARDING.md#permissions",
    "hint":     "Or run as the wiki owner (avoid root): "
               "sudo -u <user> llmwikify doctor",
    "cost":     "<1s",
    "risk":     "medium",
    "auto":     True,
}


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

    # --- 6. Wiki directory (v0.40+: uses Wiki instance + dynamic wiki.md parse) ---
    _section(f"Wiki directory ({check_wiki_root}):")
    wiki_result = _check_wiki_dir(wiki, silent=json_mode)
    wiki_status = "ok" if wiki_result["ok"] else "fail"
    wiki_entry: dict[str, Any] = {
        "category": "wiki",
        "status": wiki_status,
        "path": str(check_wiki_root),
        "in_both": wiki_result["in_both"],
        "declared_only": wiki_result["declared_only"],
        "actual_only": wiki_result["actual_only"],
    }
    if not wiki_result["ok"]:
        wiki_entry["fix"] = {
            "commands": ["llmwikify init"],
            "docs":     "docs/ONBOARDING.md#init",
            "hint":     "init 自动创建 raw/, wiki/, .llmwikify.db, wiki.md, "
                       "index.md, log.md",
            "cost":     "~5s",
            "risk":     "low",
            "auto":     True,
        }
    results.append(wiki_entry)
    if not wiki_result["ok"]:
        errors += 1
    if wiki_result["declared_only"]:
        warnings += 1
    # actual_only is info-only, doesn't affect exit code

    # --- 7. Permissions ---
    _section("Permissions:")
    ok = _check_permissions(check_wiki_root, silent=json_mode)
    perm_entry: dict[str, Any] = {
        "category": "permissions",
        "status": "ok" if ok else "fail",
    }
    if not ok:
        perm_entry["fix"] = _PERMISSIONS_FIX
    results.append(perm_entry)
    if not ok:
        errors += 1

    # --- 8. WebUI bundle ---
    _section("WebUI bundle:")
    ok = _check_webui_bundle(silent=json_mode)
    webui_entry: dict[str, Any] = {
        "category": "webui",
        "status": "ok" if ok else "fail",
    }
    if not ok:
        webui_entry["fix"] = _WEBUI_FIX
    results.append(webui_entry)
    if not ok:
        warnings += 1

    # --- 9. Server health ---
    _section(f"Server ({server_url}):")
    ok = _check_server(server_url, silent=json_mode)
    server_entry: dict[str, Any] = {
        "category": "server",
        "status": "ok" if ok else "fail",
        "url": server_url,
    }
    if not ok:
        server_entry["fix"] = _SERVER_FIX
    results.append(server_entry)
    if not ok:
        warnings += 1

    # --- LLM entry (also gets fix) ---
    # Find the LLM result we appended above and add fix if it failed.
    for r in results:
        if r.get("category") == "llm" and r.get("status") == "fail":
            r["fix"] = _LLM_FIX
            break

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
        # D9=C: print a "Recommended actions" block — aggregate of
        # every fail + warn that carries a fix dict, so users can
        # see "what to do next" in one place without scrolling.
        _print_recommended_actions(results)

    return 0 if errors == 0 else 1


def _print_recommended_actions(results: list[dict]) -> None:
    """Print a single block of fixes for every fail + warn.

    D9=C: every fail and warn that has a fix dict is shown here
    with [LEVEL i/n] header, the fix command(s), docs link, and
    the cost/risk/auto meta. Info-only entries are skipped (they
    have no actionable fix).

    Output format (D8=A — same content in text and JSON; the JSON
    side has the per-check ``fix`` field, this is just the
    text-mode aggregator).
    """
    actionable: list[tuple[str, dict]] = []  # (level, entry)
    for r in results:
        if r.get("status") in ("fail", "warn") and r.get("fix"):
            actionable.append((r["status"], r))
    if not actionable:
        return
    print()
    print("═" * 60)
    print("📋 Recommended actions:")
    print()
    for i, (level, r) in enumerate(actionable, 1):
        fix = r["fix"]
        level_label = level.upper()
        n = len(actionable)
        print(f"  [{level_label} {i}/{n}] {r['category']} "
              f"({r.get('detail') or r.get('status')})")
        print(f"      Fix:   {' | '.join(fix.get('commands', []))}")
        if fix.get("docs"):
            print(f"      Docs:  {fix['docs']}")
        cost = fix.get("cost", "?")
        risk = fix.get("risk", "?")
        auto = fix.get("auto", False)
        print(f"      Cost:  {cost}    Risk: {risk}    Auto: {auto}")
        if fix.get("hint"):
            print(f"      Hint:  {fix['hint']}")
        print()


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
        # Honour --wiki-root: if the user asked for a different path
        # than the Wiki instance was constructed with, build a fresh
        # Wiki pointing at that path. Without this, doctor would
        # always report on the package's own root, ignoring the
        # user's actual wiki (regression in v0.40+ where doctor
        # switched to consulting the Wiki object for layout).
        custom_root = getattr(args, "wiki_root", None)
        if custom_root and hasattr(wiki, "root"):
            try:
                if Path(custom_root).resolve() != Path(wiki.root).resolve():
                    from llmwikify.kernel import Wiki as _Wiki
                    wiki = _Wiki(Path(custom_root), config=config)
            except (OSError, RuntimeError):
                pass  # fall back to original wiki on path error
        return run_doctor(wiki, wiki.root if hasattr(wiki, "root") else None, args)
