"""Quant Wiki — lightweight storage for quant research.

Provides a simple read/write interface for the quant/ directory,
without the full Wiki engine overhead (no wiki.md schema, no
page type mapping, no sink, no full-text index).

Used by paper.py, factor.py, and strategy.py to store results
in quant/ instead of wiki/.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Singleton instance
_quant_wiki: QuantWiki | None = None


class QuantWiki:
    """Lightweight storage for quant research directory.

    Directory structure:
        quant/
        ├── papers/           ← paper extraction results (markdown)
        ├── factors/          ← factor definitions (6-layer YAML)
        ├── factorbacktest/   ← backtest results (markdown)
        ├── strategies/       ← strategy definitions (markdown)
        ├── datacache/        ← OHLCV cache (Parquet)
        └── factor.duckdb     ← factor value matrix
    """

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.papers_dir = self.root / "papers"
        self.factors_dir = self.root / "factors"
        self.factorbacktest_dir = self.root / "factorbacktest"
        self.strategies_dir = self.root / "strategies"
        self.datacache_dir = self.root / "datacache"
        self.duckdb_path = self.root / "factor.duckdb"

    def ensure_dirs(self) -> None:
        """Create all subdirectories if they don't exist."""
        for d in [self.papers_dir, self.factors_dir, self.factorbacktest_dir,
                   self.strategies_dir, self.datacache_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # === Page read/write (markdown with frontmatter) ===

    def read_page(self, name: str, page_type: str = "papers") -> dict[str, Any] | None:
        """Read a markdown page with frontmatter.

        Args:
            name: Page name (without .md extension)
            page_type: One of 'papers', 'factorbacktest', 'strategies'

        Returns:
            Dict with 'frontmatter' and 'content' keys, or None if not found.
        """
        dir_map = {
            "papers": self.papers_dir,
            "factorbacktest": self.factorbacktest_dir,
            "strategies": self.strategies_dir,
        }
        base_dir = dir_map.get(page_type)
        if base_dir is None:
            raise ValueError(f"Unknown page_type: {page_type}")

        md_path = base_dir / f"{name}.md"
        if not md_path.exists():
            return None

        content = md_path.read_text(encoding="utf-8")
        return self._parse_frontmatter(content)

    def write_page(self, name: str, content: str, page_type: str = "papers") -> str:
        """Write a markdown page.

        Args:
            name: Page name (without .md extension)
            content: Full markdown content (with optional frontmatter)
            page_type: One of 'papers', 'factorbacktest', 'strategies'

        Returns:
            "Created: {page_type}/{name}.md" or "Updated: {page_type}/{name}.md"
        """
        dir_map = {
            "papers": self.papers_dir,
            "factorbacktest": self.factorbacktest_dir,
            "strategies": self.strategies_dir,
        }
        base_dir = dir_map.get(page_type)
        if base_dir is None:
            raise ValueError(f"Unknown page_type: {page_type}")

        base_dir.mkdir(parents=True, exist_ok=True)
        md_path = base_dir / f"{name}.md"
        is_new = not md_path.exists()

        md_path.write_text(content, encoding="utf-8")
        action = "Created" if is_new else "Updated"
        return f"{action}: {page_type}/{name}.md"

    def list_pages(self, page_type: str = "papers") -> list[dict[str, Any]]:
        """List all pages of a given type.

        Returns:
            List of parsed frontmatter dicts with '_slug' key added.
        """
        dir_map = {
            "papers": self.papers_dir,
            "factorbacktest": self.factorbacktest_dir,
            "strategies": self.strategies_dir,
        }
        base_dir = dir_map.get(page_type)
        if base_dir is None:
            raise ValueError(f"Unknown page_type: {page_type}")

        if not base_dir.exists():
            return []

        results = []
        for md in sorted(base_dir.glob("*.md")):
            try:
                content = md.read_text(encoding="utf-8")
                fm = self._parse_frontmatter(content)
                if fm:
                    fm["_slug"] = md.stem
                    results.append(fm)
            except Exception as exc:
                logger.warning("could not read %s: %s", md, exc)
        return results

    # === Factor YAML read/write ===

    def read_factor_yaml(self, name: str) -> dict[str, Any] | None:
        """Read a factor YAML file from quant/factors/.

        Args:
            name: Factor path relative to factors/ (e.g., 'stock/price/momentum_20d')

        Returns:
            Parsed YAML dict, or None if not found.
        """
        yaml_path = self.factors_dir / f"{name}.yaml"
        if not yaml_path.exists():
            return None

        content = yaml_path.read_text(encoding="utf-8")
        return yaml.safe_load(content)

    def write_factor_yaml(self, name: str, data: dict) -> str:
        """Write a factor YAML file to quant/factors/.

        Args:
            name: Factor path relative to factors/
            data: Factor data dict to serialize

        Returns:
            "Created: factors/{name}.yaml" or "Updated: factors/{name}.yaml"
        """
        yaml_path = self.factors_dir / f"{name}.yaml"
        is_new = not yaml_path.exists()

        yaml_path.parent.mkdir(parents=True, exist_ok=True)
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        yaml_path.write_text(content, encoding="utf-8")

        action = "Created" if is_new else "Updated"
        return f"{action}: factors/{name}.yaml"

    def list_factor_yamls(self) -> list[dict[str, Any]]:
        """List all factor YAML files in quant/factors/.

        Returns:
            List of parsed YAML dicts with '_name' key added.
        """
        if not self.factors_dir.exists():
            return []

        results = []
        for yaml_file in sorted(self.factors_dir.rglob("*.yaml")):
            if yaml_file.name == "index.yaml":
                continue
            try:
                content = yaml_file.read_text(encoding="utf-8")
                data = yaml.safe_load(content)
                if data and "factor" in data:
                    # Compute relative path from factors/
                    rel = yaml_file.relative_to(self.factors_dir)
                    factor_data = data["factor"]
                    factor_data["_name"] = str(rel.with_suffix(""))
                    factor_data["_path"] = str(rel)
                    results.append(factor_data)
            except Exception as exc:
                logger.warning("could not read %s: %s", yaml_file, exc)
        return results

    # === Helpers ===

    @staticmethod
    def _parse_frontmatter(content: str) -> dict[str, Any]:
        """Parse YAML frontmatter from markdown content."""
        if not content.startswith("---"):
            return {"content": content}

        try:
            end = content.index("---", 3)
            fm_text = content[3:end].strip()
            body = content[end + 3:].strip()
            frontmatter = yaml.safe_load(fm_text) or {}
            frontmatter["content"] = body
            return frontmatter
        except (ValueError, yaml.YAMLError):
            return {"content": content}


def get_quant_root(project_root: Path | None = None) -> Path:
    """Get the quant/ directory path.

    Args:
        project_root: Project root directory. If None, uses cwd.
    """
    root = project_root or Path.cwd()
    return root / "quant"


def get_quant_wiki(project_root: Path | None = None) -> QuantWiki:
    """Get or create the QuantWiki singleton.

    Args:
        project_root: Project root directory. If None, uses cwd.
    """
    global _quant_wiki
    if _quant_wiki is None:
        quant_root = get_quant_root(project_root)
        _quant_wiki = QuantWiki(quant_root)
    return _quant_wiki
