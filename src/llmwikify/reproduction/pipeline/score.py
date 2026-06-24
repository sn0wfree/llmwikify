"""Score and status computation for factor backtest results."""
from __future__ import annotations

import math


def compute_score(icir: float | None, win_rate: float | None) -> int:
    """Compute L5 overall_assessment.score (0-100) from ICIR + WinRate.

    Weighted: 70% ICIR (dominant) + 30% WinRate.
    """
    if icir is None or (isinstance(icir, float) and math.isnan(icir)):
        return 50
    icir_score = max(0, min(100, 50 + round(icir * 50)))
    if win_rate is None or (isinstance(win_rate, float) and math.isnan(win_rate)):
        return icir_score
    wr_score = round(win_rate * 100)
    return round(icir_score * 0.7 + wr_score * 0.3)


def compute_status(icir: float | None) -> str:
    """Compute L5 overall_assessment.status from ICIR.

    Mapping (matches WebUI OverallAssessment.tsx STATUS_CONFIG):
      通过  -- ICIR > 0.10  (positive edge)
      失败  -- ICIR < -0.05 (negative edge)
      待更新 -- default
    """
    if icir is None or (isinstance(icir, float) and math.isnan(icir)):
        return "待验证"
    if icir > 0.10:
        return "通过"
    if icir < -0.05:
        return "失败"
    return "待更新"
