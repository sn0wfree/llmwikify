"""Architecture linter for the 4-layer llmwikify refactor.

This script replaces the external ``import-linter`` tool with a
small, dependency-free AST-based checker. It enforces the layer
boundaries defined in
``docs/designs/refactor-4layer-architecture.md``:

    interfaces (L4)  →  apps (L3)  →  kernel (L2)  →  foundation (L1)

Rules (one per "contract"):

  1. **layered** — imports may only flow in the L4→L3→L2→L1
     direction. No upward imports.

  2. **foundation-isolation** — the six L1 subpackages
     (llm, extractors, prompts, templates, config, io) must be
     independent of each other.

  3. **interfaces-isolation** — the four L4 subpackages
     (cli, mcp, server, web) must be independent of each other.

  4. **apps-isolation** — the L3 apps (agent, research, ppt,
     autorun) must be independent, EXCEPT that ``apps.chat``
     may import from ``apps.research``, ``apps.agent`` and
     ``apps.autorun`` (chat reuses research/agent/autorun).

The script walks the Python source tree under ``src/llmwikify/``,
parses every ``.py`` file with ``ast``, and records each
``import X`` / ``from X import Y`` statement. It then checks
each rule and prints violations. Exit code is non-zero if any
violation is found.

Run::

    python scripts/check_architecture.py

Optional flags::

    --verbose     print every import discovered (debug aid)
    --root PATH   repo root to check (default: parent of scripts/)
    --contracts a,b,c    only run the named contracts
"""
from __future__ import annotations

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
SRC_ROOT = REPO_ROOT_DEFAULT / "src" / "llmwikify"


# ─── layer definitions ─────────────────────────────────────────────

LAYERS = ("foundation", "kernel", "apps", "interfaces")
LAYER_RANK = {name: i for i, name in enumerate(LAYERS)}


def layer_of(module: str) -> str | None:
    """Return the layer name of ``llmwikify.<layer>...`` or None."""
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "llmwikify":
        return None
    second = parts[1]
    if second in LAYER_RANK:
        return second
    return None


# ─── import discovery ──────────────────────────────────────────────

@dataclass
class ImportSite:
    """One import statement in one file."""
    importer_file: Path
    importer_module: str
    imported_module: str
    lineno: int


@dataclass
class Contract:
    name: str
    description: str
    violations: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.violations.append(msg)


def iter_python_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        if path.name == "check_architecture.py":
            continue
        yield path


def file_to_module(path: Path, src_root: Path) -> str:
    """Convert ``src/llmwikify/foo/bar.py`` → ``llmwikify.foo.bar``.

    The trailing ``__init__`` is stripped because it isn't part of
    the dotted module name.
    """
    rel = path.relative_to(src_root.parent)
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect_imports(src_root: Path) -> list[ImportSite]:
    sites: list[ImportSite] = []
    for path in iter_python_files(src_root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as e:
            print(f"WARN: cannot parse {path}: {e}", file=sys.stderr)
            continue

        importer_module = file_to_module(path, src_root)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    sites.append(
                        ImportSite(
                            importer_file=path,
                            importer_module=importer_module,
                            imported_module=alias.name,
                            lineno=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue  # ``from . import x`` — skip, not relevant for layer checks
                # Resolve ``from .x import y`` relative imports to an
                # absolute module name so layer detection works.
                level = node.level or 0
                if level == 0:
                    resolved = node.module
                else:
                    importer_parts = importer_module.split(".")
                    # Drop the last ``level`` parts to get the parent
                    # package, then append the explicit module.
                    if level > len(importer_parts):
                        # Malformed relative import; skip.
                        continue
                    base = importer_parts[: len(importer_parts) - level + 1]
                    resolved = ".".join(base + [node.module])
                sites.append(
                    ImportSite(
                        importer_file=path,
                        importer_module=importer_module,
                        imported_module=resolved,
                        lineno=node.lineno,
                    )
                )
    return sites


# ─── contract rules ────────────────────────────────────────────────

def check_layered(sites: list[ImportSite]) -> Contract:
    """Imports may only flow L4→L3→L2→L1 (down the stack).

    An import from a higher-numbered layer to a lower-numbered
    layer is the correct direction (e.g. ``apps.X`` importing
    from ``kernel.Y`` is fine). The forbidden direction is the
    reverse: e.g. ``foundation.X`` importing from ``apps.Y``.
    """
    c = Contract(
        name="layered",
        description=(
            "Imports may only flow interfaces (L4) → apps (L3) → "
            "kernel (L2) → foundation (L1)."
        ),
    )
    for site in sites:
        importer_layer = layer_of(site.importer_module)
        imported_layer = layer_of(site.imported_module)
        if importer_layer is None or imported_layer is None:
            continue
        # Higher rank = closer to the user. Allowed direction is
        # importer_rank >= imported_rank (user code reaching down).
        if LAYER_RANK[importer_layer] < LAYER_RANK[imported_layer]:
            c.add(
                f"{site.importer_file.relative_to(REPO_ROOT_DEFAULT)}:"
                f"{site.lineno}: {site.importer_module} (L{LAYER_RANK[importer_layer]+1} "
                f"{importer_layer}) → {site.imported_module} (L{LAYER_RANK[imported_layer]+1} "
                f"{imported_layer}) — upward import not allowed"
            )
    return c


def check_independence(
    sites: list[ImportSite],
    contract_name: str,
    description: str,
    submodules: list[str],
) -> Contract:
    """Forbid any import from one member of ``submodules`` to another."""
    c = Contract(name=contract_name, description=description)
    sub_set = set(submodules)
    for site in sites:
        importer_top = site.importer_module.split(".")[0:2]
        imported_top = site.imported_module.split(".")[0:2]
        importer_key = ".".join(importer_top)
        imported_key = ".".join(imported_top)
        if importer_key in sub_set and imported_key in sub_set and importer_key != imported_key:
            c.add(
                f"{site.importer_file.relative_to(REPO_ROOT_DEFAULT)}:"
                f"{site.lineno}: {site.importer_module} → "
                f"{site.imported_module} — cross-subpackage import in "
                f"{contract_name}"
            )
    return c


def check_apps_chat_allowed(sites: list[ImportSite]) -> Contract:
    """apps.chat may import from apps.research, apps.agent, apps.autorun.

    This is the "chat reuses research/agent/autorun capabilities"
    exception listed in the design doc §3.2. Other apps (agent,
    research, ppt, autorun) must remain independent.
    """
    c = Contract(
        name="chat-uses-research-and-agent",
        description=(
            "apps.chat may reuse apps.research/agent/autorun; other "
            "apps must be independent."
        ),
    )
    chat_allowed = {"llmwikify.apps.research", "llmwikify.apps.agent", "llmwikify.apps.autorun"}
    apps_top = {"llmwikify.agent", "llmwikify.research", "llmwikify.ppt", "llmwikify.autorun"}
    for site in sites:
        importer_top = ".".join(site.importer_module.split(".")[0:2])
        imported_top = ".".join(site.imported_module.split(".")[0:2])
        if importer_top == "llmwikify.chat":
            if imported_top in chat_allowed:
                continue  # allowed
        # For all other app pairs, independence is required.
        if importer_top in apps_top and imported_top in apps_top and importer_top != imported_top:
            c.add(
                f"{site.importer_file.relative_to(REPO_ROOT_DEFAULT)}:"
                f"{site.lineno}: {site.importer_module} → "
                f"{site.imported_module} — apps must be independent "
                f"(only apps.chat may reuse research/agent/autorun)"
            )
    return c


# ─── main ──────────────────────────────────────────────────────────

def run_contracts(sites: list[ImportSite], only: set[str] | None) -> list[Contract]:
    contracts: list[Contract] = []

    foundation_subs = [
        "llmwikify.foundation.llm",
        "llmwikify.foundation.extractors",
        "llmwikify.foundation.prompts",
        "llmwikify.foundation.templates",
        "llmwikify.foundation.config",
        "llmwikify.foundation.io",
    ]
    interfaces_subs = [
        "llmwikify.interfaces.cli",
        "llmwikify.interfaces.mcp",
        "llmwikify.interfaces.server",
        "llmwikify.interfaces.web",
    ]

    if only is None or "layered" in only:
        contracts.append(check_layered(sites))
    if only is None or "foundation-isolation" in only:
        contracts.append(
            check_independence(
                sites,
                "foundation-isolation",
                "L1 foundation subpackages must be independent.",
                foundation_subs,
            )
        )
    if only is None or "interfaces-isolation" in only:
        contracts.append(
            check_independence(
                sites,
                "interfaces-isolation",
                "L4 interfaces subpackages must be independent.",
                interfaces_subs,
            )
        )
    if only is None or "chat-uses-research-and-agent" in only:
        contracts.append(check_apps_chat_allowed(sites))

    return contracts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO_ROOT_DEFAULT)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--contracts",
        type=str,
        default="",
        help="comma-separated contract names to run (default: all)",
    )
    args = parser.parse_args()

    src_root = args.root / "src" / "llmwikify"
    if not src_root.is_dir():
        print(f"ERROR: src root not found: {src_root}", file=sys.stderr)
        return 2

    sites = collect_imports(src_root)

    if args.verbose:
        # Group by importer for readable debug output.
        by_importer: dict[str, list[ImportSite]] = defaultdict(list)
        for s in sites:
            by_importer[s.importer_module].append(s)
        for importer in sorted(by_importer):
            print(f"{importer}:")
            for s in sorted(by_importer[importer], key=lambda x: x.lineno):
                print(f"  {s.lineno}: {s.imported_module}")
        print()

    only = set(c.strip() for c in args.contracts.split(",") if c.strip()) or None
    contracts = run_contracts(sites, only)

    total_violations = 0
    for c in contracts:
        status = "✅ PASS" if not c.violations else "❌ FAIL"
        print(f"{status}  {c.name}: {c.description}")
        for v in c.violations:
            print(f"    {v}")
        total_violations += len(c.violations)
        print()

    print(f"=== {total_violations} violation(s) across {len(contracts)} contract(s) ===")
    return 1 if total_violations else 0


if __name__ == "__main__":
    sys.exit(main())
