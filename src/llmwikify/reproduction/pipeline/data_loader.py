"""Data loader utilities: wide/long conversion, H5 I/O, input column derivation."""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import polars as pl


def wide_from_long(df_pl: pl.DataFrame, factor_series: pl.Series) -> pd.DataFrame:
    """Convert long (date, code, value) -> wide [date x code] for QuantNodes H5.

    Forces (code, date) sort to match LLM code ordering so pivot input is always
    aligned with factor_series.
    """
    assert len(df_pl) == len(factor_series), f"length mismatch: {len(df_pl)} vs {len(factor_series)}"
    df_sorted = df_pl.sort(["code", "date"])
    df_with = df_sorted.with_columns(factor_series.alias("__factor__"))
    pdf = df_with.select(["date", "code", "__factor__"]).to_pandas()
    wide = pdf.pivot(index="date", columns="code", values="__factor__")
    return wide


def write_factor_h5(wide: pd.DataFrame, factor_name: str, output_dir: Path) -> Path:
    """Write wide DataFrame to QuantNodes-compatible H5 file.

    Output file must live INSIDE data_path (PipelineRunner joins factor_dir with data_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    h5_path = output_dir / f"factor_{factor_name}.h5"
    safe_key = re.sub(r"[^A-Za-z0-9_]", "_", factor_name)
    with pd.HDFStore(h5_path, mode="w") as store:
        store.put(safe_key, wide)
    return h5_path


def derive_input_columns(formula_brief: str) -> list[str]:
    """Extract input column names from formula_brief text.

    Matches 101 alpha paper's common column tokens.
    """
    candidates = [
        "open", "high", "low", "close", "volume", "adv20", "adv30", "adv40",
        "adv50", "adv60", "adv81", "adv120", "adv150", "vwap", "returns",
        "cap", "industry",
    ]
    text = formula_brief.lower()
    found = [c for c in candidates if c in text]
    if any(t in text for t in ["close", "open", "high", "low", "vwap", "returns"]):
        for base in ["close", "open", "high", "low", "volume", "returns"]:
            if base not in found:
                found.append(base)
    return found[:10]
