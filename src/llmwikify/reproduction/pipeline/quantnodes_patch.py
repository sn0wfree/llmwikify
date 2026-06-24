"""QuantNodes SamplePoolFilter bug workaround.

SamplePoolFilter returns a DataFrame with default RangeIndex (0..n-1) on
both axes, instead of the int64 yyyymmdd index / stock-code columns from
load_data. When TradabilityFilter multiplies ``if_tradable * sample``,
pandas does index/column union -> shape doubles (e.g. 1305x50 -> 2610x100).
We patch the result to carry the correct axes.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_PATCHED = False


def patch_sample_pool_filter() -> None:
    """Set proper index/columns on SamplePoolFilter output to fix union bug."""
    global _PATCHED
    if _PATCHED:
        return

    from QuantNodes.research.factor_test.nodes.sample_pool_filter_node import (
        SamplePoolFilterNode,
    )

    orig = SamplePoolFilterNode._execute

    def patched(self, input_data=None, **kwargs):  # noqa: ANN001, ANN202
        result = orig(self, input_data, **kwargs)
        context = kwargs.get("context", {})
        load_data = context.get("LoadData") or input_data or {}
        if "stklist" in load_data and "trade_dt" in load_data:
            stklist = load_data["stklist"]
            trade_dt = load_data["trade_dt"]
            result.index = trade_dt.iloc[:, 0].values
            result.columns = stklist.iloc[:, 0].values
        return result

    SamplePoolFilterNode._execute = patched
    _PATCHED = True
    logger.debug("SamplePoolFilter monkey-patch applied")


patch_sample_pool_filter()
