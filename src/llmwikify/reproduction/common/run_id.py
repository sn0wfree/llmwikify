"""Run ID generation utility.

Generates unique, deterministic-enough run IDs for backtest results.
Uses config-driven template with UUID suffix to prevent ID collisions
when the same (start, end) window is backtested multiple times.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from .config import config


def generate_run_id(
    start: str | None = None,
    end: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    """Generate a run ID from config template.

    Template variables (config key: reproduction.run_id_template):
        {start}:    start date (YYYY-MM-DD or YYYYMMDD)
        {end}:      end date (YYYY-MM-DD or YYYYMMDD)
        {uuid4_short}: short UUID4 hex (length from config: reproduction.run_id_uuid_length)
        {uuid4}:    full UUID4
        Any extra:  from `extra` param

    Args:
        start: Start date string (default: 'unknown')
        end: End date string (default: 'unknown')
        extra: Additional template variables

    Returns:
        Generated run ID (e.g., "20240101-20241231-a1b2c3d4")
    """
    template = config.get("reproduction.run_id_template", "{start}-{end}-{uuid4_short}")
    uuid_len = int(config.get("reproduction.run_id_uuid_length", 8))

    safe_start = (start or "unknown").replace("-", "")
    safe_end = (end or "unknown").replace("-", "")

    ctx: dict[str, Any] = {
        "start": safe_start,
        "end": safe_end,
        "uuid4_short": uuid.uuid4().hex[:uuid_len],
        "uuid4": uuid.uuid4().hex,
    }
    if extra:
        ctx.update(extra)

    try:
        return template.format(**ctx)
    except KeyError:
        return f"{safe_start}-{safe_end}-{ctx['uuid4_short']}"


_SAFE_RUN_ID = re.compile(r"[^A-Za-z0-9_.-]")


def sanitize_run_id(run_id: str) -> str:
    """Sanitize run_id for use as a file path component.

    Replaces any character not in [A-Za-z0-9_.-] with underscore.
    """
    return _SAFE_RUN_ID.sub("_", run_id)


__all__ = ["generate_run_id", "sanitize_run_id"]
