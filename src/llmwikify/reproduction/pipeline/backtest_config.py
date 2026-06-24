"""Backtest configuration builder for QuantNodes PipelineRunner."""
from __future__ import annotations

import re
from pathlib import Path

# Date range for the long dataset (YYYYMMDD format for QN config)
LONG_DATE_BEG = 20200101
LONG_DATE_END = 20241231
PROJECT_ROOT = Path("/home/ll/llmwikify")


def build_qn_config(factor_name: str, h5_path: Path, expression: str) -> dict:
    """Build SingleFactorTestConfig-compatible dict for PipelineRunner.

    Schema (from QuantNodes/research/factor_test/config.py):
    - risk_corr.factors: str ('all' or comma-sep, NOT list)
    - output.format: list[str] (NOT str)
    - load_keys: list[str] (NOT None)
    """
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
            "adj_date_beg": LONG_DATE_BEG,
            "adj_date_end": LONG_DATE_END,
            "adj_mode": ["M", "end"],
            "sample_index": "all",
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
            "ic": {"min_group_size": 3},
            "group": {
                "groups": 5,
                "factor_direction": 1,
                "floor_mode": "group",
                "hedge": "equal",
                "hedge_path": None,
            },
            "longshort": {"factor_direction": 1},
            "score": {"enabled": False},
            "risk_corr": {"factors": "all"},
        },
        "output": {
            "dir": str(PROJECT_ROOT / "scripts" / "output" / "report"),
            "format": ["parquet", "json"],
        },
    }
