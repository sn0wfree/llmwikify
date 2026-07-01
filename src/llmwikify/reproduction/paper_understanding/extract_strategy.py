"""Strategy extraction from wiki pages.

Scans the single canonical location ``wiki/strategy/`` (per P1 path
uniqueness + P6 兼容窗口=0). Each page's YAML frontmatter is parsed and
a strategy_config dict is assembled for run_backtest().

This is intentionally LLM-free: the heavy lifting of "read the paper and
extract the strategy" happens upstream in the ingest pipeline via
analyze_source.yaml. By the time extract_strategy_config runs, the wiki
already contains structured Strategy pages with frontmatter.

Output schema (consumed by run_reproduction):
    {
        "signal_type": "ma_cross",            # one of 6 prewritten, or "unknown"
        "signal_params": {"fast": 5, ...},    # params for the strategy node
        "wiki_page": "some-slug",             # source page slug (under strategy/)
    }
"""

from __future__ import annotations

import logging
from typing import Any

from ..common.paths import WIKI_DIR_STRATEGY, list_pages
from ..common.utils import parse_frontmatter

logger = logging.getLogger(__name__)

VALID_SIGNAL_TYPES = {
    "ma_cross",
    "rsi",
    "factor_rank",
    "volatility",
    "momentum",
    "signal_composite",
    "unknown",
}


def _to_signal_params(raw: Any) -> dict[str, Any]:
    """Coerce frontmatter signal_params (already dict) into clean params."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        try:
            if isinstance(v, str):
                if v.lower() in ("true", "false"):
                    out[k] = v.lower() == "true"
                    continue
                if "." in v:
                    out[k] = float(v)
                    continue
                if v.lstrip("-").isdigit():
                    out[k] = int(v)
                    continue
            out[k] = v
        except (ValueError, AttributeError):
            out[k] = v
    return out


def extract_from_page(content: str) -> dict[str, Any] | None:
    """Extract a strategy_config from one wiki page's content.

    Backward-compat helper used by older callers / tests. The canonical
    wiki-scan path is now ``extract_strategy_config`` (paths-based, P1+P6).
    """
    fm = parse_frontmatter(content)
    if not fm:
        return None
    return _config_from_fm(fm)


def _config_from_fm(fm: dict[str, Any]) -> dict[str, Any] | None:
    """Build a strategy_config (without ``wiki_page`` slug) from a frontmatter dict.

    Returns:
        ``{"signal_type": str, "signal_params": dict, "page_name": str}``
        or ``None`` if no recognized ``signal_type`` is present.
    """
    signal_type = str(fm.get("signal_type", "") or "").strip().lower()
    if not signal_type:
        return None
    if signal_type not in VALID_SIGNAL_TYPES:
        logger.warning(
            "unknown signal_type %r — falling back to 'unknown' path", signal_type
        )
        signal_type = "unknown"
    return {
        "signal_type": signal_type,
        "signal_params": _to_signal_params(fm.get("signal_params", {})),
        "page_name": fm.get("title") or "",
    }


def extract_strategy_config(wiki: Any) -> dict[str, Any]:
    """Pull the first recognized strategy page from ``wiki/strategy/``.

    Single source of truth (P1 path uniqueness, P6 兼容窗口=0): scans only
    ``WIKI_DIR_STRATEGY`` via :func:`reproduction.common.paths.list_pages`.

    Returns:
        ``{"signal_type": str, "signal_params": dict, "wiki_page": str}``
        or ``{"signal_type": "unknown", "signal_params": {}, "wiki_page": None}``
    """
    for page in list_pages(wiki, WIKI_DIR_STRATEGY):
        cfg = _config_from_fm(page)
        if cfg is None:
            continue
        cfg["wiki_page"] = page["_slug"]
        return cfg
    return {"signal_type": "unknown", "signal_params": {}, "wiki_page": None}


__all__ = [
    "extract_from_page",
    "extract_strategy_config",
    "VALID_SIGNAL_TYPES",
]
