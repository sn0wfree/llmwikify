"""Factor fix utilities: detect binary/constant factors and add noise."""
from __future__ import annotations

import numpy as np
import polars as pl


def detect_binary(series: pl.Series) -> bool:
    """Return True if series has <= 2 unique non-null values (binary/constant)."""
    unique_vals = series.drop_nulls().unique()
    return len(unique_vals) <= 2


def add_noise(series: pl.Series) -> pl.Series:
    """Add small random noise to a binary/constant series to enable IC calculation."""
    noise = pl.Series("__noise", np.random.uniform(-1e-7, 1e-7, len(series)))
    return series.cast(pl.Float64) + noise
