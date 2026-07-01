"""Backtest configuration builder for QuantNodes PipelineRunner."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Date range for the long dataset (YYYYMMDD format for QN config)
LONG_DATE_BEG = 20200101
LONG_DATE_END = 20241231
PROJECT_ROOT = Path("/home/ll/llmwikify")


def build_qn_config(
    factor_name: str,
    h5_path: Path,
    expression: str,
    config: Any = None,
) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner.

    If config is provided, reads date ranges, groups, hedge, etc. from it.
    Otherwise uses hardcoded defaults.

    Schema (from QuantNodes/research/factor_test/config.py):
    - risk_corr.factors: str ('all' or comma-sep, NOT list)
    - output.format: list[str] (NOT str)
    - load_keys: list[str] (NOT None)
    """
    # Defaults
    adj_date_beg = LONG_DATE_BEG
    adj_date_end = LONG_DATE_END
    sample_index = "all"
    groups = 5
    factor_direction = 1
    hedge = "equal"
    min_group_size = 3
    adj_mode = ["M", "end"]
    output_format = ["parquet", "json"]
    output_dir = str(PROJECT_ROOT / "scripts" / "output" / "report")

    # Apply config overrides
    if config is not None:
        adj_date_beg = getattr(config, "date_beg", adj_date_beg)
        adj_date_end = getattr(config, "date_end", adj_date_end)
        sample_index = getattr(config, "sample_index", sample_index)
        groups = getattr(config, "groups", groups)
        factor_direction = getattr(config, "factor_direction", factor_direction)
        hedge = getattr(config, "hedge", hedge)
        min_group_size = getattr(config, "min_group_size", min_group_size)
        output_format = getattr(config, "output_format", output_format)
        raw_adj_mode = getattr(config, "adj_mode", "M-end")
        if isinstance(raw_adj_mode, str) and "-" in raw_adj_mode:
            adj_mode = raw_adj_mode.split("-")
        elif isinstance(raw_adj_mode, list):
            adj_mode = raw_adj_mode
        report_dir = getattr(config, "report_dir", None)
        if report_dir is not None:
            output_dir = str(report_dir)

    safe_name = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    return {
        "factor": {
            "name": safe_name,
            "factor_dir": h5_path.name,
            "factor_key": safe_name,
            "format": "h5",
            "hypothesis": "Test LLM-generated code via PipelineRunner",
            "description": "alpha-001 via LLM code path",
            "expression": expression[:500],
        },
        "data_path": str(h5_path.parent),
        "load_keys": [
            "stklist", "trade_dt", "cp", "id_citic1", "mv_float",
            "st", "suspend", "ud_limit", "ipo_days",
        ],
        "preprocess": {
            "adj_date_beg": adj_date_beg,
            "adj_date_end": adj_date_end,
            "adj_mode": adj_mode,
            "sample_index": sample_index,
            "sample_industry": "all",
            "tradable": {
                "no_st": True,
                "no_suspended": True,
                "no_up_down_limit": False,
                "min_ipo_days": 60,
            },
            "missing": "",
            "extreme": "",
            "norm": "",
            "industry_neutral": False,
            "risk_neutral": False,
            "risk_factors": [],
            "mad_n": 5.0,
            "pct_low": 0.025,
            "pct_high": 0.975,
        },
        "analysis": {
            "ic": {"min_group_size": min_group_size},
            "group": {
                "groups": groups,
                "factor_direction": factor_direction,
                "floor_mode": "group",
                "hedge": hedge,
                "hedge_path": None,
            },
            "longshort": {"factor_direction": factor_direction},
            "score": {"enabled": False},
            "risk_corr": {"factors": "all"},
        },
        "output": {
            "dir": output_dir,
            "format": output_format,
        },
    }
