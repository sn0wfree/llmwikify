"""Strategy extraction from wiki pages.

Walks the wiki looking for TradingStrategy pages (a custom page type
declared in wiki_schema.yaml). Each match is read, its YAML frontmatter is
parsed, and a strategy_config dict is assembled for run_backtest().

This is intentionally LLM-free: the heavy lifting of "read the paper and
extract the strategy" happens upstream in the ingest pipeline via
analyze_source.yaml. By the time extract_strategy_config runs, the wiki
already contains structured TradingStrategy pages with frontmatter.

Output schema (consumed by run_reproduction):
    {
        "signal_type": "ma_cross",            # one of 6 prewritten, or "unknown"
        "signal_params": {"fast": 5, ...},    # params for the strategy node
        "wiki_page": "trading/some-slug",     # source page for traceability
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

VALID_SIGNAL_TYPES = {
    "ma_cross",
    "rsi",
    "factor_rank",
    "volatility",
    "momentum",
    "signal_composite",
    "unknown",
}


def _parse_frontmatter(content: str) -> dict[str, Any]:
    """Pull YAML-ish key:value frontmatter out of a markdown page."""
    m = FRONTMATTER_RE.match(content)
    if not m:
        return {}
    out: dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            out[key] = [v.strip().strip('"').strip("'") for v in inner.split(",") if v.strip()]
        elif value.startswith("{") and value.endswith("}"):
            inner = value[1:-1].strip()
            as_dict: dict[str, Any] = {}
            for pair in inner.split(","):
                if ":" not in pair:
                    continue
                k, _, v = pair.partition(":")
                as_dict[k.strip()] = v.strip().strip('"').strip("'")
            out[key] = as_dict
        else:
            out[key] = value.strip('"').strip("'")
    return out


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


def extract_from_page(content: str) -> Optional[dict[str, Any]]:
    """Extract a strategy_config from one wiki page's content."""
    fm = _parse_frontmatter(content)
    if not fm:
        return None
    signal_type = fm.get("signal_type", "").strip().lower()
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


def _iter_strategy_pages(wiki: Any, subdir: str) -> Iterable[tuple[str, str]]:
    """Yield ``(subdir, content)`` tuples under ``wiki/{subdir}/``.

    Pairs the originating subdir so callers can record the source for
    traceability when the same logical page may live under either
    ``wiki/trading/`` (legacy TradingStrategy) or ``wiki/strategy/``
    (newly written by ``extract_paper.build_paper_pages``).
    """
    page_dir = wiki.wiki_dir / subdir
    if not page_dir.is_dir():
        return
    for md in sorted(page_dir.glob("*.md")):
        try:
            yield subdir, md.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("could not read %s: %s", md, exc)


def extract_strategy_config(wiki: Any) -> dict[str, Any]:
    """Pull the first recognized strategy page and assemble strategy_config.

    Scans both ``wiki/strategy/`` (newly written by Paper extraction via
    ``extract_paper.build_paper_pages``) and ``wiki/trading/`` (legacy
    TradingStrategy pages). Preference order: ``strategy`` first because
    paper-extracted pages carry richer frontmatter (factor_refs, etc.).

    Returns:
        {"signal_type": "...", "signal_params": {...}, "wiki_page": "..."}
        or {"signal_type": "unknown", "signal_params": {}, "wiki_page": None}
    """
    for subdir in ("strategy", "trading"):
        for origin, content in _iter_strategy_pages(wiki, subdir):
            cfg = extract_from_page(content)
            if cfg is None:
                continue
            cfg["wiki_page"] = origin
            return cfg
    return {"signal_type": "unknown", "signal_params": {}, "wiki_page": None}


__all__ = [
    "extract_from_page",
    "extract_strategy_config",
    "VALID_SIGNAL_TYPES",
]