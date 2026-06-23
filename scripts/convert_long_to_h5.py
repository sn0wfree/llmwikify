"""Convert HS300 long-format CSV → QuantNodes-compatible wide-format H5.

Input:  /home/ll/.llmwikify/akshare_cache/quantnodes/HS300_2020-01-01_2024-12-31.csv
        (long: date × code with columns code, open, high, low, close, volume, returns, vwap)

Output: /home/ll/.llmwikify/akshare_cache/quantnodes_h5_long/
        - stk_daily.h5 (keys: cp, open, high, low, close, volume, returns, vwap, stklist, trade_dt, st, suspend, ipo_days, ud_limit)
        - index_daily.h5 (placeholder)
        - *_constituents.csv (optional)
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

SRC_CSV = Path("/home/ll/.llmwikify/akshare_cache/quantnodes/HS300_2020-01-01_2024-12-31.csv")
SRC_CONSTITUENTS = Path("/home/ll/.llmwikify/akshare_cache/hs300_constituents.json")
DST_DIR = Path("/home/ll/.llmwikify/akshare_cache/quantnodes_h5_long")
DST_DIR.mkdir(parents=True, exist_ok=True)

print(f"[1/4] Reading CSV: {SRC_CSV}")
df = pd.read_csv(SRC_CSV, index_col=0, parse_dates=True)
df = df.sort_index()
print(f"  Loaded: {df.shape}, dates: {df.index.min()} - {df.index.max()}, codes: {df['code'].nunique()}")

print(f"[2/4] Pivoting to wide (date × code)...")
WIDE_KEYS = {
    "close": "close",
    "open": "open",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "returns": "returns",
    "vwap": "vwap",
}
panels: dict[str, pd.DataFrame] = {}
for col, h5_key in WIDE_KEYS.items():
    panel = df.pivot_table(index=df.index, columns="code", values=col, aggfunc="first")
    panel = panel.sort_index()
    panels[h5_key] = panel
    print(f"  {h5_key}: shape={panel.shape}, NaN={panel.isna().sum().sum()}")

# trade_dt (date axis) — must be int64 yyyymmdd per QuantNodes valid_date()
date_idx = panels["close"].index
yyyymmdd = date_idx.strftime("%Y%m%d").astype(np.int64)
trade_dt = pd.DataFrame({"trade_dt": yyyymmdd.values}, index=yyyymmdd.values)
print(f"  trade_dt: shape={trade_dt.shape}, dtype={trade_dt.dtypes.iloc[0]}, "
      f"range=[{trade_dt.iloc[0,0]}, {trade_dt.iloc[-1,0]}]")

# stklist (code axis)
stklist = pd.DataFrame({"stk_code": panels["close"].columns})
stklist.index = stklist["stk_code"]
print(f"  stklist: shape={stklist.shape}")

print(f"[3/4] Generating synthetic metadata...")
n_dates, n_stocks = panels["close"].shape
# All index axes MUST use int64 yyyymmdd for QuantNodes valid_date() check.
# Use the same yyyymmdd index as panels_int_idx to keep alignment.
rng = np.random.default_rng(seed=42)

# ipo_days: large numbers (assume all stocks existed before 2020)
ipo_days = pd.DataFrame(
    np.full(n_stocks, 5000, dtype=np.int64),
    index=stklist["stk_code"],
    columns=["ipo_days"],
)
# Add some randomization
ipo_days["ipo_days"] = rng.integers(1000, 8000, size=n_stocks)

# st: very rare (0 = normal, 1 = ST)
st = pd.DataFrame(
    rng.choice([0, 1], size=(n_dates, n_stocks), p=[0.999, 0.001]),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
).astype(np.int8)

# suspend: rare
suspend = pd.DataFrame(
    rng.choice([0, 1], size=(n_dates, n_stocks), p=[0.99, 0.01]),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
).astype(np.int8)

# ud_limit: 0 = normal
ud_limit = pd.DataFrame(
    rng.choice([0, 1], size=(n_dates, n_stocks), p=[0.97, 0.03]),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
).astype(np.int8)

# mv_float: synthetic float market value in 亿元 (1e8 RMB)
mv_float = pd.DataFrame(
    rng.uniform(10, 1000, size=(n_dates, n_stocks)),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
)

# id_citic1: synthetic industry code (1-29)
id_citic1 = pd.DataFrame(
    rng.integers(1, 30, size=(n_dates, n_stocks)),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
).astype(np.int32)

# amount: synthetic total turnover (RMB)
amount = pd.DataFrame(
    rng.uniform(1e6, 1e9, size=(n_dates, n_stocks)),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
)

# id_300: synthetic HS300 membership (1 if in HS300)
id_300 = pd.DataFrame(
    np.ones((n_dates, n_stocks), dtype=np.int8),
    index=yyyymmdd.values,
    columns=stklist["stk_code"],
)

print(f"[4/4] Writing H5 to {DST_DIR}...")
h5_path = DST_DIR / "stk_daily.h5"
if h5_path.exists():
    h5_path.unlink()

# Build panels with int64 yyyymmdd index (QuantNodes valid_date requirement)
panels_int_idx: dict[str, pd.DataFrame] = {}
for h5_key, panel in panels.items():
    panels_int_idx[h5_key] = panel.copy()
    panels_int_idx[h5_key].index = yyyymmdd.values

with pd.HDFStore(h5_path, mode="w") as store:
    for h5_key, panel in panels_int_idx.items():
        # QuantNodes expects 'cp' (close price, legacy) AND 'close' (new)
        key = "cp" if h5_key == "close" else h5_key
        store.put(key, panel.astype(np.float64))
        print(f"  saved: {key} ({panel.shape})")
    store.put("trade_dt", trade_dt)
    store.put("stklist", stklist)
    store.put("ipo_days", ipo_days.astype(np.int64))
    store.put("st", st)
    store.put("suspend", suspend)
    store.put("ud_limit", ud_limit)
    store.put("mv_float", mv_float.astype(np.float64))
    store.put("id_citic1", id_citic1)
    store.put("amount", amount.astype(np.float64))
    store.put("id_300", id_300)

print(f"\n[done] Wrote {h5_path}")
print(f"  File size: {h5_path.stat().st_size / 1024 / 1024:.1f} MB")

# index_daily.h5 (placeholder for HS300 index)
idx_path = DST_DIR / "index_daily.h5"
if idx_path.exists():
    idx_path.unlink()
hs300_vals = (rng.uniform(3000, 5000, size=n_dates).cumsum() / n_dates + 4000)
hs300 = pd.DataFrame(
    {"index_cp": hs300_vals},
    index=yyyymmdd.values,
)
with pd.HDFStore(idx_path, mode="w") as store:
    store.put("index_cp", hs300)
    store.put("trade_dt", trade_dt)
    store.put("indexlist", pd.DataFrame({"index_code": ["000300.SH"]}))
print(f"  Wrote {idx_path} (HS300 synthetic)")

# constituents
if SRC_CONSTITUENTS.exists():
    constituents = json.loads(SRC_CONSTITUENTS.read_text())
    print(f"  HS300 constituents: {len(constituents)} stocks")