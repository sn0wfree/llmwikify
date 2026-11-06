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

Beyond layering it also resolves every `llmwikify.*` import against
the real package tree (AST, no import execution), because a rename or
move that leaves a dangling path is a runtime ModuleNotFoundError the
layer check cannot see (see the broken-import check below).

Usage:

    python scripts/check_architecture.py
    # Exits 0 if clean, 1 if violations found.
"""
from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src" / "llmwikify"
APPS = SRC / "apps"

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

# ── apps peer-package rule ────────────────────────────────────────────
# Application packages inside apps/ may depend on the two shared domain
# layers — ``research`` (research engine) and ``wiki`` (knowledge base).
# They may NOT depend on each other (``chat`` ↔ ``agent`` was the cycle
# that motivated this rule). Shared infrastructure (``chat_db`` /
# ``wiki_db`` / ``db_base`` / ``db``) is deliberately NOT a peer.
#
# Two classes of edge are tracked separately:
#
# - **structural** (module-level import): import-time coupling, the
#   real cycle risk. Baseline is empty — ANY new one fails.
# - **runtime** (function-local import): the composition-root pattern
#   (a service lazily constructs its subsystems). Baseline records the
#   current count; growth requires a conscious baseline bump.
APPS_APP_PACKAGES: frozenset[str] = frozenset(
    {"agent", "chat", "research", "wiki"}
)

# Apps may consume the shared domain layers; they may not depend on
# each other (that is what created the chat↔agent cycle).
APPS_ALLOWED_TARGETS: frozenset[str] = frozenset({"research", "wiki"})
APPS_ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {(a, b) for a in APPS_APP_PACKAGES for b in APPS_ALLOWED_TARGETS if a != b}
)

# Structural (module-level) baseline: 0 — a new module-level peer edge
# anywhere in apps/ fails the check.
APPS_PEER_BASELINE: dict[tuple[str, str], int] = {}

# Runtime (function-local) baseline as of 2026-11.
# After the Category 1+2 moves all app↔app edges are gone; kept as an
# empty ceiling so any new runtime edge requires a conscious bump.
APPS_RUNTIME_BASELINE: dict[tuple[str, str], int] = {}

# Whitelist: files where a forbidden import is intentional.
# These are pre-existing back-compat shims documented in AGENTS.md /
# docs/REFACTORING.md; the alternative would be to remove them
# entirely, which we cannot do without breaking downstream callers.
WHITELIST: dict[str, set[tuple[str, str, str]]] = {
    # layer → {(from_path, to_layer, to_module)}
}


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


def _apps_peers() -> set[str]:
    """Application packages inside apps/ (shared infra is not a peer)."""
    return {
        p.name
        for p in APPS.iterdir()
        if p.is_dir() and p.name in APPS_APP_PACKAGES
    }


def _check_apps_peers() -> tuple[dict, list[str]]:
    """Classify apps→apps peer imports and flag structural regressions.

    Two kinds of edge are counted:

    - **module-level** — an import-time (structural) dependency. This is
      what the baseline guards: a new one, or more hits on an existing
      one, is a regression.
    - **function-local** — a deliberate runtime dependency (the
      composition-root pattern: a service lazily constructs its
      subsystems). Reported for visibility but not gated.

    Returns ``(report, regressions)``.
    """
    peers = _apps_peers()
    structural: dict[tuple[str, str], int] = defaultdict(int)
    runtime: dict[tuple[str, str], int] = defaultdict(int)

    for py_file in sorted(APPS.rglob("*.py")):
        rel = py_file.relative_to(APPS).parts
        if not rel or rel[0] not in peers:
            continue
        own = rel[0]
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            if not node.module.startswith("llmwikify.apps."):
                continue
            target = node.module.split(".")[2]
            if target not in peers or target == own:
                continue
            if (own, target) in APPS_ALLOWED_EDGES:
                continue
            bucket = structural if node.col_offset == 0 else runtime
            bucket[(own, target)] += 1

    regressions: list[str] = []
    for (own, target), n in sorted(structural.items()):
        allowed = APPS_PEER_BASELINE.get((own, target), 0)
        if n > allowed:
            regressions.append(
                f"{own} → {target}: {n} module-level import(s), "
                f"baseline allows {allowed}"
            )
    for (own, target), n in sorted(runtime.items()):
        if (own, target) in APPS_ALLOWED_EDGES:
            continue
        allowed = APPS_RUNTIME_BASELINE.get((own, target), 0)
        if n > allowed:
            regressions.append(
                f"{own} → {target}: {n} function-local import(s), "
                f"runtime baseline allows {allowed}"
            )

    report = {
        "structural": dict(structural),
        "runtime": dict(runtime),
    }
    return report, regressions


# ── broken-import check ──────────────────────────────────────────────
# The layer check above only compares *names*; it cannot see that a
# module was renamed/moved and an import still points at the old path.
# efba3812 shipped exactly that P0: 6 imports of
# ``llmwikify.apps.research.six_step_config_manager`` (a module that
# never existed) broke ``WikiService.get_llm()`` and the 4
# ``/api/agent/config*`` endpoints at runtime.
#
# This check resolves every ``llmwikify.*`` import against the real
# package tree via AST (no import execution) and reports two kinds of
# breakage:
#
#   MISSING_MODULE — the dotted path does not exist at all
#   MISSING_SYMBOL — the parent module exists but does not export the
#                    name (and no ``*`` / ``__getattr__`` escape hatch)
PKG_PREFIX = "llmwikify"


def _collect_modules() -> dict[str, Path]:
    """Map every importable dotted name under ``src/llmwikify`` to a path.

    Directories count as namespace packages so that a package whose
    ``__init__.py`` was deleted still resolves.
    """
    mods: dict[str, Path] = {}
    for path in SRC.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(SRC)
        if path.is_dir():
            mods[".".join((PKG_PREFIX, *rel.parts))] = path
            continue
        if path.suffix != ".py":
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods[".".join((PKG_PREFIX, *parts))] = path
    return mods


def _module_package(path: Path) -> list[str]:
    """Dotted package that relative imports in ``path`` resolve against."""
    rel = path.relative_to(SRC)
    parts = list(rel.with_suffix("").parts)
    return parts[:-1] if path.name != "__init__.py" else parts


def _replaces_own_module(node: ast.stmt) -> bool:
    """True for ``sys.modules[__name__] = other`` (module-object shims).

    Such a shim exposes the target module's namespace at runtime; the
    names are not in this file, so static export resolution must not
    second-guess it.
    """
    if not isinstance(node, ast.Assign):
        return False
    for tgt in node.targets:
        if not isinstance(tgt, ast.Subscript):
            continue
        value = tgt.value
        if not (isinstance(value, ast.Attribute) and value.attr == "modules"):
            continue
        slice_ = tgt.slice
        # ``sys.modules[__name__]`` (Name) or ``sys.modules["__name__"]``
        if isinstance(slice_, ast.Name) and slice_.id == "__name__":
            return True
        if isinstance(slice_, ast.Constant) and slice_.value == "__name__":
            return True
    return False


def _exported_names(path: Path) -> set[str] | None:
    """Names a module exposes at import time.

    ``None`` means the namespace is unresolvable (``from x import *``,
    a PEP 562 ``__getattr__``, or a ``sys.modules[__name__]`` shim) —
    callers must treat that as "ok".
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None

    names: set[str] = set()
    star = False

    def walk(body: list[ast.stmt]) -> None:
        nonlocal star
        for node in body:
            if _replaces_own_module(node):
                star = True
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        names.add(tgt.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                names.add(node.target.id)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        star = True
                    else:
                        names.add(alias.asname or alias.name)
            elif isinstance(node, ast.If):
                walk(node.body)
                walk(node.orelse)
            elif isinstance(node, (ast.Try, ast.With, ast.AsyncWith)):
                walk(node.body)
                walk(node.orelse)
                walk(node.finalbody)

    walk(tree.body)
    if star or "__getattr__" in names:
        return None
    return names


def _check_imports() -> tuple[list[tuple[Path, int, str, str]], int]:
    """Resolve every ``llmwikify.*`` import; return (problems, total)."""
    mods = _collect_modules()
    problems: list[tuple[Path, int, str, str]] = []
    total = 0

    for py_file in sorted(SRC.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        pkg = _module_package(py_file)

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [(a.name, None) for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[: len(pkg) - (node.level - 1)] if node.level > 1 else pkg
                    if node.module:
                        base = base + node.module.split(".")
                    base_d = ".".join(base)
                elif node.module:
                    base_d = node.module
                else:
                    continue
                targets = [(base_d, None)]
                targets += [(base_d, a.name) for a in node.names]
            else:
                continue

            for dotted, symbol in targets:
                if not dotted.startswith(PKG_PREFIX):
                    continue
                total += 1
                if dotted not in mods:
                    problems.append((py_file, node.lineno, "MISSING_MODULE", dotted))
                    continue
                if symbol is None:
                    continue
                # ``from pkg import name`` — name may be a submodule
                if f"{dotted}.{symbol}" in mods:
                    continue
                exports = _exported_names(mods[dotted])
                if exports is None or symbol in exports:
                    continue
                problems.append(
                    (py_file, node.lineno, "MISSING_SYMBOL", f"{dotted}.{symbol}")
                )

    # one report per (file, line, kind, target) — a single ``from a.b
    # import c`` produces two candidate targets for the same module
    return list(dict.fromkeys(problems)), total


def main() -> int:
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
    else:
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

    # ── apps peer-package debt (baselined ratchet) ───────────────────
    report, regressions = _check_apps_peers()
    structural = report["structural"]
    runtime = report["runtime"]

    s_debt = sum(
        n for (a, b), n in structural.items() if (a, b) not in APPS_ALLOWED_EDGES
    )
    r_debt = sum(n for (a, b), n in runtime.items() if (a, b) not in APPS_ALLOWED_EDGES)
    print(
        f"\napps peer packages — {s_debt} structural (module-level) + "
        f"{r_debt} runtime (function-local) import(s) "
        f"outside the allowed → research direction"
    )
    print("  structural (gated by APPS_PEER_BASELINE):")
    for (a, b), n in sorted(structural.items()):
        mark = "ok " if (a, b) in APPS_ALLOWED_EDGES else "debt"
        print(f"    [{mark}] {a} → {b}: {n}")
    if not structural:
        print("    (none)")
    print("  runtime (composition-root lazy imports, reported only):")
    for (a, b), n in sorted(runtime.items()):
        mark = "ok " if (a, b) in APPS_ALLOWED_EDGES else "lazy"
        print(f"    [{mark}] {a} → {b}: {n}")
    if not runtime:
        print("    (none)")

    # ── broken imports: every llmwikify.* import must resolve ─────────
    problems, total = _check_imports()
    print(
        f"\nimports — {len(problems)} broken of {total} llmwikify import(s) "
        "(AST-resolved, no import execution)"
    )
    if problems:
        for kind in ("MISSING_MODULE", "MISSING_SYMBOL"):
            hits = [p for p in problems if p[2] == kind]
            if not hits:
                continue
            print(f"  {kind}:")
            for f, n, _kind, target in hits[:10]:
                print(f"    {f.relative_to(REPO_ROOT)}:{n}  {target}")
            if len(hits) > 10:
                print(f"    ... and {len(hits) - 10} more")
        print(
            "\n❌ import target does not exist — a runtime ModuleNotFoundError "
            "/ ImportError waiting to happen.\n"
            "Fix the path or restore the module. The layer check cannot "
            "catch this: it only compares names."
        )
    else:
        print("  (none)")

    if regressions:
        print(
            "\n❌ structural apps peer debt grew beyond the baseline:"
            f"\n  {chr(10).join('  ' + r for r in regressions)}"
            "\nMove the code into the right package, or (if the edge is"
            "\nintentional) raise the baseline in APPS_PEER_BASELINE."
        )
        return 1

    return 1 if (violations or problems) else 0


if __name__ == "__main__":
    sys.exit(main())
