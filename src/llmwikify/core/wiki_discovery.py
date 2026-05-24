"""WikiDiscovery - scans directories for llmwikify wikis."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

CONFIG_FILENAME = ".wiki-config.yaml"


class WikiDiscovery:
    """Scans directories for llmwikify wikis.

    Looks for .wiki-config.yaml files in specified paths to discover
    wiki instances that can be registered in the WikiRegistry.
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

            config_files = self._find_config_files(root, depth, exclude_list)

            for config_file in config_files:
                wiki_root = config_file.parent
                try:
                    config = self._load_config(config_file)
                    wiki_id = self._extract_wiki_id(config, wiki_root)
                    found_wikis.append(
                        {
                            "root": wiki_root,
                            "config": config,
                            "wiki_id": wiki_id,
                        }
                    )
                    logger.info(f"Discovered wiki: {wiki_id} at {wiki_root}")
                except Exception as e:
                    logger.error(f"Failed to load config from {config_file}: {e}")

        return found_wikis

    def _find_config_files(
        self, root: Path, depth: int, exclude: list[str]
    ) -> list[Path]:
        """Recursively find .wiki-config.yaml files.

        Args:
            root: Starting directory
            depth: Maximum recursion depth
            exclude: Directory names to skip

        Returns:
            List of config file paths
        """
        config_files: list[Path] = []

        if depth < 0:
            return config_files

        try:
            for item in root.iterdir():
                if not item.is_dir():
                    continue

                # Skip excluded directories
                if item.name in exclude:
                    continue

                # Check for config file
                config_file = item / CONFIG_FILENAME
                if config_file.exists():
                    config_files.append(config_file)

                # Recurse into subdirectory
                config_files.extend(
                    self._find_config_files(item, depth - 1, exclude)
                )
        except PermissionError:
            logger.warning(f"Permission denied: {root}")
        except OSError as e:
            logger.error(f"Error scanning {root}: {e}")

        return config_files

    def _load_config(self, config_file: Path) -> dict[str, Any]:
        """Load and parse wiki config file.

        Args:
            config_file: Path to .wiki-config.yaml

        Returns:
            Parsed config dict
        """
        with open(config_file, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _extract_wiki_id(self, config: dict[str, Any], root: Path) -> str:
        """Generate wiki_id from config or directory name.

        Args:
            config: Wiki configuration dict
            root: Wiki root directory

        Returns:
            Wiki ID string
        """
        # Try to get ID from config
        if "wiki" in config and "id" in config["wiki"]:
            return config["wiki"]["id"]

        # Fall back to directory name
        return root.name
