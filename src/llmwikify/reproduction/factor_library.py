"""Factor Library — high-level API for 6-layer factor YAML management.

Provides read/write access to factor definitions stored as 6-layer
YAML files in quant/factors/. This is the canonical storage for
factor definitions (not wiki markdown).

Used by:
- factor.py (API endpoints for factor listing/detail)
- extract_factors.py (paper extraction → factor YAML generation)
- factor_backtest.py (reading factor definitions for backtest)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _get_factors_dir(project_root: Path | None = None) -> Path:
    """Get the quant/factors/ directory path."""
    root = project_root or Path.cwd()
    return root / "quant" / "factors"


def list_factors(project_root: Path | None = None) -> list[dict[str, Any]]:
    """Read quant/factors/index.yaml and return factor list.

    Returns:
        List of factor summary dicts from the index.
    """
    factors_dir = _get_factors_dir(project_root)
    index_path = factors_dir / "index.yaml"

    if not index_path.exists():
        return []

    try:
        content = index_path.read_text(encoding="utf-8")
        data = yaml.safe_load(content)
        return data.get("factors", []) if data else []
    except Exception as exc:
        logger.warning("could not read index.yaml: %s", exc)
        return []


def read_factor_yaml(name: str, project_root: Path | None = None) -> dict[str, Any] | None:
    """Read a single factor YAML file.

    Args:
        name: Factor path relative to factors/ (e.g., 'stock/price/momentum_20d')

    Returns:
        Full 6-layer factor dict, or None if not found.
    """
    factors_dir = _get_factors_dir(project_root)
    yaml_path = factors_dir / f"{name}.yaml"

    if not yaml_path.exists():
        return None

    try:
        content = yaml_path.read_text(encoding="utf-8")
        return yaml.safe_load(content)
    except Exception as exc:
        logger.warning("could not read factor YAML %s: %s", name, exc)
        return None


def write_factor_yaml(name: str, data: dict, project_root: Path | None = None) -> str:
    """Write a factor YAML file and update index.yaml.

    Args:
        name: Factor path relative to factors/
        data: Full factor dict (with 'factor' root key)

    Returns:
        "Created: factors/{name}.yaml" or "Updated: factors/{name}.yaml"
    """
    factors_dir = _get_factors_dir(project_root)
    yaml_path = factors_dir / f"{name}.yaml"
    is_new = not yaml_path.exists()

    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    yaml_path.write_text(content, encoding="utf-8")

    # Keep index.yaml in sync
    try:
        update_index(project_root)
    except Exception as exc:
        logger.warning("index.yaml update failed after writing %s: %s", name, exc)

    action = "Created" if is_new else "Updated"
    return f"{action}: factors/{name}.yaml"


def list_factors_by_category(project_root: Path | None = None) -> dict[str, list[dict]]:
    """List all factors grouped by category.

    Returns:
        Dict like {'price': [...], 'fundamental': [...], 'composite': [...]}
    """
    factors_dir = _get_factors_dir(project_root)
    if not factors_dir.exists():
        return {}

    categories: dict[str, list[dict]] = {}
    for yaml_file in sorted(factors_dir.rglob("*.yaml")):
        if yaml_file.name == "index.yaml":
            continue
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data and "factor" in data:
                factor = data["factor"]
                cat = factor.get("category", "unknown")
                rel = yaml_file.relative_to(factors_dir)
                factor["_name"] = str(rel.with_suffix(""))
                factor["_path"] = str(rel)
                categories.setdefault(cat, []).append(factor)
        except Exception as exc:
            logger.warning("could not read %s: %s", yaml_file, exc)
    return categories


def update_index(project_root: Path | None = None) -> None:
    """Regenerate quant/factors/index.yaml from actual YAML files.

    Scans all factor YAML files and rebuilds the index.
    """
    factors_dir = _get_factors_dir(project_root)
    if not factors_dir.exists():
        return

    factors = []
    stats = {
        "total": 0,
        "by_asset_type": {},
        "by_category": {},
        "by_status": {},
    }

    for yaml_file in sorted(factors_dir.rglob("*.yaml")):
        if yaml_file.name == "index.yaml":
            continue
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data and "factor" in data:
                factor = data["factor"]
                rel = yaml_file.relative_to(factors_dir)

                entry = {
                    "name": factor.get("name", ""),
                    "name_cn": factor.get("name_cn", ""),
                    "asset_type": factor.get("asset_type", ""),
                    "category": factor.get("category", ""),
                    "subcategory": factor.get("subcategory", ""),
                    "status": factor.get("status", "已注册"),
                    "definition": factor.get("l1", {}).get("definition", ""),
                    "file": str(rel),
                }
                factors.append(entry)

                # Update stats
                stats["total"] += 1
                at = factor.get("asset_type", "unknown")
                cat = factor.get("category", "unknown")
                st = factor.get("status", "已注册")
                stats["by_asset_type"][at] = stats["by_asset_type"].get(at, 0) + 1
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
                stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        except Exception as exc:
            logger.warning("could not read %s: %s", yaml_file, exc)

    index_data = {
        "factors": factors,
        "statistics": stats,
    }

    index_path = factors_dir / "index.yaml"
    content = yaml.dump(index_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
    index_path.write_text(content, encoding="utf-8")
    logger.info("index.yaml updated with %d factors", len(factors))
