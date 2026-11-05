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
# Application packages inside apps/ may only depend on each other along
# ``→ research`` (the research layer is consumable). Shared
# infrastructure (``chat_db`` / ``wiki_db`` / ``db_base`` / ``db``) is
# deliberately NOT a peer: it sits at the apps level like ``db_base``
# and is consumed by the apps.
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

APPS_ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {("chat", "research"), ("wiki", "research")}
)

# Structural (module-level) baseline: 0 — a new module-level peer edge
# anywhere in apps/ fails the check.
APPS_PEER_BASELINE: dict[tuple[str, str], int] = {}

# Runtime (function-local) baseline as of 2026-11.
APPS_RUNTIME_BASELINE: dict[tuple[str, str], int] = {
    ("agent", "chat"): 2,
    ("agent", "research"): 1,
    ("chat", "agent"): 1,
    ("chat", "wiki"): 1,
    ("wiki", "agent"): 4,
}

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
    import ast

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

    if regressions:
        print(
            "\n❌ structural apps peer debt grew beyond the baseline:"
            f"\n  {chr(10).join('  ' + r for r in regressions)}"
            "\nMove the code into the right package, or (if the edge is"
            "\nintentional) raise the baseline in APPS_PEER_BASELINE."
        )
        return 1

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
