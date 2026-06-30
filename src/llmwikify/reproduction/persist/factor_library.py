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


def _get_factors_dir(project_root: Path | None = None, factors_dir: Path | None = None) -> Path:
    """Get the quant/factors/ directory path.

    Priority: factors_dir > project_root/quant/factors > Path.cwd()/quant/factors
    """
    if factors_dir is not None:
        return Path(factors_dir)
    root = project_root or Path.cwd()
    return root / "quant" / "factors"


def list_factors(project_root: Path | None = None, factors_dir: Path | None = None) -> list[dict[str, Any]]:
    """Read quant/factors/index.yaml and return factor list.

    Returns:
        List of factor summary dicts from the index.
    """
    factors_dir = _get_factors_dir(project_root, factors_dir)
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


def read_factor_yaml(name: str, project_root: Path | None = None, factors_dir: Path | None = None) -> dict[str, Any] | None:
    """Read a single factor YAML file.

    Supports two formats:
    1. New directory format: factors/{name}/factor.yaml
    2. Old single-file format: factors/{name}.yaml

    Args:
        name: Factor path relative to factors/ (e.g., '101_alphas/stk_alpha_001_f9f371')

    Returns:
        Full 6-layer factor dict, or None if not found.
    """
    factors_dir = _get_factors_dir(project_root, factors_dir)

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


def write_factor_yaml(name: str, data: dict, project_root: Path | None = None, factors_dir: Path | None = None) -> str:
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
    factors_dir = _get_factors_dir(project_root, factors_dir)

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
        update_index(project_root, factors_dir)
    except Exception as exc:
        logger.warning("index.yaml update failed after writing %s: %s", name, exc)

    action = "Created" if is_new else "Updated"
    return f"{action}: factors/{name}"


def list_factors_by_category(project_root: Path | None = None, factors_dir: Path | None = None) -> dict[str, list[dict]]:
    """List all factors grouped by category.

    Returns:
        Dict like {'alpha': [...], 'momentum': [...], 'value': [...]}
    """
    factors_dir = _get_factors_dir(project_root, factors_dir)
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


def update_index(project_root: Path | None = None, factors_dir: Path | None = None) -> None:
    """Regenerate quant/factors/index.yaml from actual YAML files.

    Scans all factor YAML files and rebuilds the index.
    """
    factors_dir = _get_factors_dir(project_root, factors_dir)
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


# ─── DuckDB backtest storage ────────────────────────────────────────


def _resolve_factor_dir(name: str, project_root: Path | None = None, factors_dir: Path | None = None) -> Path:
    """Resolve factor directory path from name.

    Supports:
    1. Exact match: factors/{name}/factor.yaml exists
    2. Fuzzy match: name is 'alpha_001', dir is '101_alphas/stk_alpha_001_xxx'
    3. Fallback: create factors/{name}/ directory
    """
    factors_dir = _get_factors_dir(project_root, factors_dir)

    # Exact match
    exact = factors_dir / name
    if exact.is_dir():
        return exact

    # Fuzzy match: search for *{name}* in subdirectories
    for subdir in factors_dir.iterdir():
        if not subdir.is_dir():
            continue
        for child in subdir.iterdir():
            if not child.is_dir():
                continue
            if name in child.name:
                return child

    # Fallback: create directory
    exact.mkdir(parents=True, exist_ok=True)
    return exact


def save_backtest_duckdb(
    factor_name: str,
    run_id: str,
    backtest: dict,
    factor_wide: Any | None = None,
    project_root: Path | None = None,
    factors_dir: Path | None = None,
) -> Path:
    """Write backtest + factor_values to factor's factor.duckdb.

    Args:
        factor_name: slug or full path (e.g. "alpha_001" or "101_alphas/stk_alpha_001_f9f371")
        run_id: unique run identifier
        backtest: dict with ic_series, equity_curve, scalar metrics
        factor_wide: optional pandas DataFrame [date x code] of factor values
        factors_dir: explicit path to factors directory (takes priority over project_root)

    Returns:
        Path to the DuckDB file.
    """
    import math

    import duckdb

    dir_path = _resolve_factor_dir(factor_name, project_root, factors_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    db_path = dir_path / "factor.duckdb"

    def _nan(v: Any) -> float | None:
        if v is None:
            return None
        try:
            f = float(v)
            return None if math.isnan(f) else f
        except (TypeError, ValueError):
            return None

    conn = duckdb.connect(str(db_path))
    try:
        # Create tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                run_id VARCHAR PRIMARY KEY,
                created_at TIMESTAMP,
                status VARCHAR,
                ic_mean DOUBLE,
                rank_ic_mean DOUBLE,
                icir DOUBLE,
                rank_icir DOUBLE,
                win_rate DOUBLE,
                annual_return DOUBLE,
                longshort_sharpe DOUBLE,
                longshort_max_dd DOUBLE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ic_series (
                run_id VARCHAR,
                date BIGINT,
                ic DOUBLE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS equity_curve (
                run_id VARCHAR,
                group_name VARCHAR,
                date BIGINT,
                nav DOUBLE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS group_metrics (
                run_id VARCHAR,
                group_name VARCHAR,
                annual_return DOUBLE,
                sharpe DOUBLE,
                max_drawdown DOUBLE,
                win_rate DOUBLE,
                turnover DOUBLE,
                n_stocks INTEGER,
                PRIMARY KEY (run_id, group_name)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS factor_values (
                date DATE,
                stock VARCHAR,
                value DOUBLE
            )
        """)

        # Upsert backtest_runs
        conn.execute("""
            INSERT OR REPLACE INTO backtest_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            run_id,
            backtest.get("created_at") or __import__("datetime").datetime.now().isoformat(),
            backtest.get("status", "success"),
            _nan(backtest.get("ic_mean")),
            _nan(backtest.get("rank_ic_mean")),
            _nan(backtest.get("icir")),
            _nan(backtest.get("rank_icir")),
            _nan(backtest.get("win_rate")),
            _nan(backtest.get("longshort_ann_return")),
            _nan(backtest.get("longshort_sharpe")),
            _nan(backtest.get("longshort_max_dd")),
        ])

        # Insert ic_series (bulk)
        ic_rows = [
            [run_id, pt.get("date"), _nan(pt.get("ic"))]
            for pt in backtest.get("ic_series", [])
        ]
        if ic_rows:
            import pandas as pd
            ic_df = pd.DataFrame(ic_rows, columns=["run_id", "date", "ic"])
            conn.register("_ic_df", ic_df)
            conn.execute("INSERT INTO ic_series SELECT * FROM _ic_df")
            conn.unregister("_ic_df")

        # Insert equity_curve (bulk)
        equity = backtest.get("equity_curve") or backtest.get("group_nav_series") or {}
        eq_rows = [
            [run_id, gn, pt.get("date"), _nan(pt.get("nav"))]
            for gn, points in equity.items()
            for pt in points
        ]
        if eq_rows:
            import pandas as pd
            eq_df = pd.DataFrame(eq_rows, columns=["run_id", "group_name", "date", "nav"])
            conn.register("_eq_df", eq_df)
            conn.execute("INSERT INTO equity_curve SELECT * FROM _eq_df")
            conn.unregister("_eq_df")

        # Insert group_metrics (bulk)
        gm = backtest.get("group_metrics") or {}
        gm_rows = [
            [run_id, gn, _nan(v.get("annual_return")), _nan(v.get("sharpe")),
             _nan(v.get("max_drawdown")), _nan(v.get("win_rate")),
             _nan(v.get("turnover")), v.get("n_stocks", 0)]
            for gn, v in gm.items()
        ]
        if gm_rows:
            import pandas as pd
            gm_df = pd.DataFrame(gm_rows, columns=[
                "run_id", "group_name", "annual_return", "sharpe",
                "max_drawdown", "win_rate", "turnover", "n_stocks",
            ])
            conn.register("_gm_df", gm_df)
            conn.execute("INSERT OR REPLACE INTO group_metrics SELECT * FROM _gm_df")
            conn.unregister("_gm_df")

        # Insert factor_values (bulk from wide DataFrame)
        if factor_wide is not None and hasattr(factor_wide, "reset_index"):
            import pandas as pd
            factor_wide.index.name = "date"
            melted = factor_wide.reset_index().melt(
                id_vars=["date"], var_name="stock", value_name="value",
            )
            melted = melted.dropna(subset=["value"])
            if not melted.empty:
                melted["date"] = pd.to_datetime(melted["date"])
                melted["stock"] = melted["stock"].astype(str)
                melted["value"] = melted["value"].astype(float)
                fv_df = melted[["date", "stock", "value"]].reset_index(drop=True)
                # Clear old values and insert new (bulk)
                conn.execute("DELETE FROM factor_values")
                conn.register("_fv_df", fv_df)
                conn.execute("INSERT INTO factor_values SELECT * FROM _fv_df")
                conn.unregister("_fv_df")

        logger.info("saved backtest to %s (run_id=%s)", db_path, run_id)
    finally:
        conn.close()

    return db_path


def read_backtest_duckdb(
    factor_name: str,
    limit: int = 10,
    include_values: bool = False,
    project_root: Path | None = None,
    factors_dir: Path | None = None,
) -> list[dict]:
    """Read backtest runs from factor's DuckDB.

    Args:
        factor_name: slug or full path
        limit: max number of runs to return
        include_values: if True, include factor_values in each run
        factors_dir: explicit path to factors directory (takes priority over project_root)

    Returns:
        List of run dicts with metrics + ic_series + equity_curve.
    """
    import duckdb

    dir_path = _resolve_factor_dir(factor_name, project_root, factors_dir)
    db_path = dir_path / "factor.duckdb"
    if not db_path.exists():
        return []

    conn = duckdb.connect(str(db_path), read_only=True)
    try:
        # Check tables exist
        tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
        if "backtest_runs" not in tables:
            return []

        runs_df = conn.execute(
            "SELECT * FROM backtest_runs ORDER BY created_at DESC LIMIT ?", [limit]
        ).fetchdf()

        results = []
        for _, row in runs_df.iterrows():
            rid = row["run_id"]

            # IC series
            ic_data = []
            if "ic_series" in tables:
                ic_df = conn.execute(
                    "SELECT date, ic FROM ic_series WHERE run_id = ? ORDER BY date", [rid]
                ).fetchdf()
                ic_data = ic_df.to_dict("records")

            # Equity curve
            equity: dict[str, list] = {}
            if "equity_curve" in tables:
                eq_df = conn.execute(
                    "SELECT group_name, date, nav FROM equity_curve WHERE run_id = ? ORDER BY group_name, date",
                    [rid],
                ).fetchdf()
                for gn, grp in eq_df.groupby("group_name"):
                    equity[gn] = grp[["date", "nav"]].to_dict("records")

            # Group metrics
            group_metrics: dict[str, dict] = {}
            if "group_metrics" in tables:
                gm_df = conn.execute(
                    "SELECT group_name, annual_return, sharpe, max_drawdown, win_rate, turnover, n_stocks "
                    "FROM group_metrics WHERE run_id = ?",
                    [rid],
                ).fetchdf()
                for _, gm_row in gm_df.iterrows():
                    group_metrics[gm_row["group_name"]] = {
                        "annual_return": gm_row.get("annual_return"),
                        "sharpe": gm_row.get("sharpe"),
                        "max_drawdown": gm_row.get("max_drawdown"),
                        "win_rate": gm_row.get("win_rate"),
                        "turnover": gm_row.get("turnover"),
                        "n_stocks": int(gm_row.get("n_stocks") or 0),
                    }

            run: dict[str, Any] = {
                "run_id": rid,
                "created_at": str(row.get("created_at", "")),
                "status": row.get("status", ""),
                "metrics": {
                    "ic_mean": row.get("ic_mean"),
                    "rank_ic_mean": row.get("rank_ic_mean"),
                    "icir": row.get("icir"),
                    "rank_icir": row.get("rank_icir"),
                    "win_rate": row.get("win_rate"),
                    "annual_return": row.get("annual_return"),
                    "longshort_sharpe": row.get("longshort_sharpe"),
                    "longshort_max_dd": row.get("longshort_max_dd"),
                },
                "ic_series": ic_data,
                "equity_curve": equity,
                "group_metrics": group_metrics,
            }

            if include_values and "factor_values" in tables:
                fv_df = conn.execute(
                    "SELECT date, stock, value FROM factor_values"
                ).fetchdf()
                run["factor_values"] = fv_df.to_dict("records")

            results.append(run)

        return results
    finally:
        conn.close()
