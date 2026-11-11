"""Banister impulse-response training load: TRIMP, CTL (fitness), ATL (fatigue), TSB (form)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

CTL_DAYS = 42
ATL_DAYS = 7


def trimp(duration_s: float, avg_hr: float, resting_hr: float, max_hr: float,
          sex_factor: float = 1.92) -> float:
    """Banister TRIMP for one session."""
    reserve = max_hr - resting_hr
    if reserve <= 0:
        raise ValueError("max_hr must exceed resting_hr")
    hrr = min(max((avg_hr - resting_hr) / reserve, 0.0), 1.0)
    return (duration_s / 60) * hrr * 0.64 * math.exp(sex_factor * hrr)


def ewma(values: Sequence[float], time_constant_days: int) -> list[float]:
    """Exponentially weighted moving average, seeded at zero (Coggan form)."""
    out: list[float] = []
    current = 0.0
    for value in values:
        current += (value - current) / time_constant_days
        out.append(current)
    return out


@dataclass(frozen=True, slots=True)
class LoadPoint:
    ctl: float
    atl: float
    tsb: float


def training_load(daily_trimp: Sequence[float]) -> list[LoadPoint]:
    """CTL/ATL per day; TSB uses *yesterday's* CTL - ATL (form going into the day)."""
    ctl = ewma(daily_trimp, CTL_DAYS)
    atl = ewma(daily_trimp, ATL_DAYS)
    points: list[LoadPoint] = []
    for i, (c, a) in enumerate(zip(ctl, atl, strict=True)):
        prev_c, prev_a = (ctl[i - 1], atl[i - 1]) if i else (0.0, 0.0)
        points.append(LoadPoint(ctl=c, atl=a, tsb=prev_c - prev_a))
    return points


def form_label(tsb: float) -> str:
    """Human-readable form band (TrainingPeaks-style thresholds)."""
    if tsb > 25:
        return "Detrained"
    if tsb > 5:
        return "Fresh"
    if tsb > -10:
        return "Neutral"
    if tsb > -30:
        return "Productive"
    return "Overreaching"


def readiness_score(tsb: float, ctl_ramp_7d: float) -> int:
    """0-100 heuristic: fresher form scores higher; aggressive ramps are penalised."""
    ramp_penalty = max(0.0, ctl_ramp_7d - 5) * 3
    return round(min(100.0, max(0.0, 75 + tsb * 1.5 - ramp_penalty)))


def readiness_label(score: int) -> str:
    if score >= 75:
        return "Ready to train hard"
    if score >= 50:
        return "Train as planned"
    return "Prioritise recovery"
