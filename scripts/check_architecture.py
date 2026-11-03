#!/usr/bin/env python3
"""Architecture lint for llmwikify v0.40.

Enforces the 4-layer dependency direction from AGENTS.md:

    interfaces/ → apps/, kernel/, foundation/   ✅ allowed
    apps/       → kernel/, foundation/           ✅ allowed
    kernel/     → foundation/                    ✅ allowed
    foundation/ → (self only)                    ✅ allowed

Forbidden:

    foundation/ → kernel/, apps/, interfaces/    ❌
    kernel/     → apps/, interfaces/             ❌
    apps/       → interfaces/                    ❌

A real linter (`import-linter`) would use AST and respect `if
TYPE_CHECKING` blocks. This script is a pragmatic grep-based check
suitable for pre-commit and CI. It is conservative (some false
positives are tolerated via the per-layer whitelist at the bottom of
this file).

Usage:

    python scripts/check_architecture.py
    # Exits 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "llmwikify"

# Layers in dependency order (top → bottom).
LAYERS = ("interfaces", "apps", "kernel", "foundation")

# Forbidden edges: source layer → forbidden target layers.
#   source can NOT import from any of the targets in FORBIDDEN[source].
FORBIDDEN: dict[str, tuple[str, ...]] = {
    "foundation": ("kernel", "apps", "interfaces"),
    "kernel": ("apps", "interfaces"),
    "apps": ("interfaces",),
    "interfaces": (),  # interfaces may import anything below
}

# Whitelist: files where a forbidden import is intentional.
# These are pre-existing back-compat shims documented in AGENTS.md /
# docs/REFACTORING.md; the alternative would be to remove them
# entirely, which we cannot do without breaking downstream callers.
WHITELIST: dict[str, set[tuple[str, str, str]]] = {
    # layer → {(from_path, to_layer, to_module)}
}

# ── Sibling-package rule (inside ``apps``) ─────────────────────────
#
# The four layers check the *direction* between layers, but inside
# ``apps`` the sibling packages ``chat`` and ``research`` used to
# import **each other** — a cycle the layer rule cannot see (same
# layer). The shared substrate now lives in ``apps/knowledge``, so
# neither imports the other any more.
#
# The only permitted ``chat → research`` imports are the back-compat
# shims: they re-export the research implementation under its old
# path, they point one way only, and they cannot close a cycle.
#
# ``apps/knowledge`` is below both, so it may not import either.
SIBLING_RULES: tuple[tuple[str, str, frozenset[str]], ...] = (
    (
        "chat",
        "research",
        frozenset(
            {
                "actions.py",
                "engine.py",
                "report.py",
                "research_agent.py",
                "research_engine/actions.py",
                "research_engine/engine.py",
                "research_engine/gates.py",
                "research_engine/llm_step.py",
                "research_engine/observer.py",
                "research_engine/reasoner.py",
                "research_engine/report.py",
                "research_engine/resume.py",
                "research_engine/routes.py",
            }
        ),
    ),
    ("knowledge", "chat", frozenset()),
    ("knowledge", "research", frozenset()),
)


# ── the storage port rule (inside kernel/wiki) ──────────────────────
#
# The wiki layer stores its pages through ``WikiBackend`` — the port
# that makes a non-filesystem backend possible. 186 filesystem calls
# used to go around it; they are being migrated one module at a time.
#
# This rule is a **ratchet**: a module that has been migrated may not
# do direct content I/O any more, and the list of modules that still
# may may only get shorter. An entry that no longer has a violation is
# itself reported — the list has to be trimmed.
#
# Only *content* operations are covered (read / write / delete). The
# enumeration still hands out ``Path`` objects, which a virtual backend
# cannot provide — that is the remaining gap of the port.

#: The content operations the storage port owns.
_PORT_CONTENT_OPS = ("read_text", "write_text", "unlink")

#: The modules that still do direct content I/O (relative to
#: ``src/llmwikify``). Every entry is work in progress.
_STORAGE_PORT_PENDING: frozenset[str] = frozenset()
# Empty as of 2026-11-02: every module in kernel/wiki routes its
# content I/O through WikiBackend. New entries may only be added with
# a documented reason — the list has to stay short, and an entry that
# no longer needs the exemption is reported by check_storage_port().


def check_storage_port() -> list[str]:
    """Find the direct content I/O that bypasses the storage port.

    Returns a list of human-readable violations.
    """
    import ast

    violations: list[str] = []
    still_pending: set[str] = set()
    existing_pending: set[str] = set()

    for py_file in sorted(SRC.rglob("*.py")):
        rel = str(py_file.relative_to(SRC)).replace("\\", "/")
        if not rel.startswith("kernel/wiki"):
            continue
        if rel in _STORAGE_PORT_PENDING:
            existing_pending.add(rel)
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        hits: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _PORT_CONTENT_OPS
            ):
                hits.append(f"{rel}:{node.lineno}  {ast.unparse(node.func)}()")

        if not hits:
            continue
        if rel in _STORAGE_PORT_PENDING:
            still_pending.add(rel)
            continue
        violations.extend(
            f"content I/O bypasses the storage port: {hit}" for hit in hits
        )

    # The ratchet: a module that no longer needs the exemption must
    # be removed from the list. Only the modules that exist are
    # considered — a synthetic tree (the tests build one) has neither.
    stale = sorted(existing_pending - still_pending)
    for rel in stale:
        violations.append(
            f"{rel} no longer does direct content I/O — remove it from "
            "_STORAGE_PORT_PENDING"
        )

    return violations


def _sibling_of(path: Path) -> tuple[str, str] | None:
    """Return ``(package, relative_path)`` for a file under ``apps``."""
    rel = path.relative_to(SRC).parts
    if len(rel) < 3 or rel[0] != "apps":
        return None
    return rel[1], "/".join(rel[2:])


def check_sibling_packages() -> list[tuple[Path, int, str, str]]:
    """Find imports between sibling packages that are not allowed.

    A violation is (file, lineno, source_package, forbidden_package).

    Note the asymmetry: ``apps.research → apps.chat`` is the **legal**
    direction (the research pipeline is built on the chat agent
    machinery). Only the reverse direction — and any import out of
    ``apps.knowledge`` — closes a cycle.
    """
    violations: list[tuple[Path, int, str, str]] = []
    allowed_by_pair = {
        (src, dst): allowed for src, dst, allowed in SIBLING_RULES
    }

    for py_file in sorted(SRC.rglob("*.py")):
        where = _sibling_of(py_file)
        if where is None:
            continue
        package, rel_path = where
        for (src_pkg, target_package), allowed in allowed_by_pair.items():
            if src_pkg != package:
                continue
            if rel_path in allowed:
                continue
            try:
                text = py_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            prefix = f"llmwikify.apps.{target_package}"
            for lineno, line in enumerate(text.splitlines(), start=1):
                for m in re.finditer(r"^\s*(?:from|import)\s+([\w.]+)", line):
                    mod = m.group(1)
                    if mod != prefix and not mod.startswith(prefix + "."):
                        continue
                    violations.append((py_file, lineno, package, target_package))
    return violations



def _layer_of(path: Path) -> str | None:
    """Return the layer name for a file path, or None if not in a layer."""
    rel = path.relative_to(SRC).parts
    if not rel:
        return None
    head = rel[0]
    return head if head in LAYERS else None


def _is_under(path: Path, layer: str) -> bool:
    rel = path.relative_to(SRC).parts
    return bool(rel) and rel[0] == layer


def main() -> int:
    # The report uses emoji (✅/❌). On a Windows console with a legacy
    # code page (GBK) — or any time stdout is a pipe rather than a real
    # console handle — the default stream encoding cannot represent them,
    # and the script dies with UnicodeEncodeError *after* the check has
    # already passed. The guard then exits 1 on a clean tree, which makes
    # CI report a false architecture violation.
    #
    # Force UTF-8 on stdout/stderr, with errors="replace" so an exotic
    # codepoint can never take the guard down.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Stream has no reconfigure (e.g. replaced by a test capture)
            # or is already closed — nothing to do.
            pass

    violations: list[tuple[Path, int, str, str]] = []
    # violation = (file, lineno, from_layer, forbidden_target_layer)

    for py_file in sorted(SRC.rglob("*.py")):
        layer = _layer_of(py_file)
        if layer is None:
            continue
        forbidden = FORBIDDEN[layer]
        if not forbidden:
            continue
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in re.finditer(
                r"^\s*(?:from|import)\s+([\w.]+)", line
            ):
                mod = m.group(1)
                # Internal modules are `llmwikify.<layer>.<rest>`.
                if not mod.startswith("llmwikify."):
                    continue
                parts = mod.split(".", 2)
                if len(parts) < 2:
                    continue
                target_layer = parts[1]
                if target_layer not in LAYERS:
                    continue
                if target_layer == layer:
                    continue
                if target_layer not in forbidden:
                    continue
                # Check whitelist
                wl = WHITELIST.get(layer, set())
                if (
                    str(py_file.relative_to(REPO_ROOT)),
                    target_layer,
                    mod,
                ) in wl:
                    continue
                violations.append(
                    (py_file, lineno, layer, target_layer)
                )

    if not violations:
        print("✅ 0 architecture violations across 4 layers")
        port_violations = check_storage_port()
        if port_violations:
            print(
                f"❌ {len(port_violations)} storage-port violation(s) "
                "in kernel/wiki:\n"
            )
            for line in port_violations[:20]:
                print(f"    {line}")
            if len(port_violations) > 20:
                print(f"    ... and {len(port_violations) - 20} more")
            print(
                "\nContent I/O in kernel/wiki must go through WikiBackend "
                "(kernel/storage/backend.py)."
            )
            return 1
        print("✅ 0 storage-port violations in kernel/wiki")
        sibling_violations = check_sibling_packages()
        if not sibling_violations:
            print("✅ 0 sibling-package violations inside apps")
            return 0
        print(
            f"❌ {len(sibling_violations)} sibling-package violation(s) "
            "inside apps:\n"
        )
        grouped: dict[tuple[str, str], list[tuple[Path, int]]] = defaultdict(list)
        for f, n, sp, tp in sibling_violations:
            grouped[(sp, tp)].append((f, n))
        for (sp, tp), items in sorted(grouped.items()):
            print(f"  apps.{sp} → apps.{tp}  ({len(items)} hit(s))")
            for f, n in items[:5]:
                print(f"    {f.relative_to(REPO_ROOT)}:{n}")
            if len(items) > 5:
                print(f"    ... and {len(items) - 5} more")
        print(
            "\nThe shared substrate lives in apps/knowledge/ — import from\n"
            "there instead of from the sibling package."
        )
        return 1

    # Group by (from_layer, to_layer)
    grouped: dict[tuple[str, str], list[tuple[Path, int]]] = defaultdict(list)
    for f, n, fl, tl in violations:
        grouped[(fl, tl)].append((f, n))

    print(f"❌ {len(violations)} architecture violation(s) found:\n")
    for (fl, tl), items in sorted(grouped.items()):
        print(f"  {fl} → {tl}  ({len(items)} hit(s))")
        for f, n in items[:5]:
            rel = f.relative_to(REPO_ROOT)
            print(f"    {rel}:{n}")
        if len(items) > 5:
            print(f"    ... and {len(items) - 5} more")
    print(
        "\nSee AGENTS.md §'Architecture' and docs/REFACTORING.md §3.2\n"
        "for the dependency rules. Fix by moving code to the correct\n"
        "layer or by extending WHITELIST in this script (with rationale)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
