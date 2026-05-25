"""WikiDiscovery - scans directories for llmwikify wikis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DB_FILENAME = ".llmwikify.db"


class WikiDiscovery:
    """Scans directories for llmwikify wikis.

    Looks for .llmwikify.db files in specified paths to discover
    wiki instances that can be registered in the WikiRegistry.

    A directory containing .llmwikify.db is considered a wiki root.
    Subdirectories of a wiki root are NOT scanned for additional wikis.
    """

    def __init__(self, exclude_patterns: list[str] | None = None):
        """Initialize WikiDiscovery.

        Args:
            exclude_patterns: Directory names to skip during scan
        """
        self.exclude_patterns = exclude_patterns or [
            "node_modules",
            ".git",
            "__pycache__",
            ".venv",
            "venv",
        ]

    def scan(
        self,
        scan_paths: list[str],
        depth: int = 2,
        exclude: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Scan paths for wiki roots.

        Args:
            scan_paths: List of directory paths to scan
            depth: Maximum recursion depth
            exclude: Additional patterns to exclude

        Returns:
            List of dicts with keys: root, config, wiki_id
        """
        exclude_list = (exclude or []) + self.exclude_patterns
        found_wikis: list[dict[str, Any]] = []

        for scan_path in scan_paths:
            root = Path(scan_path).expanduser().resolve()
            if not root.exists():
                logger.warning(f"Scan path does not exist: {root}")
                continue

            db_files = self._find_db_files(root, depth, exclude_list)

            for db_file in db_files:
                wiki_root = db_file.parent
                try:
                    wiki_id = wiki_root.name
                    found_wikis.append(
                        {
                            "root": wiki_root,
                            "config": {},
                            "wiki_id": wiki_id,
                        }
                    )
                    logger.info(f"Discovered wiki: {wiki_id} at {wiki_root}")
                except Exception as e:
                    logger.error(f"Failed to process wiki at {db_file}: {e}")

        return found_wikis

    def _find_db_files(
        self, root: Path, depth: int, exclude: list[str]
    ) -> list[Path]:
        """Recursively find .llmwikify.db files.

        Args:
            root: Starting directory
            depth: Maximum recursion depth
            exclude: Directory names to skip

        Returns:
            List of .llmwikify.db file paths
        """
        db_files: list[Path] = []

        if depth < 0:
            return db_files

        try:
            for item in root.iterdir():
                if not item.is_dir():
                    continue

                if item.name in exclude:
                    continue

                db_file = item / DB_FILENAME
                if db_file.exists():
                    db_files.append(db_file)
                    continue

                db_files.extend(
                    self._find_db_files(item, depth - 1, exclude)
                )
        except PermissionError:
            logger.warning(f"Permission denied: {root}")
        except OSError as e:
            logger.error(f"Error scanning {root}: {e}")

        return db_files
