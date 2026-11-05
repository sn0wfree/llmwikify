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
# The counts below are the baseline (2026-11) and must not grow — a new
# edge, or more hits on an existing one, fails the check.
APPS_APP_PACKAGES: frozenset[str] = frozenset(
    {"agent", "api", "chat", "research", "wiki"}
)

APPS_ALLOWED_EDGES: frozenset[tuple[str, str]] = frozenset(
    {("chat", "research"), ("wiki", "research")}
)

APPS_PEER_BASELINE: dict[tuple[str, str], int] = {
    ("agent", "chat"): 3,
    ("agent", "research"): 1,
    ("api", "chat"): 1,
    ("chat", "agent"): 1,
    ("chat", "wiki"): 1,
    ("research", "chat"): 0,
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


def _check_apps_peers() -> tuple[dict[tuple[str, str], int], list[str]]:
    """Count apps→apps peer edges and flag ones beyond the baseline.

    Returns ``(counts, regressions)`` where regressions are human-readable
    descriptions of edges that exceed the recorded baseline.
    """
    peers = _apps_peers()
    pat = re.compile(r"^\s*(?:from|import)\s+llmwikify\.apps\.([a-z_][a-z0-9_]*)")
    counts: dict[tuple[str, str], int] = defaultdict(int)

    for py_file in sorted(APPS.rglob("*.py")):
        rel = py_file.relative_to(APPS).parts
        if not rel or rel[0] not in peers:
            continue
        own = rel[0]
        try:
            text = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line in text.splitlines():
            m = pat.match(line)
            if not m:
                continue
            target = m.group(1)
            if target not in peers or target == own:
                continue
            counts[(own, target)] += 1

    regressions: list[str] = []
    for (own, target), n in sorted(counts.items()):
        if (own, target) in APPS_ALLOWED_EDGES:
            continue
        allowed = APPS_PEER_BASELINE.get((own, target), 0)
        if n > allowed:
            regressions.append(
                f"{own} → {target}: {n} import(s), baseline allows {allowed}"
            )
    return dict(counts), regressions


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
    counts, regressions = _check_apps_peers()
    debt = sum(
        n
        for (a, b), n in counts.items()
        if (a, b) not in APPS_ALLOWED_EDGES
    )
    print(
        f"\napps peer packages: {len(counts)} edge(s), "
        f"{debt} import(s) outside the allowed → research direction"
    )
    for (a, b), n in sorted(counts.items()):
        mark = "ok " if (a, b) in APPS_ALLOWED_EDGES else "debt"
        print(f"  [{mark}] {a} → {b}: {n}")

    if regressions:
        print(
            "\n❌ apps peer-package debt grew beyond the baseline:"
            f"\n  {chr(10).join('  ' + r for r in regressions)}"
            "\nMove the code into the right package, or (if the edge is"
            "\nintentional) raise the baseline in APPS_PEER_BASELINE."
        )
        return 1

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
