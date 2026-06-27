#!/usr/bin/env python3
"""Migrate Wiki directory structure.

This script migrates the Wiki directory structure to the new layout:
- wiki/factors/*.md → wiki/factor/*.md
- wiki/factorbacktest/ → remove (results will be in DB)
- wiki/trading/*.md → wiki/strategy/*.md (if exists)

Usage:
    python scripts/migrate_wiki_paths.py [--dry-run]

The script is idempotent: running it multiple times produces the same result.
"""

from __future__ import annotations

import argparse
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def migrate_factor_pages(wiki_dir: Path, dry_run: bool = False) -> int:
    """Migrate wiki/factors/*.md → wiki/factor/*.md."""
    src_dir = wiki_dir / "factors"
    dst_dir = wiki_dir / "factor"

    if not src_dir.is_dir():
        logger.info("wiki/factors/ not found, skipping")
        return 0

    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for md in sorted(src_dir.glob("*.md")):
        dst = dst_dir / md.name
        if dst.exists():
            logger.info("skip (exists): %s", dst)
            continue
        if dry_run:
            logger.info("would move: %s → %s", md, dst)
        else:
            shutil.move(str(md), str(dst))
            logger.info("moved: %s → %s", md, dst)
        count += 1

    return count


def migrate_factorbacktest(wiki_dir: Path, dry_run: bool = False) -> int:
    """Remove wiki/factorbacktest/ (old result format)."""
    fb_dir = wiki_dir / "factorbacktest"
    if not fb_dir.is_dir():
        return 0

    # Archive instead of delete
    archive_dir = wiki_dir / "_archive" / "factorbacktest"
    if not dry_run:
        archive_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for md in sorted(fb_dir.glob("*.md")):
        dst = archive_dir / md.name
        if dry_run:
            logger.info("would archive: %s → %s", md, dst)
        else:
            shutil.move(str(md), str(dst))
            logger.info("archived: %s → %s", md, dst)
        count += 1

    if count > 0 and not dry_run:
        shutil.rmtree(fb_dir)
        logger.info("removed: %s", fb_dir)

    return count


def migrate_trading_to_strategy(wiki_dir: Path, dry_run: bool = False) -> int:
    """Migrate wiki/trading/*.md → wiki/strategy/*.md."""
    src_dir = wiki_dir / "trading"
    dst_dir = wiki_dir / "strategy"

    if not src_dir.is_dir():
        logger.info("wiki/trading/ not found, skipping")
        return 0

    if not dry_run:
        dst_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for md in sorted(src_dir.glob("*.md")):
        dst = dst_dir / md.name
        if dst.exists():
            logger.info("skip (exists): %s", dst)
            continue
        if dry_run:
            logger.info("would move: %s → %s", md, dst)
        else:
            shutil.move(str(md), str(dst))
            logger.info("moved: %s → %s", md, dst)
        count += 1

    return count


def ensure_directories(wiki_dir: Path, dry_run: bool = False) -> None:
    """Ensure all required Wiki directories exist."""
    dirs = [
        "factor",
        "strategy",
        "sources",
        "reproduction",
    ]
    for d in dirs:
        path = wiki_dir / d
        if not path.is_dir():
            if dry_run:
                logger.info("would create: %s", path)
            else:
                path.mkdir(parents=True, exist_ok=True)
                logger.info("created: %s", path)


def main() -> None:
    from llmwikify.foundation.logging import setup_logging

    setup_logging(level=logging.INFO, log_file=None, fmt="%(message)s", force=True)

    parser = argparse.ArgumentParser(description="Migrate Wiki directory structure")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    parser.add_argument(
        "--wiki-dir",
        type=Path,
        default=Path.home() / "llmwikify" / "wiki",
        help="Wiki directory path",
    )
    args = parser.parse_args()

    wiki_dir = args.wiki_dir.expanduser().resolve()
    if not wiki_dir.is_dir():
        logger.error("Wiki directory not found: %s", wiki_dir)
        return

    logger.info("Wiki directory: %s", wiki_dir)
    logger.info("Dry run: %s", args.dry_run)
    logger.info("---")

    # Run migrations
    n1 = migrate_factor_pages(wiki_dir, args.dry_run)
    n2 = migrate_factorbacktest(wiki_dir, args.dry_run)
    n3 = migrate_trading_to_strategy(wiki_dir, args.dry_run)
    ensure_directories(wiki_dir, args.dry_run)

    # Summary
    logger.info("---")
    logger.info("Migration complete:")
    logger.info("  factor pages moved: %d", n1)
    logger.info("  factorbacktest archived: %d", n2)
    logger.info("  trading pages moved: %d", n3)

    if not args.dry_run:
        logger.info("---")
        logger.info("Run 'git status wiki/' to verify the changes")


if __name__ == "__main__":
    main()
