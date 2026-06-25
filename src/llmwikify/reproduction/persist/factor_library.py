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
import time
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

    Supports two formats:
    1. New directory format: factors/{name}/factor.yaml
    2. Old single-file format: factors/{name}.yaml

    Args:
        name: Factor path relative to factors/ (e.g., '101_alphas/stk_alpha_001_f9f371')

    Returns:
        Full 6-layer factor dict, or None if not found.
    """
    factors_dir = _get_factors_dir(project_root)

    # Try new directory format first
    dir_path = factors_dir / name
    yaml_path = dir_path / "factor.yaml"
    if yaml_path.exists():
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            # Load code.py if exists
            code_path = dir_path / "code.py"
            if code_path.exists():
                data["code"] = code_path.read_text(encoding="utf-8")
            # Load backtest/latest.json if exists
            backtest_path = dir_path / "backtest" / "latest.json"
            if backtest_path.exists():
                import json
                data["backtest"] = json.loads(backtest_path.read_text(encoding="utf-8"))
            # Load meta.json if exists
            meta_path = dir_path / "meta.json"
            if meta_path.exists():
                import json
                data["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
            return data
        except Exception as exc:
            logger.warning("could not read factor YAML %s: %s", name, exc)
            return None

    # Fall back to old single-file format
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

    Supports two formats:
    1. New directory format: factors/{name}/factor.yaml
    2. Old single-file format: factors/{name}.yaml

    Args:
        name: Factor path relative to factors/
        data: Full factor dict (with 'factor' root key)

    Returns:
        "Created: factors/{name}" or "Updated: factors/{name}"
    """
    factors_dir = _get_factors_dir(project_root)

    # Check if it's a directory format
    dir_path = factors_dir / name
    if dir_path.is_dir():
        # New directory format
        yaml_path = dir_path / "factor.yaml"
        is_new = not yaml_path.exists()

        # Write factor.yaml
        content = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        yaml_path.write_text(content, encoding="utf-8")

        # Write code.py if code is in data
        if "code" in data:
            code_path = dir_path / "code.py"
            code_path.write_text(data["code"], encoding="utf-8")

        # Write meta.json if meta is in data
        if "meta" in data:
            import json
            meta_path = dir_path / "meta.json"
            meta_path.write_text(json.dumps(data["meta"], indent=2, ensure_ascii=False), encoding="utf-8")

        # Write backtest/latest.json if backtest is in data
        if "backtest" in data:
            import json
            backtest_dir = dir_path / "backtest"
            backtest_dir.mkdir(exist_ok=True)
            backtest_path = backtest_dir / "latest.json"
            backtest_path.write_text(json.dumps(data["backtest"], indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        # Old single-file format
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
    return f"{action}: factors/{name}"


def list_factors_by_category(project_root: Path | None = None) -> dict[str, list[dict]]:
    """List all factors grouped by category.

    Returns:
        Dict like {'alpha': [...], 'momentum': [...], 'value': [...]}
    """
    factors_dir = _get_factors_dir(project_root)
    if not factors_dir.exists():
        return {}

    categories: dict[str, list[dict]] = {}

    # Scan for new directory format (factor.yaml inside directories)
    for yaml_file in sorted(factors_dir.rglob("*/factor.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data:
                factor = data.get("factor", data)
                cat = factor.get("category", "unknown")
                # Get relative path without factor.yaml
                rel = yaml_file.parent.relative_to(factors_dir)
                factor["_name"] = str(rel)
                factor["_path"] = str(rel / "factor.yaml")
                categories.setdefault(cat, []).append(factor)
        except Exception as exc:
            logger.warning("could not read %s: %s", yaml_file, exc)

    # Scan for old single-file format (for backward compatibility)
    for yaml_file in sorted(factors_dir.rglob("*.yaml")):
        if yaml_file.name in ("index.yaml", "_meta.yaml", "config.yaml"):
            continue
        if yaml_file.name.startswith("test_"):
            continue
        if yaml_file.parent.name == "backtest":
            continue
        # Skip new-format sibling: factors/{name}/factor.yaml is already handled above
        if (yaml_file.parent / "factor.yaml").exists():
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

    # Scan for new directory format (factor.yaml inside directories)
    for yaml_file in sorted(factors_dir.rglob("*/factor.yaml")):
        try:
            content = yaml_file.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if data:
                factor = data.get("factor", data)
                rel = yaml_file.parent.relative_to(factors_dir)

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
                at = entry["asset_type"] or "unknown"
                stats["by_asset_type"][at] = stats["by_asset_type"].get(at, 0) + 1
                cat = entry["category"] or "unknown"
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
                st = entry["status"] or "unknown"
                stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        except Exception as exc:
            logger.warning("could not read %s: %s", yaml_file, exc)

    # Scan for old single-file format (for backward compatibility)
    for yaml_file in sorted(factors_dir.rglob("*.yaml")):
        if yaml_file.name in ("index.yaml", "_meta.yaml", "config.yaml"):
            continue
        if yaml_file.name.startswith("test_"):
            continue
        if yaml_file.parent.name == "backtest":
            continue
        # Skip new-format sibling: factors/{name}/factor.yaml is already handled above
        if (yaml_file.parent / "factor.yaml").exists():
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
                at = entry["asset_type"] or "unknown"
                stats["by_asset_type"][at] = stats["by_asset_type"].get(at, 0) + 1
                cat = entry["category"] or "unknown"
                stats["by_category"][cat] = stats["by_category"].get(cat, 0) + 1
                st = entry["status"] or "unknown"
                stats["by_status"][st] = stats["by_status"].get(st, 0) + 1
        except Exception as exc:
            logger.warning("could not read %s: %s", yaml_file, exc)

    index = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "statistics": stats,
        "factors": factors,
    }

    index_path = factors_dir / "index.yaml"
    content = yaml.dump(index, default_flow_style=False, allow_unicode=True, sort_keys=False)
    index_path.write_text(content, encoding="utf-8")
    logger.info("index.yaml updated with %d factors", len(factors))
