"""Test 101 alphas backtest via QuantNodes PipelineRunner.

直接用 QuantNodes PipelineRunner + LLM-compiled expressions.
缓存策略:
- akshare close panel 缓存在 ~/.llmwikify/akshare_cache/
- LLM 编译缓存在 ~/.llmwikify/factor_cache/
- 回测结果缓存在 quant/papers/{id}/backtest_results.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path("/home/ll/llmwikify")
sys.path.insert(0, str(ROOT / "src"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("test_101_quantnodes")


def setup_cache(universe: str = "HS300", start_date: str = "2020-01-01", end_date: str = "2024-12-31") -> str:
    """Ensure cache data exists, return path to QuantNodes-compatible HDF5 dir.

    QuantNodes LoadDataNode expects HDF5 files in data_path:
      - stk_daily.h5  (keys: stklist, trade_dt, cp, open, high, low, close, volume, etc.)
      - index_daily.h5 (keys: indexlist, trade_dt, index_cp, etc.)
    """
    from llmwikify.reproduction.akshare_data import (
        fetch_hs300_constituents,
        fetch_close_panel,
    )

    cache_dir = Path.home() / ".llmwikify" / "akshare_cache" / "quantnodes_h5"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Files: stk_daily.h5, index_daily.h5
    stk_path = cache_dir / "stk_daily.h5"
    idx_path = cache_dir / "index_daily.h5"
    if stk_path.exists() and stk_path.stat().st_size > 1_000_000:
        logger.info("Cache exists: %s (%.1f MB)", stk_path, stk_path.stat().st_size / 1e6)
        return str(cache_dir)

    # Fetch HS300 constituents
    codes = fetch_hs300_constituents(refresh=False)
    if not codes:
        codes = [f"{i:06d}.{'SZ' if i < 600000 else 'SH'}" for i in range(1, 51)]
    n_stocks = min(50, len(codes))
    codes = codes[:n_stocks]

    # Fetch or generate close panel
    close_panel = fetch_close_panel(codes, start_date, end_date, refresh=False)
    if close_panel.empty:
        logger.warning("Close panel empty, generating synthetic data")
        import pandas as pd
        import numpy as np
        dates = pd.date_range(start_date, end_date, freq="B")
        np.random.seed(42)
        data = {}
        for code in codes:
            price = 10 + np.cumsum(np.random.randn(len(dates)) * 0.02)
            data[code] = price
        close_panel = pd.DataFrame(data, index=dates)

    # Synthesize OHLCV
    import numpy as np
    import pandas as pd
    np.random.seed(0)
    long = close_panel.stack().reset_index()
    long.columns = ["date", "code", "close"]
    long["open"] = long["close"] * (1 + np.random.randn(len(long)) * 0.005)
    long["high"] = long[["open", "close"]].max(axis=1) * (1 + np.abs(np.random.randn(len(long))) * 0.003)
    long["low"] = long[["open", "close"]].min(axis=1) * (1 - np.abs(np.random.randn(len(long))) * 0.003)
    long["volume"] = np.random.randint(1_000_000, 10_000_000, len(long))
    long["returns"] = long.groupby("code")["close"].pct_change().fillna(0)
    long["vwap"] = (long["high"] + long["low"] + long["close"]) / 3
    long["amount"] = long["close"] * long["volume"]

    # Build [date × code] wide panels
    def pivot_wide(key: str) -> pd.DataFrame:
        wide = long.pivot(index="date", columns="code", values=key)
        wide.index = pd.to_datetime(wide.index)
        return wide

    stklist = pd.DataFrame({"code": codes})
    stklist.index = codes
    # trade_dt must be int yyyymmdd (QuantNodes AdjustDateNode requirement)
    trade_dates_int = [int(d.strftime("%Y%m%d")) for d in close_panel.index]
    trade_dt = pd.DataFrame({"trade_dt": trade_dates_int})
    trade_dt.index = close_panel.index

    # id_300 (HS300 membership flag) — True for all synthetic stocks
    id_300 = pd.DataFrame(
        True,
        index=pd.to_datetime(trade_dates_int, format="%Y%m%d"),
        columns=codes,
    )

    # Build HDF5
    logger.info("Building HDF5 cache at %s ...", cache_dir)
    wide_open = pivot_wide("open")
    wide_high = pivot_wide("high")
    wide_low = pivot_wide("low")
    wide_close = pivot_wide("close")
    wide_volume = pivot_wide("volume")
    wide_returns = pivot_wide("returns")
    wide_vwap = pivot_wide("vwap")
    wide_amount = pivot_wide("amount")
    # Synthesize industry + mkt_cap
    np.random.seed(1)
    industry_codes = np.random.randint(1, 30, n_stocks)
    id_citic1 = pd.DataFrame(
        [industry_codes], columns=codes, index=close_panel.index[:1]
    )
    id_citic1 = id_citic1.reindex(close_panel.index, method="ffill")
    mv_float = wide_close * np.random.randint(1e8, 1e10, (len(close_panel.index), n_stocks))
    st = pd.DataFrame(0.0, index=close_panel.index, columns=codes)
    suspend = pd.DataFrame(0.0, index=close_panel.index, columns=codes)
    ud_limit = pd.DataFrame(0.0, index=close_panel.index, columns=codes)
    ipo_days = pd.DataFrame(365, index=close_panel.index, columns=codes)

    with pd.HDFStore(stk_path, mode="w") as store:
        store.put("stklist", stklist)
        store.put("trade_dt", trade_dt)
        store.put("cp", wide_close)
        store.put("open", wide_open)
        store.put("high", wide_high)
        store.put("low", wide_low)
        store.put("close", wide_close)
        store.put("volume", wide_volume)
        store.put("returns", wide_returns)
        store.put("vwap", wide_vwap)
        store.put("amount", wide_amount)
        store.put("id_citic1", id_citic1)
        store.put("id_300", id_300)
        store.put("mv_float", mv_float)
        store.put("st", st)
        store.put("suspend", suspend)
        store.put("ud_limit", ud_limit)
        store.put("ipo_days", ipo_days)

    # Index HDF5 (HS300 baseline)
    indexlist = pd.DataFrame({"index_code": ["000300.SH"]}, index=["000300.SH"])
    index_cp = wide_close.mean(axis=1).to_frame("000300.SH")
    index_cp.columns = ["000300.SH"]
    with pd.HDFStore(idx_path, mode="w") as store:
        store.put("indexlist", indexlist)
        store.put("trade_dt", trade_dt)
        store.put("index_cp", index_cp)

    logger.info("Wrote HDF5 cache: %d stocks × %d days", n_stocks, len(close_panel.index))
    return str(cache_dir)


def main():
    parser = argparse.ArgumentParser(description="Test 101 alphas via QuantNodes")
    parser.add_argument(
        "--factors", nargs="*", default=None,
        help="Factor names to test (default: first 5 alphas)",
    )
    parser.add_argument("--universe", default="HS300")
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--limit", type=int, default=5, help="Limit number of factors")
    parser.add_argument(
        "--paper-id", default="101_alphas_v3",
        help="Paper ID (default: 101_alphas_v3)",
    )
    args = parser.parse_args()

    work_dir = ROOT / "quant" / "papers" / args.paper_id
    if not work_dir.exists():
        logger.error("Paper dir not found: %s", work_dir)
        return 1

    # Step 1: Setup cache data
    logger.info("Step 1: Setup cache data")
    data_path = setup_cache(
        universe=args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    # Step 2: Run backtest
    logger.info("Step 2: Run backtest via QuantNodes PipelineRunner")
    from llmwikify.reproduction.quantnodes_repro import run_paper_backtest, save_report

    # Pick factors
    factors_dir = work_dir / "factors"
    yaml_files = sorted(factors_dir.glob("*.yaml"))
    if args.factors:
        yaml_files = [p for p in yaml_files if p.stem in args.factors]
    else:
        yaml_files = yaml_files[:args.limit]
    factor_names = [p.stem for p in yaml_files]
    logger.info("Testing %d factors: %s", len(factor_names), factor_names[:5])

    t0 = time.monotonic()
    report = run_paper_backtest(
        paper_id=args.paper_id,
        work_dir=work_dir,
        data_path=data_path,
        sample_index=args.universe,
        start_date=args.start_date,
        end_date=args.end_date,
        factor_names=factor_names,
    )

    # Step 3: Save report
    save_report(report, work_dir)
    elapsed = (time.monotonic() - t0) / 60

    # Step 4: Print summary
    print()
    print("=" * 80)
    print(f"101 alphas backtest: {args.paper_id}")
    print(f"Data: {data_path}")
    print("=" * 80)
    print(f"Total: {report.total_factors}, Success: {report.n_success}, "
          f"Deferred: {report.n_deferred}, Failed: {report.n_failed}")
    print(f"L5: pass={report.n_pass_l5}, needs_revision={report.n_needs_revision}, "
          f"reject={report.n_reject_l5}")
    print(f"Time: {elapsed:.1f} min")
    print()
    for f in report.factors:
        ops = f", new_ops={len(f.new_operators)}" if f.new_operators else ""
        ic = f.metrics.get("ic_mean", "N/A")
        sharpe = f.metrics.get("ls_sharpe", f.metrics.get("long_short_sharpe", "N/A"))
        ic_str = f"{ic:.3f}" if isinstance(ic, (int, float)) else str(ic)
        sharpe_str = f"{sharpe:.2f}" if isinstance(sharpe, (int, float)) else str(sharpe)
        print(
            f"  {f.factor_name:<30} status={f.status:<10} "
            f"l5={f.l5_decision:<15} ic={ic_str:<8} sharpe={sharpe_str:<6} "
            f"({f.elapsed_sec:.1f}s){ops}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
