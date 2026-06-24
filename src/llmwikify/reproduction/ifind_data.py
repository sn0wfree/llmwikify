"""iFinD tradability data source for QuantNodes pipeline.

Fetches historical ST/suspension/IPO data from iFinD (同花顺),
caches as Parquet, and builds [date × code] matrices for use
by TradabilityFilterNode / FactorPreprocessNode.

Data types:
  - IPO dates:   one-time per stock, immutable
  - ST history:  timeline of ST/*ST/摘帽 events per stock
  - Suspension:  trading status per date per stock
  - Limit u/d:   derived from OHLCV (pct_chg >= 9.9% / 5%)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import requests
import yaml

from .common.config import config

logger = logging.getLogger(__name__)

# ─── iFinD client (lazy init) ───────────────────────────────


def _get_ifind_dir() -> Path:
    """Get iFinD MCP directory from config."""
    return Path(config.get("ifind.mcp_dir", "~/Public/ifind-finance-data-1.1.0")).expanduser()


def _ifind_call(server_type: str, tool_name: str, params: dict) -> dict[str, Any]:
    """Call iFinD MCP API."""
    import sys

    ifind_dir = _get_ifind_dir()
    sys.path.insert(0, str(ifind_dir))
    from call import call  # type: ignore[import-untyped]

    return call(server_type, tool_name, params)


# ─── iFinD HTTP API ─────────────────────────────────────────


def _get_ifind_date_sequence_url() -> str:
    """Get iFinD date sequence URL from config."""
    return config.get(
        "ifind.date_sequence_url",
        "https://quantapi.51ifind.com/api/v1/date_sequence",
    )


def _get_ifind_http_config() -> Path:
    """Get iFinD HTTP config path from config."""
    return Path(
        config.get("ifind.config_path", "~/.llmwikify/ifind_http.yaml")
    ).expanduser()
_INDICATORS = {
    "listed_date": "ths_listed_date_stock",
    "suspend_days": "ths_suspen_days_stock",
    "risk_warning": "ths_is_risk_warning_board_stock",
    "is_subnew": "ths_is_subnew_stock_stock",
    "trading_status": "ths_trading_status_stock",
    "up_down_status": "ths_up_and_down_status_stock",
}


def _load_ifind_access_token() -> str:
    """Load iFinD access token from environment or config file."""
    token = os.getenv("IFIND_ACCESS_TOKEN", "").strip()
    if token:
        return token
    http_config = _get_ifind_http_config()
    if http_config.exists():
        data = yaml.safe_load(http_config.read_text(encoding="utf-8")) or {}
        token = str(data.get("access_token", "")).strip()
        if token:
            return token
    raise RuntimeError(
        "iFinD HTTP access token not configured. Set IFIND_ACCESS_TOKEN or "
        "configure ifind.config_path in llmwikify.json with access_token."
    )


def _ifind_date_sequence_request(
    codes: list[str],
    start_date: str,
    end_date: str,
    timeout: int = 120,
) -> dict[str, Any]:
    """Make iFinD date sequence API request."""
    token = _load_ifind_access_token()
    url = _get_ifind_date_sequence_url()
    payload = {
        "codes": ",".join(codes),
        "startdate": start_date,
        "enddate": end_date,
        "indipara": [
            {"indicator": _INDICATORS["listed_date"], "indiparams": []},
            {"indicator": _INDICATORS["suspend_days"], "indiparams": ["", ""]},
            {"indicator": _INDICATORS["risk_warning"], "indiparams": [""]},
            {"indicator": _INDICATORS["is_subnew"], "indiparams": []},
            {"indicator": _INDICATORS["trading_status"], "indiparams": [end_date]},
            {"indicator": _INDICATORS["up_down_status"], "indiparams": [""]},
        ],
    }
    resp = requests.post(
        url,
        headers={"Content-Type": "application/json", "access_token": token},
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


# ─── Parse helpers ──────────────────────────────────────────

_RESP_CACHE: dict[str, str] = {}


def _parse_ifind_text(response: dict) -> str:
    """Extract the text content from iFinD JSON-RPC response.

    Actual nesting: response["data"]["result"]["content"][i]["text"].
    """
    try:
        result = response.get("data", {}).get("result", {})
        if not result:
            result = response.get("result", {})
        content = result.get("content", [])
        for c in content:
            if c.get("type") == "text":
                inner = json.loads(c["text"])
                return inner.get("data", {}).get("answer", "")
    except Exception:
        pass
    return ""


def _extract_table(text: str) -> list[dict[str, str]]:
    """Parse iFinD markdown table to list of dicts."""
    rows: list[dict[str, str]] = []
    lines = text.strip().split("\n")
    headers: list[str] = []
    for line in lines:
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if not headers:
                headers = cells
            elif all(c == "---" for c in cells):
                continue
            else:
                rows.append(dict(zip(headers, cells)))
    return rows


def _normalize_ifind_records(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if not isinstance(data, dict):
        return []
    for key in ("tables", "table", "data", "result", "rows", "items", "value"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            records = _normalize_ifind_records(value)
            if records:
                return records
    if all(isinstance(v, list) for v in data.values()):
        keys = list(data.keys())
        n = max((len(data[k]) for k in keys), default=0)
        return [{k: data[k][i] if i < len(data[k]) else None for k in keys} for i in range(n)]
    return [data]


def _find_key(row: dict[str, Any], candidates: tuple[str, ...]) -> str | None:
    lowered = {str(k).lower(): k for k in row}
    for candidate in candidates:
        if candidate in row:
            return candidate
        key = lowered.get(candidate.lower())
        if key is not None:
            return str(key)
    for k in row:
        text = str(k).lower()
        if any(c.lower() in text for c in candidates):
            return str(k)
    return None


def _to_date_str(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("-", "")
    m = re.search(r"\d{8}", text)
    return m.group(0) if m else None


def _is_truthy_cn(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "是", "停牌", "暂停交易", "风险警示", "st", "*st"}


def _parse_limit_status(value: Any) -> float:
    text = str(value).strip()
    if "跌停" in text:
        return -1.0
    if "涨停" in text:
        return 1.0
    return 0.0


def _parse_date_sequence_response(raw: dict[str, Any]) -> pd.DataFrame:
    data = raw.get("data", raw)
    records = _normalize_ifind_records(data)
    if not records:
        return pd.DataFrame()
    df = pd.DataFrame(records)
    if df.empty:
        return df
    rename: dict[str, str] = {}
    code_key = _find_key(df.iloc[0].to_dict(), ("code", "codes", "thscode", "证券代码"))
    date_key = _find_key(df.iloc[0].to_dict(), ("time", "date", "datetime", "日期", "交易日期"))
    if code_key:
        rename[code_key] = "code"
    if date_key:
        rename[date_key] = "date"
    indicator_aliases = {
        "listed_date": ("ths_listed_date_stock", "上市日期", "首发上市日期"),
        "suspend_days": ("ths_suspen_days_stock", "停牌天数", "连续停牌天数"),
        "risk_warning": ("ths_is_risk_warning_board_stock", "是否属于风险警示板"),
        "is_subnew": ("ths_is_subnew_stock_stock", "是否为次新股"),
        "trading_status": ("ths_trading_status_stock", "交易状态"),
        "up_down_status": ("ths_up_and_down_status_stock", "涨跌停状态"),
    }
    sample = df.iloc[0].to_dict()
    for target, aliases in indicator_aliases.items():
        key = _find_key(sample, aliases)
        if key and key not in rename:
            rename[key] = target
    return df.rename(columns=rename)


# ─── Batch tradability ──────────────────────────────────────


def fetch_tradability_batch(
    codes: list[str],
    start_date: str,
    end_date: str,
    cache_dir: str | Path = "~/.llmwikify/ifind_cache",
    batch_size: int = 800,
    force: bool = False,
) -> pd.DataFrame:
    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"tradability_{start_date.replace('-', '')}_{end_date.replace('-', '')}.parquet"
    if cache_file.exists() and not force:
        cached = pd.read_parquet(cache_file)
        cached_codes = set(cached.get("code", pd.Series(dtype=str)).astype(str))
        missing = [c for c in codes if c not in cached_codes]
        if not missing:
            return cached[cached["code"].isin(codes)].copy()

    frames: list[pd.DataFrame] = []
    unique_codes = sorted(set(codes))
    for i in range(0, len(unique_codes), batch_size):
        batch = unique_codes[i:i + batch_size]
        logger.info("fetching iFinD date_sequence %d-%d/%d", i + 1, i + len(batch), len(unique_codes))
        raw = _ifind_date_sequence_request(batch, start_date, end_date)
        df = _parse_date_sequence_response(raw)
        if df.empty:
            logger.warning("empty date_sequence response for batch %d-%d", i + 1, i + len(batch))
        else:
            frames.append(df)
        time.sleep(0.25)

    result = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not result.empty:
        result.to_parquet(cache_file, index=False)
    return result


# ─── IPO dates ──────────────────────────────────────────────


def fetch_ipo_dates(
    codes: list[str],
    cache_dir: str | Path = "~/.llmwikify/ifind_cache",
) -> dict[str, str]:
    """Fetch IPO date for each stock code from iFinD.

    Returns dict: {code: "20010827"}
    Cached as Parquet (immutable after first fetch).
    """
    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "ipo_dates.parquet"

    # Try cache
    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        return dict(zip(df["code"], df["ipo_date"]))

    result: dict[str, str] = {}
    # Field name variants in iFinD response
    ipo_fields = ("上市日期", "首发上市日期", "上市时间")
    for i, code in enumerate(sorted(set(codes))):
        if code in result:
            continue
        # Try with full code first (more reliable)
        for q in (f"{code} 上市日期", f"{code.split('.')[0]} 上市日期"):
            try:
                resp = _ifind_call("stock", "get_stock_info", {"query": q})
                text = _parse_ifind_text(resp)
                rows = _extract_table(text)
                for field in ipo_fields:
                    if rows and field in rows[0] and rows[0][field]:
                        result[code] = rows[0][field]
                        logger.info("IPO %s: %s", code, rows[0][field])
                        break
                if code in result:
                    break
            except Exception as exc:
                logger.warning("IPO fetch %s failed: %s", code, exc)

        # Rate limit: 2 req/s for free tier
        if i % 2 == 1:
            time.sleep(0.6)

    # Cache
    pdf = pd.DataFrame({"code": list(result.keys()), "ipo_date": list(result.values())})
    pdf.to_parquet(cache_file, index=False)
    logger.info("cached %d IPO dates to %s", len(result), cache_file)
    return result


# ─── ST history ─────────────────────────────────────────────


def fetch_st_history(
    codes: list[str],
    cache_dir: str | Path = "~/.llmwikify/ifind_cache",
) -> dict[str, list[dict[str, str]]]:
    """Fetch ST/*ST/摘帽 timeline for each stock from iFinD.

    Returns dict: {code: [{"date": "20240408", "action": "ST"}, ...]}
    Cached as Parquet.
    """
    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "st_history.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        # Support two formats:
        #   old: code, event_date, action (from MCP get_stock_events)
        #   new: code, date, is_st 0/1 (from date_sequence ths_is_risk_warning_board_stock)
        date_col = "date" if "date" in df.columns else "event_date"
        result: dict[str, list[dict[str, str]]] = {}
        if "is_st" in df.columns:
            # New format: only keep ST entries (is_st=1)
            st_df = df[df["is_st"] == 1]
            for _, row in st_df.iterrows():
                result.setdefault(row["code"], []).append({
                    "date": str(row[date_col]),
                    "action": "ST",
                })
        else:
            for _, row in df.iterrows():
                result.setdefault(row["code"], []).append({
                    "date": str(row[date_col]),
                    "action": row["action"],
                })
        return result

    def _parse_hat_timeline(text: str) -> list[dict[str, str]]:
        """Parse 戴帽摘帽时间: ST:20240408;*ST:20240430;摘*:20250506"""
        events: list[dict[str, str]] = []
        for row in _extract_table(text):
            raw = row.get("戴帽摘帽时间", "")
            if raw:
                for chunk in raw.split(";"):
                    chunk = chunk.strip()
                    if ":" in chunk:
                        action, date = chunk.split(":", 1)
                        events.append({"date": date.strip(), "action": action.strip()})
        if not events:
            pattern = r"(ST|\*ST|摘\*|摘帽):?(\d{8})"
            for m in re.finditer(pattern, text):
                events.append({"date": m.group(2), "action": m.group(1)})
        return events

    result = {}
    for i, code in enumerate(sorted(set(codes))):
        name = code.split(".")[0]
        try:
            resp = _ifind_call("stock", "get_stock_events", {
                "query": f"{name} 戴帽摘帽时间"
            })
            text = _parse_ifind_text(resp)
            events = _parse_hat_timeline(text)
            if events:
                result[code] = events
                logger.info("ST history %s: %s", code, events)
        except Exception as exc:
            logger.warning("ST history failed for %s: %s", code, exc)

        if i % 2 == 1:
            time.sleep(0.5)

    # Cache: explode to row-per-event
    rows: list[dict] = []
    for code, events in result.items():
        for ev in events:
            rows.append({"code": code, "event_date": int(ev["date"]), "action": ev["action"]})
    if rows:
        pdf = pd.DataFrame(rows)
        pdf.to_parquet(cache_file, index=False)
        logger.info("cached %d ST events to %s", len(pdf), cache_file)
    else:
        # Write empty cache marker
        pd.DataFrame(columns=["code", "event_date", "action"]).to_parquet(cache_file, index=False)
    return result


# ─── Suspension history ─────────────────────────────────────


def fetch_suspend_history(
    codes: list[str],
    cache_dir: str | Path = "~/.llmwikify/ifind_cache",
) -> dict[str, list[dict[str, str]]]:
    """Fetch suspension dates for each stock from iFinD.

    Returns dict: {code: [{"date": "20240115", "days": "5"}, ...]}
    Cached as Parquet.

    Note: iFinD returns daily entries with "连续停牌天数".
    A stock with days > 0 is suspended on that date.
    """
    cache_dir = Path(cache_dir).expanduser()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "suspend_history.parquet"

    if cache_file.exists():
        df = pd.read_parquet(cache_file)
        # Support both old (s_date/days) and new (date/suspend_days) formats
        date_col = "date" if "date" in df.columns else "s_date"
        days_col = "suspend_days" if "suspend_days" in df.columns else "days"
        result: dict[str, list[dict[str, str]]] = {}
        for _, row in df.iterrows():
            d = str(row[date_col])
            # Filter: only keep entries within requested date range (skip full-market daily if we have it)
            result.setdefault(row["code"], []).append({
                "date": d,
                "days": str(row.get(days_col, "0")),
            })
        return result

    result = {}
    for i, code in enumerate(sorted(set(codes))):
        name = code.split(".")[0]
        try:
            resp = _ifind_call("stock", "get_stock_events", {
                "query": f"{name} 历史上停牌复牌日期"
            })
            text = _parse_ifind_text(resp)
            rows = _extract_table(text)
            if rows:
                events = []
                for row in rows:
                    date = row.get("日期", "")
                    days = row.get("连续停牌天数（单位：天）", "0")
                    if date:
                        events.append({"date": date, "days": days})
                if events:
                    result[code] = events
                    logger.info("suspend history %s: %d entries", code, len(events))
        except Exception as exc:
            logger.warning("suspend history failed for %s: %s", code, exc)

        if i % 2 == 1:
            time.sleep(0.5)

    # Cache
    rows_out: list[dict] = []
    for code, events in result.items():
        for ev in events:
            rows_out.append({"code": code, "s_date": int(ev["date"]), "days": int(ev["days"])})
    if rows_out:
        pdf = pd.DataFrame(rows_out)
        pdf.to_parquet(cache_file, index=False)
        logger.info("cached %d suspend records to %s", len(pdf), cache_file)
    else:
        pd.DataFrame(columns=["code", "s_date", "days"]).to_parquet(cache_file, index=False)
    return result


# ─── Build tradability matrices ─────────────────────────────


def build_tradable_matrices(
    codes: list[str],
    trade_dates: pd.DatetimeIndex | list[str],
    ipo_dates: dict[str, str] | None = None,
    st_history: dict[str, list[dict[str, str]]] | None = None,
    suspend_history: dict[str, list[dict[str, str]]] | None = None,
    cache_dir: str | Path = "~/.llmwikify/ifind_cache",
    use_batch_api: bool = False,
    batch_data: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Build [date × code] DataFrames for QuantNodes tradability.

    Produces 4 matrices:
      - st:        1.0=ST, 0.0=normal
      - suspend:   1.0=suspended, 0.0=normal
      - ud_limit:  1.0=limit up/down, 0.0=normal
      - ipo_days:  int64 days since IPO

    Args:
        codes: list of stock codes (e.g. ["000001.SZ", ...])
        trade_dates: list of all trading dates (str or DatetimeIndex)
        ipo_dates: from fetch_ipo_dates() (optional, auto-fetch if None)
        st_history: from fetch_st_history() (optional, auto-fetch if None)
        suspend_history: from fetch_suspend_history() (optional, auto-fetch if None)
        cache_dir: cache directory for fetched data

    Returns:
        {"st": DataFrame, "suspend": DataFrame, "ud_limit": DataFrame, "ipo_days": DataFrame}
    """
    # Resolve dates
    if isinstance(trade_dates, pd.DatetimeIndex):
        date_strs = [d.strftime("%Y%m%d") for d in trade_dates]
        date_idx = trade_dates
    else:
        date_strs = list(trade_dates)
        date_idx = pd.DatetimeIndex([pd.Timestamp(d) for d in trade_dates])

    date_set = set(date_strs)

    n_dates = len(date_strs)
    n_codes = len(codes)
    code_to_idx = {c: i for i, c in enumerate(codes)}
    date_to_idx = {d: i for i, d in enumerate(date_strs)}

    st_mat = np.zeros((n_dates, n_codes), dtype=np.float64)
    suspend_mat = np.zeros((n_dates, n_codes), dtype=np.float64)
    ud_limit_mat = np.zeros((n_dates, n_codes), dtype=np.float64)
    ipo_days_mat = np.zeros((n_dates, n_codes), dtype=np.int64)

    if use_batch_api or batch_data is not None:
        if batch_data is None:
            batch_data = fetch_tradability_batch(codes, date_strs[0], date_strs[-1], cache_dir)
        if batch_data is not None and not batch_data.empty:
            batch_data = batch_data.copy()
            if "date" in batch_data.columns:
                batch_data["date"] = batch_data["date"].map(_to_date_str)
            else:
                batch_data["date"] = date_strs[-1]
            if "code" in batch_data.columns:
                batch_data["code"] = batch_data["code"].astype(str)
            for _, row in batch_data.iterrows():
                code = str(row.get("code", ""))
                d = str(row.get("date", ""))
                ci = code_to_idx.get(code)
                if ci is None or d not in date_set:
                    continue
                di = date_to_idx.get(d)
                if "risk_warning" in row and _is_truthy_cn(row.get("risk_warning")):
                    st_mat[di, ci] = 1.0
                if "suspend_days" in row:
                    try:
                        suspend_mat[di, ci] = 1.0 if float(row.get("suspend_days") or 0) > 0 else 0.0
                    except Exception:
                        pass
                if "trading_status" in row and _is_truthy_cn(row.get("trading_status")):
                    suspend_mat[di, ci] = 1.0
                if "up_down_status" in row:
                    ud_limit_mat[di, ci] = _parse_limit_status(row.get("up_down_status"))

            listed = batch_data.dropna(subset=["code"]).drop_duplicates("code", keep="first") if "code" in batch_data.columns else pd.DataFrame()
            ipo_dates = {}
            for _, row in listed.iterrows():
                ipo = _to_date_str(row.get("listed_date")) if "listed_date" in row else None
                if ipo:
                    ipo_dates[str(row["code"])] = ipo
        else:
            ipo_dates = {}
        st_history = st_history or {}
        suspend_history = suspend_history or {}
    else:
        if ipo_dates is None:
            ipo_dates = fetch_ipo_dates(codes, cache_dir)
        if st_history is None:
            st_history = fetch_st_history(codes, cache_dir)
        if suspend_history is None:
            suspend_history = fetch_suspend_history(codes, cache_dir)

    ipo_dates = ipo_dates or {}
    st_history = st_history or {}
    suspend_history = suspend_history or {}

    for code in codes:
        ci = code_to_idx.get(code)
        if ci is None:
            continue

        # IPO days: compute from IPO date
        ipo_date_str = ipo_dates.get(code, "20000101")
        try:
            ipo_dt = pd.Timestamp(str(ipo_date_str))
        except Exception:
            ipo_dt = pd.Timestamp("2000-01-01")
        for di, d in enumerate(date_strs):
            days_since = (pd.Timestamp(d) - ipo_dt).days
            ipo_days_mat[di, ci] = max(days_since, 0)

        # ST status: build date ranges from events
        events = st_history.get(code, [])
        st_ranges: list[tuple[str, str]] = []
        current_st = False
        prev_event_date = None
        for ev in sorted(events, key=lambda x: x["date"]):
            action = ev["action"]
            if action in ("ST", "*ST"):
                if not current_st:
                    current_st = True
                    prev_event_date = ev["date"]
            elif action in ("摘*", "摘帽"):
                if current_st and prev_event_date:
                    st_ranges.append((prev_event_date, ev["date"]))
                    current_st = False
                prev_event_date = None
        if current_st and prev_event_date:
            st_ranges.append((prev_event_date, "99991231"))

        for start, end in st_ranges:
            for di, d in enumerate(date_strs):
                if start <= d <= end:
                    st_mat[di, ci] = 1.0

        # Suspension: iFinD returns daily data with "连续停牌天数"
        # days > 0 means suspended on that date
        suspend_entries = suspend_history.get(code, [])
        suspend_dates: set[str] = set()
        for entry in suspend_entries:
            d = entry["date"]
            days = int(entry.get("days", "0"))
            if days > 0 or (d in date_set):
                suspend_dates.add(d)
        for di, d in enumerate(date_strs):
            if d in suspend_dates:
                suspend_mat[di, ci] = 1.0
            # Also suspend if in date_set but no close price (for future coverage)

    # Build DataFrames with DatetimeIndex and str-code columns
    # (matching the format of factor_wide passed to build_qn_context)
    return {
        "st": pd.DataFrame(st_mat, index=date_idx, columns=list(codes)),
        "suspend": pd.DataFrame(suspend_mat, index=date_idx, columns=list(codes)),
        "ud_limit": pd.DataFrame(np.zeros((n_dates, n_codes), dtype=np.float64),
                                 index=date_idx, columns=list(codes)),
        "ipo_days": pd.DataFrame(ipo_days_mat, index=date_idx, columns=list(codes)),
    }


__all__ = [
    "fetch_ipo_dates",
    "fetch_st_history",
    "fetch_suspend_history",
    "build_tradable_matrices",
]
