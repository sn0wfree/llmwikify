"""Stock universe resolution.

Maps user-friendly universe specifiers (HS300, 沪深300, custom lists) to
concrete stock code lists. Primary data source: AKShare index constituent
endpoints, with a small in-memory cache to avoid repeated network calls.

API:
    get_index_constituents(index_code) -> list[str]
    resolve_universe(spec) -> list[str]
    get_index_close_series(index_code, router) -> pd.Series | None
"""

from __future__ import annotations

import logging
from typing import Optional, Union

import pandas as pd

from .common.config import config

logger = logging.getLogger(__name__)


def _get_index_aliases() -> dict[str, str]:
    """Get index aliases from config or use defaults."""
    # Default aliases
    default_aliases = {
        # 沪深 300
        "HS300": "000300", "hs300": "000300", "000300": "000300",
        "000300.SH": "000300", "沪深300": "000300", "沪深三百": "000300",
        "CSI300": "000300", "csi300": "000300",
        # 中证 500
        "ZZ500": "000905", "zz500": "000905", "000905": "000905",
        "000905.SH": "000905", "中证500": "000905", "中证五百": "000905",
        "CSI500": "000905", "csi500": "000905",
        # 上证 50
        "SZ50": "000016", "sz50": "000016", "000016": "000016",
        "000016.SH": "000016", "上证50": "000016", "上证五十": "000016",
        "SSE50": "000016", "sse50": "000016",
        # 中证 1000
        "ZZ1000": "000852", "zz1000": "000852", "000852": "000852",
        "000852.SH": "000852", "中证1000": "000852", "中证一千": "000852",
        "CSI1000": "000852", "csi1000": "000852",
        # 中证 800
        "ZZ800": "000906", "zz800": "000906", "000906": "000906",
        "000906.SH": "000906", "中证800": "000906",
        # 创业板指
        "399006": "399006", "399006.SZ": "399006", "创业板指": "399006",
        "ChiNext": "399006", "chinext": "399006",
    }
    # Merge with config aliases
    config_aliases = config.get("universe.aliases", {})
    if config_aliases:
        default_aliases.update(config_aliases)
    return default_aliases


# Get aliases (lazy initialization)
INDEX_ALIASES: dict[str, str] = _get_index_aliases()


# In-memory cache: index_code -> list of 6-digit codes
_CACHE: dict[str, list[str]] = {}


def get_index_constituents(index_code: str) -> list[str]:
    """Fetch constituent stock codes for a Chinese A-share index.

    Args:
        index_code: Alias or 6-digit index code. e.g. "HS300", "000300",
            "沪深300", "CSI500". All resolved via INDEX_ALIASES.

    Returns:
        List of 6-digit stock codes (without exchange suffix), e.g.
        ["000001", "600519", ...]. Returns empty list on failure.

    Notes:
        - Result is cached in-process; first call hits AKShare.
        - AKShare endpoints: ak.index_stock_cons (Sina) preferred for
          speed; ak.index_stock_cons_csindex (中证) as fallback.
    """
    if not index_code:
        return []
    code = INDEX_ALIASES.get(index_code, index_code)
    if code in _CACHE:
        return list(_CACHE[code])

    try:
        import akshare as ak
    except ImportError:
        logger.warning("akshare not installed; cannot resolve universe")
        return []

    df = None
    # Try Sina source first (faster)
    try:
        df = ak.index_stock_cons(symbol=code)
    except Exception as exc:
        logger.warning("ak.index_stock_cons(%s) failed: %s", code, exc)
        df = None

    # Fallback to CSIndex
    if df is None or df.empty:
        try:
            df = ak.index_stock_cons_csindex(symbol=code)
        except Exception as exc:
            logger.warning("ak.index_stock_cons_csindex(%s) failed: %s", code, exc)
            df = None

    if df is None or df.empty:
        logger.warning("no constituents for %s", code)
        return []

    # Sina source: ["品种代码", "品种名称", "纳入日期"] → 品种代码
    # CSIndex source: ["日期", "指数代码", "指数名称", "成分券代码", ...] → 成分券代码
    if "品种代码" in df.columns:
        raw = df["品种代码"].astype(str).tolist()
    elif "成分券代码" in df.columns:
        raw = df["成分券代码"].astype(str).tolist()
    else:
        logger.warning("unknown constituent columns: %s", df.columns.tolist())
        return []

    # Normalize to 6-digit codes (strip exchange suffix if present)
    codes: list[str] = []
    for c in raw:
        s = str(c).strip()
        if not s:
            continue
        if "." in s:
            s = s.split(".")[0]
        if len(s) == 6 and s.isdigit():
            codes.append(s)

    _CACHE[code] = codes
    logger.info("resolved universe %s -> %d stocks", code, len(codes))
    return codes


def resolve_universe(spec: Union[str, list[str], None]) -> list[str]:
    """Resolve a universe specifier to a list of stock codes.

    Args:
        spec:
            - None or "all": returns empty list (signals "all A-shares")
            - "single": returns empty list (signals "single-stock mode")
            - "custom": returns empty list (frontend should provide codes)
            - "HS300" / "000300" / "沪深300": resolved via INDEX_ALIASES
            - list[str]: returned as-is (deduped, validated)

    Returns:
        List of 6-digit stock codes, or empty list for special specifiers.
    """
    if spec is None:
        return []
    if isinstance(spec, str):
        s = spec.strip()
        if s in ("", "all", "single", "custom"):
            return []
        return get_index_constituents(s)
    if isinstance(spec, (list, tuple)):
        seen: set[str] = set()
        out: list[str] = []
        for c in spec:
            if not c:
                continue
            s = str(c).strip()
            if "." in s:
                s = s.split(".")[0]
            if len(s) == 6 and s.isdigit() and s not in seen:
                seen.add(s)
                out.append(s)
        return out
    return []


def _get_hedge_index_code() -> dict[str, str]:
    """Get hedge index code mapping from config or use defaults."""
    default_hedge = {
        "HS300": "000300.SH",
        "000300.SH": "000300.SH",
        "CSI300": "000300.SH",
        "ZZ500": "000905.SH",
        "000905.SH": "000905.SH",
        "CSI500": "000905.SH",
        "SZ50": "000016.SH",
        "000016.SH": "000016.SH",
        "SSE50": "000016.SH",
    }
    # Merge with config hedge aliases
    config_hedge = config.get("universe.hedge_aliases", {})
    if config_hedge:
        default_hedge.update(config_hedge)
    return default_hedge


# Mapping from hedge name to index code used by get_index_close_series
HEDGE_INDEX_CODE: dict[str, str] = _get_hedge_index_code()


def get_index_close_series(
    index_code: str,
    router: Any,
    start: str,
    end: str,
) -> Optional[pd.Series]:
    """Fetch close price series for an index via the given DataRouter.

    Args:
        index_code: Hedge alias (HS300/ZZ500/SZ50) or full code.
        router: DataRouter instance.
        start: Start date YYYY-MM-DD.
        end: End date YYYY-MM-DD.

    Returns:
        pd.Series indexed by date with close prices, or None on failure.
    """
    code = HEDGE_INDEX_CODE.get(index_code, index_code)
    try:
        df, _ = router.get(code, start, end)
    except Exception as exc:
        logger.warning("get_index_close_series(%s) failed: %s", code, exc)
        return None
    if df is None or df.empty or "close" not in df.columns:
        return None
    if "date" in df.columns:
        s = df.set_index("date")["close"]
    else:
        s = df["close"]
    s = s.sort_index()
    s.name = code
    return s


__all__ = [
    "INDEX_ALIASES",
    "HEDGE_INDEX_CODE",
    "get_index_constituents",
    "resolve_universe",
    "get_index_close_series",
]


# Late import to avoid circular
from typing import Any  # noqa: E402
