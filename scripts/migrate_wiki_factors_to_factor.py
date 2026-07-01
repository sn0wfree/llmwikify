"""Idempotent migration: wiki/factors/*.md → wiki/factor/*.md.

Per P1 path uniqueness + P6 兼容窗口=0, the canonical Wiki directory for
factor definitions is ``wiki/factor/`` (singular). Older runs may have
written to ``wiki/factors/`` (plural) — this script relocates those files
to the canonical location in a safe, idempotent way.

Usage:
    python scripts/migrate_wiki_factors_to_factor.py [--root PATH]

Behavior:
    - Creates ``wiki/factor/`` if missing.
    - For each ``wiki/factors/*.md``:
        * If ``wiki/factor/<name>.md`` already exists: skip (refuse to overwrite).
        * Otherwise: move file via rename.
    - After all moves, removes ``wiki/factors/`` if it is empty.
    - Re-running on an already-migrated tree is a no-op (idempotent).

Exit codes:
    0 — migration complete (or no-op)
    1 — a target file already exists in factor/ (manual conflict resolution required)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def migrate(root: Path) -> int:
    """Run the migration. Returns 0 on success, 1 on conflict."""
    src_dir = root / "wiki" / "factors"
    dst_dir = root / "wiki" / "factor"

    if not src_dir.is_dir():
        print(f"[ok] no wiki/factors/ to migrate (root={root})")
        return 0

    dst_dir.mkdir(parents=True, exist_ok=True)

    conflicts: list[str] = []
    moved = 0
    skipped = 0

    for md in sorted(src_dir.glob("*.md")):
        target = dst_dir / md.name
        if target.exists():
            conflicts.append(md.name)
            print(f"[conflict] {md.name} already exists in factor/ — skip")
            skipped += 1
            continue
        md.rename(target)
        moved += 1
        print(f"[moved] factors/{md.name} → factor/{md.name}")

    if not conflicts:
        # Remove the now-empty source directory.
        try:
            src_dir.rmdir()
            print(f"[rmdir] removed empty {src_dir}")
        except OSError:
            # Non-empty (leftover non-md files) — leave it.
            print(f"[keep] {src_dir} not empty, leaving in place")
    else:
        print(f"[FAIL] {len(conflicts)} conflict(s); resolve manually:")
        for name in conflicts:
            print(f"  - {name}")
        return 1

    print(f"[done] moved={moved} skipped={skipped}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate wiki/factors/ → wiki/factor/ (P1 path uniqueness)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root (default: current working directory)",
    )
    args = parser.parse_args()
    return migrate(args.root)


if __name__ == "__main__":
    sys.exit(main())
